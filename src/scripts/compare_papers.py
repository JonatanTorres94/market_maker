# src/scripts/compare_papers.py
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from src.db.database import Database

EXPORT_FILENAME = "paper_metrics_summary.csv"


def _d(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _pct(value) -> Decimal:
    val = _d(value)
    return val * Decimal("100") if val <= Decimal("1") else val


def _fmt(value: Decimal, places: int = 4) -> str:
    try:
        return str(value.quantize(Decimal("1").scaleb(-places)))
    except Exception:
        return str(value)


def _extract_metrics(session_id: str, summary: dict) -> dict:
    return {
        "session": session_id,
        "cycles": _d(summary.get("total_cycles", 0)),
        "orders": _d(summary.get("total_orders", 0)),
        "executions": _d(summary.get("total_executions", 0)),
        "fill_ratio_pct": _pct(summary.get("fill_ratio", 0)),
        "cancel_ratio_pct": _pct(summary.get("cancel_ratio", 0)),
        "edge_bps": _d(summary.get("avg_edge_at_placement_bps", 0)),
        "adverse_5s_bps": _d(summary.get("adverse_selection_5s_bps", 0)),
        "adverse_30s_bps": _d(summary.get("adverse_selection_30s_bps", 0)),
        "equity_delta": _d(summary.get("equity_delta", 0)),
        "inventory_delta": _d(summary.get("inventory_delta", 0)),
        "realized_pnl": _d(summary.get("realized_pnl", 0)),
        "realized_pnl_on_notional_bps": _d(summary.get("realized_pnl_bps_on_notional", 0)),
        "total_quote_notional": _d(summary.get("total_quote_notional", 0)),
        "drift_cancel_total": _d(summary.get("drift_cancel_total", 0)),
        "drift_cancel_buy": _d(summary.get("drift_cancel_buy", 0)),
        "drift_cancel_sell": _d(summary.get("drift_cancel_sell", 0)),
    }


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("No data to display.")
        return

    headers = [
        "session", "realized_pnl_on_notional_bps", "realized_pnl",
        "fill_ratio_pct", "cancel_ratio_pct", "edge_bps",
        "adverse_5s_bps", "adverse_30s_bps", "drift_cancel_total",
        "orders", "executions", "cycles",
    ]

    printable = []
    for row in rows:
        printable.append({
            "session": row["session"],
            "realized_pnl_on_notional_bps": _fmt(row["realized_pnl_on_notional_bps"], 4),
            "realized_pnl": _fmt(row["realized_pnl"], 4),
            "fill_ratio_pct": _fmt(row["fill_ratio_pct"], 2),
            "cancel_ratio_pct": _fmt(row["cancel_ratio_pct"], 2),
            "edge_bps": _fmt(row["edge_bps"], 4),
            "adverse_5s_bps": _fmt(row["adverse_5s_bps"], 4),
            "adverse_30s_bps": _fmt(row["adverse_30s_bps"], 4),
            "drift_cancel_total": str(int(row["drift_cancel_total"])),
            "orders": str(int(row["orders"])),
            "executions": str(int(row["executions"])),
            "cycles": str(int(row["cycles"])),
        })

    widths = {h: max(len(h), max(len(r[h]) for r in printable)) for h in headers}
    print(" | ".join(h.ljust(widths[h]) for h in headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for row in printable:
        print(" | ".join(row[h].ljust(widths[h]) for h in headers))


def _print_summary(rows: list[dict]) -> None:
    if not rows:
        return
    n = Decimal(len(rows))
    avg = lambda key: sum((r[key] for r in rows), Decimal("0")) / n
    positive = sum(1 for r in rows if r["realized_pnl_on_notional_bps"] > 0)
    negative = sum(1 for r in rows if r["realized_pnl_on_notional_bps"] < 0)
    print(f"\nSummary ({len(rows)} sessions):")
    print(f"  Realized PnL on notional avg (bps): {_fmt(avg('realized_pnl_on_notional_bps'), 4)}")
    print(f"  Fill ratio avg (%):                 {_fmt(avg('fill_ratio_pct'), 2)}")
    print(f"  Edge avg (bps):                     {_fmt(avg('edge_bps'), 4)}")
    print(f"  Adverse +5s avg (bps):              {_fmt(avg('adverse_5s_bps'), 4)}")
    print(f"  Positive sessions: {positive} | Negative: {negative}")


def _export_csv(rows: list[dict]) -> None:
    if not rows:
        return
    fieldnames = [
        "session", "cycles", "orders", "executions",
        "fill_ratio_pct", "cancel_ratio_pct", "edge_bps",
        "adverse_5s_bps", "adverse_30s_bps", "equity_delta",
        "inventory_delta", "realized_pnl", "realized_pnl_on_notional_bps",
        "total_quote_notional", "drift_cancel_total", "drift_cancel_buy", "drift_cancel_sell",
    ]
    output_path = Path(EXPORT_FILENAME)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(row[k]) if isinstance(row[k], Decimal) else row[k] for k in fieldnames})
    print(f"\nCSV exported to: {output_path.resolve()}")


def main():
    db = Database()
    sessions = db.get_all_sessions()
    rows = []

    for session in sessions:
        sid = session["session_id"]
        result = db.get_analysis_result(sid)
        if result is None:
            continue
        rows.append(_extract_metrics(sid, result))

    db.close()

    rows.sort(key=lambda r: r["session"])
    _print_table(rows)
    _print_summary(rows)
    _export_csv(rows)


if __name__ == "__main__":
    main()
