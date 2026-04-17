# src/analytics/execution_pnl_analysis.py
import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from src.domain.execution import Execution
from src.domain.execution_ledger import ExecutionLedger

@dataclass(frozen=True)
class ExecutionPnlSummary:
    source_filename: str
    total_executions: int
    total_symbols: int
    total_quote_notional: Decimal
    total_fees_in_quote: Decimal
    realized_pnl: Decimal
    realized_pnl_bps_on_notional: Decimal
    executions_with_fee_resolved: int
    executions_with_fee_missing: int
    executions_with_fee_zero: int

class ExecutionPnlAnalyzer:
    def __init__(self, base_path: str = "data/journals", data: dict | None = None):
        self.base_path = Path(base_path)
        self._data = data or {}

    def analyze(self) -> ExecutionPnlSummary:
        if "executions_reconciled" in self._data:
            rows = self._data["executions_reconciled"]
            source = "executions_reconciled"
        elif "executions" in self._data:
            rows = self._data["executions"]
            source = "executions"
        else:
            reconciled_file = self.base_path / "executions_reconciled.csv"
            raw_file = self.base_path / "executions.csv"
            path_to_load = reconciled_file if reconciled_file.exists() else raw_file
            if not path_to_load.exists():
                return self._empty_summary()
            rows = self._read_csv(path_to_load.name)
            source = path_to_load.name

        if not rows:
            return self._empty_summary()

        _ = source  # used only for source_filename below
        executions = [self._parse_execution(row) for row in rows]
        # Ordenar cronológicamente para que el Ledger calcule bien el avg_cost
        executions.sort(key=lambda e: (e.executed_at, e.trade_id))

        ledger = ExecutionLedger()
        total_quote_notional = Decimal("0")
        total_fees_in_quote = Decimal("0")
        symbols = set()

        resolved, missing, zero = 0, 0, 0

        for execution in executions:
            # Determinamos el fee
            fee_val = execution.commission_in_quote
            if fee_val is None:
                missing += 1
                current_fee = Decimal("0")
            else:
                resolved += 1
                current_fee = fee_val
                total_fees_in_quote += current_fee
                if current_fee == Decimal("0"):
                    zero += 1

            # Quote notional para el cálculo de BPS
            q_qty = execution.quote_qty if execution.quote_qty > 0 else execution.price * execution.qty
            total_quote_notional += q_qty
            symbols.add((execution.exchange, execution.account, execution.symbol))

            # Aplicar al Ledger (que ya maneja multi-symbol internamente)
            ledger.apply(execution, current_fee)

        # Sumar PnL realizado de todos los símbolos activos
        total_realized_pnl = sum(s.realized_pnl for s in ledger.states.values())

        realized_bps = Decimal("0")
        if total_quote_notional > 0:
            realized_bps = (total_realized_pnl / total_quote_notional) * Decimal("10000")

        return ExecutionPnlSummary(
            source_filename=source,
            total_executions=len(executions),
            total_symbols=len(symbols),
            total_quote_notional=total_quote_notional,
            total_fees_in_quote=total_fees_in_quote,
            realized_pnl=total_realized_pnl,
            realized_pnl_bps_on_notional=realized_bps,
            executions_with_fee_resolved=resolved,
            executions_with_fee_missing=missing,
            executions_with_fee_zero=zero
        )

    def _read_csv(self, filename: str) -> list[dict]:
        path = self.base_path / filename
        with path.open("r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _parse_execution(self, row: dict) -> Execution:
        def d(key):
            v = row.get(key)
            return Decimal(v) if v and v != "" else Decimal("0")

        return Execution(
            exchange=row["exchange"],
            account=row["account"],
            symbol=row["symbol"],
            trade_id=int(row["trade_id"]),
            order_id=int(row["order_id"]),
            client_order_id=row.get("client_order_id", ""),
            side=row["side"],
            price=d("price"),
            qty=d("qty"),
            quote_qty=d("quote_qty"),
            commission=d("commission"),
            commission_asset=row.get("commission_asset", ""),
            commission_in_quote=Decimal(row["commission_in_quote"]) if row.get("commission_in_quote") else None,
            commission_fx_rate=d("commission_fx_rate"),
            commission_fx_symbol=row.get("commission_fx_symbol"),
            commission_fx_timestamp=row.get("commission_fx_timestamp"),
            is_maker=str(row.get("is_maker", "")).lower() == "true",
            executed_at=row["executed_at"],
            source=row.get("source", "unknown")
        )

    def _empty_summary(self) -> ExecutionPnlSummary:
        z = Decimal("0")
        return ExecutionPnlSummary("", 0, 0, z, z, z, z, 0, 0, 0)