# src/engine/execution_service.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from src.analytics.execution_ledger import ExecutionLedger
from src.core.fee_normalizer import FeeNormalizationResult, FeeNormalizer
from src.core.logger import setup_logger
from src.domain.execution import Execution
from src.engine.execution_store import ExecutionStore, ExecutionUpsertResult
from src.exchange.order_manager import OrderManager
from src.journal.execution_journal import ExecutionJournal


@dataclass(frozen=True)
class ExecutionReconciliationResult:
    symbol: str
    fetched: int
    inserted: int
    updated: int
    duplicates: int
    pages_fetched: int
    from_trade_id: int | None
    to_trade_id: int | None


class ExecutionService:
    def __init__(
        self,
        symbol: str,
        account_name: str,
        order_manager: OrderManager,
        execution_store: ExecutionStore,
        execution_journal: ExecutionJournal,
        ledger: ExecutionLedger,
        fee_normalizer: FeeNormalizer,
    ):
        self.symbol = symbol
        self.account_name = account_name
        self.order_manager = order_manager
        self.execution_store = execution_store
        self.execution_journal = execution_journal
        self.ledger = ledger
        self.fee_normalizer = fee_normalizer
        self.logger = setup_logger("execution_service")

        self._last_reconciled_trade_id_by_symbol: dict[str, int] = {}

    def on_stream_execution(self, execution: Execution) -> ExecutionUpsertResult:
        self._validate_symbol(execution.symbol)

        result = self.execution_store.upsert(execution)

        if result.inserted:
            self.execution_journal.record_execution(execution)
            self.ledger.apply(execution)
            self._bump_last_trade_id(execution.symbol, execution.trade_id)
            self.logger.info(
                "Stream execution inserted | symbol=%s trade_id=%s order_id=%s side=%s qty=%s price=%s",
                execution.symbol,
                execution.trade_id,
                execution.order_id,
                execution.side,
                execution.qty,
                execution.price,
            )
            return result

        if result.updated:
            stored = self.execution_store.get(
                execution.exchange,
                execution.account,
                execution.symbol,
                execution.trade_id,
            )
            if stored is None:
                raise RuntimeError(
                    f"ExecutionStore returned updated but execution not found "
                    f"for trade_id={execution.trade_id} symbol={execution.symbol}"
                )
            self.execution_journal.record_execution(stored)
            self.logger.info(
                "Stream execution updated | symbol=%s trade_id=%s changed_fields=%s",
                execution.symbol,
                execution.trade_id,
                result.changed_fields,
            )
            return result

        self.logger.debug(
            "Stream execution duplicate ignored | symbol=%s trade_id=%s",
            execution.symbol,
            execution.trade_id,
        )
        return result

    def on_rest_execution(self, execution: Execution) -> ExecutionUpsertResult:
        self._validate_symbol(execution.symbol)

        result = self.execution_store.upsert(execution)

        if result.inserted:
            self.execution_journal.record_execution(execution)
            self.ledger.apply(execution)
            self._bump_last_trade_id(execution.symbol, execution.trade_id)
            self.logger.info(
                "REST execution inserted | symbol=%s trade_id=%s order_id=%s side=%s qty=%s price=%s",
                execution.symbol,
                execution.trade_id,
                execution.order_id,
                execution.side,
                execution.qty,
                execution.price,
            )
            return result

        if result.updated:
            stored = self.execution_store.get(
                execution.exchange,
                execution.account,
                execution.symbol,
                execution.trade_id,
            )
            if stored is None:
                raise RuntimeError(
                    f"ExecutionStore returned updated but execution not found "
                    f"for trade_id={execution.trade_id} symbol={execution.symbol}"
                )
            self.execution_journal.record_execution(stored)
            self._bump_last_trade_id(execution.symbol, execution.trade_id)
            self.logger.info(
                "REST execution enriched | symbol=%s trade_id=%s changed_fields=%s",
                execution.symbol,
                execution.trade_id,
                result.changed_fields,
            )
            return result

        self._bump_last_trade_id(execution.symbol, execution.trade_id)
        self.logger.debug(
            "REST execution duplicate ignored | symbol=%s trade_id=%s",
            execution.symbol,
            execution.trade_id,
        )
        return result

    def reconcile_symbol(
        self,
        symbol: str,
        limit: int = 1000,
        max_pages: int = 1,
    ) -> ExecutionReconciliationResult:
        self._validate_symbol(symbol)

        next_from_id = self._last_reconciled_trade_id_by_symbol.get(symbol)
        if next_from_id is not None:
            next_from_id += 1

        fetched = 0
        inserted = 0
        updated = 0
        duplicates = 0
        pages_fetched = 0
        first_trade_id: int | None = None
        last_trade_id: int | None = None

        for _ in range(max_pages):
            rows = self.order_manager.get_my_trades(
                symbol=symbol,
                limit=limit,
                from_id=next_from_id,
            )

            if not rows:
                break

            pages_fetched += 1
            fetched += len(rows)

            page_trade_ids = [int(row["id"]) for row in rows]
            page_min_trade_id = min(page_trade_ids)
            page_max_trade_id = max(page_trade_ids)

            if first_trade_id is None:
                first_trade_id = page_min_trade_id
            last_trade_id = page_max_trade_id

            for row in rows:
                execution = self._execution_from_trade_row(symbol=symbol, row=row)
                result = self.on_rest_execution(execution)

                if result.inserted:
                    inserted += 1
                elif result.updated:
                    updated += 1
                else:
                    duplicates += 1

            if len(rows) < limit:
                break

            next_from_id = page_max_trade_id + 1

        summary = ExecutionReconciliationResult(
            symbol=symbol,
            fetched=fetched,
            inserted=inserted,
            updated=updated,
            duplicates=duplicates,
            pages_fetched=pages_fetched,
            from_trade_id=first_trade_id,
            to_trade_id=last_trade_id,
        )

        self.logger.info(
            "Execution REST reconciliation completed | symbol=%s fetched=%s inserted=%s updated=%s duplicates=%s pages=%s range=[%s,%s]",
            summary.symbol,
            summary.fetched,
            summary.inserted,
            summary.updated,
            summary.duplicates,
            summary.pages_fetched,
            summary.from_trade_id,
            summary.to_trade_id,
        )
        return summary

    def get_position(self, symbol: str) -> Decimal:
        self._validate_symbol(symbol)
        return self.ledger.state.position_qty

    def get_avg_cost(self, symbol: str) -> Decimal:
        self._validate_symbol(symbol)
        return self.ledger.state.average_cost

    def get_realized_pnl(self, symbol: str) -> Decimal:
        self._validate_symbol(symbol)
        return self.ledger.state.realized_net_pnl

    def get_total_executions(self, symbol: str) -> int:
        self._validate_symbol(symbol)
        return self.ledger.state.applied_executions

    def get_last_reconciled_trade_id(self, symbol: str) -> int | None:
        self._validate_symbol(symbol)
        return self._last_reconciled_trade_id_by_symbol.get(symbol)

    def _bump_last_trade_id(self, symbol: str, trade_id: int) -> None:
        current = self._last_reconciled_trade_id_by_symbol.get(symbol)
        if current is None or trade_id > current:
            self._last_reconciled_trade_id_by_symbol[symbol] = trade_id

    def _execution_from_trade_row(self, symbol: str, row: dict) -> Execution:
        price = Decimal(str(row.get("price", "0")))
        qty = Decimal(str(row.get("qty", "0")))
        quote_qty = Decimal(str(row.get("quoteQty", "0")))
        if quote_qty <= 0 and price > 0 and qty > 0:
            quote_qty = price * qty

        commission = Decimal(str(row.get("commission", "0")))
        commission_asset = row.get("commissionAsset") or ""
        executed_at = self._ms_to_iso(int(row.get("time", 0)))
        side = "BUY" if bool(row.get("isBuyer", False)) else "SELL"

        normalized_fee: FeeNormalizationResult = self.fee_normalizer.normalize(
            symbol=symbol,
            execution_price=price,
            commission=commission,
            commission_asset=commission_asset,
            executed_at=executed_at,
        )

        return Execution(
            exchange="binance",
            account=self.account_name,
            symbol=symbol,
            trade_id=int(row["id"]),
            order_id=int(row["orderId"]),
            client_order_id=str(row.get("clientOrderId", "")),
            side=side,
            price=price,
            qty=qty,
            quote_qty=quote_qty,
            commission=commission,
            commission_asset=commission_asset,
            commission_in_quote=normalized_fee.commission_in_quote,
            commission_fx_rate=normalized_fee.fx_rate,
            commission_fx_symbol=normalized_fee.fx_symbol,
            commission_fx_timestamp=normalized_fee.fx_timestamp,
            is_maker=bool(row.get("isMaker", False)),
            executed_at=executed_at,
            source="rest",
        )

    def _validate_symbol(self, symbol: str) -> None:
        if symbol != self.symbol:
            raise ValueError(
                f"ExecutionService is bound to symbol={self.symbol}, received symbol={symbol}"
            )

    @staticmethod
    def _ms_to_iso(value_ms: int) -> str:
        return datetime.fromtimestamp(value_ms / 1000, tz=UTC).isoformat()