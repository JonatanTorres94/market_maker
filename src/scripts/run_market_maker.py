# src/scripts/run_market_maker.py
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime

from src.analytics.execution_ledger import ExecutionLedger
from src.config.settings import get_settings
from src.core.fee_normalizer import FeeNormalizer
from src.core.run_paths import build_default_session_id
from src.db.database import Database
from src.db.execution_journal import DbExecutionJournal
from src.db.section_marker_service import SectionMarkerService
from src.db.trade_journal import DbTradeJournal
from src.engine.execution_service import ExecutionService
from src.engine.execution_store import ExecutionStore
from src.engine.market_making_engine import MarketMakingEngine
from src.exchange.binance_client import create_binance_client
from src.exchange.binance_price_provider import BinancePriceProvider
from src.exchange.order_manager import OrderManager


def _install_signal_handlers() -> None:
    def _handle(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main():
    _install_signal_handlers()
    settings = get_settings()

    session_id = os.getenv("RUN_SESSION_ID", "").strip() or build_default_session_id("paper")
    started_at = datetime.now(UTC).isoformat()

    db = Database()
    db.open_session(
        session_id=session_id,
        started_at=started_at,
        mode="paper",
        account_name=settings.infrastructure.account_name,
        binance_testnet=settings.infrastructure.binance_testnet,
        enabled_symbols=settings.infrastructure.enabled_symbols,
        config_snapshot={
            "engine_loop_sleep_seconds": settings.infrastructure.engine_loop_sleep_seconds,
            "market_event_timeout_seconds": settings.infrastructure.market_event_timeout_seconds,
            "rest_sync_interval_seconds": settings.infrastructure.rest_sync_interval_seconds,
            "strategy_config": {
                symbol: {
                    "base_quote_quantity": str(cfg.base_quote_quantity),
                    "min_spread": str(cfg.min_spread),
                    "inventory_target": str(cfg.inventory_target),
                    "inventory_tolerance": str(cfg.inventory_tolerance),
                    "max_inventory_skew_factor": str(cfg.max_inventory_skew_factor),
                    "drift_gate_lookback_seconds": cfg.drift_gate_lookback_seconds,
                    "drift_gate_threshold_bps": str(cfg.drift_gate_threshold_bps),
                    "min_base_inventory": str(cfg.min_base_inventory),
                    "max_base_inventory": str(cfg.max_base_inventory),
                    "min_quote_balance": str(cfg.min_quote_balance),
                    "replace_threshold_ticks": cfg.replace_threshold_ticks,
                    "quantity_rel_change_threshold": str(cfg.quantity_rel_change_threshold),
                    "max_quote_age_seconds": cfg.max_quote_age_seconds,
                }
                for symbol, cfg in settings.symbol_configs.items()
            },
        },
    )

    section_marker_svc = SectionMarkerService(db, session_id)
    section_marker_svc.start()

    trade_journal = DbTradeJournal(db, session_id)
    execution_journal = DbExecutionJournal(db, session_id)

    logger = logging.getLogger("market_making_engine")
    logger.info("Session started | session_id=%s", session_id)

    if len(settings.infrastructure.enabled_symbols) != 1:
        raise ValueError(
            "This runner currently supports exactly one enabled symbol. "
            "Multi-symbol runtime orchestration is not implemented yet."
        )

    symbol = settings.infrastructure.enabled_symbols[0]
    symbol_config = settings.symbol_configs[symbol]

    client = create_binance_client()
    order_manager = OrderManager(client)
    price_provider = BinancePriceProvider(client)

    execution_service = ExecutionService(
        symbol=symbol,
        account_name=settings.infrastructure.account_name,
        order_manager=order_manager,
        execution_store=ExecutionStore(),
        execution_journal=execution_journal,
        ledger=ExecutionLedger(),
        fee_normalizer=FeeNormalizer(price_provider=price_provider),
    )

    engine = MarketMakingEngine(
        client=client,
        infrastructure=settings.infrastructure,
        symbol_config=symbol_config,
        execution_service=execution_service,
        order_manager=order_manager,
        journal=trade_journal,
    )

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
        section_marker_svc.stop()
        db.close_session(session_id, datetime.now(UTC).isoformat())
        db.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
