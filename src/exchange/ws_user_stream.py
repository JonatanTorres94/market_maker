from dataclasses import dataclass
from decimal import Decimal
from queue import Empty, Queue
from typing import Optional

from binance import ThreadedWebsocketManager

from src.config.settings import get_settings
from src.core.logger import setup_logger
from src.domain.events import ExecutionReceivedEvent, OrderStatusSyncedEvent

UserStreamEvent = OrderStatusSyncedEvent | ExecutionReceivedEvent


@dataclass(frozen=True)
class UserStreamHealth:
    messages_received: int
    execution_reports_received: int
    parse_errors: int
    last_event_at: Optional[str]


class WsUserDataStream:
    def __init__(self, manager: ThreadedWebsocketManager):
        self.settings = get_settings()
        self.logger = setup_logger("ws_user_stream")
        self._queue: Queue[UserStreamEvent] = Queue()
        self._manager = manager
        self._conn_key = None
        self._messages_received = 0
        self._execution_reports_received = 0
        self._parse_errors = 0
        self._last_event_at: Optional[str] = None
        self._last_cumulative_qty_by_order: dict[int, Decimal] = {}

    @property
    def queue(self) -> Queue[UserStreamEvent]:
        return self._queue

    def start(self) -> None:
        self._conn_key = self._manager.start_user_socket(
            callback=self._handle_message,
        )

        self.logger.info("Started user data websocket")

    def stop(self) -> None:
        try:
            if self._conn_key is not None:
                self._manager.stop_socket(self._conn_key)
                self._conn_key = None
            self.logger.info("Stopped user websocket connection")
        finally:
            self._manager.stop()
            self._manager = None
            self._conn_key = None
            self.logger.info("Stopped user websocket")

    def drain_events(self) -> list[UserStreamEvent]:
        events: list[UserStreamEvent] = []

        while True:
            try:
                events.append(self._queue.get_nowait())
            except Empty:
                return events

    def health(self) -> UserStreamHealth:
        return UserStreamHealth(
            messages_received=self._messages_received,
            execution_reports_received=self._execution_reports_received,
            parse_errors=self._parse_errors,
            last_event_at=self._last_event_at,
        )

    def _handle_message(self, message: dict) -> None:
        if message is None:
            return

        self._messages_received += 1

        if message.get("e") == "error":
            self.logger.error("User websocket error payload: %s", message)
            return

        if message.get("e") != "executionReport":
            return

        try:
            occurred_at = self._ms_to_iso(message.get("E"))
            updated_at = self._ms_to_iso(message.get("T") or message.get("E"))
            order_id = int(message["i"])
            cumulative_qty = Decimal(message.get("z", "0"))

            event = OrderStatusSyncedEvent(
                occurred_at=occurred_at,
                symbol=message["s"],
                order_id=order_id,
                client_order_id=message.get("c", ""),
                side=message["S"],
                price=Decimal(message.get("p", "0")),
                orig_qty=Decimal(message.get("q", "0")),
                executed_qty=cumulative_qty,
                status=message["X"],
                updated_at=updated_at,
            )

            self._queue.put(event)

            execution_event = self._build_execution_event(
                message=message,
                occurred_at=occurred_at,
                executed_at=updated_at,
                order_id=order_id,
                cumulative_qty=cumulative_qty,
            )
            if execution_event is not None:
                self._queue.put(execution_event)

            self._execution_reports_received += 1
            self._last_event_at = occurred_at

        except Exception as exc:
            self._parse_errors += 1
            self.logger.exception("Failed to parse user websocket message: %s | %s", exc, message)

    def _build_execution_event(
        self,
        message: dict,
        occurred_at: str,
        executed_at: str,
        order_id: int,
        cumulative_qty: Decimal,
    ) -> ExecutionReceivedEvent | None:
        previous_cumulative_qty = self._last_cumulative_qty_by_order.get(order_id, Decimal("0"))
        delta_qty = cumulative_qty - previous_cumulative_qty
        self._last_cumulative_qty_by_order[order_id] = cumulative_qty

        if delta_qty <= 0:
            return None

        last_fill_qty = Decimal(message.get("l", "0"))
        if last_fill_qty > 0:
            delta_qty = last_fill_qty

        if delta_qty <= 0:
            return None

        trade_id_raw = message.get("t")
        if trade_id_raw is None:
            self.logger.warning(
                "executionReport with positive fill delta but missing trade id for order_id=%s",
                order_id,
            )
            return None

        last_fill_price = Decimal(message.get("L", "0"))
        execution_price = last_fill_price if last_fill_price > 0 else Decimal(message.get("p", "0"))
        quote_qty = execution_price * delta_qty

        return ExecutionReceivedEvent(
            occurred_at=occurred_at,
            exchange="binance",
            account=self.settings.infrastructure.account_name,
            symbol=message["s"],
            trade_id=int(trade_id_raw),
            order_id=order_id,
            client_order_id=message.get("c", ""),
            side=message["S"],
            price=execution_price,
            qty=delta_qty,
            quote_qty=quote_qty,
            commission=Decimal(message.get("n", "0")),
            commission_asset=message.get("N") or "",
            is_maker=bool(message.get("m", False)),
            executed_at=executed_at,
            source="stream",
        )

    @staticmethod
    def _ms_to_iso(value: Optional[int]) -> str:
        from datetime import UTC, datetime

        if value is None:
            return datetime.now(UTC).isoformat()

        return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
