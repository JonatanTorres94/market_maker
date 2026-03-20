from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Execution:
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
    commission_in_quote: Decimal | None
    commission_fx_rate: Decimal | None
    commission_fx_symbol: str | None
    commission_fx_timestamp: str | None
    is_maker: bool
    executed_at: str
    source: str

    @property
    def unique_key(self) -> tuple[str, str, str, int]:
        return (self.exchange, self.account, self.symbol, self.trade_id)
