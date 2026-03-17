from decimal import Decimal
from binance.client import Client

from src.domain.models import SymbolFilters


class ExchangeInfoService:
    def __init__(self, client: Client):
        self.client = client

    def get_symbol_filters(self, symbol: str) -> SymbolFilters:
        exchange_info = self.client.get_symbol_info(symbol)

        if not exchange_info:
            raise ValueError(f"Symbol info not found for {symbol}")

        filters = {item["filterType"]: item for item in exchange_info["filters"]}

        price_filter = filters.get("PRICE_FILTER")
        lot_size_filter = filters.get("LOT_SIZE")
        min_notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")

        if not price_filter or not lot_size_filter:
            raise ValueError(f"Missing required filters for {symbol}")

        min_notional = Decimal("0")
        if min_notional_filter:
            min_notional = Decimal(min_notional_filter["minNotional"])

        return SymbolFilters(
            symbol=symbol,
            tick_size=Decimal(price_filter["tickSize"]),
            step_size=Decimal(lot_size_filter["stepSize"]),
            min_qty=Decimal(lot_size_filter["minQty"]),
            min_notional=min_notional,
        )