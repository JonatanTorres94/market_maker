#src/engine/maintenace_service.py
import time
from src.core.logger import setup_logger
from src.infrastructure.binance.order_mapper import to_domain_sync_event

class MaintenanceService:
    def __init__(self, symbol, infrastructure, order_manager, state_store, execution_service, session_start_ms, logger=None):
        self.symbol = symbol
        self.infra = infrastructure
        self.order_manager = order_manager
        self.state_store = state_store
        self.execution_service = execution_service
        self.session_start_ms = session_start_ms
        self.logger = logger or setup_logger("maintenance_service")
        
        self._last_rest_sync_at = 0.0
        self._last_execution_sync_at = 0.0

    def run_scheduled_tasks(self):
        if self._should_run_sync(): self.sync_orders()
        if self._should_run_execution_sync(): self.reconcile_executions()
        self.prune_terminal_cache()

    def _should_run_sync(self) -> bool:
        return (time.monotonic() - self._last_rest_sync_at) >= self.infra.rest_sync_interval_seconds

    def _should_run_execution_sync(self) -> bool:
        return (time.monotonic() - self._last_execution_sync_at) >= self.infra.rest_sync_interval_seconds

    def sync_orders(self):
        active_orders = self.state_store.get_active_orders(self.symbol)
        for local in active_orders:
            try:
                payload = self.order_manager.get_order(self.symbol, local.order_id)
                # Uso del mapper independiente, ya no importa al Coordinator
                event = to_domain_sync_event(payload)
                self.state_store.apply_status_sync(event)
            except Exception as e:
                self.logger.warning("Sync failed id=%s: %s", local.order_id, e)
        self._last_rest_sync_at = time.monotonic()

    def reconcile_executions(self):
        try:
            last_id = self.execution_service.get_last_reconciled_trade_id(self.symbol)
            start_time = None if last_id else self.session_start_ms
            self.execution_service.reconcile_symbol(self.symbol, start_time_ms=start_time)
        except Exception as e:
            self.logger.warning("Execution sync failed: %s", e)
        finally:
            self._last_execution_sync_at = time.monotonic()

    def prune_terminal_cache(self):
        if len(self.state_store.get_terminal_orders(self.symbol)) >= self.infra.local_terminal_cleanup_threshold:
            self.state_store.cleanup_terminal_orders()