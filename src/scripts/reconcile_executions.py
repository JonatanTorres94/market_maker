# src/scripts/reconcile_executions.py
import os
from datetime import UTC, datetime, timedelta

from src.config.settings import get_settings
from src.core.fee_normalizer import FeeNormalizer
from src.core.logger import setup_logger
from src.db.database import Database
from src.db.execution_journal import DbExecutionJournal
from src.engine.execution_store import ExecutionStore
from src.exchange.binance_client import create_binance_client
from src.exchange.binance_price_provider import BinancePriceProvider
from src.exchange.order_manager import OrderManager
from src.reconciliation.trade_reconciler import TradeReconciler


def main():
    logger = setup_logger("reconcile_executions")
    session_id = os.getenv("RUN_SESSION_ID", "").strip()
    if not session_id:
        raise ValueError("RUN_SESSION_ID environment variable is required")

    settings = get_settings()
    symbol = settings.infrastructure.enabled_symbols[0]

    db = Database()
    started_at = db.get_session_started_at(session_id)
    if not started_at:
        raise ValueError(f"Session not found in DB: {session_id}")

    dt = datetime.fromisoformat(started_at)
    start_ms = int((dt - timedelta(minutes=2)).timestamp() * 1000)
    logger.info("session=%s symbol=%s start_ms=%s", session_id, symbol, start_ms)

    client = create_binance_client()
    price_provider = BinancePriceProvider(client)
    execution_journal = DbExecutionJournal(db, session_id)

    reconciler = TradeReconciler(
        order_manager=OrderManager(client),
        execution_store=ExecutionStore(),
        execution_journal=execution_journal,
        fee_normalizer=FeeNormalizer(price_provider=price_provider),
    )

    summary = reconciler.reconcile_symbol(symbol=symbol, start_time_ms=start_ms)
    db.close()

    logger.info(
        "Reconciliation done | fetched=%s inserted=%s duplicates=%s pages=%s missing_fee=%s range=[%s,%s]",
        summary.fetched_trades, summary.inserted_trades, summary.duplicate_trades,
        summary.pages_fetched, summary.missing_fee_conversions,
        summary.earliest_trade_id, summary.latest_trade_id,
    )


if __name__ == "__main__":
    main()
