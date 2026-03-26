# src/engine/market_making_engine.py
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional

from binance import ThreadedWebsocketManager
from binance.exceptions import BinanceAPIException


from src.analytics.pnl import PnLService
from src.config.settings import InfrastructureSettings
from src.config.symbol_config import SymbolTradingConfig

from src.core.exceptions import InvalidOrderRequestError
from src.core.logger import setup_logger
from src.core.utils.time_utils import exchange_ms_to_iso, utc_now_iso

from src.domain.events import (
    ExecutionReceivedEvent,
    OrderCancelRequestedEvent,
    OrderPlacedEvent,
    OrderStatusSyncedEvent,
)
from src.domain.execution import Execution
from src.domain.models import BestBidAsk, CycleSnapshot, OrderPlacementRecord, OrderRequest
from src.engine.execution_service import ExecutionService
from src.engine.order_state_store import OrderStateStore
from src.engine.quote_lifecycle import QuoteLifecycleConfig, QuoteLifecyclePolicy
from src.exchange.exchange_info import ExchangeInfoService
from src.exchange.order_manager import OrderManager
from src.exchange.ws_market_stream import WsMarketDataStream
from src.exchange.ws_user_stream import WsUserDataStream
from src.journal.trade_journal import TradeJournal
from src.risk.risk_manager import RiskManager
from src.strategies.market_context import DriftSignalDetector, MarketContext
from src.strategies.market_maker import MarketMakerConfig, MarketMakerStrategy


class MarketMakingEngine:
    def __init__(
        self,
        client,
        infrastructure: InfrastructureSettings,
        symbol_config: SymbolTradingConfig,
        execution_service: ExecutionService,
        order_manager: OrderManager | None = None,
    ):
        self.logger = setup_logger("market_making_engine")
        self.client = client
        self.infrastructure = infrastructure
        self.symbol_config = symbol_config
        self.symbol = symbol_config.symbol

        self.exchange_info = ExchangeInfoService(client)
        self.order_manager = order_manager or OrderManager(client)
        self.execution_service = execution_service

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
                quote_offset_bps=self.symbol_config.quote_offset_bps,
                inventory_target=self.symbol_config.inventory_target,
                inventory_tolerance=self.symbol_config.inventory_tolerance,
                max_inventory_skew_factor=self.symbol_config.max_inventory_skew_factor,
                drift_gate_lookback_seconds=self.symbol_config.drift_gate_lookback_seconds,
                drift_gate_threshold_bps=self.symbol_config.drift_gate_threshold_bps,
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

        self.drift_signal_detector = DriftSignalDetector(max_window_seconds=5)
        self.latest_market_context: MarketContext | None = None
        self._last_rest_sync_at = 0.0
        self._last_execution_rest_sync_at = 0.0
        self._execution_session_start_ms = int(datetime.now(UTC).timestamp() * 1000)
        self._ws_started = False
        self._shutdown_started = False
        self._shutdown_completed = False
    
    def _is_order_placeable(
        self,
        side: str,
        price: Decimal | None,
        quantity: Decimal,
    ) -> tuple[bool, str | None]:
        if price is None or quantity <= 0:
            return False, "price_or_quantity_disabled"

        normalized_price = self.order_manager.normalize_price(price, self.filters)
        normalized_quantity = self.order_manager.normalize_quantity(quantity, self.filters)

        if normalized_quantity < self.filters.min_qty:
            return False, (
                f"normalized_qty_below_min_qty:"
                f"{normalized_quantity}<{self.filters.min_qty}"
            )

        notional = normalized_price * normalized_quantity
        if self.filters.min_notional > 0 and notional < self.filters.min_notional:
            return False, (
                f"normalized_notional_below_min_notional:"
                f"{notional}<{self.filters.min_notional}"
            )

        return True, None

    def _selected_drift_bps(self, market_context: MarketContext) -> Decimal:
        lookback_seconds = self.symbol_config.drift_gate_lookback_seconds

        if lookback_seconds == 1:
            return market_context.mid_return_1s_bps
        if lookback_seconds == 3:
            return market_context.mid_return_3s_bps
        if lookback_seconds == 5:
            return market_context.mid_return_5s_bps

        raise ValueError(
            f"Unsupported drift_gate_lookback_seconds={lookback_seconds}. "
            "Expected 1, 3 or 5."
    )

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

                        if self._should_run_execution_rest_sync():
                            self._reconcile_executions_via_rest()

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

                        market_context = self.drift_signal_detector.update(
                            timestamp_iso=timestamp,
                            mid_price=market.mid_price,
                            spread=market.spread,
                        )
                        self.latest_market_context = market_context

                        inventory = self.order_manager.get_inventory_state(self.symbol)
                        inventory_bias = self.risk_manager.inventory_bias(inventory)

                        quote = self.strategy.generate_quotes(
                            market=market,
                            inventory=inventory,
                            market_context=market_context,
                        )

                        self.logger.info(
                            "Quote decision | mode=%s bid=%s bid_qty=%s ask=%s ask_qty=%s reason=%s",
                            quote.participation_mode,
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
                            "Inventory | base_total=%s quote_total=%s bias=%s equity=%s",
                            inventory.base_total,
                            inventory.quote_total,
                            inventory_bias,
                            equity.mark_to_market_equity,
                        )
                        self._log_local_state()

                        buy_active = self.state_store.get_active_order_by_side(self.symbol, "BUY")
                        sell_active = self.state_store.get_active_order_by_side(self.symbol, "SELL")

                        selected_drift_bps = self._selected_drift_bps(market_context)

                        buy_adverse_drift_bps = max(Decimal("0"), -selected_drift_bps)
                        sell_adverse_drift_bps = max(Decimal("0"), selected_drift_bps)

                        buy_decision = self.lifecycle.decide_side(
                            active_order=buy_active,
                            target_price=quote.bid_price,
                            target_quantity=quote.bid_quantity,
                            tick_size=self.filters.tick_size,
                            now_iso=timestamp,
                            adverse_drift_bps=buy_adverse_drift_bps,
                            adverse_drift_threshold_bps=self.symbol_config.drift_gate_threshold_bps,
                        )

                        sell_decision = self.lifecycle.decide_side(
                            active_order=sell_active,
                            target_price=quote.ask_price,
                            target_quantity=quote.ask_quantity,
                            tick_size=self.filters.tick_size,
                            now_iso=timestamp,
                            adverse_drift_bps=sell_adverse_drift_bps,
                            adverse_drift_threshold_bps=self.symbol_config.drift_gate_threshold_bps,
                        )

                        decision_reason = f"BUY:{buy_decision.reason}|SELL:{sell_decision.reason}"
                        canceled_count = 0

                        if buy_decision.should_cancel and buy_active is not None:
                            canceled_count += self._cancel_specific_order(buy_active.order_id)

                        if sell_decision.should_cancel and sell_active is not None:
                            canceled_count += self._cancel_specific_order(sell_active.order_id)
                        
                        bid_placeable = False
                        ask_placeable = False
                        bid_block_reason = ""
                        ask_block_reason = ""

                        if quote.bid_price is not None and quote.bid_quantity > 0:
                            bid_placeable, buy_block_reason = self._is_order_placeable(
                                side="BUY",
                                price=quote.bid_price,
                                quantity=quote.bid_quantity,
                            )
                            bid_block_reason = "" if bid_placeable else (buy_block_reason or "")

                        if quote.ask_price is not None and quote.ask_quantity > 0:
                            ask_placeable, sell_block_reason = self._is_order_placeable(
                                side="SELL",
                                price=quote.ask_price,
                                quantity=quote.ask_quantity,
                            )
                            ask_block_reason = "" if ask_placeable else (sell_block_reason or "")

                        self.journal.record_cycle(
                            CycleSnapshot(
                                timestamp=timestamp,
                                symbol=self.symbol,
                                best_bid=market.best_bid_price,
                                best_ask=market.best_ask_price,
                                spread=market.spread,
                                mid_price=market.mid_price,
                                mid_return_1s_bps=market_context.mid_return_1s_bps,
                                mid_return_3s_bps=market_context.mid_return_3s_bps,
                                mid_return_5s_bps=market_context.mid_return_5s_bps,
                                volatility_5s_bps=market_context.volatility_5s_bps,
                                base_free=inventory.base_free,
                                base_locked=inventory.base_locked,
                                base_total=inventory.base_total,
                                quote_free=inventory.quote_free,
                                quote_locked=inventory.quote_locked,
                                quote_total=inventory.quote_total,
                                inventory_bias=inventory_bias,
                                participation_mode=quote.participation_mode.value,
                                proposed_bid=quote.bid_price,
                                proposed_ask=quote.ask_price,
                                proposed_bid_qty=quote.bid_quantity,
                                proposed_ask_qty=quote.ask_quantity,
                                bid_placeable=bid_placeable,
                                ask_placeable=ask_placeable,
                                bid_block_reason=bid_block_reason,
                                ask_block_reason=ask_block_reason,
                                canceled_orders=canceled_count,
                                decision_reason=decision_reason,
                            )
                        )

                        # --- LÓGICA DE EJECUCIÓN CORREGIDA ---

                        # 1. Procesar COMPRA (BUY)
                        if buy_decision.should_place and quote.bid_price is not None and quote.bid_quantity > 0:
                            if not bid_placeable:
                                self.logger.info(
                                    "Suppressed non-placeable BUY quote | price=%s qty=%s reason=%s",
                                    quote.bid_price, quote.bid_quantity, bid_block_reason
                                )
                            else:
                                try:
                                    self._place_order(
                                        timestamp=timestamp,
                                        side="BUY",
                                        price=quote.bid_price,
                                        quantity=quote.bid_quantity,
                                    )
                                except InvalidOrderRequestError as exc:
                                    self.logger.warning("Skipped invalid BUY order: %s", exc)

                        # 2. Procesar VENTA (SELL)
                        if sell_decision.should_place and quote.ask_price is not None and quote.ask_quantity > 0:
                            if not ask_placeable:
                                self.logger.info(
                                    "Suppressed non-placeable SELL quote | price=%s qty=%s reason=%s",
                                    quote.ask_price, quote.ask_quantity, ask_block_reason
                                )
                            else:
                                try:
                                    self._place_order(
                                        timestamp=timestamp,
                                        side="SELL",
                                        price=quote.ask_price,
                                        quantity=quote.ask_quantity,
                                    )
                                except InvalidOrderRequestError as exc:
                                    self.logger.warning("Skipped invalid SELL order: %s", exc)

                        # --- FIN LÓGICA DE EJECUCIÓN ---

                        self._apply_user_stream_events()

                        if self._should_run_rest_sync(force=True):
                            self._sync_active_orders_via_rest()

                        if self._should_run_execution_rest_sync(force=True):
                            self._reconcile_executions_via_rest()

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
                self.logger.info("Engine loop interrupted by termination signal.")
                raise

    def shutdown(self) -> None:
        if self._shutdown_completed:
            self.logger.info("Shutdown already completed. Ignoring duplicate shutdown call.")
            return

        if self._shutdown_started:
            self.logger.info("Shutdown already in progress. Ignoring duplicate shutdown call.")
            return

        self._shutdown_started = True

        try:
            self.logger.info("Initiating graceful shutdown...")

            # 1. Drenar eventos pendientes del user stream para no perder fills recientes.
            self._apply_user_stream_events()

            # 2. Reconciliar executions de sesión antes de tocar órdenes.
            self._reconcile_executions_via_rest()

            # 3. Sincronizar estado actual de órdenes.
            self._sync_active_orders_via_rest()

            # 4. Cancelar todas las órdenes activas que sigan trackeadas.
            canceled_count = self._cancel_all_tracked_active_orders()
            self.logger.info("Canceled %s active orders on shutdown", canceled_count)

            # 5. Re-drenar por si entraron updates/fills durante la cancelación.
            self._apply_user_stream_events()

            # 6. Reconciliar executions otra vez para capturar cualquier trade tardío.
            self._reconcile_executions_via_rest()

            # 7. Sync final de órdenes post-cancel.
            self._sync_active_orders_via_rest()

            # 8. Log final del estado.
            self._log_local_state()

        except Exception as exc:
            self.logger.exception("Error during shutdown: %s", exc)
        finally:
            try:
                self._stop_streams()
            finally:
                self._shutdown_completed = True
                self.logger.info("Engine shutdown complete.")

    def _start_streams(self) -> None:
        if self._shutdown_started:
            raise RuntimeError("Cannot start streams after shutdown has started.")

        if self._ws_started:
            return

        self.ws_manager.start()
        self.market_stream.start(self.symbol)
        self.user_stream.start()
        self._ws_started = True

    def _stop_streams(self) -> None:
        if not self._ws_started:
            self.logger.info("Stream shutdown skipped because streams are already stopped.")
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
            self.logger.debug("Skipping cancel for unknown local order_id=%s", order_id)
            return 0

        if local_order.is_terminal:
            self.logger.debug(
                "Skipping cancel for terminal local order_id=%s status=%s",
                order_id,
                local_order.status,
            )
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
            self.logger.info(
                "Cancel returned no payload for order_id=%s. Assuming already closed or missing on exchange.",
                order_id,
            )
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

        status_events_applied = 0
        new_executions_recorded = 0
        updated_executions_recorded = 0
        duplicate_executions_ignored = 0

        for event in events:
            if event.symbol != self.symbol:
                continue

            if isinstance(event, OrderStatusSyncedEvent):
                self.state_store.apply_status_sync(event)
                status_events_applied += 1
                continue

            if isinstance(event, ExecutionReceivedEvent):
                execution = Execution(
                    exchange=event.exchange,
                    account=event.account,
                    symbol=event.symbol,
                    trade_id=event.trade_id,
                    order_id=event.order_id,
                    client_order_id=event.client_order_id,
                    side=event.side,
                    price=event.price,
                    qty=event.qty,
                    quote_qty=event.quote_qty,
                    commission=event.commission,
                    commission_asset=event.commission_asset,
                    commission_in_quote=None,
                    commission_fx_rate=None,
                    commission_fx_symbol=None,
                    commission_fx_timestamp=None,
                    is_maker=event.is_maker,
                    executed_at=event.executed_at,
                    source=event.source,
                )

                result = self.execution_service.on_stream_execution(execution)
                if result.inserted:
                    new_executions_recorded += 1
                elif result.updated:
                    updated_executions_recorded += 1
                else:
                    duplicate_executions_ignored += 1

        self.logger.info(
            "Applied user stream events | status_updates=%s new_executions=%s updated_executions=%s duplicate_executions=%s total_events=%s",
            status_events_applied,
            new_executions_recorded,
            updated_executions_recorded,
            duplicate_executions_ignored,
            len(events),
        )

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

    def _reconcile_executions_via_rest(self) -> None:
        try:
            last_trade_id = self.execution_service.get_last_reconciled_trade_id(self.symbol)

            start_time_ms = None
            if last_trade_id is None:
                start_time_ms = self._execution_session_start_ms

            summary = self.execution_service.reconcile_symbol(
                symbol=self.symbol,
                start_time_ms=start_time_ms,
                limit=1000,
                max_pages=1,
            )

            self.logger.info(
                "Execution REST sync | fetched=%s inserted=%s updated=%s duplicates=%s pages=%s range=[%s,%s] start_time_ms=%s last_trade_id_before=%s last_trade_id_after=%s",
                summary.fetched,
                summary.inserted,
                summary.updated,
                summary.duplicates,
                summary.pages_fetched,
                summary.from_trade_id,
                summary.to_trade_id,
                summary.used_start_time_ms,
                last_trade_id,
                self.execution_service.get_last_reconciled_trade_id(self.symbol),
            )
        except BinanceAPIException as exc:
            self.logger.warning(
                "Execution REST reconciliation failed for symbol=%s: %s",
                self.symbol,
                exc,
            )
        finally:
            self._last_execution_rest_sync_at = time.monotonic()

    def _should_run_rest_sync(self, force: bool = False) -> bool:
        if force:
            return True

        elapsed = time.monotonic() - self._last_rest_sync_at
        return elapsed >= self.infrastructure.rest_sync_interval_seconds

    def _should_run_execution_rest_sync(self, force: bool = False) -> bool:
        if force:
            return True

        elapsed = time.monotonic() - self._last_execution_rest_sync_at
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

        execution_position = self.execution_service.get_position(self.symbol)
        execution_avg_cost = self.execution_service.get_avg_cost(self.symbol)
        execution_realized_pnl = self.execution_service.get_realized_pnl(self.symbol)
        execution_count = self.execution_service.get_total_executions(self.symbol)
        last_reconciled_trade_id = self.execution_service.get_last_reconciled_trade_id(self.symbol)

        self.logger.info(
            "Local order state | active=%s terminal=%s counts=%s",
            active_count,
            terminal_count,
            counts,
        )
        self.logger.info(
            "Execution financial state | position=%s avg_cost=%s realized_pnl=%s applied_executions=%s last_trade_id=%s session_start_ms=%s",
            execution_position,
            execution_avg_cost,
            execution_realized_pnl,
            execution_count,
            last_reconciled_trade_id,
            self._execution_session_start_ms,
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
