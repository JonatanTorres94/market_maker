#src/reconciliation/trade_reconciler.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional

from src.config.settings import get_settings
from src.core.logger import setup_logger
from src.core.fee_normalizer import FeeNormalizer, FeeNormalizationResult
from src.domain.execution import Execution
from src.engine.execution_store import ExecutionStore
from src.exchange.order_manager import OrderManager
from src.journal.execution_journal import ExecutionJournal


@dataclass(frozen=True)
class TradeReconciliationSummary:
    symbol: str
    fetched_trades: int
    inserted_trades: int
    duplicate_trades: int
    pages_fetched: int
    earliest_trade_id: int | None
    latest_trade_id: int | None
    missing_fee_conversions: int


class TradeReconciler:
    """
    REST backfill / verification for account trades.

    Design intent:
    - stream remains the low-latency ingestion path
    - REST myTrades is the repair/verification path
    - deduplication is enforced by ExecutionStore unique key
    """

    def __init__(
        self,
        order_manager: OrderManager,
        execution_store: ExecutionStore,
        execution_journal: ExecutionJournal,
        fee_normalizer: FeeNormalizer,
        exchange_name: str = "binance",
        account_name: str | None = None,
    ):
        self.order_manager = order_manager
        self.execution_store = execution_store
        self.execution_journal = execution_journal
        self.fee_normalizer = fee_normalizer
        self.exchange_name = exchange_name
        self.account_name = account_name or get_settings().infrastructure.account_name
        self.logger = setup_logger("trade_reconciler")

    def reconcile_symbol(
        self,
        symbol: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        from_id: int | None = None,
        limit: int = 1000,
        max_pages: int = 20,
    ) -> TradeReconciliationSummary:
        fetched_trades = 0
        inserted_trades = 0
        duplicate_trades = 0
        pages_fetched = 0
        missing_fee_conversions = 0
        earliest_trade_id: int | None = None
        latest_trade_id: int | None = None

        next_from_id = from_id
        seen_trade_ids: set[int] = set()

        self.logger.info(
            "Starting trade reconciliation for %s | start_ms=%s end_ms=%s from_id=%s limit=%s max_pages=%s",
            symbol,
            start_time_ms,
            end_time_ms,
            from_id,
            limit,
            max_pages,
        )

        for page in range(1, max_pages + 1):
            params = {
                "symbol": symbol,
                "limit": limit
            }
            if next_from_id:
                params["from_id"] = next_from_id
            else:
                if start_time_ms:
                    params["start_time"] = start_time_ms
                if end_time_ms:
                    params["end_time"] = end_time_ms
            page_rows = self.order_manager.get_my_trades(**params)

            if not page_rows:
                self.logger.info("Trade reconciliation page %s returned 0 rows. Stopping.", page)
                break

            pages_fetched += 1
            fetched_trades += len(page_rows)

            page_ids = [int(row["id"]) for row in page_rows]
            page_min_id = min(page_ids)
            page_max_id = max(page_ids)
            earliest_trade_id = page_min_id if earliest_trade_id is None else min(earliest_trade_id, page_min_id)
            latest_trade_id = page_max_id if latest_trade_id is None else max(latest_trade_id, page_max_id)

            inserted_this_page = 0
            duplicate_this_page = 0
            unresolved_fee_this_page = 0

            for row in page_rows:
                trade_id = int(row["id"])
                if trade_id in seen_trade_ids:
                    duplicate_this_page += 1
                    duplicate_trades += 1
                    continue
                seen_trade_ids.add(trade_id)

                execution = self._execution_from_trade_row(symbol=symbol, row=row)
                if execution.commission_in_quote is None:
                    unresolved_fee_this_page += 1
                    missing_fee_conversions += 1

                upsert_result = self.execution_store.upsert(execution)

                if upsert_result.inserted:
                    self.execution_journal.record_execution(execution)
                    inserted_this_page += 1
                    inserted_trades += 1

                elif upsert_result.updated:
                    self.execution_journal.record_execution(
                        self.execution_store.get(
                            self.exchange_name,
                            self.account_name,
                            symbol,
                            trade_id,
                        )
                    )
                    self.logger.info(
                        "Execution enriched from REST for trade_id=%s symbol=%s changed_fields=%s",
                        trade_id,
                        symbol,
                        upsert_result.changed_fields,
                    )

                else:
                    duplicate_this_page += 1
                    duplicate_trades += 1

            self.logger.info(
                "Trade reconciliation page %s fetched=%s inserted=%s duplicates=%s unresolved_fee=%s page_range=[%s,%s]",
                page,
                len(page_rows),
                inserted_this_page,
                duplicate_this_page,
                unresolved_fee_this_page,
                page_min_id,
                page_max_id,
            )

            if len(page_rows) < limit:
                break

            next_from_id = page_max_id + 1

        summary = TradeReconciliationSummary(
            symbol=symbol,
            fetched_trades=fetched_trades,
            inserted_trades=inserted_trades,
            duplicate_trades=duplicate_trades,
            pages_fetched=pages_fetched,
            earliest_trade_id=earliest_trade_id,
            latest_trade_id=latest_trade_id,
            missing_fee_conversions=missing_fee_conversions,
        )
        self.logger.info("Trade reconciliation completed: %s", summary)
        return summary

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
            exchange=self.exchange_name,
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

    @staticmethod
    def _ms_to_iso(value_ms: int) -> str:
        return datetime.fromtimestamp(value_ms / 1000, tz=UTC).isoformat()
