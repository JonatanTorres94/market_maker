from dataclasses import dataclass
from decimal import Decimal

from src.domain.models import BestBidAsk, InventoryState, QuoteDecision
from src.risk.risk_manager import RiskManager
from src.strategies.market_context import MarketContext, QuoteParticipationMode


@dataclass(frozen=True)
class MarketMakerConfig:
    base_quote_quantity: Decimal
    min_spread: Decimal
    inventory_target: Decimal
    inventory_tolerance: Decimal
    max_inventory_skew_factor: Decimal
    drift_gate_lookback_seconds: int
    drift_gate_threshold_bps: Decimal


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

    def _determine_participation_mode(
        self,
        market_context: MarketContext,
    ) -> QuoteParticipationMode:
        lookback_seconds = self.config.drift_gate_lookback_seconds
        threshold_bps = self.config.drift_gate_threshold_bps

        if lookback_seconds == 1:
            drift_bps = market_context.mid_return_1s_bps
        elif lookback_seconds == 3:
            drift_bps = market_context.mid_return_3s_bps
        elif lookback_seconds == 5:
            drift_bps = market_context.mid_return_5s_bps
        else:
            raise ValueError(
                f"Unsupported drift_gate_lookback_seconds={lookback_seconds}. Expected 1, 3 or 5."
            )

        if drift_bps >= threshold_bps:
            return QuoteParticipationMode.BID_ONLY

        if drift_bps <= -threshold_bps:
            return QuoteParticipationMode.ASK_ONLY

        return QuoteParticipationMode.BOTH

    def generate_quotes(
        self,
        market: BestBidAsk,
        inventory: InventoryState,
        market_context: MarketContext,
    ) -> QuoteDecision:
        if market.spread < self.config.min_spread:
            return QuoteDecision(
                bid_price=None,
                ask_price=None,
                bid_quantity=Decimal("0"),
                ask_quantity=Decimal("0"),
                participation_mode=QuoteParticipationMode.NONE,
                reason="SPREAD_BELOW_THRESHOLD",
            )

        bid_price = market.best_bid_price
        ask_price = market.best_ask_price

        participation_mode = self._determine_participation_mode(market_context)

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

        if participation_mode == QuoteParticipationMode.BID_ONLY:
            ask_price = None
            ask_quantity = Decimal("0")
        elif participation_mode == QuoteParticipationMode.ASK_ONLY:
            bid_price = None
            bid_quantity = Decimal("0")

        required_quote = (
            Decimal("0")
            if bid_price is None or bid_quantity <= 0
            else bid_price * bid_quantity
        )

        can_bid = bid_quantity > 0 and self.risk_manager.can_place_bid(inventory, required_quote)
        can_ask = ask_quantity > 0 and self.risk_manager.can_place_ask(inventory, ask_quantity)

        return QuoteDecision(
            bid_price=bid_price if can_bid else None,
            ask_price=ask_price if can_ask else None,
            bid_quantity=bid_quantity,
            ask_quantity=ask_quantity,
            participation_mode=participation_mode,
            reason="OK",
        )