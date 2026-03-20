from src.domain.models import BestBidAsk, InventoryPnL, InventoryState


class PnLService:
    @staticmethod
    def mark_to_market(
        symbol: str,
        inventory: InventoryState,
        market: BestBidAsk,
        timestamp: str,
    ) -> InventoryPnL:
        equity = inventory.quote_total + (inventory.base_total * market.mid_price)

        return InventoryPnL(
            timestamp=timestamp,
            symbol=symbol,
            base_free=inventory.base_free,
            base_locked=inventory.base_locked,
            base_total=inventory.base_total,
            quote_free=inventory.quote_free,
            quote_locked=inventory.quote_locked,
            quote_total=inventory.quote_total,
            mid_price=market.mid_price,
            mark_to_market_equity=equity,
        )