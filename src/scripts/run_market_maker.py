# src/scripts/run_market_maker.py
import sys
import logging

from src.analytics.execution_ledger import ExecutionLedger
from src.config.settings import get_settings
from src.core.fee_normalizer import FeeNormalizer
from src.engine.execution_service import ExecutionService
from src.engine.execution_store import ExecutionStore
from src.engine.market_making_engine import MarketMakingEngine
from src.exchange.binance_client import create_binance_client
from src.exchange.order_manager import OrderManager
from src.journal.execution_journal import ExecutionJournal


def main():
    settings = get_settings()
    client = create_binance_client()

    if len(settings.infrastructure.enabled_symbols) != 1:
        raise ValueError(
            "This runner currently supports exactly one enabled symbol. "
            "Multi-symbol runtime orchestration is not implemented yet."
        )

    symbol = settings.infrastructure.enabled_symbols[0]
    symbol_config = settings.symbol_configs[symbol]

    order_manager = OrderManager(client)

    execution_service = ExecutionService(
        symbol=symbol,
        account_name=settings.infrastructure.account_name,
        order_manager=order_manager,
        execution_store=ExecutionStore(),
        execution_journal=ExecutionJournal(),
        ledger=ExecutionLedger(),
        fee_normalizer=FeeNormalizer(),
    )

    engine = MarketMakingEngine(
        client=client,
        infrastructure=settings.infrastructure,
        symbol_config=symbol_config,
        execution_service=execution_service,
        order_manager=order_manager,
    )

    try:
        engine.run()
    except KeyboardInterrupt:
        print("\n[INFO] Shutdown signal received (Ctrl+C). Cleaning up...")
    except Exception as e:
        logging.getLogger("market_making_engine").error(f"Fatal error: {e}")
        engine.shutdown()
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()