# src/scripts/analyze_journal.py
import os
import re
from datetime import UTC, datetime
from decimal import Decimal

from src.analytics.execution_metrics import ExecutionMetricsAnalyzer
from src.analytics.fill_quality import FillQualityAnalyzer
from src.analytics.lifecycle_analytics import LifecycleAnalyticsAnalyzer
from src.analytics.pnl_decomposition import PnLDecompositionAnalyzer
from src.analytics.execution_pnl_analysis import ExecutionPnlAnalyzer
from src.core.logger import setup_logger
from src.db.database import Database

DRIFT_CANCEL_PATTERN = re.compile(r"cancel_due_to_adverse_drift_([0-9]+(?:\.[0-9]+)?)")


def _parse_side_reasons(reason: str) -> tuple[str | None, str | None]:
    buy_reason = sell_reason = None
    for part in reason.split("|"):
        if part.startswith("BUY:"):
            buy_reason = part[4:]
        elif part.startswith("SELL:"):
            sell_reason = part[5:]
    return buy_reason, sell_reason


def _extract_drift_cancel_value(reason: str | None) -> Decimal | None:
    if not reason:
        return None
    m = DRIFT_CANCEL_PATTERN.search(reason)
    return Decimal(m.group(1)) if m else None


def _analyze_drift_cancels(cycles: list[dict]) -> dict:
    buy_vals: list[Decimal] = []
    sell_vals: list[Decimal] = []

    for row in cycles:
        reason = row.get("decision_reason") or ""
        buy_r, sell_r = _parse_side_reasons(reason)
        if (v := _extract_drift_cancel_value(buy_r)) is not None:
            buy_vals.append(v)
        if (v := _extract_drift_cancel_value(sell_r)) is not None:
            sell_vals.append(v)

    all_vals = buy_vals + sell_vals

    def _avg(vals: list[Decimal]) -> Decimal:
        return sum(vals, Decimal("0")) / Decimal(len(vals)) if vals else Decimal("0")

    return {
        "total_drift_cancels": len(all_vals),
        "buy_drift_cancels": len(buy_vals),
        "sell_drift_cancels": len(sell_vals),
        "avg_drift_cancel_bps": str(_avg(all_vals)),
        "avg_buy_drift_cancel_bps": str(_avg(buy_vals)),
        "avg_sell_drift_cancel_bps": str(_avg(sell_vals)),
        "max_drift_cancel_bps": str(max(all_vals)) if all_vals else "0",
        "min_drift_cancel_bps": str(min(all_vals)) if all_vals else "0",
    }


def main():
    logger = setup_logger("analyze_journal")
    session_id = os.getenv("RUN_SESSION_ID", "").strip()
    if not session_id:
        raise ValueError("RUN_SESSION_ID environment variable is required")

    db = Database()

    data = {
        "cycles": db.get_cycles_for_session(session_id),
        "orders": db.get_orders_for_session(session_id),
        "equity": db.get_equity_for_session(session_id),
        "orders_reconciled": db.get_reconciled_orders_for_session(session_id),
        "executions": db.get_executions_for_session(session_id),
        "executions_reconciled": db.get_executions_for_session(session_id),
    }

    logger.info(
        "Session %s | cycles=%s orders=%s equity=%s reconciled=%s executions=%s",
        session_id,
        len(data["cycles"]),
        len(data["orders"]),
        len(data["equity"]),
        len(data["orders_reconciled"]),
        len(data["executions"]),
    )

    if data["orders"] and not data["orders_reconciled"]:
        logger.warning("No reconciled orders found. Run reconcile_orders before relying on execution analytics.")

    execution = ExecutionMetricsAnalyzer(data=data).analyze()
    fill_quality = FillQualityAnalyzer(data=data).analyze()
    pnl = PnLDecompositionAnalyzer(data=data).analyze()
    lifecycle = LifecycleAnalyticsAnalyzer(data=data).analyze()
    execution_pnl = ExecutionPnlAnalyzer(data=data).analyze()
    drift = _analyze_drift_cancels(data["cycles"])

    pct = lambda v: f"{v * 100:.2f}%"

    logger.info("--- Execution Analytics ---")
    logger.info("Total orders: %s | Fill: %s | Cancel: %s", execution.total_orders, pct(execution.fill_ratio), pct(execution.cancel_ratio))
    logger.info("BUY=%s SELL=%s | Avg lifetime=%ss fill=%ss cancel=%ss", execution.buy_orders, execution.sell_orders, execution.average_quote_lifetime_seconds, execution.average_time_to_fill_seconds, execution.average_time_to_cancel_seconds)

    logger.info("--- Fill Quality ---")
    logger.info("Total fills: %s | Edge at placement: %s bps | Adverse +5s: %s bps +30s: %s bps", fill_quality.total_fills, fill_quality.avg_edge_at_placement_bps, fill_quality.adverse_selection_5s_bps, fill_quality.adverse_selection_30s_bps)

    logger.info("--- Execution PnL ---")
    logger.info("Total executions: %s | Realized PnL: %s | On notional: %s bps", execution_pnl.total_executions, execution_pnl.realized_pnl, execution_pnl.realized_pnl_bps_on_notional)

    logger.info("--- Lifecycle ---")
    logger.info("Cycles: %s | keep=%s age=%s price=%s qty=%s no_target=%s", lifecycle.total_cycles, lifecycle.keep_existing_order_cycles, lifecycle.quote_age_replace_cycles, lifecycle.price_delta_replace_cycles, lifecycle.qty_change_replace_cycles, lifecycle.no_target_cycles)

    logger.info("--- Drift Cancels ---")
    logger.info("Total=%s BUY=%s SELL=%s avg=%s bps", drift["total_drift_cancels"], drift["buy_drift_cancels"], drift["sell_drift_cancels"], drift["avg_drift_cancel_bps"])

    payload = {
        "session_id": session_id,
        "total_cycles": lifecycle.total_cycles,
        "total_orders": execution.total_orders,
        "fill_ratio": str(execution.fill_ratio),
        "cancel_ratio": str(execution.cancel_ratio),
        "total_fills": fill_quality.total_fills,
        "avg_edge_at_placement_bps": str(fill_quality.avg_edge_at_placement_bps),
        "adverse_selection_5s_bps": str(fill_quality.adverse_selection_5s_bps),
        "adverse_selection_30s_bps": str(fill_quality.adverse_selection_30s_bps),
        "notional_weighted_edge_at_placement_bps": str(fill_quality.notional_weighted_edge_at_placement_bps),
        "notional_weighted_adverse_selection_5s_bps": str(fill_quality.notional_weighted_adverse_selection_5s_bps),
        "notional_weighted_adverse_selection_30s_bps": str(fill_quality.notional_weighted_adverse_selection_30s_bps),
        "total_executions": execution_pnl.total_executions,
        "total_quote_notional": str(execution_pnl.total_quote_notional),
        "total_fees_in_quote": str(execution_pnl.total_fees_in_quote),
        "executions_with_fee_resolved": execution_pnl.executions_with_fee_resolved,
        "executions_with_fee_missing": execution_pnl.executions_with_fee_missing,
        "realized_pnl": str(execution_pnl.realized_pnl),
        "realized_pnl_bps_on_notional": str(execution_pnl.realized_pnl_bps_on_notional),
        "drift_cancel_total": drift["total_drift_cancels"],
        "drift_cancel_buy": drift["buy_drift_cancels"],
        "drift_cancel_sell": drift["sell_drift_cancels"],
        "avg_drift_cancel_bps": drift["avg_drift_cancel_bps"],
        "equity_delta": str(pnl.equity_delta),
        "inventory_delta": str(pnl.inventory_delta),
    }

    db.insert_analysis_result(session_id, datetime.now(UTC).isoformat(), payload)
    db.close()
    logger.info("Analysis result stored for session %s", session_id)


if __name__ == "__main__":
    main()
