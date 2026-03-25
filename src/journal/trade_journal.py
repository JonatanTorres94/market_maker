from src.domain.models import CycleSnapshot, InventoryPnL, OrderPlacementRecord
from src.journal.csv_journal import CsvJournalWriter
from src.core.run_paths import get_journal_base_path

class TradeJournal:
    def __init__(self, base_path: str | None = None):
        base_path = base_path or get_journal_base_path()

        self.cycles_writer = CsvJournalWriter(
            filepath=f"{base_path}/cycles.csv",            
            fieldnames=[
                "timestamp",
                "symbol",
                "best_bid",
                "best_ask",
                "spread",
                "mid_price",
                "mid_return_1s_bps",
                "mid_return_3s_bps",
                "mid_return_5s_bps",
                "volatility_5s_bps",
                "base_free",
                "base_locked",
                "base_total",
                "quote_free",
                "quote_locked",
                "quote_total",
                "inventory_bias",
                "participation_mode",
                "proposed_bid",
                "proposed_ask",
                "proposed_bid_qty",
                "proposed_ask_qty",
                "canceled_orders",
                "decision_reason",
            ],
        )

        self.orders_writer = CsvJournalWriter(
            filepath=f"{base_path}/orders.csv",
            fieldnames=[
                "timestamp",
                "symbol",
                "side",
                "order_id",
                "client_order_id",
                "status",
                "price",
                "quantity",
                "executed_quantity",
                "placed_at",
            ],
        )

        self.equity_writer = CsvJournalWriter(
            filepath=f"{base_path}/equity.csv",
            fieldnames=[
                "timestamp",
                "symbol",
                "base_free",
                "base_locked",
                "base_total",
                "quote_free",
                "quote_locked",
                "quote_total",
                "mid_price",
                "mark_to_market_equity",
            ],
        )

    def record_cycle(self, snapshot: CycleSnapshot) -> None:
        self.cycles_writer.append_row(
            {
                "timestamp": snapshot.timestamp,
                "symbol": snapshot.symbol,
                "best_bid": str(snapshot.best_bid),
                "best_ask": str(snapshot.best_ask),
                "spread": str(snapshot.spread),
                "mid_price": str(snapshot.mid_price),
                "mid_return_1s_bps": str(snapshot.mid_return_1s_bps),
                "mid_return_3s_bps": str(snapshot.mid_return_3s_bps),
                "mid_return_5s_bps": str(snapshot.mid_return_5s_bps),
                "volatility_5s_bps": str(snapshot.volatility_5s_bps),
                "base_free": str(snapshot.base_free),
                "base_locked": str(snapshot.base_locked),
                "base_total": str(snapshot.base_total),
                "quote_free": str(snapshot.quote_free),
                "quote_locked": str(snapshot.quote_locked),
                "quote_total": str(snapshot.quote_total),
                "inventory_bias": snapshot.inventory_bias,
                "participation_mode": snapshot.participation_mode,
                "proposed_bid": "" if snapshot.proposed_bid is None else str(snapshot.proposed_bid),
                "proposed_ask": "" if snapshot.proposed_ask is None else str(snapshot.proposed_ask),
                "proposed_bid_qty": str(snapshot.proposed_bid_qty),
                "proposed_ask_qty": str(snapshot.proposed_ask_qty),
                "canceled_orders": snapshot.canceled_orders,
                "decision_reason": snapshot.decision_reason,
            }
        )

    def record_order(self, order: OrderPlacementRecord) -> None:
        self.orders_writer.append_row(
            {
                "timestamp": order.timestamp,
                "symbol": order.symbol,
                "side": order.side,
                "order_id": order.order_id,
                "client_order_id": order.client_order_id,
                "status": order.status,
                "price": str(order.price),
                "quantity": str(order.quantity),
                "executed_quantity": str(order.executed_quantity),
                "placed_at": order.placed_at,
            }
        )

    def record_equity(self, equity: InventoryPnL) -> None:
        self.equity_writer.append_row(
            {
                "timestamp": equity.timestamp,
                "symbol": equity.symbol,
                "base_free": str(equity.base_free),
                "base_locked": str(equity.base_locked),
                "base_total": str(equity.base_total),
                "quote_free": str(equity.quote_free),
                "quote_locked": str(equity.quote_locked),
                "quote_total": str(equity.quote_total),
                "mid_price": str(equity.mid_price),
                "mark_to_market_equity": str(equity.mark_to_market_equity),
            }
        )
