# src/scripts/create_paper_session.py
from __future__ import annotations

import os

from src.config.settings import get_settings
from src.core.logger import setup_logger
from src.core.run_paths import (
    build_default_session_id,
    ensure_run_directories,
    get_journal_base_path,
    get_reports_base_path,
    write_run_meta,
)


def main():
    logger = setup_logger("create_paper_session")
    settings = get_settings()

    session_id = os.getenv("RUN_SESSION_ID", "").strip() or build_default_session_id("paper")
    os.environ["RUN_SESSION_ID"] = session_id

    ensure_run_directories()

    meta_path = write_run_meta(
        {
            "mode": "paper",
            "account_name": settings.infrastructure.account_name,
            "binance_testnet": settings.infrastructure.binance_testnet,
            "enabled_symbols": settings.infrastructure.enabled_symbols,
            "journal_base_path": get_journal_base_path(),
            "reports_base_path": get_reports_base_path(),
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
        }
    )

    logger.info("Paper session created.")
    logger.info("RUN_SESSION_ID=%s", session_id)
    logger.info("Journal base path: %s", get_journal_base_path())
    logger.info("Reports base path: %s", get_reports_base_path())
    logger.info("Meta written to: %s", meta_path)


if __name__ == "__main__":
    main()