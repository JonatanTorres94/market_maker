from decimal import Decimal
from binance.client import Client

from src.domain.models import BestBidAsk


class MarketDataService:
    def __init__(self, client: Client):
        self.client = client

    def get_symbol_ticker(self, symbol: str) -> dict:
        return self.client.get_symbol_ticker(symbol=symbol)

    def get_order_book(self, symbol: str, limit: int = 5) -> dict:
        return self.client.get_order_book(symbol=symbol, limit=limit)

    def get_best_bid_ask(self, symbol: str) -> BestBidAsk:
        book = self.get_order_book(symbol=symbol, limit=5)

        if not book["bids"] or not book["asks"]:
            raise ValueError(f"No bids/asks available for symbol={symbol}")

        best_bid_price, best_bid_qty = book["bids"][0]
        best_ask_price, best_ask_qty = book["asks"][0]

        return BestBidAsk(
            symbol=symbol,
            best_bid_price=Decimal(best_bid_price),
            best_bid_qty=Decimal(best_bid_qty),
            best_ask_price=Decimal(best_ask_price),
            best_ask_qty=Decimal(best_ask_qty),
        )