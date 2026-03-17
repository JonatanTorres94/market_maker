import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

from dotenv import load_dotenv

from src.config.symbol_config import SymbolTradingConfig, build_symbol_config_map

load_dotenv()


@dataclass(frozen=True)
class InfrastructureSettings:
    binance_api_key: str
    binance_secret: str
    binance_testnet: bool
    enabled_symbols: List[str]
    engine_loop_sleep_seconds: float
    market_event_timeout_seconds: float
    rest_sync_interval_seconds: float
    local_terminal_cleanup_threshold: int


@dataclass(frozen=True)
class AppSettings:
    infrastructure: InfrastructureSettings
    symbol_configs: Dict[str, SymbolTradingConfig]


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_decimal(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def _get_float(name: str, default: str) -> float:
    return float(os.getenv(name, default))


def _get_int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


def _get_enabled_symbols() -> List[str]:
    raw = os.getenv("ENABLED_SYMBOLS", "BTCUSDT")
    symbols = [item.strip().upper() for item in raw.split(",")]
    return [symbol for symbol in symbols if symbol]


def get_settings() -> AppSettings:
    api_key = os.getenv("BINANCE_API_KEY")
    secret = os.getenv("BINANCE_SECRET")

    if not api_key:
        raise ValueError("Missing BINANCE_API_KEY in environment variables")

    if not secret:
        raise ValueError("Missing BINANCE_SECRET in environment variables")

    enabled_symbols = _get_enabled_symbols()
    if not enabled_symbols:
        raise ValueError("At least one symbol must be configured in ENABLED_SYMBOLS")

    infrastructure = InfrastructureSettings(
        binance_api_key=api_key,
        binance_secret=secret,
        binance_testnet=_get_bool("BINANCE_TESTNET", True),
        enabled_symbols=enabled_symbols,
        engine_loop_sleep_seconds=_get_float("ENGINE_LOOP_SLEEP_SECONDS", "0.25"),
        market_event_timeout_seconds=_get_float("MARKET_EVENT_TIMEOUT_SECONDS", "2.0"),
        rest_sync_interval_seconds=_get_float("REST_SYNC_INTERVAL_SECONDS", "10.0"),
        local_terminal_cleanup_threshold=_get_int("LOCAL_TERMINAL_CLEANUP_THRESHOLD", "200"),
    )

    symbol_configs = build_symbol_config_map(
        symbols=enabled_symbols,
        base_quote_quantity=_get_decimal("BASE_QUOTE_QUANTITY", "0.001"),
        min_spread=_get_decimal("MIN_SPREAD", "0.01"),
        inventory_target=_get_decimal("INVENTORY_TARGET", "1.000"),
        inventory_tolerance=_get_decimal("INVENTORY_TOLERANCE", "0.005"),
        max_inventory_skew_factor=_get_decimal("MAX_INVENTORY_SKEW_FACTOR", "1"),
        min_base_inventory=_get_decimal("MIN_BASE_INVENTORY", "0.995"),
        max_base_inventory=_get_decimal("MAX_BASE_INVENTORY", "1.005"),
        min_quote_balance=_get_decimal("MIN_QUOTE_BALANCE", "50"),
        replace_threshold_ticks=_get_int("REPLACE_THRESHOLD_TICKS", "2"),
        quantity_rel_change_threshold=_get_decimal("QUANTITY_REL_CHANGE_THRESHOLD", "0.25"),
        max_quote_age_seconds=_get_float("MAX_QUOTE_AGE_SECONDS", "20"),
    )

    return AppSettings(
        infrastructure=infrastructure,
        symbol_configs=symbol_configs,
    )