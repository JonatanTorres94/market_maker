#src/analytics/execution_fill_quality.py
import csv
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class ExecutionFillQualitySummary:
    total_executions: int
    buy_executions: int
    sell_executions: int
    maker_executions: int
    taker_executions: int
    maker_ratio: Decimal

    avg_edge_at_execution_bps: Decimal
    avg_edge_at_execution_buy_bps: Decimal
    avg_edge_at_execution_sell_bps: Decimal

    adverse_selection_5s_bps: Decimal
    adverse_selection_30s_bps: Decimal

    notional_weighted_edge_at_execution_bps: Decimal
    notional_weighted_adverse_selection_5s_bps: Decimal
    notional_weighted_adverse_selection_30s_bps: Decimal

    total_quote_notional: Decimal
    total_fees_in_quote: Decimal
    avg_fee_bps: Decimal
    notional_weighted_net_edge_after_fees_bps: Decimal

    executions_with_cycle_match: int
    executions_with_postfill_5s_match: int
    executions_with_postfill_30s_match: int


class ExecutionFillQualityAnalyzer:
    def __init__(self, base_path: str = "data/journals"):
        self.base_path = Path(base_path)

    def analyze(self) -> ExecutionFillQualitySummary:
        executions = self._read_csv("executions.csv")
        cycles = self._read_csv("cycles.csv")

        cycle_times, cycle_rows = self._prepare_cycles(cycles)

        buy_executions = 0
        sell_executions = 0
        maker_executions = 0
        taker_executions = 0

        edge_all: list[Decimal] = []
        edge_buy: list[Decimal] = []
        edge_sell: list[Decimal] = []

        adverse_5s: list[Decimal] = []
        adverse_30s: list[Decimal] = []

        weighted_edge_pairs: list[tuple[Decimal, Decimal]] = []
        weighted_adverse_5s_pairs: list[tuple[Decimal, Decimal]] = []
        weighted_adverse_30s_pairs: list[tuple[Decimal, Decimal]] = []
        weighted_net_edge_pairs: list[tuple[Decimal, Decimal]] = []

        executions_with_cycle_match = 0
        executions_with_postfill_5s_match = 0
        executions_with_postfill_30s_match = 0

        total_quote_notional = Decimal("0")
        total_fees_in_quote = Decimal("0")

        for execution in executions:
            side = execution.get("side", "")
            price = self._to_decimal(execution.get("price"))
            qty = self._to_decimal(execution.get("qty"))
            quote_qty = self._to_decimal(execution.get("quote_qty"))
            fee_in_quote = self._to_decimal(execution.get("commission_in_quote"))
            executed_at = execution.get("executed_at")

            if not executed_at:
                continue
            if price <= 0 or qty <= 0:
                continue

            if quote_qty <= 0:
                quote_qty = price * qty

            total_quote_notional += quote_qty
            total_fees_in_quote += fee_in_quote

            if side == "BUY":
                buy_executions += 1
            elif side == "SELL":
                sell_executions += 1

            is_maker = self._to_bool(execution.get("is_maker"))
            if is_maker:
                maker_executions += 1
            else:
                taker_executions += 1

            executed_dt = datetime.fromisoformat(executed_at)

            placement_cycle = self._find_latest_cycle_at_or_before(
                cycle_times=cycle_times,
                cycle_rows=cycle_rows,
                target_dt=executed_dt,
            )
            if placement_cycle is not None:
                executions_with_cycle_match += 1
                placement_mid = self._to_decimal(placement_cycle.get("mid_price"))
                edge_bps = self._edge_bps(
                    side=side,
                    execution_price=price,
                    reference_mid=placement_mid,
                )
                edge_all.append(edge_bps)
                weighted_edge_pairs.append((edge_bps, quote_qty))

                fee_bps = self._fee_bps(fee_in_quote=fee_in_quote, quote_qty=quote_qty)
                net_edge_bps = edge_bps - fee_bps
                weighted_net_edge_pairs.append((net_edge_bps, quote_qty))

                if side == "BUY":
                    edge_buy.append(edge_bps)
                elif side == "SELL":
                    edge_sell.append(edge_bps)

            post_5s_cycle = self._find_first_cycle_at_or_after(
                cycle_times=cycle_times,
                cycle_rows=cycle_rows,
                target_dt=executed_dt + timedelta(seconds=5),
            )
            if post_5s_cycle is not None:
                executions_with_postfill_5s_match += 1
                post_mid_5s = self._to_decimal(post_5s_cycle.get("mid_price"))
                adverse_bps_5s = self._adverse_selection_bps(
                    side=side,
                    execution_price=price,
                    post_fill_mid=post_mid_5s,
                )
                adverse_5s.append(adverse_bps_5s)
                weighted_adverse_5s_pairs.append((adverse_bps_5s, quote_qty))

            post_30s_cycle = self._find_first_cycle_at_or_after(
                cycle_times=cycle_times,
                cycle_rows=cycle_rows,
                target_dt=executed_dt + timedelta(seconds=30),
            )
            if post_30s_cycle is not None:
                executions_with_postfill_30s_match += 1
                post_mid_30s = self._to_decimal(post_30s_cycle.get("mid_price"))
                adverse_bps_30s = self._adverse_selection_bps(
                    side=side,
                    execution_price=price,
                    post_fill_mid=post_mid_30s,
                )
                adverse_30s.append(adverse_bps_30s)
                weighted_adverse_30s_pairs.append((adverse_bps_30s, quote_qty))

        total_executions = buy_executions + sell_executions

        return ExecutionFillQualitySummary(
            total_executions=total_executions,
            buy_executions=buy_executions,
            sell_executions=sell_executions,
            maker_executions=maker_executions,
            taker_executions=taker_executions,
            maker_ratio=self._safe_ratio(maker_executions, total_executions),
            avg_edge_at_execution_bps=self._avg(edge_all),
            avg_edge_at_execution_buy_bps=self._avg(edge_buy),
            avg_edge_at_execution_sell_bps=self._avg(edge_sell),
            adverse_selection_5s_bps=self._avg(adverse_5s),
            adverse_selection_30s_bps=self._avg(adverse_30s),
            notional_weighted_edge_at_execution_bps=self._weighted_average(weighted_edge_pairs),
            notional_weighted_adverse_selection_5s_bps=self._weighted_average(weighted_adverse_5s_pairs),
            notional_weighted_adverse_selection_30s_bps=self._weighted_average(weighted_adverse_30s_pairs),
            total_quote_notional=total_quote_notional,
            total_fees_in_quote=total_fees_in_quote,
            avg_fee_bps=self._fee_bps(fee_in_quote=total_fees_in_quote, quote_qty=total_quote_notional),
            notional_weighted_net_edge_after_fees_bps=self._weighted_average(weighted_net_edge_pairs),
            executions_with_cycle_match=executions_with_cycle_match,
            executions_with_postfill_5s_match=executions_with_postfill_5s_match,
            executions_with_postfill_30s_match=executions_with_postfill_30s_match,
        )

    def _prepare_cycles(self, cycles: list[dict]) -> tuple[list[datetime], list[dict]]:
        prepared = sorted(
            cycles,
            key=lambda row: datetime.fromisoformat(row["timestamp"]),
        )
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
    def _to_bool(value: str | None) -> bool:
        if value is None:
            return False
        return str(value).strip().lower() == "true"

    @staticmethod
    def _edge_bps(side: str, execution_price: Decimal, reference_mid: Decimal) -> Decimal:
        if reference_mid <= 0:
            return Decimal("0")

        if side == "BUY":
            return ((reference_mid - execution_price) / reference_mid) * Decimal("10000")
        return ((execution_price - reference_mid) / reference_mid) * Decimal("10000")

    @staticmethod
    def _adverse_selection_bps(side: str, execution_price: Decimal, post_fill_mid: Decimal) -> Decimal:
        if execution_price <= 0:
            return Decimal("0")

        if side == "BUY":
            return ((execution_price - post_fill_mid) / execution_price) * Decimal("10000")
        return ((post_fill_mid - execution_price) / execution_price) * Decimal("10000")

    @staticmethod
    def _fee_bps(fee_in_quote: Decimal, quote_qty: Decimal) -> Decimal:
        if quote_qty <= 0:
            return Decimal("0")
        return (fee_in_quote / quote_qty) * Decimal("10000")

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