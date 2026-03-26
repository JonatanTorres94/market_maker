#src/engine/order_validator.py
from decimal import Decimal

class OrderValidator:
    def __init__(self, filters):
        self.filters = filters

    def validate_placeable(self, price: Decimal | None, quantity: Decimal) -> tuple[bool, str | None]:
        """Valida que la orden cumpla con los filtros del exchange."""
        if price is None or quantity <= 0:
            return False, "invalid_params"

        if quantity < self.filters.min_qty:
            return False, f"qty_below_min:{quantity}<{self.filters.min_qty}"

        notional = price * quantity
        if self.filters.min_notional > 0 and notional < self.filters.min_notional:
            return False, f"notional_below_min:{notional}<{self.filters.min_notional}"

        return True, None