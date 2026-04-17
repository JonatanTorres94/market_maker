# src/scripts/reconcile_orders.py
import os
from datetime import UTC, datetime

from src.config.settings import get_settings
from src.core.logger import setup_logger
from src.db.database import Database
from src.exchange.binance_client import create_binance_client
from src.exchange.order_manager import OrderManager
from src.reconciliation.order_reconciler import OrderReconciler


def main():
    logger = setup_logger("reconcile_orders")
    session_id = os.getenv("RUN_SESSION_ID", "").strip()
    if not session_id:
        raise ValueError("RUN_SESSION_ID environment variable is required")

    settings = get_settings()
    if len(settings.infrastructure.enabled_symbols) != 1:
        raise ValueError("This reconciliation runner currently supports exactly one enabled symbol.")

    symbol = settings.infrastructure.enabled_symbols[0]
    db = Database()
    orders_data = db.get_orders_for_session(session_id)
    logger.info("session=%s symbol=%s orders_loaded=%s", session_id, symbol, len(orders_data))

    client = create_binance_client()
    reconciler = OrderReconciler(order_manager=OrderManager(client))
    summary, records = reconciler.reconcile(symbol=symbol, orders_data=orders_data)

    db.reset_reconciled_orders(session_id, symbol)
    reconciled_at = datetime.now(UTC).isoformat()
    for rec in records:
        db.insert_reconciled_order(
            session_id=session_id,
            reconciled_at=reconciled_at,
            updated_at=rec["updated_at"],
            symbol=rec["symbol"],
            order_id=int(rec["order_id"]),
            side=rec["side"],
            status=rec["status"],
            price=float(rec["price"]) if rec["price"] else 0.0,
            orig_qty=float(rec["orig_qty"]) if rec["orig_qty"] else 0.0,
            executed_qty=float(rec["executed_qty"]) if rec["executed_qty"] else 0.0,
            cumulative_quote_qty=float(rec["cumulative_quote_qty"]) if rec["cumulative_quote_qty"] else 0.0,
        )

    db.close()

    logger.info("Journal orders: %s", summary.journal_orders)
    logger.info("Reconciled: %s | Missing: %s | Coverage: %s", summary.reconciled_orders, summary.missing_orders, summary.coverage_ratio)
    logger.info("FILLED=%s CANCELED=%s PARTIAL=%s OPEN=%s", summary.filled_orders, summary.canceled_orders, summary.partially_filled_orders, summary.open_orders)


if __name__ == "__main__":
    main()
