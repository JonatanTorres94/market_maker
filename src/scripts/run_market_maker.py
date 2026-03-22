# src/scripts/run_market_maker.py
import logging
import signal
import sys

from src.analytics.execution_ledger import ExecutionLedger
from src.config.settings import get_settings
from src.core.fee_normalizer import FeeNormalizer
from src.engine.execution_service import ExecutionService
from src.engine.execution_store import ExecutionStore
from src.engine.market_making_engine import MarketMakingEngine
from src.exchange.binance_client import create_binance_client
from src.exchange.order_manager import OrderManager
from src.journal.execution_journal import ExecutionJournal
from src.exchange.binance_price_provider import BinancePriceProvider
from src.core.run_paths import ensure_run_directories, get_journal_base_path, get_reports_base_path, get_run_session_id, write_run_meta


def _install_signal_handlers() -> None:
    def _handle_termination_signal(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handle_termination_signal)
    signal.signal(signal.SIGTERM, _handle_termination_signal)


def main():
    _install_signal_handlers()
    ensure_run_directories()
    settings = get_settings()

    write_run_meta(
        {
            "mode": "paper_runtime",
            "account_name": settings.infrastructure.account_name,
            "binance_testnet": settings.infrastructure.binance_testnet,
            "enabled_symbols": settings.infrastructure.enabled_symbols,
            "journal_base_path": get_journal_base_path(),
            "reports_base_path": get_reports_base_path(),
        }
    )

    logging.getLogger("market_making_engine").info(
        "Run context | session_id=%s journal_base_path=%s reports_base_path=%s",
        get_run_session_id(),
        get_journal_base_path(),
        get_reports_base_path(),
    )

    client = create_binance_client()

    if len(settings.infrastructure.enabled_symbols) != 1:
        raise ValueError(
            "This runner currently supports exactly one enabled symbol. "
            "Multi-symbol runtime orchestration is not implemented yet."
        )

    symbol = settings.infrastructure.enabled_symbols[0]
    symbol_config = settings.symbol_configs[symbol]

    order_manager = OrderManager(client)

    price_provider = BinancePriceProvider(client)

    execution_service = ExecutionService(
        symbol=symbol,
        account_name=settings.infrastructure.account_name,
        order_manager=order_manager,
        execution_store=ExecutionStore(),
        execution_journal=ExecutionJournal(),
        ledger=ExecutionLedger(),
        fee_normalizer=FeeNormalizer(price_provider=price_provider),
    )

    engine = MarketMakingEngine(
        client=client,
        infrastructure=settings.infrastructure,
        symbol_config=symbol_config,
        execution_service=execution_service,
        order_manager=order_manager,
    )

    logger = logging.getLogger("market_making_engine")

    try:
        engine.run()
    except KeyboardInterrupt:
        logger.info("Termination signal received. Starting graceful shutdown.")
        engine.shutdown()
    except Exception as exc:
        logger.exception("Fatal error in runner: %s", exc)
        engine.shutdown()
        raise
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()