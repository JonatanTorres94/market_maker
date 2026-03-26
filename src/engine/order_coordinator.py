from decimal import Decimal

from src.core.logger import setup_logger
from src.core.utils.time_utils import utc_now_iso
from src.domain.events import (
    OrderPlacedEvent,
    OrderCancelRequestedEvent,
)
from src.domain.models import (
    OrderPlacementRecord,
    OrderRequest,
)
from src.infrastructure.binance.order_mapper import to_domain_sync_event


class OrderCoordinator:
    def __init__(
        self,
        symbol,
        order_manager,
        state_store,
        journal,
        filters,
        logger=None,
    ):
        self.symbol = symbol
        self.order_manager = order_manager
        self.state_store = state_store
        self.journal = journal
        self.filters = filters
        self.logger = logger or setup_logger("order_coordinator")

    def place_order(
        self,
        timestamp: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
    ) -> None:
        request = OrderRequest(
            symbol=self.symbol,
            side=side,
            quantity=quantity,
            price=price,
        )

        result = self.order_manager.place_limit_order(request, self.filters)

        self.logger.info(
            "Placed %s order | symbol=%s order_id=%s client_order_id=%s price=%s qty=%s status=%s",
            result.side,
            result.symbol,
            result.order_id,
            result.client_order_id,
            result.price,
            result.orig_qty,
            result.status,
        )

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

    def cancel_order(self, order_id: int) -> int:
        local_order = self.state_store.get_order(order_id)
        if local_order is None:
            self.logger.warning("Cancel skipped | order_id=%s not found in local state", order_id)
            return 0

        if local_order.is_terminal:
            self.logger.info("Cancel skipped | order_id=%s already terminal", order_id)
            return 0

        # 1. Marcamos intención de cancelación (Optimistic Lock)
        self.state_store.mark_cancel_requested(
            OrderCancelRequestedEvent(
                occurred_at=utc_now_iso(),
                symbol=self.symbol,
                order_id=order_id,
            )
        )

        # 2. Intentamos cancelar en el exchange
        try:
            payload = self.order_manager.cancel_order(
                symbol=self.symbol,
                order_id=order_id,
            )
        except Exception as e:
            self.logger.error("Exception during cancel_order for %s: %s", order_id, e)
            payload = None

        # 3. MANEJO DE FALLO / PAYLOAD VACÍO (El "Ideal")
        if not payload:
            self.logger.warning("Cancel failed or empty for %s. Triggering immediate REST sync...", order_id)
            
            # Sincronización inmediata vía REST para ver qué pasó realmente
            # Esto evita que el bot crea que la orden sigue viva si se canceló por otro medio
            # o que crea que se canceló si sigue abierta.
            sync_data = self.order_manager.get_order(self.symbol, order_id)
            
            if sync_data:
                sync_event = to_domain_sync_event(sync_data)
                self.state_store.apply_status_sync(sync_event)
                self.logger.info("REST sync completed for %s | current_status=%s", order_id, sync_event.status)
            else:
                self.logger.error("Critical: Could not sync order %s via REST after failed cancel.", order_id)
            
            return 0
        # 4. ÉXITO: Aplicamos el resultado del payload de cancelación
        # Usamos una función auxiliar o acceso seguro para manejar dict u objeto
        sync_event = to_domain_sync_event(payload)
        self.state_store.apply_status_sync(sync_event)

        # Extraemos los datos de forma segura (funciona para dict y para objeto)
        def get_val(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        p_symbol = get_val(payload, 'symbol', self.symbol)
        p_order_id = get_val(payload, 'order_id', order_id)
        p_status = get_val(payload, 'status', 'CANCELED')
        p_exec_qty = get_val(payload, 'executed_qty', "unknown")

        self.logger.info(
            "Canceled order successfully | symbol=%s order_id=%s status=%s executedQty=%s",
            p_symbol, 
            p_order_id, 
            p_status, 
            p_exec_qty
        )
        return 1