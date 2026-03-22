#src/scripts/analyze_journal.py
import csv
import json
from decimal import Decimal
from pathlib import Path

from src.analytics.execution_metrics import ExecutionMetricsAnalyzer
from src.analytics.fill_quality import FillQualityAnalyzer
from src.analytics.lifecycle_analytics import LifecycleAnalyticsAnalyzer
from src.analytics.pnl_decomposition import PnLDecompositionAnalyzer
from src.analytics.execution_pnl_analysis import ExecutionPnlAnalyzer
from src.core.logger import setup_logger
from src.core.run_paths import ensure_run_directories, get_journal_base_path, get_reports_base_path, get_run_session_id


def read_csv(filepath: str) -> list[dict]:
    path = Path(filepath)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def pct(value: Decimal) -> str:
    return f"{(value * Decimal('100')):.2f}%"


def main():
    logger = setup_logger("analyze_journal")

    ensure_run_directories()
    base_path = get_journal_base_path()
    reports_base_path = Path(get_reports_base_path())
    logger.info("Run context | session_id=%s journal_base_path=%s reports_base_path=%s",
        get_run_session_id(),
        base_path, reports_base_path)

    cycles = read_csv(f"{base_path}/cycles.csv")
    orders = read_csv(f"{base_path}/orders.csv")
    equity = read_csv(f"{base_path}/equity.csv")
    reconciled_orders = read_csv(f"{base_path}/orders_reconciled.csv")
    executions = read_csv(f"{base_path}/executions.csv")

    logger.info("--- Journal Stats ---")
    logger.info("Cycles recorded: %s", len(cycles))
    logger.info("Orders recorded: %s", len(orders))
    logger.info("Equity snapshots recorded: %s", len(equity))
    logger.info("Reconciled orders recorded: %s", len(reconciled_orders))
    logger.info("Executions recorded: %s", len(executions))

    if orders and not reconciled_orders:
        logger.warning(
            "No reconciled orders found. Run reconcile_orders before relying on execution analytics."
        )

    if not executions:
        logger.warning(
            "No executions found in data/journals/executions.csv. Financial execution PnL analysis will be empty."
        )

    execution = ExecutionMetricsAnalyzer(base_path=base_path).analyze()
    fill_quality = FillQualityAnalyzer(base_path=base_path).analyze()
    pnl = PnLDecompositionAnalyzer(base_path=base_path).analyze()
    lifecycle = LifecycleAnalyticsAnalyzer(base_path=base_path).analyze()
    execution_pnl = ExecutionPnlAnalyzer(base_path=base_path).analyze()

    logger.info("--- Execution Analytics ---")
    logger.info("Total Orders: %s", execution.total_orders)
    logger.info("Fill Ratio: %s", pct(execution.fill_ratio))
    logger.info("Cancel Ratio: %s", pct(execution.cancel_ratio))
    logger.info("Avg Quote Lifetime: %ss", execution.average_quote_lifetime_seconds)
    logger.info("Avg Time to Fill: %ss", execution.average_time_to_fill_seconds)
    logger.info("Avg Time to Cancel: %ss", execution.average_time_to_cancel_seconds)
    logger.info(
        "Orders by side | BUY: %s, SELL: %s",
        execution.buy_orders,
        execution.sell_orders,
    )

    logger.info("--- Fill Quality ---")
    logger.info("Total fills: %s", fill_quality.total_fills)
    logger.info(
        "Fill ratio by side | BUY: %s, SELL: %s",
        pct(fill_quality.fill_ratio_buy),
        pct(fill_quality.fill_ratio_sell),
    )
    logger.info(
        "Avg time to fill by side | BUY: %ss, SELL: %ss",
        fill_quality.avg_time_to_fill_buy_seconds,
        fill_quality.avg_time_to_fill_sell_seconds,
    )
    logger.info(
        "Edge at placement (bps) | total: %s, BUY: %s, SELL: %s",
        fill_quality.avg_edge_at_placement_bps,
        fill_quality.avg_edge_at_placement_buy_bps,
        fill_quality.avg_edge_at_placement_sell_bps,
    )
    logger.info(
        "Adverse selection proxy (bps) | +5s: %s, +30s: %s",
        fill_quality.adverse_selection_5s_bps,
        fill_quality.adverse_selection_30s_bps,
    )
    logger.info(
        "Notional-weighted fill quality (bps) | edge: %s, adverse+5s: %s, adverse+30s: %s",
        fill_quality.notional_weighted_edge_at_placement_bps,
        fill_quality.notional_weighted_adverse_selection_5s_bps,
        fill_quality.notional_weighted_adverse_selection_30s_bps,
    )
    logger.info(
        "Cycle match coverage | placement: %s, postfill+5s: %s, postfill+30s: %s",
        fill_quality.fills_with_cycle_match,
        fill_quality.fills_with_postfill_5s_match,
        fill_quality.fills_with_postfill_30s_match,
    )

    logger.info("--- PnL Decomposition Proxy ---")
    logger.info(
        "Equity | Initial: %s, Final: %s, Delta: %s",
        pnl.initial_equity,
        pnl.final_equity,
        pnl.equity_delta,
    )
    logger.info(
        "Inventory | Initial base: %s, Final base: %s, Delta: %s",
        pnl.initial_base_inventory,
        pnl.final_base_inventory,
        pnl.inventory_delta,
    )
    logger.info(
        "Mid price | Initial: %s, Final: %s",
        pnl.initial_mid_price,
        pnl.final_mid_price,
    )
    logger.info(
        "PnL proxy | Realized: %s, Unrealized: %s, Final cost basis: %s, Processed fills: %s",
        pnl.realized_pnl_proxy,
        pnl.unrealized_pnl_proxy,
        pnl.anchored_inventory_cost_basis,
        pnl.processed_fills,
    )

    logger.info("--- Execution PnL (Ledger-Based Truth) ---")
    logger.info("Total executions: %s", execution_pnl.total_executions)
    logger.info("Total symbols: %s", execution_pnl.total_symbols)
    logger.info("Total quote notional: %s", execution_pnl.total_quote_notional)
    logger.info("Total fees in quote: %s", execution_pnl.total_fees_in_quote)
    logger.info(
        "Fee resolution | resolved: %s, missing: %s, zero: %s",
        execution_pnl.executions_with_fee_resolved,
        execution_pnl.executions_with_fee_missing,
        execution_pnl.executions_with_fee_zero,
    )
    logger.info("Realized pnl: %s", execution_pnl.realized_pnl)
    logger.info(
        "Realized pnl on notional (bps): %s",
        execution_pnl.realized_pnl_bps_on_notional,
    )

    if execution_pnl.executions_with_fee_missing > 0:
        logger.warning(
            "Execution PnL contains %s executions with missing fee normalization. Net edge conclusions are not final.",
            execution_pnl.executions_with_fee_missing,
        )

    logger.info("--- Lifecycle Analytics ---")
    logger.info("Total cycles: %s", lifecycle.total_cycles)
    logger.info("Total canceled orders recorded: %s", lifecycle.total_canceled_orders_recorded)
    logger.info("keep_existing_order cycles: %s", lifecycle.keep_existing_order_cycles)
    logger.info("quote_age replace cycles: %s", lifecycle.quote_age_replace_cycles)
    logger.info("price_delta replace cycles: %s", lifecycle.price_delta_replace_cycles)
    logger.info("qty_change replace cycles: %s", lifecycle.qty_change_replace_cycles)
    logger.info("no_target cycles: %s", lifecycle.no_target_cycles)

    logger.info("--- Top Decision Reasons ---")
    for reason, count in lifecycle.top_decision_reasons:
        logger.info("%s -> %s", reason, count)

    reports_base_path.mkdir(parents=True, exist_ok=True)
    summary_path = reports_base_path / "analysis_summary.json"

    summary_payload = {
        "run_session_id": get_run_session_id(),
        "journal_base_path": base_path,
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
        "execution_pnl_source": execution_pnl.source_filename,
        "total_executions": execution_pnl.total_executions,
        "total_quote_notional": str(execution_pnl.total_quote_notional),
        "total_fees_in_quote": str(execution_pnl.total_fees_in_quote),
        "executions_with_fee_resolved": execution_pnl.executions_with_fee_resolved,
        "executions_with_fee_missing": execution_pnl.executions_with_fee_missing,
        "executions_with_fee_zero": execution_pnl.executions_with_fee_zero,
        "realized_pnl": str(execution_pnl.realized_pnl),
        "realized_pnl_bps_on_notional": str(execution_pnl.realized_pnl_bps_on_notional),
    }

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=4)

    logger.info("Analysis summary written to %s", summary_path)
if __name__ == "__main__":
    main()