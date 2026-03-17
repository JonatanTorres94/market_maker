import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional

from binance import ThreadedWebsocketManager
from binance.exceptions import BinanceAPIException

from src.analytics.pnl import PnLService
from src.config.settings import InfrastructureSettings
from src.config.symbol_config import SymbolTradingConfig
from src.core.logger import setup_logger
from src.domain.events import OrderCancelRequestedEvent, OrderPlacedEvent, OrderStatusSyncedEvent
from src.domain.models import BestBidAsk, CycleSnapshot, OrderPlacementRecord, OrderRequest
from src.engine.order_state_store import OrderStateStore
from src.engine.quote_lifecycle import QuoteLifecycleConfig, QuoteLifecyclePolicy
from src.exchange.exchange_info import ExchangeInfoService
from src.exchange.order_manager import OrderManager
from src.exchange.ws_market_stream import WsMarketDataStream
from src.exchange.ws_user_stream import WsUserDataStream
from src.journal.trade_journal import TradeJournal
from src.risk.risk_manager import RiskManager
from src.strategies.market_maker import MarketMakerConfig, MarketMakerStrategy


class MarketMakingEngine:
    def __init__(
        self,
        client,
        infrastructure: InfrastructureSettings,
        symbol_config: SymbolTradingConfig,
    ):
        self.logger = setup_logger("market_making_engine")
        self.client = client
        self.infrastructure = infrastructure
        self.symbol_config = symbol_config
        self.symbol = symbol_config.symbol

        self.exchange_info = ExchangeInfoService(client)
        self.order_manager = OrderManager(client)
        self.journal = TradeJournal()
        self.state_store = OrderStateStore()

        self.ws_manager = ThreadedWebsocketManager(
            api_key=self.infrastructure.binance_api_key,
            api_secret=self.infrastructure.binance_secret,
            testnet=self.infrastructure.binance_testnet,
        )

        self.market_stream = WsMarketDataStream(self.ws_manager)
        self.user_stream = WsUserDataStream(self.ws_manager)

        self.filters = self.exchange_info.get_symbol_filters(self.symbol)

        self.risk_manager = RiskManager(
            min_base_inventory=self.symbol_config.min_base_inventory,
            max_base_inventory=self.symbol_config.max_base_inventory,
            min_quote_balance=self.symbol_config.min_quote_balance,
        )

        self.strategy = MarketMakerStrategy(
            config=MarketMakerConfig(
                base_quote_quantity=self.symbol_config.base_quote_quantity,
                min_spread=self.symbol_config.min_spread,
                inventory_target=self.symbol_config.inventory_target,
                inventory_tolerance=self.symbol_config.inventory_tolerance,
                max_inventory_skew_factor=self.symbol_config.max_inventory_skew_factor,
            ),
            risk_manager=self.risk_manager,
        )

        self.lifecycle = QuoteLifecyclePolicy(
            QuoteLifecycleConfig(
                replace_threshold_ticks=self.symbol_config.replace_threshold_ticks,
                quantity_rel_change_threshold=self.symbol_config.quantity_rel_change_threshold,
                max_quote_age_seconds=self.symbol_config.max_quote_age_seconds,
            )
        )

        self._last_rest_sync_at = 0.0
        self._ws_started = False

    def run(self) -> None:
        self.logger.info("Starting market making engine for %s", self.symbol)
        self.logger.info("Symbol config: %s", self.symbol_config)

        self._start_streams()

        try:
            while True:
                try:
                    self._apply_user_stream_events()

                    if self._should_run_rest_sync():
                        self._sync_active_orders_via_rest()

                    market_event = self.market_stream.get_latest_event(
                        timeout=self.infrastructure.market_event_timeout_seconds
                    )

                    if market_event is None:
                        self.logger.warning("No market websocket event received within timeout window")
                        time.sleep(self.infrastructure.engine_loop_sleep_seconds)
                        continue

                    market = BestBidAsk(
                        symbol=market_event.symbol,
                        best_bid_price=market_event.best_bid,
                        best_bid_qty=Decimal("0"),
                        best_ask_price=market_event.best_ask,
                        best_ask_qty=Decimal("0"),
                    )

                    timestamp = utc_now_iso()
                    inventory = self.order_manager.get_inventory_state(self.symbol)
                    inventory_bias = self.risk_manager.inventory_bias(inventory)

                    quote = self.strategy.generate_quotes(market=market, inventory=inventory)

                    self.logger.info(
                        "Quote decision | bid=%s bid_qty=%s ask=%s ask_qty=%s reason=%s",
                        quote.bid_price,
                        quote.bid_quantity,
                        quote.ask_price,
                        quote.ask_quantity,
                        quote.reason,
                    )

                    equity = PnLService.mark_to_market(
                        symbol=self.symbol,
                        inventory=inventory,
                        market=market,
                        timestamp=timestamp,
                    )
                    self.journal.record_equity(equity)

                    self.logger.info(
                        "Market | bid=%s ask=%s spread=%s mid=%s",
                        market.best_bid_price,
                        market.best_ask_price,
                        market.spread,
                        market.mid_price,
                    )
                    self.logger.info(
                        "Inventory | base=%s quote=%s bias=%s equity=%s",
                        inventory.base_free,
                        inventory.quote_free,
                        inventory_bias,
                        equity.mark_to_market_equity,
                    )
                    self._log_local_state()

                    buy_active = self.state_store.get_active_order_by_side(self.symbol, "BUY")
                    sell_active = self.state_store.get_active_order_by_side(self.symbol, "SELL")

                    buy_decision = self.lifecycle.decide_side(
                        active_order=buy_active,
                        target_price=quote.bid_price,
                        target_quantity=quote.bid_quantity,
                        tick_size=self.filters.tick_size,
                        now_iso=timestamp,
                    )
                    sell_decision = self.lifecycle.decide_side(
                        active_order=sell_active,
                        target_price=quote.ask_price,
                        target_quantity=quote.ask_quantity,
                        tick_size=self.filters.tick_size,
                        now_iso=timestamp,
                    )

                    decision_reason = f"BUY:{buy_decision.reason}|SELL:{sell_decision.reason}"
                    canceled_count = 0

                    if buy_decision.should_cancel and buy_active is not None:
                        canceled_count += self._cancel_specific_order(buy_active.order_id)

                    if sell_decision.should_cancel and sell_active is not None:
                        canceled_count += self._cancel_specific_order(sell_active.order_id)

                    self.journal.record_cycle(
                        CycleSnapshot(
                            timestamp=timestamp,
                            symbol=self.symbol,
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
                            decision_reason=decision_reason,
                        )
                    )

                    if buy_decision.should_place and quote.bid_price is not None and quote.bid_quantity > 0:
                        self._place_order(
                            timestamp=timestamp,
                            side="BUY",
                            price=quote.bid_price,
                            quantity=quote.bid_quantity,
                        )

                    if sell_decision.should_place and quote.ask_price is not None and quote.ask_quantity > 0:
                        self._place_order(
                            timestamp=timestamp,
                            side="SELL",
                            price=quote.ask_price,
                            quantity=quote.ask_quantity,
                        )

                    self._apply_user_stream_events()
                    if self._should_run_rest_sync(force=True):
                        self._sync_active_orders_via_rest()

                    self._log_local_state()
                    self._prune_terminal_cache_if_needed()

                    time.sleep(self.infrastructure.engine_loop_sleep_seconds)

                except BinanceAPIException as exc:
                    self.logger.exception("Binance API error in engine loop: %s", exc)
                    time.sleep(self.infrastructure.engine_loop_sleep_seconds)

                except Exception as exc:
                    self.logger.exception("Engine loop failed: %s", exc)
                    time.sleep(self.infrastructure.engine_loop_sleep_seconds)

        except KeyboardInterrupt:
            self.logger.info("Stopping engine...")
            self.shutdown()

    def shutdown(self) -> None:
        try:
            self.logger.info("Initiating graceful shutdown...")
            self._apply_user_stream_events()
            self._sync_active_orders_via_rest()

            canceled_count = self._cancel_all_tracked_active_orders()
            self.logger.info("Canceled %s active orders on shutdown", canceled_count)

            self._sync_active_orders_via_rest()
            self._log_local_state()
        except Exception as exc:
            self.logger.exception("Error during shutdown: %s", exc)
        finally:
            self._stop_streams()
            self.logger.info("Engine shutdown complete.")
    def _start_streams(self) -> None:
        if self._ws_started:
            return

        self.ws_manager.start()
        self.market_stream.start(self.symbol)
        self.user_stream.start()
        self._ws_started = True

    def _stop_streams(self) -> None:
        if not self._ws_started:
            return

        try:
            self.market_stream.stop()
            self.user_stream.stop()
            self.ws_manager.stop()
        except Exception as exc:
            self.logger.exception("Error stopping WebSocket streams: %s", exc)
        finally:
            self._ws_started = False

    def _place_order(self, timestamp: str, side: str, price: Decimal, quantity: Decimal) -> None:
        request = OrderRequest(
            symbol=self.symbol,
            side=side,
            quantity=quantity,
            price=price,
        )

        result = self.order_manager.place_limit_order(request, self.filters)
        self.logger.info("%s order placed: %s", side, result)

        placed_event = OrderPlacedEvent(
            occurred_at=timestamp,
            symbol=result.symbol,
            order_id=result.order_id,
            client_order_id=result.client_order_id,
            side=result.side,
            price=result.price,
            orig_qty=result.orig_qty,
            executed_qty=result.executed_qty,
            status=result.status,
            placed_at=result.placed_at,
        )
        self.state_store.add_open_order(placed_event)

        self.journal.record_order(
            OrderPlacementRecord(
                timestamp=timestamp,
                symbol=result.symbol,
                side=result.side,
                order_id=result.order_id,
                client_order_id=result.client_order_id,
                status=result.status,
                price=result.price,
                quantity=result.orig_qty,
                executed_quantity=result.executed_qty,
                placed_at=result.placed_at,
            )
        )

    def _cancel_specific_order(self, order_id: int) -> int:
        local_order = self.state_store.get_order(order_id)
        if local_order is None:
            return 0

        self.state_store.mark_cancel_requested(
            OrderCancelRequestedEvent(
                occurred_at=utc_now_iso(),
                symbol=self.symbol,
                order_id=order_id,
            )
        )

        payload = self.order_manager.cancel_order(symbol=self.symbol, order_id=order_id)
        if payload is None:
            return 0

        self.state_store.apply_status_sync(self._build_status_sync_event(payload))
        self.logger.info("Canceled specific order_id=%s", order_id)
        return 1

    def _cancel_all_tracked_active_orders(self) -> int:
        tracked_active = self.state_store.get_active_orders(self.symbol)

        canceled_count = 0
        for local_order in tracked_active:
            canceled_count += self._cancel_specific_order(local_order.order_id)

        return canceled_count

    def _apply_user_stream_events(self) -> None:
        events = self.user_stream.drain_events()
        if not events:
            return

        for event in events:
            if event.symbol != self.symbol:
                continue
            self.state_store.apply_status_sync(event)

        self.logger.info("Applied %s execution report events from user stream", len(events))

    def _sync_active_orders_via_rest(self) -> None:
        active_orders = self.state_store.get_active_orders(self.symbol)

        if not active_orders:
            self._last_rest_sync_at = time.monotonic()
            return

        for local_order in active_orders:
            try:
                payload = self.order_manager.get_order(
                    symbol=self.symbol,
                    order_id=local_order.order_id,
                )
                self.state_store.apply_status_sync(self._build_status_sync_event(payload))
            except BinanceAPIException as exc:
                self.logger.warning(
                    "REST sync failed for order_id=%s: %s",
                    local_order.order_id,
                    exc,
                )

        self._last_rest_sync_at = time.monotonic()

    def _should_run_rest_sync(self, force: bool = False) -> bool:
        if force:
            return True

        elapsed = time.monotonic() - self._last_rest_sync_at
        return elapsed >= self.infrastructure.rest_sync_interval_seconds

    def _prune_terminal_cache_if_needed(self) -> None:
        terminal_count = len(self.state_store.get_terminal_orders(self.symbol))
        threshold = self.infrastructure.local_terminal_cleanup_threshold

        if terminal_count < threshold:
            return

        self.state_store.cleanup_terminal_orders()
        self.logger.info(
            "Pruned terminal local order cache after reaching threshold=%s",
            threshold,
        )

    def _log_local_state(self) -> None:
        counts = self.state_store.status_counts(self.symbol)
        active_count = len(self.state_store.get_active_orders(self.symbol))
        terminal_count = len(self.state_store.get_terminal_orders(self.symbol))

        market_health = self.market_stream.health()
        user_health = self.user_stream.health()

        self.logger.info(
            "Local order state | active=%s terminal=%s counts=%s",
            active_count,
            terminal_count,
            counts,
        )
        self.logger.info(
            "Stream health | market_msgs=%s market_parse_errors=%s user_msgs=%s exec_reports=%s user_parse_errors=%s",
            market_health.messages_received,
            market_health.parse_errors,
            user_health.messages_received,
            user_health.execution_reports_received,
            user_health.parse_errors,
        )

    @staticmethod
    def _build_status_sync_event(order_payload: dict) -> OrderStatusSyncedEvent:
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


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def exchange_ms_to_iso(value: Optional[int]) -> str:
    if value is None:
        return utc_now_iso()
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
