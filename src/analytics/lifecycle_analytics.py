import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class LifecycleAnalyticsSummary:
    total_cycles: int
    total_canceled_orders_recorded: int
    keep_existing_order_cycles: int
    quote_age_replace_cycles: int
    price_delta_replace_cycles: int
    qty_change_replace_cycles: int
    no_target_cycles: int
    top_decision_reasons: list[tuple[str, int]]


class LifecycleAnalyticsAnalyzer:
    def __init__(self, base_path: str = "data/journals"):
        self.base_path = Path(base_path)

    def analyze(self) -> LifecycleAnalyticsSummary:
        cycles = self._read_csv("cycles.csv")

        total_cycles = len(cycles)
        total_canceled_orders_recorded = sum(
            int(row.get("canceled_orders", 0) or 0)
            for row in cycles
        )

        keep_existing = 0
        quote_age = 0
        price_delta = 0
        qty_change = 0
        no_target = 0

        reason_counts: dict[str, int] = {}

        for row in cycles:
            reason = row.get("decision_reason", "") or ""
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

            lowered = reason.lower()

            if "keep_existing_order" in lowered:
                keep_existing += 1
            if "quote_age" in lowered:
                quote_age += 1
            if "price_delta" in lowered:
                price_delta += 1
            if "qty_change" in lowered:
                qty_change += 1
            if "no_target" in lowered:
                no_target += 1

        top_reasons = sorted(
            reason_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:10]

        return LifecycleAnalyticsSummary(
            total_cycles=total_cycles,
            total_canceled_orders_recorded=total_canceled_orders_recorded,
            keep_existing_order_cycles=keep_existing,
            quote_age_replace_cycles=quote_age,
            price_delta_replace_cycles=price_delta,
            qty_change_replace_cycles=qty_change,
            no_target_cycles=no_target,
            top_decision_reasons=top_reasons,
        )

    def _read_csv(self, filename: str) -> list[dict]:
        path = self.base_path / filename
        if not path.exists():
            return []

        with path.open("r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))