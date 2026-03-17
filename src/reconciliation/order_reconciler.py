import csv
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.core.logger import setup_logger
from src.domain.models import ReconciledOrderRecord, ReconciliationSummary
from src.exchange.order_manager import OrderManager
from src.journal.csv_journal import CsvJournalWriter


class OrderReconciler:
    def __init__(
        self,
        order_manager: OrderManager,
        orders_source_path: str = "data/journals/orders.csv",
        reconciled_output_path: str = "data/journals/orders_reconciled.csv",
        bulk_limit: int = 1000,
        fallback_sleep_seconds: float = 0.05,
        window_hours: int = 12,
    ):
        self.order_manager = order_manager
        self.orders_source_path = Path(orders_source_path)
        self.logger = setup_logger("order_reconciler")
        self.bulk_limit = bulk_limit
        self.fallback_sleep_seconds = fallback_sleep_seconds
        self.window_hours = window_hours

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

    def _fetch_bulk_orders(self, symbol: str, start_ms: int | None, end_ms: int | None) -> dict[int, dict]:
        """
        Estrategia principal:
        - consulta por ventana temporal amplia
        - si Binance devuelve menos de lo esperado, igual queda fallback individual
        - se indexa por order_id
        """
        self.logger.info(
            "Fetching bulk orders for %s | start_ms=%s end_ms=%s limit=%s",
            symbol,
            start_ms,
            end_ms,
            self.bulk_limit,
        )

        fetched_orders = self.order_manager.get_all_orders(
            symbol=symbol,
            limit=self.bulk_limit,
            start_time=start_ms,
            end_time=end_ms,
        )

        orders_map = {int(order["orderId"]): order for order in fetched_orders}

        self.logger.info(
            "Bulk fetch returned %s orders for %s",
            len(orders_map),
            symbol,
        )
        return orders_map

    def _fallback_fetch_missing_orders(
        self,
        symbol: str,
        missing_order_ids: list[int],
    ) -> dict[int, dict]:
        resolved: dict[int, dict] = {}

        if not missing_order_ids:
            return resolved

        self.logger.info(
            "Starting fallback per-order fetch for %s missing orders",
            len(missing_order_ids),
        )

        for index, order_id in enumerate(missing_order_ids, start=1):
            order = self.order_manager.get_order_safe(symbol=symbol, order_id=order_id)
            if order is not None:
                resolved[int(order["orderId"])] = order

            if self.fallback_sleep_seconds > 0:
                time.sleep(self.fallback_sleep_seconds)

            if index % 100 == 0:
                self.logger.info(
                    "Fallback progress: %s/%s",
                    index,
                    len(missing_order_ids),
                )

        self.logger.info(
            "Fallback resolved %s/%s missing orders",
            len(resolved),
            len(missing_order_ids),
        )
        return resolved

    def _write_reconciled_record(self, order_data: dict) -> ReconciledOrderRecord:
        updated_at = self._ms_to_iso(order_data.get("updateTime") or order_data.get("time"))

        record = ReconciledOrderRecord(
            timestamp=self._utc_now_iso(),
            updated_at=updated_at,
            symbol=order_data["symbol"],
            order_id=int(order_data["orderId"]),
            side=order_data["side"],
            status=order_data["status"],
            price=Decimal(order_data["price"]),
            orig_qty=Decimal(order_data["origQty"]),
            executed_qty=Decimal(order_data["executedQty"]),
            cumulative_quote_qty=Decimal(order_data["cummulativeQuoteQty"]),
        )

        self.writer.append_row(
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
        return record

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
                fallback_requested_orders=0,
                fallback_resolved_orders=0,
            )

        start_ms, end_ms = self._extract_time_bounds_ms(symbol_rows)
        self.logger.info("Starting reconciliation for %s | journal_orders=%s", symbol, len(unique_order_ids))

        bulk_orders_map = self._fetch_bulk_orders(symbol=symbol, start_ms=start_ms, end_ms=end_ms)
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
        records_to_save = [] # Para el guardado masivo

        for order_id in unique_order_ids:
            order_data = combined_orders_map.get(order_id)
            if order_data is None:
                continue

            updated_at = self._ms_to_iso(order_data.get("updateTime") or order_data.get("time"))
            
            # 1. Preparamos el registro para el CSV
            records_to_save.append({
                "timestamp": self._utc_now_iso(),
                "updated_at": updated_at,
                "symbol": order_data["symbol"],
                "order_id": int(order_data["orderId"]),
                "side": order_data["side"],
                "status": order_data["status"],
                "price": str(order_data["price"]),
                "orig_qty": str(order_data["origQty"]),
                "executed_qty": str(order_data["executedQty"]),
                "cumulative_quote_qty": str(order_data["cummulativeQuoteQty"]),
            })

            # 2. Actualizamos contadores internos
            reconciled_orders += 1
            status = order_data["status"]
            if status == "FILLED":
                filled_orders += 1
            elif status == "CANCELED":
                canceled_orders += 1
            elif status == "PARTIALLY_FILLED":
                partially_filled_orders += 1
            elif status in {"NEW", "PENDING_NEW"}:
                open_orders += 1

        # --- MEJORA: GUARDADO ÚNICO FUERA DEL BUCLE ---
        if records_to_save:
            self.writer.append_rows(records_to_save)
            self.logger.info("Saved %s reconciled records to CSV", len(records_to_save))

        missing_orders = len(unique_order_ids) - reconciled_orders
        coverage_ratio = (Decimal(reconciled_orders) / Decimal(len(unique_order_ids)) 
                          if unique_order_ids else Decimal("0"))

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
            fallback_requested_orders=len(missing_after_bulk),
            fallback_resolved_orders=len(fallback_orders_map),
        )