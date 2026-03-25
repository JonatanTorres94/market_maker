from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class MarketContext:
    mid_price: Decimal
    spread: Decimal
    mid_return_1s_bps: Decimal
    mid_return_3s_bps: Decimal
    mid_return_5s_bps: Decimal
    volatility_5s_bps: Decimal


class QuoteParticipationMode(str, Enum):
    BOTH = "BOTH"
    BID_ONLY = "BID_ONLY"
    ASK_ONLY = "ASK_ONLY"
    NONE = "NONE"


@dataclass(frozen=True)
class MidPriceSample:
    timestamp: datetime
    mid_price: Decimal


class DriftSignalDetector:
    """
    Mantiene una ventana corta de mids y construye features simples
    de microestructura basadas en retornos del mid.
    """

    def __init__(self, max_window_seconds: int = 5):
        if max_window_seconds <= 0:
            raise ValueError("max_window_seconds must be > 0")

        self.max_window_seconds = max_window_seconds
        self._samples: deque[MidPriceSample] = deque()

    def update(self, timestamp_iso: str, mid_price: Decimal, spread: Decimal) -> MarketContext:
        timestamp = datetime.fromisoformat(timestamp_iso)

        self._samples.append(
            MidPriceSample(
                timestamp=timestamp,
                mid_price=mid_price,
            )
        )
        self._prune(timestamp)

        return MarketContext(
            mid_price=mid_price,
            spread=spread,
            mid_return_1s_bps=self._return_bps_from_lookback(
                now=timestamp,
                current_mid=mid_price,
                lookback_seconds=1,
            ),
            mid_return_3s_bps=self._return_bps_from_lookback(
                now=timestamp,
                current_mid=mid_price,
                lookback_seconds=3,
            ),
            mid_return_5s_bps=self._return_bps_from_lookback(
                now=timestamp,
                current_mid=mid_price,
                lookback_seconds=5,
            ),
            volatility_5s_bps=self._volatility_bps(
                now=timestamp,
                lookback_seconds=5,
            ),
        )

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.max_window_seconds)
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()

    def _return_bps_from_lookback(
        self,
        now: datetime,
        current_mid: Decimal,
        lookback_seconds: int,
    ) -> Decimal:
        reference = self._latest_sample_at_or_before(
            target=now - timedelta(seconds=lookback_seconds)
        )
        if reference is None:
            return Decimal("0")

        if reference.mid_price <= 0:
            return Decimal("0")

        return ((current_mid - reference.mid_price) / reference.mid_price) * Decimal("10000")

    def _volatility_bps(self, now: datetime, lookback_seconds: int) -> Decimal:
        window_start = now - timedelta(seconds=lookback_seconds)
        window_samples = [sample for sample in self._samples if sample.timestamp >= window_start]

        if len(window_samples) < 2:
            return Decimal("0")

        returns: list[Decimal] = []
        previous = window_samples[0]

        for current in window_samples[1:]:
            if previous.mid_price > 0:
                ret_bps = ((current.mid_price - previous.mid_price) / previous.mid_price) * Decimal("10000")
                returns.append(ret_bps)
            previous = current

        if not returns:
            return Decimal("0")

        mean = sum(returns) / Decimal(len(returns))
        variance = sum((value - mean) ** 2 for value in returns) / Decimal(len(returns))

        # Evitamos sqrt manual con floats para no mezclar tipos ni perder control.
        # Como primera aproximación robusta para gating, usamos RMS de retornos en bps.
        rms = variance.sqrt() if variance >= 0 else Decimal("0")
        return rms

    def _latest_sample_at_or_before(self, target: datetime) -> MidPriceSample | None:
        candidate: MidPriceSample | None = None

        for sample in self._samples:
            if sample.timestamp <= target:
                candidate = sample
            else:
                break

        return candidate