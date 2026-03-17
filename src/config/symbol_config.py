from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List


@dataclass(frozen=True)
class SymbolTradingConfig:
    symbol: str

    # Strategy
    base_quote_quantity: Decimal
    min_spread: Decimal
    inventory_target: Decimal
    inventory_tolerance: Decimal
    max_inventory_skew_factor: Decimal

    # Risk
    min_base_inventory: Decimal
    max_base_inventory: Decimal
    min_quote_balance: Decimal

    # Lifecycle
    replace_threshold_ticks: int
    quantity_rel_change_threshold: Decimal
    max_quote_age_seconds: float


def build_symbol_config_map(
    symbols: List[str],
    base_quote_quantity: Decimal,
    min_spread: Decimal,
    inventory_target: Decimal,
    inventory_tolerance: Decimal,
    max_inventory_skew_factor: Decimal,
    min_base_inventory: Decimal,
    max_base_inventory: Decimal,
    min_quote_balance: Decimal,
    replace_threshold_ticks: int,
    quantity_rel_change_threshold: Decimal,
    max_quote_age_seconds: float,
) -> Dict[str, SymbolTradingConfig]:
    config_map: Dict[str, SymbolTradingConfig] = {}

    for symbol in symbols:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            continue

        config_map[normalized_symbol] = SymbolTradingConfig(
            symbol=normalized_symbol,
            base_quote_quantity=base_quote_quantity,
            min_spread=min_spread,
            inventory_target=inventory_target,
            inventory_tolerance=inventory_tolerance,
            max_inventory_skew_factor=max_inventory_skew_factor,
            min_base_inventory=min_base_inventory,
            max_base_inventory=max_base_inventory,
            min_quote_balance=min_quote_balance,
            replace_threshold_ticks=replace_threshold_ticks,
            quantity_rel_change_threshold=quantity_rel_change_threshold,
            max_quote_age_seconds=max_quote_age_seconds,
        )

    return config_map