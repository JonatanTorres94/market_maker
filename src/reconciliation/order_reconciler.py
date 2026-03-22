import csv
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.core.logger import setup_logger
from src.domain.models import ReconciledOrderRecord, ReconciliationSummary
from src.exchange.order_manager import OrderManager
from src.journal.csv_journal import CsvJournalWriter
from src.core.run_paths import get_journal_base_path

class OrderReconciler:
    def __init__(
        self,
        order_manager: OrderManager,
        orders_source_path: str | None = None,
        reconciled_output_path: str | None = None,
        bulk_limit: int = 1000,
        fallback_sleep_seconds: float = 0.05,
        window_hours: int = 12,
        max_bulk_pages: int = 10,
    ):
        base_path = get_journal_base_path()

        orders_source_path = orders_source_path or f"{base_path}/orders.csv"
        reconciled_output_path = reconciled_output_path or f"{base_path}/orders_reconciled.csv"

        self.order_manager = order_manager
        self.orders_source_path = Path(orders_source_path)
        self.logger = setup_logger("order_reconciler")
        self.bulk_limit = bulk_limit
        self.fallback_sleep_seconds = fallback_sleep_seconds
        self.window_hours = window_hours
        self.max_bulk_pages = max_bulk_pages

        self.writer = CsvJournalWriter(
            filepath=reconciled_output_path,
            fieldnames=[
                "timestamp",
                "updated_at",
                "symbol",
                "order_id",
                "side",
                "status",
                "price",
                "orig_qty",
                "executed_qty",
                "cumulative_quote_qty",
            ],
        )

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _ms_to_iso(value: int | None) -> str:
        if value is None:
            return datetime.now(UTC).isoformat()
        return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()

    def _read_recorded_orders(self) -> list[dict]:
        if not self.orders_source_path.exists():
            return []

        with self.orders_source_path.open("r", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def _extract_symbol_rows(self, recorded_orders: list[dict], symbol: str) -> list[dict]:
        return [row for row in recorded_orders if row["symbol"] == symbol]

    def _extract_unique_order_ids(self, rows: list[dict]) -> list[int]:
        unique_order_ids: list[int] = []
        seen = set()

        for row in rows:
            order_id = int(row["order_id"])
            if order_id in seen:
                continue
            seen.add(order_id)
            unique_order_ids.append(order_id)

        return unique_order_ids

    def _extract_time_bounds_ms(self, rows: list[dict]) -> tuple[int | None, int | None]:
        if not rows:
            return None, None

        placed_times = []
        for row in rows:
            placed_at = row.get("placed_at", "")
            if not placed_at:
                continue
            placed_times.append(datetime.fromisoformat(placed_at))

        if not placed_times:
            return None, None

        min_dt = min(placed_times) - timedelta(hours=self.window_hours)
        max_dt = max(placed_times) + timedelta(hours=self.window_hours)

        return int(min_dt.timestamp() * 1000), int(max_dt.timestamp() * 1000)

    def _fetch_bulk_orders(self, symbol: str, start_ms: int | None, end_ms: int | None, journal_order_ids: set[int]) -> tuple[dict[int, dict], int]:
        self.logger.info(
            "Fetching bulk orders for %s | start_ms=%s end_ms=%s limit=%s max_pages=%s",
            symbol,
            start_ms,
            end_ms,
            self.bulk_limit,
            self.max_bulk_pages,
        )

        orders_map: dict[int, dict] = {}
        next_order_id: int | None = None
        pages_fetched = 0

        while pages_fetched < self.max_bulk_pages:
            # Construcción dinámica de parámetros para evitar el error -1106
            params = {
                "symbol": symbol,
                "limit": self.bulk_limit,
            }

            if next_order_id:
                # Si ya tenemos un cursor, usamos SOLO orderId. 
                # Binance prohíbe startTime/endTime junto con orderId en este endpoint.
                params["order_id"] = next_order_id
            else:
                # Solo en la primera página aplicamos el filtro de tiempo del Journal
                if start_ms: params["start_time"] = start_ms
                if end_ms: params["end_time"] = end_ms

            try:
                fetched_orders = self.order_manager.get_all_orders(**params)
            except Exception as e:
                self.logger.error("Error fetching bulk page %s: %s", pages_fetched + 1, e)
                break

            pages_fetched += 1

            if not fetched_orders:
                self.logger.info("Bulk page %s returned 0 orders", pages_fetched)
                break

            page_added = 0
            for order in fetched_orders:
                order_id = int(order["orderId"])
                if order_id not in orders_map:
                    page_added += 1
                orders_map[order_id] = order

            matched_journal = len(journal_order_ids.intersection(orders_map.keys()))
            min_page_id = min(int(order["orderId"]) for order in fetched_orders)
            max_page_id = max(int(order["orderId"]) for order in fetched_orders)
            
            self.logger.info(
                "Bulk page %s fetched=%s added=%s matched_journal=%s/%s page_range=[%s,%s]",
                pages_fetched,
                len(fetched_orders),
                page_added,
                matched_journal,
                len(journal_order_ids),
                min_page_id,
                max_page_id,
            )

            # Optimización: Si ya encontramos todas las órdenes del Journal, no seguimos pidiendo páginas
            if matched_journal >= len(journal_order_ids):
                self.logger.info("Bulk pagination achieved full journal coverage. Stopping early.")
                break

            # Si la página vino incompleta, es que llegamos al final de la historia de órdenes
            if len(fetched_orders) < self.bulk_limit:
                self.logger.info("Bulk pagination exhausted: last page size < limit")
                break

            # Seteamos el cursor para la siguiente página (último ID + 1)
            # Esto garantiza que no haya solapamiento y que la data sea 100% real
            last_order_id = int(fetched_orders[-1]["orderId"])
            next_order_id = last_order_id + 1

        self.logger.info(
            "Bulk fetch accumulated %s unique orders for %s across %s page(s)", 
            len(orders_map), 
            symbol, 
            pages_fetched
        )
        return orders_map, pages_fetched

    def _fallback_fetch_missing_orders(self, symbol: str, missing_order_ids: list[int]) -> dict[int, dict]:
        resolved: dict[int, dict] = {}

        if not missing_order_ids:
            return resolved

        self.logger.info("Starting fallback per-order fetch for %s missing orders", len(missing_order_ids))

        for index, order_id in enumerate(missing_order_ids, start=1):
            order = self.order_manager.get_order_safe(symbol=symbol, order_id=order_id)
            if order is not None:
                resolved[int(order["orderId"])] = order

            if self.fallback_sleep_seconds > 0:
                time.sleep(self.fallback_sleep_seconds)

            if index % 100 == 0:
                self.logger.info("Fallback progress: %s/%s", index, len(missing_order_ids))

        self.logger.info("Fallback resolved %s/%s missing orders", len(resolved), len(missing_order_ids))
        return resolved

    def reconcile(self, symbol: str) -> ReconciliationSummary:
        recorded_orders = self._read_recorded_orders()
        symbol_rows = self._extract_symbol_rows(recorded_orders, symbol)
        unique_order_ids = self._extract_unique_order_ids(symbol_rows)

        self.writer.reset()

        if not unique_order_ids:
            self.logger.warning("No recorded orders found for %s", symbol)
            return ReconciliationSummary(
                journal_orders=0,
                reconciled_orders=0,
                missing_orders=0,
                coverage_ratio=Decimal("0"),
                filled_orders=0,
                canceled_orders=0,
                open_orders=0,
                partially_filled_orders=0,
                bulk_fetched_orders=0,
                bulk_matched_orders=0,
                bulk_pages_fetched=0,
                fallback_requested_orders=0,
                fallback_resolved_orders=0,
            )

        start_ms, end_ms = self._extract_time_bounds_ms(symbol_rows)
        self.logger.info("Starting reconciliation for %s | journal_orders=%s", symbol, len(unique_order_ids))

        journal_order_ids = set(unique_order_ids)
        bulk_orders_map, bulk_pages_fetched = self._fetch_bulk_orders(
            symbol=symbol,
            start_ms=start_ms,
            end_ms=end_ms,
            journal_order_ids=journal_order_ids,
        )
        bulk_matched_orders = len(journal_order_ids.intersection(bulk_orders_map.keys()))
        missing_after_bulk = [oid for oid in unique_order_ids if oid not in bulk_orders_map]

        fallback_orders_map = self._fallback_fetch_missing_orders(
            symbol=symbol,
            missing_order_ids=missing_after_bulk,
        )

        combined_orders_map = {**bulk_orders_map, **fallback_orders_map}

        filled_orders = 0
        canceled_orders = 0
        open_orders = 0
        partially_filled_orders = 0
        reconciled_orders = 0
        records_to_save: list[dict] = []

        for order_id in unique_order_ids:
            order_data = combined_orders_map.get(order_id)
            if order_data is None:
                continue

            record = ReconciledOrderRecord(
                timestamp=self._utc_now_iso(),
                updated_at=self._ms_to_iso(order_data.get("updateTime") or order_data.get("time")),
                symbol=order_data["symbol"],
                order_id=int(order_data["orderId"]),
                side=order_data["side"],
                status=order_data["status"],
                price=Decimal(order_data["price"]),
                orig_qty=Decimal(order_data["origQty"]),
                executed_qty=Decimal(order_data["executedQty"]),
                cumulative_quote_qty=Decimal(order_data["cummulativeQuoteQty"]),
            )
            records_to_save.append(
                {
                    "timestamp": record.timestamp,
                    "updated_at": record.updated_at,
                    "symbol": record.symbol,
                    "order_id": record.order_id,
                    "side": record.side,
                    "status": record.status,
                    "price": str(record.price),
                    "orig_qty": str(record.orig_qty),
                    "executed_qty": str(record.executed_qty),
                    "cumulative_quote_qty": str(record.cumulative_quote_qty),
                }
            )

            reconciled_orders += 1
            status = record.status
            if status == "FILLED":
                filled_orders += 1
            elif status == "CANCELED":
                canceled_orders += 1
            elif status == "PARTIALLY_FILLED":
                partially_filled_orders += 1
            elif status in {"NEW", "PENDING_NEW"}:
                open_orders += 1

        if records_to_save:
            self.writer.append_rows(records_to_save)
            self.logger.info("Saved %s reconciled records to CSV", len(records_to_save))

        missing_orders = len(unique_order_ids) - reconciled_orders
        coverage_ratio = Decimal(reconciled_orders) / Decimal(len(unique_order_ids)) if unique_order_ids else Decimal("0")

        return ReconciliationSummary(
            journal_orders=len(unique_order_ids),
            reconciled_orders=reconciled_orders,
            missing_orders=missing_orders,
            coverage_ratio=coverage_ratio,
            filled_orders=filled_orders,
            canceled_orders=canceled_orders,
            open_orders=open_orders,
            partially_filled_orders=partially_filled_orders,
            bulk_fetched_orders=len(bulk_orders_map),
            bulk_matched_orders=bulk_matched_orders,
            bulk_pages_fetched=bulk_pages_fetched,
            fallback_requested_orders=len(missing_after_bulk),
            fallback_resolved_orders=len(fallback_orders_map),
        )
