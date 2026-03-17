from dataclasses import dataclass
from decimal import Decimal
from queue import Empty, Queue
from typing import Optional

from binance import ThreadedWebsocketManager

from src.config.settings import get_settings
from src.core.logger import setup_logger
from src.domain.events import MarketTickEvent


@dataclass(frozen=True)
class MarketStreamHealth:
    messages_received: int
    parse_errors: int
    last_event_at: Optional[str]


class WsMarketDataStream:
    def __init__(self, manager:ThreadedWebsocketManager):
        self.settings = get_settings()
        self.logger = setup_logger("ws_market_stream")
        self._queue: Queue[MarketTickEvent] = Queue()
        self._manager = manager
        self._conn_key = None
        self._messages_received = 0
        self._parse_errors = 0
        self._last_event_at: Optional[str] = None

    @property
    def queue(self) -> Queue[MarketTickEvent]:
        return self._queue

    def start(self, symbol: str) -> None:
        # if self._manager is not None:
        #     return

        # self._manager = ThreadedWebsocketManager(
        #     api_key=self.settings.binance_api_key,
        #     api_secret=self.settings.binance_secret,
        #     testnet=self.settings.binance_testnet,
        # )
        # self._manager.start()

        self._conn_key = self._manager.start_symbol_book_ticker_socket(
            callback=self._handle_message,
            symbol=symbol.lower(),
        )

        self.logger.info("Started bookTicker websocket for %s", symbol)

    def stop(self) -> None:
        if self._manager is None:
            return

        try:
            if self._conn_key is not None:
                self._manager.stop_socket(self._conn_key)
        finally:
            self._manager.stop()
            self._manager = None
            self._conn_key = None
            self.logger.info("Stopped market websocket")

    def get_latest_event(self, timeout: float) -> Optional[MarketTickEvent]:
        try:
            latest = self._queue.get(timeout=timeout)
        except Empty:
            return None

        while True:
            try:
                latest = self._queue.get_nowait()
            except Empty:
                return latest

    def health(self) -> MarketStreamHealth:
        return MarketStreamHealth(
            messages_received=self._messages_received,
            parse_errors=self._parse_errors,
            last_event_at=self._last_event_at,
        )

    def _handle_message(self, message: dict) -> None:
        if message is None:
            return

        if message.get("e") == "error":
            self.logger.error("Market websocket error payload: %s", message)
            return

        try:
            event_time_ms = message.get("E")
            occurred_at = self._ms_to_iso(event_time_ms)

            best_bid = Decimal(message["b"])
            best_ask = Decimal(message["a"])

            event = MarketTickEvent(
                occurred_at=occurred_at,
                symbol=message["s"],
                best_bid=best_bid,
                best_ask=best_ask,
                spread=best_ask - best_bid,
                mid_price=(best_bid + best_ask) / Decimal("2"),
            )

            self._queue.put(event)
            self._messages_received += 1
            self._last_event_at = occurred_at

        except Exception as exc:
            self._parse_errors += 1
            self.logger.exception("Failed to parse market websocket message: %s | %s", exc, message)

    @staticmethod
    def _ms_to_iso(value: Optional[int]) -> str:
        from datetime import UTC, datetime

        if value is None:
            return datetime.now(UTC).isoformat()

        return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()