from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class BestBidAsk:
    symbol: str
    best_bid_price: Decimal
    best_bid_qty: Decimal
    best_ask_price: Decimal
    best_ask_qty: Decimal

    @property
    def spread(self) -> Decimal:
        return self.best_ask_price - self.best_bid_price

    @property
    def mid_price(self) -> Decimal:
        return (self.best_bid_price + self.best_ask_price) / Decimal("2")


@dataclass(frozen=True)
class SymbolFilters:
    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal


@dataclass(frozen=True)
class OrderResult:
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    status: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    placed_at: str


@dataclass(frozen=True)
class InventoryState:
    base_asset: str
    quote_asset: str
    base_free: Decimal
    quote_free: Decimal


@dataclass(frozen=True)
class QuoteProposal:
    bid_price: Optional[Decimal]
    ask_price: Optional[Decimal]
    quantity: Decimal


@dataclass(frozen=True)
class PlacedOrders:
    buy_order_id: int | None
    sell_order_id: int | None


@dataclass(frozen=True)
class CycleSnapshot:
    timestamp: str
    symbol: str
    best_bid: Decimal
    best_ask: Decimal
    spread: Decimal
    mid_price: Decimal
    base_free: Decimal
    quote_free: Decimal
    inventory_bias: str
    proposed_bid: Optional[Decimal]
    proposed_ask: Optional[Decimal]
    proposed_bid_qty: Decimal
    proposed_ask_qty: Decimal
    canceled_orders: int
    decision_reason: str


@dataclass(frozen=True)
class OrderPlacementRecord:
    timestamp: str
    symbol: str
    side: str
    order_id: int
    client_order_id: str
    status: str
    price: Decimal
    quantity: Decimal
    executed_quantity: Decimal
    placed_at: str


@dataclass(frozen=True)
class InventoryPnL:
    timestamp: str
    symbol: str
    base_free: Decimal
    quote_free: Decimal
    mid_price: Decimal
    mark_to_market_equity: Decimal


@dataclass(frozen=True)
class ReconciledOrderRecord:
    timestamp: str
    updated_at: str
    symbol: str
    order_id: int
    side: str
    status: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    cumulative_quote_qty: Decimal


@dataclass(frozen=True)
class ReconciliationSummary:
    journal_orders: int
    reconciled_orders: int
    missing_orders: int
    coverage_ratio: Decimal
    filled_orders: int
    canceled_orders: int
    open_orders: int
    partially_filled_orders: int
    bulk_fetched_orders: int
    fallback_requested_orders: int
    fallback_resolved_orders: int


@dataclass(frozen=True)
class QuoteDecision:
    bid_price: Optional[Decimal]
    ask_price: Optional[Decimal]
    bid_quantity: Decimal
    ask_quantity: Decimal
    reason: str