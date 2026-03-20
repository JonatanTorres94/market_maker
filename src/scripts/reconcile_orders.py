#src/scripts/reconcile_orders.py
from src.config.settings import get_settings
from src.core.logger import setup_logger
from src.exchange.binance_client import create_binance_client
from src.exchange.order_manager import OrderManager
from src.reconciliation.order_reconciler import OrderReconciler


def main():
    logger = setup_logger("reconcile_orders")
    settings = get_settings()

    if len(settings.infrastructure.enabled_symbols) != 1:
        raise ValueError(
            "This reconciliation runner currently supports exactly one enabled symbol."
        )

    symbol = settings.infrastructure.enabled_symbols[0]

    client = create_binance_client()
    order_manager = OrderManager(client)
    reconciler = OrderReconciler(order_manager=order_manager)

    summary = reconciler.reconcile(symbol=symbol)

    logger.info("Reconciliation completed for %s", symbol)
    logger.info("Journal orders: %s", summary.journal_orders)
    logger.info("Reconciled orders: %s", summary.reconciled_orders)
    logger.info("Missing orders: %s", summary.missing_orders)
    logger.info("Coverage ratio: %s", summary.coverage_ratio)
    logger.info("Bulk fetched orders: %s", summary.bulk_fetched_orders)
    logger.info("Bulk matched journal orders: %s", summary.bulk_matched_orders)
    logger.info("Bulk pages fetched: %s", summary.bulk_pages_fetched)
    logger.info("Fallback requested orders: %s", summary.fallback_requested_orders)
    logger.info("Fallback resolved orders: %s", summary.fallback_resolved_orders)
    logger.info("FILLED: %s", summary.filled_orders)
    logger.info("CANCELED: %s", summary.canceled_orders)
    logger.info("PARTIALLY_FILLED: %s", summary.partially_filled_orders)
    logger.info("OPEN: %s", summary.open_orders)


if __name__ == "__main__":
    main()