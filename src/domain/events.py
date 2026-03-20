from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MarketTickEvent:
    occurred_at: str
    symbol: str
    best_bid: Decimal
    best_ask: Decimal
    spread: Decimal
    mid_price: Decimal


@dataclass(frozen=True)
class InventoryUpdatedEvent:
    occurred_at: str
    symbol: str
    base_free: Decimal
    quote_free: Decimal
    inventory_bias: str


@dataclass(frozen=True)
class OrderPlacedEvent:
    occurred_at: str
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: str
    placed_at: str


@dataclass(frozen=True)
class OrderCancelRequestedEvent:
    occurred_at: str
    symbol: str
    order_id: int


@dataclass(frozen=True)
class OrderCanceledEvent:
    occurred_at: str
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: str
    updated_at: str


@dataclass(frozen=True)
class OrderPartiallyFilledEvent:
    occurred_at: str
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: str
    updated_at: str


@dataclass(frozen=True)
class OrderFilledEvent:
    occurred_at: str
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: str
    updated_at: str


@dataclass(frozen=True)
class OrderStatusSyncedEvent:
    occurred_at: str
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: str
    updated_at: str

@dataclass(frozen=True)
class ExecutionReceivedEvent:
    occurred_at: str
    exchange: str
    account: str
    symbol: str
    trade_id: int
    order_id: int
    client_order_id: str
    side: str
    price: Decimal
    qty: Decimal
    quote_qty: Decimal
    commission: Decimal
    commission_asset: str
    is_maker: bool
    executed_at: str
    source: str
