# src/domain/execution_ledger.py
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Tuple, Set
from collections import defaultdict
from .execution import Execution

@dataclass
class LedgerState:
    position: Decimal = Decimal("0")
    avg_cost: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

class ExecutionLedger:
    def __init__(self):
        # Usamos lambda para evitar errores de inicialización de defaultdict
        self.states: Dict[Tuple[str, str, str], LedgerState] = defaultdict(LedgerState)
        self.applied: Set[Tuple[str, str, str, int]] = set()

    def apply(self, execution: Execution, fee_in_quote: Decimal):
        key = execution.unique_key

        if key in self.applied:
            return

        state_key = (execution.exchange, execution.account, execution.symbol)
        state = self.states[state_key]

        if execution.side.upper() == "BUY":
            self._apply_buy(state, execution, fee_in_quote)
        else:
            self._apply_sell(state, execution, fee_in_quote)

        self.applied.add(key)

    def _apply_buy(self, state: LedgerState, e: Execution, fee: Decimal):
        if state.position < 0:
            closing_qty = min(abs(state.position), e.qty)
            opening_qty = e.qty - closing_qty
            realized = (state.avg_cost - e.price) * closing_qty
            realized -= fee * (closing_qty / e.qty)
            state.realized_pnl += realized
            state.position += closing_qty
            if opening_qty > 0:
                state.position += opening_qty
                state.avg_cost = e.price
            if state.position == 0:
                state.avg_cost = Decimal("0")
        else:
            new_pos = state.position + e.qty
            total_cost = (state.position * state.avg_cost) + (e.qty * e.price) + fee
            state.avg_cost = total_cost / new_pos if new_pos != 0 else Decimal("0")
            state.position = new_pos

    def _apply_sell(self, state: LedgerState, e: Execution, fee: Decimal):
        if state.position > 0:
            closing_qty = min(state.position, e.qty)
            opening_qty = e.qty - closing_qty
            realized = (e.price - state.avg_cost) * closing_qty
            realized -= fee * (closing_qty / e.qty)
            state.realized_pnl += realized
            state.position -= closing_qty
            if opening_qty > 0:
                state.position -= opening_qty
                state.avg_cost = e.price
            if state.position == 0:
                state.avg_cost = Decimal("0")
        else:
            new_pos = state.position - e.qty
            total_cost = (abs(state.position) * state.avg_cost) + (e.qty * e.price) + fee
            state.avg_cost = total_cost / abs(new_pos) if new_pos != 0 else Decimal("0")
            state.position = new_pos
            
    def get_state(self, exchange, account, symbol):
        return self.states[(exchange, account, symbol)]