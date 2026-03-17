from decimal import Decimal

from src.domain.models import InventoryPnL, InventoryState, BestBidAsk


class PnLService:
    @staticmethod
    def mark_to_market(
        symbol: str,
        inventory: InventoryState,
        market: BestBidAsk,
        timestamp: str,
    ) -> InventoryPnL:
        equity = inventory.quote_free + (inventory.base_free * market.mid_price)

        return InventoryPnL(
            timestamp=timestamp,
            symbol=symbol,
            base_free=inventory.base_free,
            quote_free=inventory.quote_free,
            mid_price=market.mid_price,
            mark_to_market_equity=equity,
        )