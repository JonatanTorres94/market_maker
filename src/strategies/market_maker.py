from dataclasses import dataclass
from decimal import Decimal

from src.domain.models import BestBidAsk, InventoryState, QuoteDecision
from src.risk.risk_manager import RiskManager


@dataclass(frozen=True)
class MarketMakerConfig:
    base_quote_quantity: Decimal
    min_spread: Decimal
    inventory_target: Decimal
    inventory_tolerance: Decimal
    max_inventory_skew_factor: Decimal


class MarketMakerStrategy:
    def __init__(
        self,
        config: MarketMakerConfig,
        risk_manager: RiskManager,
    ):
        self.config = config
        self.risk_manager = risk_manager

    def _compute_skew_factor(self, inventory: InventoryState) -> Decimal:
        deviation = inventory.base_total - self.config.inventory_target

        if self.config.inventory_tolerance == Decimal("0"):
            return Decimal("0")

        normalized = deviation / self.config.inventory_tolerance

        if normalized > self.config.max_inventory_skew_factor:
            return self.config.max_inventory_skew_factor

        if normalized < -self.config.max_inventory_skew_factor:
            return -self.config.max_inventory_skew_factor

        return normalized

    def generate_quotes(
        self,
        market: BestBidAsk,
        inventory: InventoryState,
    ) -> QuoteDecision:
        if market.spread < self.config.min_spread:
            return QuoteDecision(
                bid_price=None,
                ask_price=None,
                bid_quantity=Decimal("0"),
                ask_quantity=Decimal("0"),
                reason="SPREAD_BELOW_THRESHOLD",
            )

        bid_price = market.best_bid_price
        ask_price = market.best_ask_price

        skew = self._compute_skew_factor(inventory)

        bid_quantity = self.config.base_quote_quantity
        ask_quantity = self.config.base_quote_quantity

        if skew > 0:
            bid_quantity = self.config.base_quote_quantity * max(
                Decimal("0"),
                Decimal("1") - skew
            )
            ask_quantity = self.config.base_quote_quantity * min(
                Decimal("2"),
                Decimal("1") + skew
            )
        elif skew < 0:
            ask_quantity = self.config.base_quote_quantity * max(
                Decimal("0"),
                Decimal("1") + skew
            )
            bid_quantity = self.config.base_quote_quantity * min(
                Decimal("2"),
                Decimal("1") - skew
            )

        required_quote = bid_price * bid_quantity

        can_bid = bid_quantity > 0 and self.risk_manager.can_place_bid(inventory, required_quote)
        can_ask = ask_quantity > 0 and self.risk_manager.can_place_ask(inventory, ask_quantity)

        return QuoteDecision(
            bid_price=bid_price if can_bid else None,
            ask_price=ask_price if can_ask else None,
            bid_quantity=bid_quantity,
            ask_quantity=ask_quantity,
            reason="OK",
        )