# src/scripts/reconcile_executions.py
import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.config.settings import get_settings
from src.core.fee_normalizer import FeeNormalizer
from src.core.logger import setup_logger
from src.engine.execution_store import ExecutionStore
from src.exchange.binance_client import create_binance_client
from src.exchange.binance_price_provider import BinancePriceProvider
from src.exchange.order_manager import OrderManager
from src.journal.null_execution_journal import NullExecutionJournal
from src.reconciliation.trade_reconciler import TradeReconciler
from src.core.run_paths import ensure_run_directories, get_journal_base_path, get_run_session_id

def main():
    logger = setup_logger("reconcile_executions")
    ensure_run_directories()
    logger.info("Run context | session_id=%s journal_base_path=%s", get_run_session_id(), get_journal_base_path())
    settings = get_settings()
    symbol = settings.infrastructure.enabled_symbols[0]

    base_path = Path(get_journal_base_path())
    orders_path = base_path / "orders.csv"
    raw_path = base_path / "executions.csv"
    output_path = base_path / "executions_reconciled.csv"
    meta_path = base_path / "executions_reconciled_meta.json"

    start_ms = None
    if orders_path.exists():
        try:
            with orders_path.open("r", encoding="utf-8") as f:
                reader = list(csv.DictReader(f))
                if reader:
                    first_ts = reader[0].get("placed_at") or reader[0].get("timestamp")
                    dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                    start_ms = int((dt - timedelta(minutes=2)).timestamp() * 1000)
                    logger.info("Detectado inicio de sesión en: %s", first_ts)
        except Exception as exc:
            logger.error("Error al calcular start_time: %s", exc)

    client = create_binance_client()
    price_provider = BinancePriceProvider(client)
    execution_store = ExecutionStore()

    reconciler = TradeReconciler(
        order_manager=OrderManager(client),
        execution_store=execution_store,
        execution_journal=NullExecutionJournal(),
        fee_normalizer=FeeNormalizer(price_provider=price_provider),
    )

    logger.info("Solicitando trades de %s a Binance...", symbol)
    summary = reconciler.reconcile_symbol(symbol=symbol, start_time_ms=start_ms)

    reconciled_executions = execution_store.list_by_symbol(symbol)
    reconciled_executions.sort(key=lambda x: (x.executed_at, x.trade_id))

    fieldnames = [
        "exchange",
        "account",
        "symbol",
        "trade_id",
        "order_id",
        "client_order_id",
        "side",
        "price",
        "qty",
        "quote_qty",
        "commission",
        "commission_asset",
        "commission_in_quote",
        "commission_fx_rate",
        "commission_fx_symbol",
        "commission_fx_timestamp",
        "is_maker",
        "executed_at",
        "source",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for execution in reconciled_executions:
            writer.writerow(
                {
                    "exchange": execution.exchange,
                    "account": execution.account,
                    "symbol": execution.symbol,
                    "trade_id": execution.trade_id,
                    "order_id": execution.order_id,
                    "client_order_id": execution.client_order_id,
                    "side": execution.side,
                    "price": str(execution.price),
                    "qty": str(execution.qty),
                    "quote_qty": str(execution.quote_qty),
                    "commission": str(execution.commission),
                    "commission_asset": execution.commission_asset,
                    "commission_in_quote": ""
                    if execution.commission_in_quote is None
                    else str(execution.commission_in_quote),
                    "commission_fx_rate": ""
                    if execution.commission_fx_rate is None
                    else str(execution.commission_fx_rate),
                    "commission_fx_symbol": execution.commission_fx_symbol or "",
                    "commission_fx_timestamp": execution.commission_fx_timestamp or "",
                    "is_maker": execution.is_maker,
                    "executed_at": execution.executed_at,
                    "source": execution.source,
                }
            )

    meta = {
        "symbol": symbol,
        "start_ms": start_ms,
        "rows_written": len(reconciled_executions),
        "raw_rows_seen": sum(1 for _ in raw_path.open(encoding="utf-8")) - 1 if raw_path.exists() else 0,
        "source_file": str(raw_path),
        "generated_at": datetime.now(UTC).isoformat(),
        "notes": (
            "Silver file built from REST-reconciled executions in ExecutionStore. "
            "Fees normalized via BinancePriceProvider when possible."
        ),
        "trade_reconciliation_summary": {
            "fetched_trades": summary.fetched_trades,
            "inserted_trades": summary.inserted_trades,
            "duplicate_trades": summary.duplicate_trades,
            "pages_fetched": summary.pages_fetched,
            "earliest_trade_id": summary.earliest_trade_id,
            "latest_trade_id": summary.latest_trade_id,
            "missing_fee_conversions": summary.missing_fee_conversions,
        },
    }

    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4)

    logger.info("✅ Archivo Silver y Meta creados con %s trades.", len(reconciled_executions))


if __name__ == "__main__":
    main()