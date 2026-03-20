#src/journal/execution_journal.py
from src.domain.execution import Execution
from src.journal.csv_journal import CsvJournalWriter


class ExecutionJournal:
    def __init__(self, base_path: str = "data/journals"):
        self.writer = CsvJournalWriter(
            filepath=f"{base_path}/executions.csv",
            fieldnames=[
                "exchange",
                "account",
                "symbol",
                "trade_id",
                "order_id",
                "client_order_id",
                "side",
                "price",
                "qty",
                "quote_qty",
                "commission",
                "commission_asset",
                "commission_in_quote",
                "commission_fx_rate",
                "commission_fx_symbol",
                "commission_fx_timestamp",
                "is_maker",
                "executed_at",
                "source",
            ],
        )

    def record_execution(self, execution: Execution) -> None:
        self.writer.append_row(
            {
                "exchange": execution.exchange,
                "account": execution.account,
                "symbol": execution.symbol,
                "trade_id": execution.trade_id,
                "order_id": execution.order_id,
                "client_order_id": execution.client_order_id,
                "side": execution.side,
                "price": str(execution.price),
                "qty": str(execution.qty),
                "quote_qty": str(execution.quote_qty),
                "commission": str(execution.commission),
                "commission_asset": execution.commission_asset,
                "commission_in_quote": "" if execution.commission_in_quote is None else str(execution.commission_in_quote),
                "commission_fx_rate": "" if execution.commission_fx_rate is None else str(execution.commission_fx_rate),
                "commission_fx_symbol": execution.commission_fx_symbol or "",
                "commission_fx_timestamp": execution.commission_fx_timestamp or "",
                "is_maker": execution.is_maker,
                "executed_at": execution.executed_at,
                "source": execution.source,
            }
        )
