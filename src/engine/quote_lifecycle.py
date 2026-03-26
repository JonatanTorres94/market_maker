from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.engine.order_state_store import LocalOrderState


@dataclass(frozen=True)
class SideLifecycleDecision:
    should_cancel: bool
    should_place: bool
    reason: str


@dataclass(frozen=True)
class QuoteLifecycleConfig:
    replace_threshold_ticks: int
    quantity_rel_change_threshold: Decimal
    max_quote_age_seconds: float


class QuoteLifecyclePolicy:
    def __init__(self, config: QuoteLifecycleConfig):
        self.config = config

    def decide_side(
        self,
        active_order: Optional[LocalOrderState],
        target_price: Optional[Decimal],
        target_quantity: Decimal,
        tick_size: Decimal,
        now_iso: str,
        adverse_drift_bps: Decimal,
        adverse_drift_threshold_bps: Decimal,
    ) -> SideLifecycleDecision:
        if target_price is None or target_quantity <= 0:
            if active_order is None:
                return SideLifecycleDecision(
                    should_cancel=False,
                    should_place=False,
                    reason="no_target_no_active_order",
                )
            return SideLifecycleDecision(
                should_cancel=True,
                should_place=False,
                reason="no_target_cancel_active_order",
            )

        if active_order is None:
            return SideLifecycleDecision(
                should_cancel=False,
                should_place=True,
                reason="no_active_order_place_new",
            )

        if adverse_drift_bps >= adverse_drift_threshold_bps:
            return SideLifecycleDecision(
                should_cancel=True,
                should_place=False,
                reason=f"cancel_due_to_adverse_drift_{adverse_drift_bps}",
            )

        age_seconds = self._age_seconds(active_order.placed_at, now_iso)
        if age_seconds >= self.config.max_quote_age_seconds:
            return SideLifecycleDecision(
                should_cancel=True,
                should_place=True,
                reason="replace_due_to_quote_age",
            )

        price_delta_ticks = self._price_delta_ticks(
            current_price=active_order.price,
            target_price=target_price,
            tick_size=tick_size,
        )
        if price_delta_ticks >= self.config.replace_threshold_ticks:
            return SideLifecycleDecision(
                should_cancel=True,
                should_place=True,
                reason=f"replace_due_to_price_delta_{price_delta_ticks}_ticks",
            )

        qty_rel_change = self._relative_quantity_change(
            current_qty=active_order.orig_qty,
            target_qty=target_quantity,
        )
        if qty_rel_change >= self.config.quantity_rel_change_threshold:
            return SideLifecycleDecision(
                should_cancel=True,
                should_place=True,
                reason=f"replace_due_to_qty_change_{qty_rel_change}",
            )

        return SideLifecycleDecision(
            should_cancel=False,
            should_place=False,
            reason="keep_existing_order",
        )

    @staticmethod
    def _price_delta_ticks(
        current_price: Decimal,
        target_price: Decimal,
        tick_size: Decimal,
    ) -> int:
        if tick_size <= 0:
            return 0

        delta = abs(target_price - current_price)
        return int(delta / tick_size)

    @staticmethod
    def _relative_quantity_change(
        current_qty: Decimal,
        target_qty: Decimal,
    ) -> Decimal:
        if current_qty <= 0:
            return Decimal("1")

        return abs(target_qty - current_qty) / current_qty

    @staticmethod
    def _age_seconds(placed_at_iso: str, now_iso: str) -> float:
        placed_at = datetime.fromisoformat(placed_at_iso)
        now = datetime.fromisoformat(now_iso)
        return (now - placed_at).total_seconds()