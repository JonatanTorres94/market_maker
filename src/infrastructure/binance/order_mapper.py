#src/infrastructure/binance/order_mapper.py
from decimal import Decimal
from src.domain.events import OrderStatusSyncedEvent
from src.core.utils.time_utils import utc_now_iso, exchange_ms_to_iso

def to_domain_sync_event(payload: dict) -> OrderStatusSyncedEvent:
    """Traduce un payload de Binance a un evento interno de dominio."""
    updated_at = exchange_ms_to_iso(payload.get("updateTime") or payload.get("time"))
    return OrderStatusSyncedEvent(
        occurred_at=utc_now_iso(),
        symbol=payload["symbol"],
        order_id=int(payload["orderId"]),
        client_order_id=payload.get("clientOrderId", ""),
        side=payload["side"],
        price=Decimal(payload["price"]),
        orig_qty=Decimal(payload["origQty"]),
        executed_qty=Decimal(payload["executedQty"]),
        status=payload["status"],
        updated_at=updated_at
    )