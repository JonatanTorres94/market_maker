from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.execution import Execution


@dataclass
class ExecutionLedgerState:
    position_qty: Decimal = Decimal("0")
    average_cost: Decimal = Decimal("0")
    realized_gross_pnl: Decimal = Decimal("0")
    realized_fees: Decimal = Decimal("0")
    realized_net_pnl: Decimal = Decimal("0")
    total_buy_notional: Decimal = Decimal("0")
    total_sell_notional: Decimal = Decimal("0")
    applied_executions: int = 0


class ExecutionLedger:
    def __init__(self):
        self.state = ExecutionLedgerState()
        self._applied_keys: set[tuple[str, str, str, int]] = set()

    def apply(self, execution: Execution, reference_mid_price: Decimal | None = None) -> None:
        key = execution.unique_key
        if key in self._applied_keys:
            return
        self._applied_keys.add(key)

        side = execution.side.upper()
        qty = execution.qty
        price = execution.price
        quote_qty = execution.quote_qty if execution.quote_qty > 0 else execution.price * execution.qty
        fee_in_quote = execution.commission_in_quote or Decimal("0")

        if side == "BUY":
            self.state.total_buy_notional += quote_qty
            realized_delta, new_pos, new_avg = self._apply_buy(qty=qty, price=price)
            self.state.realized_gross_pnl += realized_delta
        elif side == "SELL":
            self.state.total_sell_notional += quote_qty
            realized_delta, new_pos, new_avg = self._apply_sell(qty=qty, price=price)
            self.state.realized_gross_pnl += realized_delta
        else:
            raise ValueError(f"Unsupported execution side: {execution.side}")

        self.state.position_qty = new_pos
        self.state.average_cost = new_avg
        self.state.realized_fees += fee_in_quote
        self.state.realized_net_pnl = self.state.realized_gross_pnl - self.state.realized_fees
        self.state.applied_executions += 1

    def unrealized_pnl(self, reference_mid_price: Decimal) -> Decimal:
        return self._mark_to_market(reference_mid_price)

    def total_net_pnl(self, reference_mid_price: Decimal) -> Decimal:
        return self.state.realized_net_pnl + self._mark_to_market(reference_mid_price)

    def _apply_buy(self, qty: Decimal, price: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        pos = self.state.position_qty
        avg = self.state.average_cost
        if pos >= 0:
            new_pos = pos + qty
            new_avg = ((pos * avg) + (qty * price)) / new_pos if pos > 0 else price
            return Decimal("0"), new_pos, new_avg
        cover_qty = min(qty, -pos)
        realized = (avg - price) * cover_qty
        remaining_buy = qty - cover_qty
        new_pos = pos + cover_qty
        if remaining_buy > 0:
            new_pos += remaining_buy
            new_avg = price
        else:
            new_avg = avg if new_pos != 0 else Decimal("0")
        return realized, new_pos, new_avg

    def _apply_sell(self, qty: Decimal, price: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        pos = self.state.position_qty
        avg = self.state.average_cost
        if pos <= 0:
            new_pos = pos - qty
            new_abs = abs(new_pos)
            cur_abs = abs(pos)
            new_avg = ((cur_abs * avg) + (qty * price)) / new_abs if cur_abs > 0 else price
            return Decimal("0"), new_pos, new_avg
        close_qty = min(qty, pos)
        realized = (price - avg) * close_qty
        remaining_sell = qty - close_qty
        new_pos = pos - close_qty
        if remaining_sell > 0:
            new_pos -= remaining_sell
            new_avg = price
        else:
            new_avg = avg if new_pos != 0 else Decimal("0")
        return realized, new_pos, new_avg

    def _mark_to_market(self, reference_mid_price: Decimal) -> Decimal:
        if self.state.position_qty == 0 or reference_mid_price <= 0:
            return Decimal("0")
        if self.state.position_qty > 0:
            return (reference_mid_price - self.state.average_cost) * self.state.position_qty
        return (self.state.average_cost - reference_mid_price) * abs(self.state.position_qty)
