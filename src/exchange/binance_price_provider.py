# src/exchange/binance_price_provider.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException

from src.core.logger import setup_logger


@dataclass(frozen=True)
class PriceCacheKey:
    symbol: str
    minute_bucket_ms: int


class BinancePriceProvider:
    """
    Best-effort historical/current spot price provider for fee normalization.

    Strategy:
    - if at_iso is provided: fetch 1m klines around the execution timestamp
    - select the candle containing the timestamp when possible
    - otherwise fallback to the nearest returned candle
    - if no candle exists, fallback to current ticker price

    This is not tick-accurate historical reconstruction.
    It is a practical V1 approximation for fee normalization in quote terms.
    """

    def __init__(self, client: Client):
        self.client = client
        self.logger = setup_logger("binance_price_provider")
        self._minute_cache: dict[PriceCacheKey, Decimal | None] = {}
        self._spot_cache: dict[str, Decimal | None] = {}

    def get_price(self, symbol: str, at_iso: str | None = None) -> Decimal | None:
        if not symbol:
            return None

        normalized_symbol = symbol.upper()

        if at_iso is None:
            return self._get_spot_price(normalized_symbol)

        try:
            target_ms = self._iso_to_ms(at_iso)
        except Exception:
            self.logger.warning(
                "Failed to parse at_iso=%s for symbol=%s. Falling back to spot price.",
                at_iso,
                normalized_symbol,
            )
            return self._get_spot_price(normalized_symbol)

        minute_bucket_ms = (target_ms // 60_000) * 60_000
        cache_key = PriceCacheKey(symbol=normalized_symbol, minute_bucket_ms=minute_bucket_ms)

        if cache_key in self._minute_cache:
            return self._minute_cache[cache_key]

        price = self._get_historical_minute_price(
            symbol=normalized_symbol,
            target_ms=target_ms,
            minute_bucket_ms=minute_bucket_ms,
        )

        self._minute_cache[cache_key] = price
        return price

    def _get_historical_minute_price(
        self,
        symbol: str,
        target_ms: int,
        minute_bucket_ms: int,
    ) -> Decimal | None:
        start_ms = minute_bucket_ms - 60_000
        end_ms = minute_bucket_ms + 120_000

        try:
            rows = self.client.get_klines(
                symbol=symbol,
                interval=Client.KLINE_INTERVAL_1MINUTE,
                startTime=start_ms,
                endTime=end_ms,
                limit=3,
            )
        except BinanceAPIException as exc:
            self.logger.warning(
                "Historical kline lookup failed for symbol=%s target_ms=%s: %s",
                symbol,
                target_ms,
                exc,
            )
            return self._get_spot_price(symbol)
        except Exception as exc:
            self.logger.warning(
                "Unexpected historical kline lookup failure for symbol=%s target_ms=%s: %s",
                symbol,
                target_ms,
                exc,
            )
            return self._get_spot_price(symbol)

        if not rows:
            self.logger.info(
                "No 1m klines returned for symbol=%s target_ms=%s. Falling back to spot.",
                symbol,
                target_ms,
            )
            return self._get_spot_price(symbol)

        selected_row = None

        for row in rows:
            open_time_ms = int(row[0])
            close_time_ms = open_time_ms + 60_000
            if open_time_ms <= target_ms < close_time_ms:
                selected_row = row
                break

        if selected_row is None:
            selected_row = min(rows, key=lambda row: abs(int(row[0]) - minute_bucket_ms))

        # Use candle close as a practical proxy.
        close_price = Decimal(str(selected_row[4]))
        if close_price > 0:
            return close_price

        self.logger.warning(
            "Selected candle had non-positive close price for symbol=%s target_ms=%s. Falling back to spot.",
            symbol,
            target_ms,
        )
        return self._get_spot_price(symbol)

    def _get_spot_price(self, symbol: str) -> Decimal | None:
        if symbol in self._spot_cache:
            return self._spot_cache[symbol]

        try:
            row = self.client.get_symbol_ticker(symbol=symbol)
            price = Decimal(str(row["price"]))
            self._spot_cache[symbol] = price if price > 0 else None
            return self._spot_cache[symbol]
        except BinanceAPIException as exc:
            self.logger.warning("Spot ticker lookup failed for symbol=%s: %s", symbol, exc)
            self._spot_cache[symbol] = None
            return None
        except Exception as exc:
            self.logger.warning("Unexpected spot ticker lookup failure for symbol=%s: %s", symbol, exc)
            self._spot_cache[symbol] = None
            return None

    @staticmethod
    def _iso_to_ms(value: str) -> int:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)