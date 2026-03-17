import csv
from decimal import Decimal
from pathlib import Path

from src.core.logger import setup_logger
# Nueva importación
from src.analytics.execution_metrics import ExecutionMetricsAnalyzer


def read_csv(filepath: str) -> list[dict]:
    path = Path(filepath)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def main():
    logger = setup_logger("analyze_journal")

    cycles = read_csv("data/journals/cycles.csv")
    orders = read_csv("data/journals/orders.csv")
    equity = read_csv("data/journals/equity.csv")
    reconciled_orders = read_csv("data/journals/orders_reconciled.csv")

    logger.info("--- Journal Stats ---")
    logger.info("Cycles recorded: %s", len(cycles))
    logger.info("Orders recorded: %s", len(orders))
    logger.info("Equity snapshots recorded: %s", len(equity))
    logger.info("Reconciled orders recorded: %s", len(reconciled_orders))

    # --- MÉTRICAS DE EJECUCIÓN AVANZADAS ---
    logger.info("--- Execution Analytics ---")
    try:
        # El analyzer lee por defecto los archivos en data/journals/
        metrics = ExecutionMetricsAnalyzer().analyze()

        logger.info("Total Orders: %s", metrics.total_orders)
        logger.info("Fill Ratio: %s%%", (metrics.fill_ratio * 100).quantize(Decimal("0.01")))
        logger.info("Cancel Ratio: %s%%", (metrics.cancel_ratio * 100).quantize(Decimal("0.01")))
        
        logger.info("Avg Quote Lifetime: %ss", metrics.average_quote_lifetime_seconds)
        logger.info("Avg Time to Fill: %ss", metrics.average_time_to_fill_seconds)
        logger.info("Avg Time to Cancel: %ss", metrics.average_time_to_cancel_seconds)
    except Exception as e:
        logger.error("Could not calculate execution metrics: %s", e)

    # --- ESTADÍSTICAS BÁSICAS EXISTENTES ---
    if orders:
        buy_orders = [o for o in orders if o["side"] == "BUY"]
        sell_orders = [o for o in orders if o["side"] == "SELL"]
        logger.info("Orders by side | BUY: %s, SELL: %s", len(buy_orders), len(sell_orders))

    if equity:
        first = Decimal(equity[0]["mark_to_market_equity"])
        last = Decimal(equity[-1]["mark_to_market_equity"])
        logger.info("Profit/Loss | Initial: %s, Final: %s, Delta: %s", first, last, last - first)

    if reconciled_orders:
            filled = [o for o in reconciled_orders if o["status"] == "FILLED"]
            total_filled_qty = sum(Decimal(o["executed_qty"]) for o in filled)
            logger.info("Fills | Total filled: %s, Total Qty: %s", len(filled), total_filled_qty)
            
    # Esta es la versión correcta (usando len)
    if len(reconciled_orders) == 0 and len(orders) > 0:
            logger.warning(
                "No reconciled orders found. Run reconcile_orders before relying on execution analytics."
            )


if __name__ == "__main__":
    main()