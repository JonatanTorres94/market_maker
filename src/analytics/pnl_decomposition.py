import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class PnLDecompositionSummary:
    initial_equity: Decimal
    final_equity: Decimal
    equity_delta: Decimal
    initial_base_inventory: Decimal
    final_base_inventory: Decimal
    inventory_delta: Decimal
    initial_mid_price: Decimal
    final_mid_price: Decimal
    realized_pnl_proxy: Decimal
    unrealized_pnl_proxy: Decimal
    anchored_inventory_cost_basis: Decimal
    processed_fills: int


class PnLDecompositionAnalyzer:
    def __init__(self, base_path: str = "data/journals"):
        self.base_path = Path(base_path)

    def analyze(self) -> PnLDecompositionSummary:
        equity_rows = self._read_csv("equity.csv")
        reconciled_rows = self._read_csv("orders_reconciled.csv")

        if not equity_rows:
            zero = Decimal("0")
            return PnLDecompositionSummary(
                initial_equity=zero,
                final_equity=zero,
                equity_delta=zero,
                initial_base_inventory=zero,
                final_base_inventory=zero,
                inventory_delta=zero,
                initial_mid_price=zero,
                final_mid_price=zero,
                realized_pnl_proxy=zero,
                unrealized_pnl_proxy=zero,
                anchored_inventory_cost_basis=zero,
                processed_fills=0,
            )

        initial_equity = Decimal(equity_rows[0]["mark_to_market_equity"])
        final_equity = Decimal(equity_rows[-1]["mark_to_market_equity"])
        initial_base = Decimal(equity_rows[0]["base_free"])
        final_base = Decimal(equity_rows[-1]["base_free"])
        initial_mid = Decimal(equity_rows[0]["mid_price"])
        final_mid = Decimal(equity_rows[-1]["mid_price"])

        fills = [row for row in reconciled_rows if row["status"] == "FILLED"]
        fills.sort(key=lambda row: self._parse_dt(row.get("updated_at") or row["timestamp"]))

        position_qty = initial_base
        average_cost = initial_mid if position_qty > 0 else Decimal("0")
        realized_pnl = Decimal("0")

        for row in fills:
            side = row["side"]
            qty = Decimal(row["executed_qty"])
            quote_qty = Decimal(row["cumulative_quote_qty"])

            if qty <= 0:
                continue

            if side == "BUY":
                total_cost_before = position_qty * average_cost
                total_cost_after = total_cost_before + quote_qty
                position_qty += qty
                if position_qty > Decimal("0.00000001"):  # Evitamos división por cero o costos absurdos por datos inconsistentes
                    average_cost = total_cost_after / position_qty
                else:
                    average_cost = Decimal("0")

            elif side == "SELL":
                if position_qty <= 0:
                    # Si por datos artificiales o inconsistencia vendés sin base previa,
                    # tratamos el costo base como 0. Mejor eso que inventar.
                    realized_pnl += quote_qty
                    position_qty -= qty
                    average_cost = Decimal("0")
                    continue

                sell_cost_basis = average_cost * qty
                realized_pnl += quote_qty - sell_cost_basis
                position_qty -= qty

                if position_qty <= 0:
                    position_qty = Decimal("0")
                    average_cost = Decimal("0")

        unrealized_pnl = Decimal("0")
        if final_base > 0 and average_cost > 0:
            unrealized_pnl = (final_mid - average_cost) * final_base

        return PnLDecompositionSummary(
            initial_equity=initial_equity,
            final_equity=final_equity,
            equity_delta=final_equity - initial_equity,
            initial_base_inventory=initial_base,
            final_base_inventory=final_base,
            inventory_delta=final_base - initial_base,
            initial_mid_price=initial_mid,
            final_mid_price=final_mid,
            realized_pnl_proxy=realized_pnl,
            unrealized_pnl_proxy=unrealized_pnl,
            anchored_inventory_cost_basis=average_cost,
            processed_fills=len(fills),
        )

    def _read_csv(self, filename: str) -> list[dict]:
        path = self.base_path / filename
        if not path.exists():
            return []

        with path.open("r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(value)