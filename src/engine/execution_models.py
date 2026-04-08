#src/engine/execution_models.py

from dataclasses import dataclass, field
from typing import Any, List, Optional
from decimal import Decimal
from src.domain.models import BestBidAsk, InventoryState, QuoteDecision
from src.strategies.market_context import MarketContext
from src.engine.quote_lifecycle import SideLifecycleDecision
from src.domain.models import InventoryBias, BestBidAsk

@dataclass(frozen=True)
class CycleState:
    """INPUT: Lo que el bot ve antes de decidir. 100% Determinístico."""
    timestamp: str
    symbol: str
    market: BestBidAsk
    context: MarketContext
    inventory: InventoryState
    inventory_bias: Decimal

@dataclass(frozen=True)
class ExecutionPlan:
    """DECISION: Lo que el bot quiere hacer basándose en el CycleState."""
    quote: QuoteDecision
    buy_decision: SideLifecycleDecision
    sell_decision: SideLifecycleDecision
    drift_bps: Decimal
    decision_reason: str

@dataclass(frozen=True)
class ExecutionOutcome:
    """OUTPUT: Lo que realmente pasó en el exchange después de intentar el plan."""
    canceled_count: int
    placed_count: int
    bid_ok: bool
    bid_reason: str
    ask_ok: bool
    ask_reason: str
    drift_bps: Decimal
    canceled_buy: int = 0
    canceled_sell: int = 0
    place_responses: List[Any] = field(default_factory=list)
    cancel_responses: List[Any] = field(default_factory=list)