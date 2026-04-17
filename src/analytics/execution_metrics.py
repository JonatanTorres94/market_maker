import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class ExecutionMetricsSummary:
    total_orders: int
    buy_orders: int
    sell_orders: int
    filled_orders: int
    canceled_orders: int
    partially_filled_orders: int
    fill_ratio: Decimal
    cancel_ratio: Decimal
    average_quote_lifetime_seconds: Decimal
    average_time_to_fill_seconds: Decimal
    average_time_to_cancel_seconds: Decimal


class ExecutionMetricsAnalyzer:
    def __init__(self, base_path: str = "data/journals", data: dict | None = None):
        self.base_path = Path(base_path)
        self._data = data or {}

    def analyze(self) -> ExecutionMetricsSummary:
        orders = self._read_orders()
        reconciled = self._read_reconciled()

        orders_by_id = {int(row["order_id"]): row for row in orders}

        total_orders = len(orders)
        buy_orders = sum(1 for row in orders if row["side"] == "BUY")
        sell_orders = sum(1 for row in orders if row["side"] == "SELL")

        filled_orders = 0
        canceled_orders = 0
        partially_filled_orders = 0

        fill_lifetimes: list[Decimal] = []
        cancel_lifetimes: list[Decimal] = []
        all_terminal_lifetimes: list[Decimal] = []

        for row in reconciled:
            order_id = int(row["order_id"])
            placed = orders_by_id.get(order_id)
            if placed is None:
                continue

            status = row["status"]
            placed_at = placed["placed_at"]
            updated_at = row.get("updated_at", "") or row.get("timestamp", "")

            if not updated_at:
                continue

            lifetime = Decimal(str(self._seconds_between(placed_at, updated_at)))
            all_terminal_lifetimes.append(lifetime)

            if status == "FILLED":
                filled_orders += 1
                fill_lifetimes.append(lifetime)
            elif status == "CANCELED":
                canceled_orders += 1
                cancel_lifetimes.append(lifetime)
            elif status == "PARTIALLY_FILLED":
                partially_filled_orders += 1

        fill_ratio = self._safe_ratio(filled_orders, total_orders)
        cancel_ratio = self._safe_ratio(canceled_orders, total_orders)

        return ExecutionMetricsSummary(
            total_orders=total_orders,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            filled_orders=filled_orders,
            canceled_orders=canceled_orders,
            partially_filled_orders=partially_filled_orders,
            fill_ratio=fill_ratio,
            cancel_ratio=cancel_ratio,
            average_quote_lifetime_seconds=self._average(all_terminal_lifetimes),
            average_time_to_fill_seconds=self._average(fill_lifetimes),
            average_time_to_cancel_seconds=self._average(cancel_lifetimes),
        )

    def _read_csv(self, key: str) -> list[dict]:
        if key in self._data:
            return self._data[key]
        path = self.base_path / f"{key}.csv"
        if not path.exists():
            return []
        with path.open("r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _read_orders(self) -> list[dict]:
        return self._read_csv("orders")

    def _read_reconciled(self) -> list[dict]:
        return self._read_csv("orders_reconciled")

    @staticmethod
    def _seconds_between(start_iso: str, end_iso: str) -> float:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return max((end - start).total_seconds(), 0.0)

    @staticmethod
    def _average(values: list[Decimal]) -> Decimal:
        if not values:
            return Decimal("0")
        return sum(values) / Decimal(len(values))

    @staticmethod
    def _safe_ratio(numerator: int, denominator: int) -> Decimal:
        if denominator == 0:
            return Decimal("0")
        return Decimal(numerator) / Decimal(denominator)