#src/engine/market_making_engine.py
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Any, Optional

from binance import ThreadedWebsocketManager

from src.config.settings import InfrastructureSettings
from src.config.symbol_config import SymbolTradingConfig
from src.core.logger import setup_logger
from src.core.utils.time_utils import UTC, utc_now_iso

from src.domain.models import BestBidAsk, InventoryBias, InventoryPnL
from src.engine.execution_models import CycleState, ExecutionPlan, ExecutionOutcome
from src.engine.execution_service import ExecutionService
from src.engine.order_state_store import OrderStateStore
from src.engine.quote_lifecycle import (
    QuoteLifecycleConfig,
    QuoteLifecyclePolicy,
)
from src.engine.order_coordinator import OrderCoordinator
from src.engine.maintenance_service import MaintenanceService
from src.engine.order_validator import OrderValidator
from src.engine.cycle_recorder import CycleRecorder

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
        journal=None,
    ):
        self.logger = setup_logger("market_making_engine")
        self.infrastructure = infrastructure
        self.symbol_config = symbol_config
        self.symbol = symbol_config.symbol
        self._shutdown_started = False
        self._shutdown_completed = False

        # Infra / exchange
        self.exchange_info = ExchangeInfoService(client)
        self.order_manager = order_manager or OrderManager(client)
        self.execution_service = execution_service
        self.state_store = OrderStateStore()
        self.journal = journal if journal is not None else TradeJournal()
        self.filters = self.exchange_info.get_symbol_filters(self.symbol)

        # Servicios
        self.coordinator = OrderCoordinator(
            symbol=self.symbol,
            order_manager=self.order_manager,
            state_store=self.state_store,
            journal=self.journal,
            filters=self.filters,
            logger=self.logger,
        )
        self.validator = OrderValidator(self.filters)
        self.recorder = CycleRecorder(self.journal)

        session_start_ms = int(datetime.now(UTC).timestamp() * 1000)
        self.maintenance = MaintenanceService(
            symbol=self.symbol,
            infrastructure=self.infrastructure,
            order_manager=self.order_manager,
            state_store=self.state_store,
            execution_service=self.execution_service,
            session_start_ms=session_start_ms,
            logger=self.logger,
        )

        # Estrategia / riesgo
        self.risk_manager = RiskManager(
            min_base_inventory=symbol_config.min_base_inventory,
            max_base_inventory=symbol_config.max_base_inventory,
            min_quote_balance=symbol_config.min_quote_balance,
        )
        self.strategy = MarketMakerStrategy(
            config=MarketMakerConfig(
                base_quote_quantity=symbol_config.base_quote_quantity,
                min_spread=symbol_config.min_spread,
                quote_offset_bps=symbol_config.quote_offset_bps,
                inventory_target=symbol_config.inventory_target,
                inventory_tolerance=symbol_config.inventory_tolerance,
                max_inventory_skew_factor=symbol_config.max_inventory_skew_factor,
                drift_gate_lookback_seconds=symbol_config.drift_gate_lookback_seconds,
                drift_gate_threshold_bps=symbol_config.drift_gate_threshold_bps,
            ),
            risk_manager=self.risk_manager,
        )
        self.lifecycle = QuoteLifecyclePolicy(
            QuoteLifecycleConfig(
                replace_threshold_ticks=symbol_config.replace_threshold_ticks,
                quantity_rel_change_threshold=symbol_config.quantity_rel_change_threshold,
                max_quote_age_seconds=symbol_config.max_quote_age_seconds,
            )
        )
        self.drift_signal_detector = DriftSignalDetector(max_window_seconds=5)

        # Streams
        self.ws_manager = ThreadedWebsocketManager(
            api_key=infrastructure.binance_api_key,
            api_secret=infrastructure.binance_secret,
            testnet=infrastructure.binance_testnet,
        )
        self.market_stream = WsMarketDataStream(self.ws_manager)
        self.user_stream = WsUserDataStream(self.ws_manager)

    def run(self) -> None:
        self.logger.info("Starting engine for %s", self.symbol)
        self._start_streams()

        try:
            while not self._shutdown_started:
                try:
                    self.maintenance.run_scheduled_tasks()

                    state = self._capture_cycle_state()
                    if state is None:
                        continue
                    
                    self._log_inventory_snapshot(state)
                    self._record_equity_snapshot(state)

                    plan = self._build_execution_plan(state)
                    outcome = self._execute_plan(plan, state.timestamp)
                    self.recorder.record(state, plan, outcome)

                    time.sleep(self.infrastructure.engine_loop_sleep_seconds)

                except KeyboardInterrupt:
                    self.logger.info("KeyboardInterrupt received. Starting shutdown.")
                    break

                except Exception as exc:
                    self.logger.exception("Engine loop failed: %s", exc)
                    time.sleep(self.infrastructure.engine_loop_sleep_seconds)

        finally:
            self.shutdown()
    
    

    def _capture_cycle_state(self) -> CycleState | None:
        market_event = self.market_stream.get_latest_event(
            timeout=self.infrastructure.market_event_timeout_seconds
        )
        if not market_event:
            self.logger.warning("No market event received")
            return None

        timestamp = utc_now_iso()
        market = BestBidAsk(
            symbol=market_event.symbol,
            best_bid_price=market_event.best_bid,
            best_bid_qty=Decimal("0"),
            best_ask_price=market_event.best_ask,
            best_ask_qty=Decimal("0"),
        )
        context = self.drift_signal_detector.update(
            timestamp,
            market.mid_price,
            market.spread,
        )
        
        self.logger.info(
            "Context | drift_1s=%s drift_3s=%s drift_5s=%s vol_5s=%s",
            context.mid_return_1s_bps,
            context.mid_return_3s_bps,
            context.mid_return_5s_bps,
            context.volatility_5s_bps,
        )
        
        inventory = self.order_manager.get_inventory_state(self.symbol)

        return CycleState(
            timestamp=timestamp,
            symbol=self.symbol,
            market=market,
            context=context,
            inventory=inventory,
            inventory_bias=self.risk_manager.inventory_bias(inventory),
        )

    def _build_execution_plan(self, state: CycleState) -> ExecutionPlan:
        drift_bps = self._get_selected_drift(state.context)

        threshhold = self.symbol_config.drift_gate_threshold_bps
        dynamic_inventory_target = self.symbol_config.inventory_target

        if drift_bps >= threshhold:
            adjustment = Decimal("0.01") # limite duro (1% de BTC)
            (drift_bps / Decimal("10")) # escalamos el drift para que a 1000 bps (10%) ajuste el target en 1%

            if drift_bps < 0:
                dynamic_inventory_target = max(
                    self.symbol_config.min_base_inventory,
                    self.symbol_config.inventory_target - adjustment
                )
            else:
                dynamic_inventory_target = min(
                    self.symbol_config.max_base_inventory,
                    self.symbol_config.inventory_target + adjustment
                )


        quote = self.strategy.generate_quotes(
            state.market,
            state.inventory,
            state.context,
            inventory_target_override=dynamic_inventory_target,
        )

        buy_active = self.state_store.get_active_order_by_side(self.symbol, "BUY")
        sell_active = self.state_store.get_active_order_by_side(self.symbol, "SELL")

        buy_decision = self.lifecycle.decide_side(
            active_order=buy_active,
            target_price=quote.bid_price,
            target_quantity=quote.bid_quantity,
            tick_size=self.filters.tick_size,
            now_iso=state.timestamp,
            adverse_drift_bps=max(Decimal("0"), -drift_bps),
            adverse_drift_threshold_bps=self.symbol_config.drift_gate_threshold_bps,
        )

        sell_decision = self.lifecycle.decide_side(
            active_order=sell_active,
            target_price=quote.ask_price,
            target_quantity=quote.ask_quantity,
            tick_size=self.filters.tick_size,
            now_iso=state.timestamp,
            adverse_drift_bps=max(Decimal("0"), drift_bps),
            adverse_drift_threshold_bps=self.symbol_config.drift_gate_threshold_bps,
        )

        self.logger.info(
            "PLAN | drift=%s | dynamic_inventory_target=%s | buy_reason=%s | sell_reason=%s | bid_price=%s | bid_qty=%s | ask_price=%s | ask_qty=%s",
            drift_bps,
            dynamic_inventory_target,
            buy_decision.reason,
            sell_decision.reason,
            quote.bid_price,
            quote.bid_quantity,
            quote.ask_price,
            quote.ask_quantity,
        )

        return ExecutionPlan(
            quote=quote,
            buy_decision=buy_decision,
            sell_decision=sell_decision,
            drift_bps=drift_bps,
            decision_reason=(
                f"drift={drift_bps}|target={dynamic_inventory_target}|"
                f"BUY:{buy_decision.reason}|"
                f"SELL:{sell_decision.reason}"
            ),
        )

    def _execute_plan(self, plan: ExecutionPlan, timestamp: str) -> ExecutionOutcome:
        canceled_count = 0
        canceled_buy = 0
        canceled_sell = 0
        placed_count = 0

        buy_active = self.state_store.get_active_order_by_side(self.symbol, "BUY")
        sell_active = self.state_store.get_active_order_by_side(self.symbol, "SELL")

        # 1. Cancelaciones
        if plan.buy_decision.should_cancel and buy_active is not None:
            cancel_result = self.coordinator.cancel_order(buy_active.order_id)
            canceled_buy += cancel_result
            canceled_count += cancel_result

        if plan.sell_decision.should_cancel and sell_active is not None:
            cancel_result = self.coordinator.cancel_order(sell_active.order_id)
            canceled_sell += cancel_result
            canceled_count += cancel_result

        # 2. Validaciones y colocación BUY
        bid_ok, bid_reason = self.validator.validate_placeable(
            plan.quote.bid_price,
            plan.quote.bid_quantity,
        )
        if plan.buy_decision.should_place and bid_ok:
            self.coordinator.place_order(
                timestamp=timestamp,
                side="BUY",
                price=plan.quote.bid_price,
                quantity=plan.quote.bid_quantity,
            )
            placed_count += 1

        # 3. Validaciones y colocación SELL
        ask_ok, ask_reason = self.validator.validate_placeable(
            plan.quote.ask_price,
            plan.quote.ask_quantity,
        )
        if plan.sell_decision.should_place and ask_ok:
            self.coordinator.place_order(
                timestamp=timestamp,
                side="SELL",
                price=plan.quote.ask_price,
                quantity=plan.quote.ask_quantity,
            )
            placed_count += 1

        self.logger.info(
            "OUTCOME | canceled=%s | canceled_buy=%s | canceled_sell=%s | placed=%s | bid_ok=%s | ask_ok=%s | drift=%s",
            canceled_count,
            canceled_buy,
            canceled_sell,
            placed_count,
            bid_ok,
            ask_ok,
            plan.drift_bps,
        )

        return ExecutionOutcome(
            canceled_count=canceled_count,
            placed_count=placed_count,
            bid_ok=bid_ok,
            bid_reason=bid_reason or "",
            ask_ok=ask_ok,
            ask_reason=ask_reason or "",
            drift_bps=plan.drift_bps,
            canceled_buy=canceled_buy,
            canceled_sell=canceled_sell,
        )

    def _get_selected_drift(self, market_context: MarketContext) -> Decimal:
        lookback = self.symbol_config.drift_gate_lookback_seconds
        mapping = {
            1: market_context.mid_return_1s_bps,
            3: market_context.mid_return_3s_bps,
            5: market_context.mid_return_5s_bps,
        }
        if lookback not in mapping:
            raise ValueError(
                f"Unsupported drift_gate_lookback_seconds={lookback}. Expected 1, 3 or 5."
            )
        return mapping[lookback]

    def _log_inventory_snapshot(self, state: CycleState) -> None:
        """
        Loguea el estado actual del inventario y equity.
        """
        inv = state.inventory
        equity = self._compute_equity(state)
        bias_label = self._inventory_bias_label(state.inventory_bias)

        self.logger.info(
            "Inventory | base_total=%s quote_total=%s | bias=%s | equity=%s",
            inv.base_total,
            inv.quote_total,
            bias_label,
            equity
        )

    def _record_equity_snapshot(self, state: CycleState) -> None:
            """
            Persiste un snapshot de inventory/equity en el journal usando la Dataclass correcta.
            """
            equity = self._compute_equity(state)

            # Creamos el registro estructurado que el Journal espera
            record = InventoryPnL(
                timestamp=state.timestamp,
                symbol=state.symbol,
                base_free=state.inventory.base_free,
                base_locked=state.inventory.base_locked,
                base_total=state.inventory.base_total,
                quote_free=state.inventory.quote_free,
                quote_locked=state.inventory.quote_locked,
                quote_total=state.inventory.quote_total,
                mid_price=state.market.mid_price,
                mark_to_market_equity=equity
            )

            # Ahora pasamos el objeto, no argumentos sueltos
            self.journal.record_equity(record)

    def _compute_equity(self, state: CycleState) -> Decimal:
        """
        Calcula el valor total de la cartera en moneda de cotización (Quote).
        """
        try:
            # Usamos los datos que ya vienen en el objeto 'state'
            base_total = Decimal(str(state.inventory.base_total))
            mid_price = Decimal(str(state.market.mid_price))
            quote_total = Decimal(str(state.inventory.quote_total))
            
            return (base_total * mid_price) + quote_total
        except Exception:
            return Decimal("0")

    def _inventory_bias_label(self, bias: InventoryBias) -> str:
        """
        Retorna la representación en texto del Enum InventoryBias.
        """
        # Si 'bias' es el Enum que definimos, solo retornamos su valor string
        return bias.value if hasattr(bias, 'value') else str(bias)

    def _start_streams(self) -> None:
        self.ws_manager.start()
        self.market_stream.start(self.symbol)
        self.user_stream.start()
    
    def _stop_streams(self) -> None:
        try:
            self.market_stream.stop()
        except Exception as exc:
            self.logger.warning("Error stopping market stream: %s", exc)

        try:
            self.user_stream.stop()
        except Exception as exc:
            self.logger.warning("Error stopping user stream: %s", exc)

        try:
            self.ws_manager.stop()
        except Exception as exc:
            self.logger.warning("Error stopping websocket manager: %s", exc)

    def shutdown(self) -> None:
        if self._shutdown_completed:
            return

        if self._shutdown_started:
            return

        self._shutdown_started = True

        try:
            self.logger.info("Initiating graceful shutdown...")
            self.maintenance.sync_orders()

            canceled_count = 0
            active_orders = self.state_store.get_active_orders(self.symbol)

            for order in active_orders:
                canceled_count += self.coordinator.cancel_order(order.order_id)

            self.logger.info("Canceled %s active orders on shutdown", canceled_count)
            self.maintenance.sync_orders()
            self.maintenance.reconcile_executions()

        except Exception as exc:
            self.logger.exception("Error during shutdown: %s", exc)

        finally:
            try:
                self._stop_streams()
            except Exception as exc:
                self.logger.warning("Error stopping streams: %s", exc)
            finally:
                self._shutdown_completed = True
                self.logger.info("Engine shutdown complete.")