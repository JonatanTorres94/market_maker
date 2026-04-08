from src.domain.models import CycleSnapshot
from src.journal.trade_journal import TradeJournal
from src.engine.execution_models import CycleState, ExecutionPlan, ExecutionOutcome


class CycleRecorder:
    def __init__(self, journal: TradeJournal):
        self.journal = journal

    def record(self, state: CycleState, plan: ExecutionPlan, outcome: ExecutionOutcome):
        """Une las tres capas (Input, Decisión, Resultado) en un único Snapshot para el CSV."""
        snapshot = CycleSnapshot(
            # 1. Datos del STATE
            timestamp=state.timestamp,
            symbol=state.symbol,
            best_bid=state.market.best_bid_price,
            best_ask=state.market.best_ask_price,
            spread=state.market.spread,
            mid_price=state.market.mid_price,
            mid_return_1s_bps=state.context.mid_return_1s_bps,
            mid_return_3s_bps=state.context.mid_return_3s_bps,
            mid_return_5s_bps=state.context.mid_return_5s_bps,
            volatility_5s_bps=state.context.volatility_5s_bps,
            base_free=state.inventory.base_free,
            base_locked=state.inventory.base_locked,
            base_total=state.inventory.base_total,
            quote_free=state.inventory.quote_free,
            quote_locked=state.inventory.quote_locked,
            quote_total=state.inventory.quote_total,
            inventory_bias=state.inventory_bias,

            # 2. Datos del PLAN
            participation_mode=plan.quote.participation_mode.value,
            proposed_bid=plan.quote.bid_price,
            proposed_ask=plan.quote.ask_price,
            proposed_bid_qty=plan.quote.bid_quantity,
            proposed_ask_qty=plan.quote.ask_quantity,
            decision_reason=plan.decision_reason,

            # 3. Datos del OUTCOME
            bid_placeable=outcome.bid_ok,
            ask_placeable=outcome.ask_ok,
            bid_block_reason=outcome.bid_reason,
            ask_block_reason=outcome.ask_reason,
            canceled_orders=outcome.canceled_count,
            placed_count=outcome.placed_count,
            canceled_buy=outcome.canceled_buy,
            canceled_sell=outcome.canceled_sell,
        )

        self.journal.record_cycle(snapshot)