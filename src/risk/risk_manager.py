from decimal import Decimal

from src.domain.models import InventoryState


class RiskManager:
    def __init__(
        self,
        max_base_inventory: Decimal,
        min_base_inventory: Decimal,
        min_quote_balance: Decimal,
    ):
        self.max_base_inventory = max_base_inventory
        self.min_base_inventory = min_base_inventory
        self.min_quote_balance = min_quote_balance

    def can_place_bid(self, inventory: InventoryState, required_quote: Decimal) -> bool:
        if inventory.base_total >= self.max_base_inventory:
            return False

        return inventory.quote_free >= max(required_quote, self.min_quote_balance)

    def can_place_ask(self, inventory: InventoryState, order_qty: Decimal) -> bool:
        if inventory.base_total <= self.min_base_inventory:
            return False

        return inventory.base_free >= order_qty

    def inventory_bias(self, inventory: InventoryState) -> str:
        if inventory.base_total >= self.max_base_inventory:
            return "TOO_LONG_BASE"
        if inventory.base_total <= self.min_base_inventory:
            return "TOO_SHORT_BASE"
        return "NEUTRAL"
