from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from src.domain.events import (
    OrderCancelRequestedEvent,
    OrderCanceledEvent,
    OrderFilledEvent,
    OrderPartiallyFilledEvent,
    OrderPlacedEvent,
    OrderStatusSyncedEvent,
)


ACTIVE_STATUSES = {"NEW", "PARTIALLY_FILLED", "PENDING_CANCEL", "CANCEL_REQUESTED"}
TERMINAL_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}


@dataclass
class LocalOrderState:
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: str
    placed_at: str
    last_update_at: str
    cancel_requested_at: Optional[str] = None
    filled_at: Optional[str] = None
    terminal_at: Optional[str] = None

    @property
    def remaining_qty(self) -> Decimal:
        remaining = self.orig_qty - self.executed_qty
        return remaining if remaining > 0 else Decimal("0")

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class OrderStateStore:
    def __init__(self):
        self._orders: Dict[int, LocalOrderState] = {}

    def add_open_order(self, event: OrderPlacedEvent) -> None:
        self._orders[event.order_id] = LocalOrderState(
            symbol=event.symbol,
            order_id=event.order_id,
            client_order_id=event.client_order_id,
            side=event.side,
            price=event.price,
            orig_qty=event.orig_qty,
            executed_qty=event.executed_qty,
            status=event.status,
            placed_at=event.placed_at,
            last_update_at=event.occurred_at,
        )

    def mark_cancel_requested(self, event: OrderCancelRequestedEvent) -> None:
        state = self._orders.get(event.order_id)
        if state is None:
            return

        if state.is_terminal:
            return

        state.status = "CANCEL_REQUESTED"
        state.cancel_requested_at = event.occurred_at
        state.last_update_at = event.occurred_at

    def apply_canceled(self, event: OrderCanceledEvent) -> None:
        state = self._orders.get(event.order_id)

        if state is None:
            state = LocalOrderState(
                symbol=event.symbol,
                order_id=event.order_id,
                client_order_id=event.client_order_id,
                side=event.side,
                price=event.price,
                orig_qty=event.orig_qty,
                executed_qty=event.executed_qty,
                status="CANCELED",
                placed_at=event.updated_at,
                last_update_at=event.updated_at,
                terminal_at=event.updated_at,
            )
            self._orders[event.order_id] = state
            return

        state.client_order_id = event.client_order_id
        state.side = event.side
        state.price = event.price
        state.orig_qty = event.orig_qty
        state.executed_qty = event.executed_qty
        state.status = "CANCELED"
        state.last_update_at = event.updated_at
        state.terminal_at = event.updated_at

    def apply_partial_fill(self, event: OrderPartiallyFilledEvent) -> None:
        state = self._orders.get(event.order_id)

        if state is None:
            state = LocalOrderState(
                symbol=event.symbol,
                order_id=event.order_id,
                client_order_id=event.client_order_id,
                side=event.side,
                price=event.price,
                orig_qty=event.orig_qty,
                executed_qty=event.executed_qty,
                status="PARTIALLY_FILLED",
                placed_at=event.updated_at,
                last_update_at=event.updated_at,
            )
            self._orders[event.order_id] = state
            return

        state.client_order_id = event.client_order_id
        state.side = event.side
        state.price = event.price
        state.orig_qty = event.orig_qty
        state.executed_qty = event.executed_qty
        state.status = "PARTIALLY_FILLED"
        state.last_update_at = event.updated_at

    def apply_fill(self, event: OrderFilledEvent) -> None:
        state = self._orders.get(event.order_id)

        if state is None:
            state = LocalOrderState(
                symbol=event.symbol,
                order_id=event.order_id,
                client_order_id=event.client_order_id,
                side=event.side,
                price=event.price,
                orig_qty=event.orig_qty,
                executed_qty=event.executed_qty,
                status="FILLED",
                placed_at=event.updated_at,
                last_update_at=event.updated_at,
                filled_at=event.updated_at,
                terminal_at=event.updated_at,
            )
            self._orders[event.order_id] = state
            return

        state.client_order_id = event.client_order_id
        state.side = event.side
        state.price = event.price
        state.orig_qty = event.orig_qty
        state.executed_qty = event.executed_qty
        state.status = "FILLED"
        state.last_update_at = event.updated_at
        state.filled_at = event.updated_at
        state.terminal_at = event.updated_at

    def apply_status_sync(self, event: OrderStatusSyncedEvent) -> None:
        if event.status == "FILLED":
            self.apply_fill(
                OrderFilledEvent(
                    occurred_at=event.occurred_at,
                    symbol=event.symbol,
                    order_id=event.order_id,
                    client_order_id=event.client_order_id,
                    side=event.side,
                    price=event.price,
                    orig_qty=event.orig_qty,
                    executed_qty=event.executed_qty,
                    status=event.status,
                    updated_at=event.updated_at,
                )
            )
            return

        if event.status == "PARTIALLY_FILLED":
            self.apply_partial_fill(
                OrderPartiallyFilledEvent(
                    occurred_at=event.occurred_at,
                    symbol=event.symbol,
                    order_id=event.order_id,
                    client_order_id=event.client_order_id,
                    side=event.side,
                    price=event.price,
                    orig_qty=event.orig_qty,
                    executed_qty=event.executed_qty,
                    status=event.status,
                    updated_at=event.updated_at,
                )
            )
            return

        if event.status == "CANCELED":
            self.apply_canceled(
                OrderCanceledEvent(
                    occurred_at=event.occurred_at,
                    symbol=event.symbol,
                    order_id=event.order_id,
                    client_order_id=event.client_order_id,
                    side=event.side,
                    price=event.price,
                    orig_qty=event.orig_qty,
                    executed_qty=event.executed_qty,
                    status=event.status,
                    updated_at=event.updated_at,
                )
            )
            return

        state = self._orders.get(event.order_id)

        if state is None:
            state = LocalOrderState(
                symbol=event.symbol,
                order_id=event.order_id,
                client_order_id=event.client_order_id,
                side=event.side,
                price=event.price,
                orig_qty=event.orig_qty,
                executed_qty=event.executed_qty,
                status=event.status,
                placed_at=event.updated_at,
                last_update_at=event.updated_at,
            )
            self._orders[event.order_id] = state
            return

        state.client_order_id = event.client_order_id
        state.side = event.side
        state.price = event.price
        state.orig_qty = event.orig_qty
        state.executed_qty = event.executed_qty
        state.status = event.status
        state.last_update_at = event.updated_at

        if event.status in TERMINAL_STATUSES:
            state.terminal_at = event.updated_at

    def get_order(self, order_id: int) -> Optional[LocalOrderState]:
        return self._orders.get(order_id)

    def get_all_orders(self, symbol: Optional[str] = None) -> List[LocalOrderState]:
        values = list(self._orders.values())
        if symbol is None:
            return values
        return [order for order in values if order.symbol == symbol]

    def get_active_orders(self, symbol: Optional[str] = None) -> List[LocalOrderState]:
        return [order for order in self.get_all_orders(symbol) if order.is_active]

    def get_terminal_orders(self, symbol: Optional[str] = None) -> List[LocalOrderState]:
        return [order for order in self.get_all_orders(symbol) if order.is_terminal]

    def get_open_order_by_side(self, symbol: str, side: str) -> Optional[LocalOrderState]:
        for order in self.get_active_orders(symbol):
            if order.side == side:
                return order
        return None

    def status_counts(self, symbol: Optional[str] = None) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for order in self.get_all_orders(symbol):
            counts[order.status] = counts.get(order.status, 0) + 1
        return counts

    def cleanup_terminal_orders(self) -> None:
        removable = [order_id for order_id, order in self._orders.items() if order.is_terminal]
        for order_id in removable:
            del self._orders[order_id]
            
    def get_active_order_by_side(self, symbol: str, side: str) -> Optional[LocalOrderState]:
        active = [order for order in self.get_active_orders(symbol) if order.side == side]
        if not active:
            return None
        active.sort(key=lambda x: x.placed_at)
        return active[0]

    def get_oldest_active_order_age_seconds(self, symbol: str, now_iso: str) -> float:
        active_orders = self.get_active_orders(symbol)
        if not active_orders:
            return 0.0

        from datetime import datetime

        now = datetime.fromisoformat(now_iso)
        ages = [
            (now - datetime.fromisoformat(order.placed_at)).total_seconds()
            for order in active_orders
        ]
        return max(ages) if ages else 0.0