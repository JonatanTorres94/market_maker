import time
from datetime import UTC, datetime
from decimal import Decimal

from binance.exceptions import BinanceAPIException

from src.analytics.pnl import PnLService
from src.core.logger import setup_logger
from src.domain.events import (
    OrderCancelRequestedEvent,
    OrderPlacedEvent,
    OrderStatusSyncedEvent,
)
from src.domain.models import CycleSnapshot, OrderPlacementRecord, OrderRequest
from src.engine.order_state_store import OrderStateStore
from src.exchange.binance_client import create_binance_client
from src.exchange.exchange_info import ExchangeInfoService
from src.exchange.market_data import MarketDataService
from src.exchange.order_manager import OrderManager
from src.journal.trade_journal import TradeJournal
from src.risk.risk_manager import RiskManager
from src.strategies.market_maker import MarketMakerConfig, MarketMakerStrategy


SLEEP_SECONDS = 5


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def exchange_ms_to_iso(value: int | None) -> str:
    if value is None:
        return utc_now_iso()
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()


def build_status_sync_event(order_payload: dict) -> OrderStatusSyncedEvent:
    updated_at = exchange_ms_to_iso(order_payload.get("updateTime") or order_payload.get("time"))

    return OrderStatusSyncedEvent(
        occurred_at=utc_now_iso(),
        symbol=order_payload["symbol"],
        order_id=int(order_payload["orderId"]),
        client_order_id=order_payload.get("clientOrderId", ""),
        side=order_payload["side"],
        price=Decimal(order_payload["price"]),
        orig_qty=Decimal(order_payload["origQty"]),
        executed_qty=Decimal(order_payload["executedQty"]),
        status=order_payload["status"],
        updated_at=updated_at,
    )


def refresh_tracked_orders(
    symbol: str,
    order_manager: OrderManager,
    state_store: OrderStateStore,
    logger,
) -> None:
    active_orders = state_store.get_active_orders(symbol)

    if not active_orders:
        return

    for local_order in active_orders:
        try:
            payload = order_manager.get_order(symbol=symbol, order_id=local_order.order_id)
            event = build_status_sync_event(payload)
            state_store.apply_status_sync(event)
        except BinanceAPIException as exc:
            logger.warning(
                "Failed to refresh local order state for order_id=%s: %s",
                local_order.order_id,
                exc,
            )


def log_order_state_snapshot(symbol: str, state_store: OrderStateStore, logger) -> None:
    counts = state_store.status_counts(symbol)
    active_count = len(state_store.get_active_orders(symbol))
    terminal_count = len(state_store.get_terminal_orders(symbol))

    logger.info(
        "Local order state | active=%s terminal=%s counts=%s",
        active_count,
        terminal_count,
        counts,
    )


def main():
    logger = setup_logger("run_market_maker")

    client = create_binance_client()
    market_data = MarketDataService(client)
    exchange_info = ExchangeInfoService(client)
    order_manager = OrderManager(client)
    journal = TradeJournal()
    state_store = OrderStateStore()

    symbol = "BTCUSDT"
    filters = exchange_info.get_symbol_filters(symbol)

    risk_manager = RiskManager(
        min_base_inventory=Decimal("0.995"),
        max_base_inventory=Decimal("1.005"),
        min_quote_balance=Decimal("50"),
    )

    strategy = MarketMakerStrategy(
        config=MarketMakerConfig(
            base_quote_quantity=Decimal("0.001"),
            min_spread=Decimal("0.01"),
            inventory_target=Decimal("1.000"),
            inventory_tolerance=Decimal("0.005"),
            max_inventory_skew_factor=Decimal("1"),
        ),
        risk_manager=risk_manager,
    )

    last_bid_price = None
    last_ask_price = None
    last_bid_qty = None
    last_ask_qty = None

    logger.info("Starting market maker for %s", symbol)

    try:
        while True:
            timestamp = utc_now_iso()

            try:
                refresh_tracked_orders(
                    symbol=symbol,
                    order_manager=order_manager,
                    state_store=state_store,
                    logger=logger,
                )

                market = market_data.get_best_bid_ask(symbol)
                inventory = order_manager.get_inventory_state(symbol)
                inventory_bias = risk_manager.inventory_bias(inventory)

                quote = strategy.generate_quotes(market=market, inventory=inventory)

                logger.info(
                    "Quote decision | bid=%s bid_qty=%s ask=%s ask_qty=%s reason=%s",
                    quote.bid_price,
                    quote.bid_quantity,
                    quote.ask_price,
                    quote.ask_quantity,
                    quote.reason,
                )

                current_signature = (
                    quote.bid_price,
                    quote.bid_quantity,
                    quote.ask_price,
                    quote.ask_quantity,
                )
                previous_signature = (
                    last_bid_price,
                    last_bid_qty,
                    last_ask_price,
                    last_ask_qty,
                )

                equity = PnLService.mark_to_market(
                    symbol=symbol,
                    inventory=inventory,
                    market=market,
                    timestamp=timestamp,
                )
                journal.record_equity(equity)

                logger.info(
                    "Market | bid=%s ask=%s spread=%s mid=%s",
                    market.best_bid_price,
                    market.best_ask_price,
                    market.spread,
                    market.mid_price,
                )
                logger.info(
                    "Inventory | base=%s quote=%s bias=%s equity=%s",
                    inventory.base_free,
                    inventory.quote_free,
                    inventory_bias,
                    equity.mark_to_market_equity,
                )
                log_order_state_snapshot(symbol=symbol, state_store=state_store, logger=logger)

                if current_signature == previous_signature:
                    logger.info("Quote unchanged. Skipping cancel/replace cycle.")

                    journal.record_cycle(
                        CycleSnapshot(
                            timestamp=timestamp,
                            symbol=symbol,
                            best_bid=market.best_bid_price,
                            best_ask=market.best_ask_price,
                            spread=market.spread,
                            mid_price=market.mid_price,
                            base_free=inventory.base_free,
                            quote_free=inventory.quote_free,
                            inventory_bias=inventory_bias,
                            proposed_bid=quote.bid_price,
                            proposed_ask=quote.ask_price,
                            proposed_bid_qty=quote.bid_quantity,
                            proposed_ask_qty=quote.ask_quantity,
                            canceled_orders=0,
                            decision_reason="quote_unchanged",
                        )
                    )

                    time.sleep(SLEEP_SECONDS)
                    continue

                tracked_open_orders = state_store.get_active_orders(symbol)
                for local_order in tracked_open_orders:
                    state_store.mark_cancel_requested(
                        OrderCancelRequestedEvent(
                            occurred_at=utc_now_iso(),
                            symbol=symbol,
                            order_id=local_order.order_id,
                        )
                    )

                canceled_orders = order_manager.cancel_all_open_orders(symbol)
                canceled_count = len(canceled_orders)
                logger.info("Canceled %s open orders", canceled_count)

                for canceled_payload in canceled_orders:
                    state_store.apply_status_sync(build_status_sync_event(canceled_payload))

                journal.record_cycle(
                    CycleSnapshot(
                        timestamp=timestamp,
                        symbol=symbol,
                        best_bid=market.best_bid_price,
                        best_ask=market.best_ask_price,
                        spread=market.spread,
                        mid_price=market.mid_price,
                        base_free=inventory.base_free,
                        quote_free=inventory.quote_free,
                        inventory_bias=inventory_bias,
                        proposed_bid=quote.bid_price,
                        proposed_ask=quote.ask_price,
                        proposed_bid_qty=quote.bid_quantity,
                        proposed_ask_qty=quote.ask_quantity,
                        canceled_orders=canceled_count,
                        decision_reason=quote.reason,
                    )
                )

                if quote.bid_price is None and quote.ask_price is None:
                    logger.info("No quote placed this cycle")

                    last_bid_price = quote.bid_price
                    last_ask_price = quote.ask_price
                    last_bid_qty = quote.bid_quantity
                    last_ask_qty = quote.ask_quantity

                    time.sleep(SLEEP_SECONDS)
                    continue

                if quote.bid_price is not None and quote.bid_quantity > 0:
                    buy_order = OrderRequest(
                        symbol=symbol,
                        side="BUY",
                        quantity=quote.bid_quantity,
                        price=quote.bid_price,
                    )
                    buy_result = order_manager.place_limit_order(buy_order, filters)
                    logger.info("BUY order placed: %s", buy_result)

                    placed_event = OrderPlacedEvent(
                        occurred_at=timestamp,
                        symbol=buy_result.symbol,
                        order_id=buy_result.order_id,
                        client_order_id=buy_result.client_order_id,
                        side=buy_result.side,
                        price=buy_result.price,
                        orig_qty=buy_result.orig_qty,
                        executed_qty=buy_result.executed_qty,
                        status=buy_result.status,
                        placed_at=buy_result.placed_at,
                    )
                    state_store.add_open_order(placed_event)

                    journal.record_order(
                        OrderPlacementRecord(
                            timestamp=timestamp,
                            symbol=buy_result.symbol,
                            side=buy_result.side,
                            order_id=buy_result.order_id,
                            client_order_id=buy_result.client_order_id,
                            status=buy_result.status,
                            price=buy_result.price,
                            quantity=buy_result.orig_qty,
                            executed_quantity=buy_result.executed_qty,
                            placed_at=buy_result.placed_at,
                        )
                    )

                if quote.ask_price is not None and quote.ask_quantity > 0:
                    sell_order = OrderRequest(
                        symbol=symbol,
                        side="SELL",
                        quantity=quote.ask_quantity,
                        price=quote.ask_price,
                    )
                    sell_result = order_manager.place_limit_order(sell_order, filters)
                    logger.info("SELL order placed: %s", sell_result)

                    placed_event = OrderPlacedEvent(
                        occurred_at=timestamp,
                        symbol=sell_result.symbol,
                        order_id=sell_result.order_id,
                        client_order_id=sell_result.client_order_id,
                        side=sell_result.side,
                        price=sell_result.price,
                        orig_qty=sell_result.orig_qty,
                        executed_qty=sell_result.executed_qty,
                        status=sell_result.status,
                        placed_at=sell_result.placed_at,
                    )
                    state_store.add_open_order(placed_event)

                    journal.record_order(
                        OrderPlacementRecord(
                            timestamp=timestamp,
                            symbol=sell_result.symbol,
                            side=sell_result.side,
                            order_id=sell_result.order_id,
                            client_order_id=sell_result.client_order_id,
                            status=sell_result.status,
                            price=sell_result.price,
                            quantity=sell_result.orig_qty,
                            executed_quantity=sell_result.executed_qty,
                            placed_at=sell_result.placed_at,
                        )
                    )

                refresh_tracked_orders(
                    symbol=symbol,
                    order_manager=order_manager,
                    state_store=state_store,
                    logger=logger,
                )
                log_order_state_snapshot(symbol=symbol, state_store=state_store, logger=logger)

                last_bid_price = quote.bid_price
                last_ask_price = quote.ask_price
                last_bid_qty = quote.bid_quantity
                last_ask_qty = quote.ask_quantity

                time.sleep(SLEEP_SECONDS)

            except BinanceAPIException as exc:
                logger.exception("Binance API error in loop: %s", exc)
                time.sleep(SLEEP_SECONDS)

            except Exception as exc:
                logger.exception("Market maker loop failed: %s", exc)
                time.sleep(SLEEP_SECONDS)

    except KeyboardInterrupt:
        logger.info("Stopping market maker...")
        try:
            refresh_tracked_orders(
                symbol=symbol,
                order_manager=order_manager,
                state_store=state_store,
                logger=logger,
            )

            tracked_open_orders = state_store.get_active_orders(symbol)
            for local_order in tracked_open_orders:
                state_store.mark_cancel_requested(
                    OrderCancelRequestedEvent(
                        occurred_at=utc_now_iso(),
                        symbol=symbol,
                        order_id=local_order.order_id,
                    )
                )

            canceled_orders = order_manager.cancel_all_open_orders(symbol)
            for canceled_payload in canceled_orders:
                state_store.apply_status_sync(build_status_sync_event(canceled_payload))

            log_order_state_snapshot(symbol=symbol, state_store=state_store, logger=logger)
            logger.info("Canceled %s open orders on shutdown", len(canceled_orders))
        except BinanceAPIException as exc:
            logger.exception("Failed during shutdown cancellation: %s", exc)


if __name__ == "__main__":
    main()