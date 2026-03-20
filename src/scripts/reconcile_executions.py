import csv
import json
from pathlib import Path
from datetime import datetime, timedelta, UTC
from src.core.logger import setup_logger
from src.config.settings import get_settings
from src.exchange.binance_client import create_binance_client
from src.exchange.order_manager import OrderManager
from src.reconciliation.trade_reconciler import TradeReconciler
from src.engine.execution_store import ExecutionStore
from src.core.fee_normalizer import FeeNormalizer
from src.journal.null_execution_journal import NullExecutionJournal

def main():
    logger = setup_logger("reconcile_executions_bridge")
    settings = get_settings()
    symbol = settings.infrastructure.enabled_symbols[0]
    
    # 1. PATHS
    orders_path = Path("data/journals/orders.csv")
    raw_path = Path("data/journals/executions.csv")
    output_path = Path("data/journals/executions_reconciled.csv")
    meta_path = Path("data/journals/executions_reconciled_meta.json")

    # 2. DETERMINAR EL START_TIME
    start_ms = None
    if orders_path.exists():
        try:
            with orders_path.open("r", encoding="utf-8") as f:
                reader = list(csv.DictReader(f))
                if reader:
                    first_ts = reader[0].get('placed_at') or reader[0].get('timestamp')
                    dt = datetime.fromisoformat(first_ts.replace('Z', '+00:00'))
                    start_ms = int((dt - timedelta(minutes=2)).timestamp() * 1000)
                    logger.info(f"Detectado inicio de sesión en: {first_ts}")
        except Exception as e:
            logger.error(f"Error al calcular start_time: {e}")

    # 3. SETUP Y RECONCILIACIÓN (BINANCE)
    client = create_binance_client()
    reconciler = TradeReconciler(
        order_manager=OrderManager(client),
        execution_store=ExecutionStore(),
        execution_journal=NullExecutionJournal(), # No queremos que duplique en el raw
        fee_normalizer=FeeNormalizer()
    )

    logger.info(f"Solicitando trades de {symbol} a Binance...")
    reconciler.reconcile_symbol(symbol=symbol, start_time_ms=start_ms)

    # 4. PROCESAMIENTO (DEDUPLICACIÓN Y FILTRADO)
    latest_trades = {}
    fieldnames = []
    if raw_path.exists():
        with raw_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                key = (row['exchange'], row['account'], row['symbol'], row['trade_id'])
                
                # Filtro por tiempo
                trade_time_ms = int(datetime.fromisoformat(row['executed_at'].replace('Z', '+00:00')).timestamp() * 1000)
                if start_ms and trade_time_ms < start_ms:
                    continue

                if key in latest_trades:
                    has_fee = latest_trades[key].get('commission_in_quote') not in [None, '', 'None']
                    new_fee = row.get('commission_in_quote') not in [None, '', 'None']
                    if new_fee or not has_fee:
                        latest_trades[key] = row
                else:
                    latest_trades[key] = row

    data_to_save = list(latest_trades.values())
    data_to_save.sort(key=lambda x: (x['executed_at'], x['trade_id']))

    # 5. ESCRITURA DE ARCHIVOS (SILVER + META)
    if data_to_save:
        # Escribir CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data_to_save)
        
        # Generar y Escribir META (AHORA SÍ TIENE LOS DATOS)
        meta = {
            "symbol": symbol,
            "start_ms": start_ms,
            "rows_written": len(data_to_save),
            "raw_rows_seen": sum(1 for _ in open(raw_path, encoding="utf-8")) - 1 if raw_path.exists() else 0,
            "source_file": str(raw_path),
            "generated_at": datetime.now(UTC).isoformat(),
            "notes": "Deduplicated by (exchange, account, symbol, trade_id). Prioritized commission_in_quote."
        }
        
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4)

        logger.info(f"✅ Archivo Silver y Meta creados con {len(data_to_save)} trades.")
    else:
        logger.warning("No se encontraron trades para guardar.")

if __name__ == "__main__":
    main()