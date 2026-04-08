import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path


# ============================================================
# CONFIGURACIÓN "DURA"
# ============================================================
PAPER_START = 52
PAPER_END = 59

RUNS_BASE_PATH = Path("data/runs")
EXPORT_CSV = True
EXPORT_FILENAME = "paper_metrics_summary.csv"


# ============================================================
# HELPERS
# ============================================================
def d(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def pct_from_ratio(value) -> Decimal:
    """
    Convierte ratio a porcentaje si viene como 0.0541 -> 5.41
    Si ya viene en porcentaje, dejalo igual.
    """
    val = d(value)
    if val <= Decimal("1"):
        return val * Decimal("100")
    return val


def get_nested(data: dict, *keys, default=None):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def format_decimal(value: Decimal, places: int = 4) -> str:
    q = Decimal("1").scaleb(-places)  # ej: 0.0001
    try:
        return str(value.quantize(q))
    except Exception:
        return str(value)


# ============================================================
# EXTRACCIÓN
# ============================================================
def load_analysis_summary(paper_number: int) -> dict | None:
    run_id = f"paper_{paper_number:03d}"
    summary_path = RUNS_BASE_PATH / run_id / "reports" / "analysis_summary.json"

    if not summary_path.exists():
        print(f"[WARN] No existe: {summary_path}")
        return None

    try:
        with summary_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[ERROR] No se pudo leer {summary_path}: {exc}")
        return None


def extract_metrics(paper_number: int, summary: dict) -> dict:
    run_id = f"paper_{paper_number:03d}"

    return {
        "paper": run_id,
        "cycles": d(summary.get("total_cycles", 0)),  # si no existe, queda 0
        "orders": d(summary.get("total_orders", 0)),
        "executions": d(summary.get("total_executions", 0)),
        "fill_ratio_pct": pct_from_ratio(summary.get("fill_ratio", 0)),
        "cancel_ratio_pct": pct_from_ratio(summary.get("cancel_ratio", 0)),
        "edge_bps": d(summary.get("avg_edge_at_placement_bps", 0)),
        "adverse_5s_bps": d(summary.get("adverse_selection_5s_bps", 0)),
        "adverse_30s_bps": d(summary.get("adverse_selection_30s_bps", 0)),
        "equity_delta": d(summary.get("equity_delta", 0)),  # si no existe, queda 0
        "inventory_delta": d(summary.get("inventory_delta", 0)),  # si no existe, queda 0
        "pnl_proxy_realized": d(summary.get("pnl_proxy_realized", 0)),  # si no existe, queda 0
        "realized_pnl": d(summary.get("realized_pnl", 0)),
        "realized_pnl_on_notional_bps": d(summary.get("realized_pnl_bps_on_notional", 0)),
        "total_quote_notional": d(summary.get("total_quote_notional", 0)),
        "drift_cancel_total": d(summary.get("drift_cancel_total", 0)),
        "drift_cancel_buy": d(summary.get("drift_cancel_buy", 0)),
        "drift_cancel_sell": d(summary.get("drift_cancel_sell", 0)),
    }


# ============================================================
# OUTPUT
# ============================================================
def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No hay datos para mostrar.")
        return

    headers = [
        "paper",
        "realized_pnl_on_notional_bps",
        "realized_pnl",
        "fill_ratio_pct",
        "cancel_ratio_pct",
        "edge_bps",
        "adverse_5s_bps",
        "adverse_30s_bps",
        "drift_cancel_total",
        "orders",
        "executions",
        "cycles",
    ]

    printable_rows = []
    for row in rows:
        printable_rows.append({
            "paper": row["paper"],
            "realized_pnl_on_notional_bps": format_decimal(row["realized_pnl_on_notional_bps"], 4),
            "realized_pnl": format_decimal(row["realized_pnl"], 4),
            "equity_delta": format_decimal(row["equity_delta"], 4),
            "inventory_delta": format_decimal(row["inventory_delta"], 6),
            "fill_ratio_pct": format_decimal(row["fill_ratio_pct"], 2),
            "cancel_ratio_pct": format_decimal(row["cancel_ratio_pct"], 2),
            "edge_bps": format_decimal(row["edge_bps"], 4),
            "adverse_5s_bps": format_decimal(row["adverse_5s_bps"], 4),
            "adverse_30s_bps": format_decimal(row["adverse_30s_bps"], 4),
            "drift_cancel_total": str(int(row["drift_cancel_total"])),
            "orders": str(int(row["orders"])),
            "executions": str(int(row["executions"])),
            "cycles": str(int(row["cycles"])),
        })

    widths = {}
    for h in headers:
        widths[h] = max(len(h), max(len(r[h]) for r in printable_rows))

    header_line = " | ".join(h.ljust(widths[h]) for h in headers)
    sep_line = "-+-".join("-" * widths[h] for h in headers)

    print(header_line)
    print(sep_line)

    for row in printable_rows:
        print(" | ".join(row[h].ljust(widths[h]) for h in headers))


def export_csv(rows: list[dict], output_path: Path) -> None:
    if not rows:
        return

    fieldnames = [
        "paper",
        "cycles",
        "orders",
        "executions",
        "fill_ratio_pct",
        "cancel_ratio_pct",
        "edge_bps",
        "adverse_5s_bps",
        "adverse_30s_bps",
        "equity_delta",
        "inventory_delta",
        "pnl_proxy_realized",
        "realized_pnl",
        "realized_pnl_on_notional_bps",
        "total_quote_notional",
        "drift_cancel_total",
        "drift_cancel_buy",
        "drift_cancel_sell",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({
                "paper": row["paper"],
                "cycles": str(int(row["cycles"])),
                "orders": str(int(row["orders"])),
                "executions": str(int(row["executions"])),
                "fill_ratio_pct": str(row["fill_ratio_pct"]),
                "cancel_ratio_pct": str(row["cancel_ratio_pct"]),
                "edge_bps": str(row["edge_bps"]),
                "adverse_5s_bps": str(row["adverse_5s_bps"]),
                "adverse_30s_bps": str(row["adverse_30s_bps"]),
                "equity_delta": str(row["equity_delta"]),
                "inventory_delta": str(row["inventory_delta"]),
                "pnl_proxy_realized": str(row["pnl_proxy_realized"]),
                "realized_pnl": str(row["realized_pnl"]),
                "realized_pnl_on_notional_bps": str(row["realized_pnl_on_notional_bps"]),
                "total_quote_notional": str(row["total_quote_notional"]),
                "drift_cancel_total": str(int(row["drift_cancel_total"])),
                "drift_cancel_buy": str(int(row["drift_cancel_buy"])),
                "drift_cancel_sell": str(int(row["drift_cancel_sell"])),
            })


def print_summary(rows: list[dict]) -> None:
    if not rows:
        return

    count = Decimal(len(rows))
    avg_realized_bps = sum((r["realized_pnl_on_notional_bps"] for r in rows), Decimal("0")) / count
    avg_fill_ratio = sum((r["fill_ratio_pct"] for r in rows), Decimal("0")) / count
    avg_edge = sum((r["edge_bps"] for r in rows), Decimal("0")) / count
    avg_adv_5 = sum((r["adverse_5s_bps"] for r in rows), Decimal("0")) / count
    avg_adv_30 = sum((r["adverse_30s_bps"] for r in rows), Decimal("0")) / count

    positive_runs = sum(1 for r in rows if r["realized_pnl_on_notional_bps"] > 0)
    negative_runs = sum(1 for r in rows if r["realized_pnl_on_notional_bps"] < 0)

    print("\nResumen:")
    print(f"- Runs analizados: {len(rows)}")
    print(f"- Realized pnl on notional promedio (bps): {format_decimal(avg_realized_bps, 4)}")
    print(f"- Fill ratio promedio (%): {format_decimal(avg_fill_ratio, 2)}")
    print(f"- Edge promedio (bps): {format_decimal(avg_edge, 4)}")
    print(f"- Adverse +5s promedio (bps): {format_decimal(avg_adv_5, 4)}")
    print(f"- Adverse +30s promedio (bps): {format_decimal(avg_adv_30, 4)}")
    print(f"- Runs con realized pnl on notional > 0: {positive_runs}")
    print(f"- Runs con realized pnl on notional < 0: {negative_runs}")


# ============================================================
# MAIN
# ============================================================
def main():
    rows = []

    for paper_number in range(PAPER_START, PAPER_END + 1):
        summary = load_analysis_summary(paper_number)
        if summary is None:
            continue

        row = extract_metrics(paper_number, summary)
        rows.append(row)

    rows.sort(key=lambda r: r["paper"])

    print_table(rows)
    print_summary(rows)

    if EXPORT_CSV:
        output_path = Path(EXPORT_FILENAME)
        export_csv(rows, output_path)
        print(f"\nCSV exportado en: {output_path.resolve()}")


if __name__ == "__main__":
    main()