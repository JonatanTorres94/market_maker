from dataclasses import dataclass
from decimal import Decimal
from queue import Empty, Queue
from typing import Optional

from binance import ThreadedWebsocketManager

from src.config.settings import get_settings
from src.core.logger import setup_logger
from src.domain.events import OrderStatusSyncedEvent


@dataclass(frozen=True)
class UserStreamHealth:
    messages_received: int
    execution_reports_received: int
    parse_errors: int
    last_event_at: Optional[str]


class WsUserDataStream:
    def __init__(self, manager:ThreadedWebsocketManager):
        self.settings = get_settings()
        self.logger = setup_logger("ws_user_stream")
        self._queue: Queue[OrderStatusSyncedEvent] = Queue()
        self._manager = manager
        self._conn_key = None
        self._messages_received = 0
        self._execution_reports_received = 0
        self._parse_errors = 0
        self._last_event_at: Optional[str] = None

    @property
    def queue(self) -> Queue[OrderStatusSyncedEvent]:
        return self._queue

    def start(self) -> None:
    #     if self._manager is not None:
    #         return

    #     self._manager = ThreadedWebsocketManager(
    #         api_key=self.settings.binance_api_key,
    #         api_secret=self.settings.binance_secret,
    #         testnet=self.settings.binance_testnet,
    #     )
    #     self._manager.start()

        self._conn_key = self._manager.start_user_socket(
            callback=self._handle_message,
        )

        self.logger.info("Started user data websocket")

    def stop(self) -> None:
        # if self._manager is None:
        #     return

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

    def drain_events(self) -> list[OrderStatusSyncedEvent]:
        events: list[OrderStatusSyncedEvent] = []

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

            event = OrderStatusSyncedEvent(
                occurred_at=occurred_at,
                symbol=message["s"],
                order_id=int(message["i"]),
                client_order_id=message.get("c", ""),
                side=message["S"],
                price=Decimal(message["p"]),
                orig_qty=Decimal(message["q"]),
                executed_qty=Decimal(message["z"]),
                status=message["X"],
                updated_at=updated_at,
            )

            self._queue.put(event)
            self._execution_reports_received += 1
            self._last_event_at = occurred_at

        except Exception as exc:
            self._parse_errors += 1
            self.logger.exception("Failed to parse user websocket message: %s | %s", exc, message)

    @staticmethod
    def _ms_to_iso(value: Optional[int]) -> str:
        from datetime import UTC, datetime

        if value is None:
            return datetime.now(UTC).isoformat()

        return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()