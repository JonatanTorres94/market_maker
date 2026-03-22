from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from src.domain.execution import Execution
from src.core.run_paths import get_journal_base_path

@dataclass(frozen=True)
class ExecutionLedgerRecord:
    timestamp: str
    exchange: str
    account: str
    symbol: str
    trade_id: int
    order_id: int
    side: str
    execution_price: Decimal
    execution_qty: Decimal
    execution_quote_qty: Decimal
    fee_in_quote: Decimal
    position_qty: Decimal
    average_cost: Decimal
    realized_gross_pnl: Decimal
    realized_fees: Decimal
    realized_net_pnl: Decimal
    unrealized_pnl: Decimal
    total_net_pnl: Decimal
    reference_mid_price: Decimal


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
    
    def __init__(
        self,
        journal_path: str | None = None,
        snapshot_path: str | None = None,
        snapshot_every: int = 1000,
    ):
        base_path = get_journal_base_path()
        self.state = ExecutionLedgerState()
        self.journal_path = Path(journal_path) if journal_path else Path(f"{base_path}/execution_ledger.csv")
        self.snapshot_path = Path(snapshot_path) if snapshot_path else Path(f"{base_path}/execution_ledger_snapshot.json")
        self.snapshot_every = snapshot_every
        self._applied_keys: set[tuple[str, str, str, int]] = set()
        self._ensure_journal_header()

    def apply(self, execution: Execution, reference_mid_price: Decimal | None = None) -> ExecutionLedgerRecord | None:
        key = execution.unique_key
        if key in self._applied_keys:
            return None
        self._applied_keys.add(key)

        side = execution.side.upper()
        qty = execution.qty
        price = execution.price
        quote_qty = execution.quote_qty if execution.quote_qty > 0 else execution.price * execution.qty
        fee_in_quote = execution.commission_in_quote or Decimal("0")

        realized_delta = Decimal("0")
        new_position_qty = self.state.position_qty
        new_average_cost = self.state.average_cost

        if side == "BUY":
            self.state.total_buy_notional += quote_qty
            realized_delta, new_position_qty, new_average_cost = self._apply_buy(qty=qty, price=price)
        elif side == "SELL":
            self.state.total_sell_notional += quote_qty
            realized_delta, new_position_qty, new_average_cost = self._apply_sell(qty=qty, price=price)
        else:
            raise ValueError(f"Unsupported execution side: {execution.side}")

        self.state.position_qty = new_position_qty
        self.state.average_cost = new_average_cost
        self.state.realized_gross_pnl += realized_delta
        self.state.realized_fees += fee_in_quote
        self.state.realized_net_pnl = self.state.realized_gross_pnl - self.state.realized_fees
        self.state.applied_executions += 1

        ref_mid = reference_mid_price if reference_mid_price is not None and reference_mid_price > 0 else price
        unrealized_pnl = self._mark_to_market(reference_mid_price=ref_mid)
        total_net_pnl = self.state.realized_net_pnl + unrealized_pnl

        record = ExecutionLedgerRecord(
            timestamp=execution.executed_at,
            exchange=execution.exchange,
            account=execution.account,
            symbol=execution.symbol,
            trade_id=execution.trade_id,
            order_id=execution.order_id,
            side=execution.side,
            execution_price=execution.price,
            execution_qty=execution.qty,
            execution_quote_qty=quote_qty,
            fee_in_quote=fee_in_quote,
            position_qty=self.state.position_qty,
            average_cost=self.state.average_cost,
            realized_gross_pnl=self.state.realized_gross_pnl,
            realized_fees=self.state.realized_fees,
            realized_net_pnl=self.state.realized_net_pnl,
            unrealized_pnl=unrealized_pnl,
            total_net_pnl=total_net_pnl,
            reference_mid_price=ref_mid,
        )
        self._append_record(record)
        if self.snapshot_every > 0 and self.state.applied_executions % self.snapshot_every == 0:
            self.save_snapshot()
        return record

    def unrealized_pnl(self, reference_mid_price: Decimal) -> Decimal:
        return self._mark_to_market(reference_mid_price)

    def total_net_pnl(self, reference_mid_price: Decimal) -> Decimal:
        return self.state.realized_net_pnl + self._mark_to_market(reference_mid_price)

    def save_snapshot(self) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "position_qty": str(self.state.position_qty),
            "average_cost": str(self.state.average_cost),
            "realized_gross_pnl": str(self.state.realized_gross_pnl),
            "realized_fees": str(self.state.realized_fees),
            "realized_net_pnl": str(self.state.realized_net_pnl),
            "total_buy_notional": str(self.state.total_buy_notional),
            "total_sell_notional": str(self.state.total_sell_notional),
            "applied_executions": self.state.applied_executions,
        }
        self.snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_snapshot(self) -> bool:
        if not self.snapshot_path.exists():
            return False
        payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        self.state = ExecutionLedgerState(
            position_qty=Decimal(payload.get("position_qty", "0")),
            average_cost=Decimal(payload.get("average_cost", "0")),
            realized_gross_pnl=Decimal(payload.get("realized_gross_pnl", "0")),
            realized_fees=Decimal(payload.get("realized_fees", "0")),
            realized_net_pnl=Decimal(payload.get("realized_net_pnl", "0")),
            total_buy_notional=Decimal(payload.get("total_buy_notional", "0")),
            total_sell_notional=Decimal(payload.get("total_sell_notional", "0")),
            applied_executions=int(payload.get("applied_executions", 0)),
        )
        return True

    def _apply_buy(self, qty: Decimal, price: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        pos = self.state.position_qty
        avg = self.state.average_cost

        if pos >= 0:
            new_pos = pos + qty
            if new_pos == 0:
                return Decimal("0"), Decimal("0"), Decimal("0")
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
            new_abs_pos = abs(new_pos)
            current_abs_pos = abs(pos)
            if new_abs_pos == 0:
                return Decimal("0"), Decimal("0"), Decimal("0")
            new_avg = ((current_abs_pos * avg) + (qty * price)) / new_abs_pos if current_abs_pos > 0 else price
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

    def _ensure_journal_header(self) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        if self.journal_path.exists():
            return
        with self.journal_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "exchange",
                    "account",
                    "symbol",
                    "trade_id",
                    "order_id",
                    "side",
                    "execution_price",
                    "execution_qty",
                    "execution_quote_qty",
                    "fee_in_quote",
                    "position_qty",
                    "average_cost",
                    "realized_gross_pnl",
                    "realized_fees",
                    "realized_net_pnl",
                    "unrealized_pnl",
                    "total_net_pnl",
                    "reference_mid_price",
                ],
            )
            writer.writeheader()

    def _append_record(self, record: ExecutionLedgerRecord) -> None:
        with self.journal_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "timestamp",
                "exchange",
                "account",
                "symbol",
                "trade_id",
                "order_id",
                "side",
                "execution_price",
                "execution_qty",
                "execution_quote_qty",
                "fee_in_quote",
                "position_qty",
                "average_cost",
                "realized_gross_pnl",
                "realized_fees",
                "realized_net_pnl",
                "unrealized_pnl",
                "total_net_pnl",
                "reference_mid_price",
            ])
            writer.writerow(
                {
                    "timestamp": record.timestamp,
                    "exchange": record.exchange,
                    "account": record.account,
                    "symbol": record.symbol,
                    "trade_id": record.trade_id,
                    "order_id": record.order_id,
                    "side": record.side,
                    "execution_price": str(record.execution_price),
                    "execution_qty": str(record.execution_qty),
                    "execution_quote_qty": str(record.execution_quote_qty),
                    "fee_in_quote": str(record.fee_in_quote),
                    "position_qty": str(record.position_qty),
                    "average_cost": str(record.average_cost),
                    "realized_gross_pnl": str(record.realized_gross_pnl),
                    "realized_fees": str(record.realized_fees),
                    "realized_net_pnl": str(record.realized_net_pnl),
                    "unrealized_pnl": str(record.unrealized_pnl),
                    "total_net_pnl": str(record.total_net_pnl),
                    "reference_mid_price": str(record.reference_mid_price),
                }
            )
