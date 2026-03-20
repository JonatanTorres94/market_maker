import csv
from bisect import bisect_right, bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class FillQualitySummary:
    total_orders: int
    total_fills: int
    buy_orders: int
    sell_orders: int
    buy_fills: int
    sell_fills: int
    fill_ratio_total: Decimal
    fill_ratio_buy: Decimal
    fill_ratio_sell: Decimal
    avg_time_to_fill_seconds: Decimal
    avg_time_to_fill_buy_seconds: Decimal
    avg_time_to_fill_sell_seconds: Decimal
    avg_edge_at_placement_bps: Decimal
    avg_edge_at_placement_buy_bps: Decimal
    avg_edge_at_placement_sell_bps: Decimal
    adverse_selection_5s_bps: Decimal
    adverse_selection_30s_bps: Decimal
    notional_weighted_edge_at_placement_bps: Decimal
    notional_weighted_adverse_selection_5s_bps: Decimal
    notional_weighted_adverse_selection_30s_bps: Decimal
    fills_with_cycle_match: int
    fills_with_postfill_5s_match: int
    fills_with_postfill_30s_match: int


class FillQualityAnalyzer:
    def __init__(self, base_path: str = "data/journals"):
        self.base_path = Path(base_path)

    def analyze(self) -> FillQualitySummary:
        orders = self._read_csv("orders.csv")
        reconciled = self._read_csv("orders_reconciled.csv")
        cycles = self._read_csv("cycles.csv")

        total_orders = len(orders)
        buy_orders = sum(1 for row in orders if row["side"] == "BUY")
        sell_orders = sum(1 for row in orders if row["side"] == "SELL")

        orders_by_id = {int(row["order_id"]): row for row in orders}
        filled_statuses = {"FILLED", "PARTIALLY_FILLED"}
        filled = [row for row in reconciled if row["status"] in filled_statuses]

        cycle_times, cycle_rows = self._prepare_cycles(cycles)

        buy_fills = 0
        sell_fills = 0

        time_to_fill_all: list[Decimal] = []
        time_to_fill_buy: list[Decimal] = []
        time_to_fill_sell: list[Decimal] = []

        edge_all: list[Decimal] = []
        edge_buy: list[Decimal] = []
        edge_sell: list[Decimal] = []

        adverse_5s: list[Decimal] = []
        adverse_30s: list[Decimal] = []

        weighted_edge_pairs: list[tuple[Decimal, Decimal]] = []
        weighted_adverse_5s_pairs: list[tuple[Decimal, Decimal]] = []
        weighted_adverse_30s_pairs: list[tuple[Decimal, Decimal]] = []

        fills_with_cycle_match = 0
        fills_with_postfill_5s_match = 0
        fills_with_postfill_30s_match = 0

        for fill in filled:
            order_id = int(fill["order_id"])
            placed_order = orders_by_id.get(order_id)
            if placed_order is None:
                continue

            side = fill["side"]
            placed_at = placed_order["placed_at"]
            updated_at = fill.get("updated_at")
            fill_price = self._to_decimal(fill.get("price"))
            executed_qty = self._to_decimal(fill.get("executed_qty"))
            cumulative_quote_qty = self._to_decimal(fill.get("cumulative_quote_qty"))
            quote_weight = cumulative_quote_qty if cumulative_quote_qty > 0 else fill_price * executed_qty

            if not updated_at:
                continue

            if side == "BUY":
                buy_fills += 1
            else:
                sell_fills += 1

            ttf = Decimal(str(self._seconds_between(placed_order["placed_at"], updated_at)))
            time_to_fill_all.append(ttf)
            if side == "BUY":
                time_to_fill_buy.append(ttf)
            else:
                time_to_fill_sell.append(ttf)

            placement_cycle = self._find_latest_cycle_at_or_before(
                cycle_times=cycle_times,
                cycle_rows=cycle_rows,
                target_dt=datetime.fromisoformat(placed_at),
            )
            if placement_cycle is not None:
                fills_with_cycle_match += 1
                placement_mid = self._to_decimal(placement_cycle.get("mid_price"))
                edge_bps = self._edge_at_placement_bps(
                    side=side,
                    fill_price=fill_price,
                    mid_price=placement_mid,
                )
                edge_all.append(edge_bps)
                weighted_edge_pairs.append((edge_bps, quote_weight))
                if side == "BUY":
                    edge_buy.append(edge_bps)
                else:
                    edge_sell.append(edge_bps)

            fill_dt = datetime.fromisoformat(updated_at)

            post_5s_cycle = self._find_first_cycle_at_or_after(
                cycle_times=cycle_times,
                cycle_rows=cycle_rows,
                target_dt=fill_dt + timedelta(seconds=5),
            )
            if post_5s_cycle is not None:
                fills_with_postfill_5s_match += 1
                post_mid_5s = self._to_decimal(post_5s_cycle.get("mid_price"))
                adverse_bps_5s = self._adverse_selection_bps(
                    side=side,
                    fill_price=fill_price,
                    post_fill_mid=post_mid_5s,
                )
                adverse_5s.append(adverse_bps_5s)
                weighted_adverse_5s_pairs.append((adverse_bps_5s, quote_weight))

            post_30s_cycle = self._find_first_cycle_at_or_after(
                cycle_times=cycle_times,
                cycle_rows=cycle_rows,
                target_dt=fill_dt + timedelta(seconds=30),
            )
            if post_30s_cycle is not None:
                fills_with_postfill_30s_match += 1
                post_mid_30s = self._to_decimal(post_30s_cycle.get("mid_price"))
                adverse_bps_30s = self._adverse_selection_bps(
                    side=side,
                    fill_price=fill_price,
                    post_fill_mid=post_mid_30s,
                )
                adverse_30s.append(adverse_bps_30s)
                weighted_adverse_30s_pairs.append((adverse_bps_30s, quote_weight))

        return FillQualitySummary(
            total_orders=total_orders,
            total_fills=len(filled),
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            buy_fills=buy_fills,
            sell_fills=sell_fills,
            fill_ratio_total=self._safe_ratio(len(filled), total_orders),
            fill_ratio_buy=self._safe_ratio(buy_fills, buy_orders),
            fill_ratio_sell=self._safe_ratio(sell_fills, sell_orders),
            avg_time_to_fill_seconds=self._avg(time_to_fill_all),
            avg_time_to_fill_buy_seconds=self._avg(time_to_fill_buy),
            avg_time_to_fill_sell_seconds=self._avg(time_to_fill_sell),
            avg_edge_at_placement_bps=self._avg(edge_all),
            avg_edge_at_placement_buy_bps=self._avg(edge_buy),
            avg_edge_at_placement_sell_bps=self._avg(edge_sell),
            adverse_selection_5s_bps=self._avg(adverse_5s),
            adverse_selection_30s_bps=self._avg(adverse_30s),
            notional_weighted_edge_at_placement_bps=self._weighted_average(weighted_edge_pairs),
            notional_weighted_adverse_selection_5s_bps=self._weighted_average(weighted_adverse_5s_pairs),
            notional_weighted_adverse_selection_30s_bps=self._weighted_average(weighted_adverse_30s_pairs),
            fills_with_cycle_match=fills_with_cycle_match,
            fills_with_postfill_5s_match=fills_with_postfill_5s_match,
            fills_with_postfill_30s_match=fills_with_postfill_30s_match,
        )

    def _prepare_cycles(self, cycles: list[dict]) -> tuple[list[datetime], list[dict]]:
        prepared = sorted(cycles, key=lambda row: datetime.fromisoformat(row["timestamp"]))
        times = [datetime.fromisoformat(row["timestamp"]) for row in prepared]
        return times, prepared

    def _find_latest_cycle_at_or_before(
        self,
        cycle_times: list[datetime],
        cycle_rows: list[dict],
        target_dt: datetime,
    ) -> dict | None:
        if not cycle_times:
            return None

        idx = bisect_right(cycle_times, target_dt) - 1
        if idx < 0:
            return None
        return cycle_rows[idx]

    def _find_first_cycle_at_or_after(
        self,
        cycle_times: list[datetime],
        cycle_rows: list[dict],
        target_dt: datetime,
    ) -> dict | None:
        if not cycle_times:
            return None

        idx = bisect_left(cycle_times, target_dt)
        if idx >= len(cycle_rows):
            return None
        return cycle_rows[idx]

    def _read_csv(self, filename: str) -> list[dict]:
        path = self.base_path / filename
        if not path.exists():
            return []
        with path.open("r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def _to_decimal(value: str | None) -> Decimal:
        if value is None or value == "":
            return Decimal("0")
        return Decimal(value)

    @staticmethod
    def _seconds_between(start_iso: str, end_iso: str) -> float:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return max((end - start).total_seconds(), 0.0)

    @staticmethod
    def _edge_at_placement_bps(side: str, fill_price: Decimal, mid_price: Decimal) -> Decimal:
        if mid_price <= 0:
            return Decimal("0")
        if side == "BUY":
            return ((mid_price - fill_price) / mid_price) * Decimal("10000")
        return ((fill_price - mid_price) / mid_price) * Decimal("10000")

    @staticmethod
    def _adverse_selection_bps(side: str, fill_price: Decimal, post_fill_mid: Decimal) -> Decimal:
        if fill_price <= 0:
            return Decimal("0")
        if side == "BUY":
            return ((fill_price - post_fill_mid) / fill_price) * Decimal("10000")
        return ((post_fill_mid - fill_price) / fill_price) * Decimal("10000")

    @staticmethod
    def _avg(values: list[Decimal]) -> Decimal:
        if not values:
            return Decimal("0")
        return sum(values) / Decimal(len(values))

    @staticmethod
    def _weighted_average(pairs: list[tuple[Decimal, Decimal]]) -> Decimal:
        if not pairs:
            return Decimal("0")
        total_weight = sum(weight for _, weight in pairs)
        if total_weight <= 0:
            return Decimal("0")
        weighted_sum = sum(value * weight for value, weight in pairs)
        return weighted_sum / total_weight

    @staticmethod
    def _safe_ratio(numerator: int, denominator: int) -> Decimal:
        if denominator == 0:
            return Decimal("0")
        return Decimal(numerator) / Decimal(denominator)