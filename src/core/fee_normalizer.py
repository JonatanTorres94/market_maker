#src/core/fee_normalizer.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


COMMON_QUOTE_ASSETS = (
    "USDT",
    "USDC",
    "FDUSD",
    "BUSD",
    "TUSD",
    "BTC",
    "ETH",
    "BNB",
    "EUR",
    "TRY",
)


class PriceProvider(Protocol):
    def get_price(self, symbol: str, at_iso: str | None = None) -> Decimal | None:
        ...


class NullPriceProvider:
    def get_price(self, symbol: str, at_iso: str | None = None) -> Decimal | None:
        return None


@dataclass(frozen=True)
class FeeNormalizationResult:
    commission_in_quote: Decimal | None
    fx_rate: Decimal | None
    fx_symbol: str | None
    fx_timestamp: str | None
    status: str


class FeeNormalizer:
    def __init__(self, price_provider: PriceProvider | None = None):
        self.price_provider = price_provider or NullPriceProvider()

    def normalize(
        self,
        symbol: str,
        execution_price: Decimal,
        commission: Decimal,
        commission_asset: str,
        executed_at: str,
    ) -> FeeNormalizationResult:
        if commission <= 0:
            return FeeNormalizationResult(
                commission_in_quote=Decimal("0"),
                fx_rate=Decimal("0"),
                fx_symbol=None,
                fx_timestamp=executed_at,
                status="zero_fee",
            )

        base_asset, quote_asset = self._split_symbol(symbol)
        asset = (commission_asset or "").upper()

        if asset == quote_asset:
            return FeeNormalizationResult(
                commission_in_quote=commission,
                fx_rate=Decimal("1"),
                fx_symbol=quote_asset,
                fx_timestamp=executed_at,
                status="direct_quote",
            )

        if asset == base_asset:
            return FeeNormalizationResult(
                commission_in_quote=commission * execution_price,
                fx_rate=execution_price,
                fx_symbol=symbol,
                fx_timestamp=executed_at,
                status="base_via_execution_price",
            )

        direct_symbol = f"{asset}{quote_asset}"
        direct_rate = self.price_provider.get_price(direct_symbol, at_iso=executed_at)
        if direct_rate is not None and direct_rate > 0:
            return FeeNormalizationResult(
                commission_in_quote=commission * direct_rate,
                fx_rate=direct_rate,
                fx_symbol=direct_symbol,
                fx_timestamp=executed_at,
                status="external_direct",
            )

        inverse_symbol = f"{quote_asset}{asset}"
        inverse_rate = self.price_provider.get_price(inverse_symbol, at_iso=executed_at)
        if inverse_rate is not None and inverse_rate > 0:
            return FeeNormalizationResult(
                commission_in_quote=commission / inverse_rate,
                fx_rate=inverse_rate,
                fx_symbol=inverse_symbol,
                fx_timestamp=executed_at,
                status="external_inverse",
            )

        return FeeNormalizationResult(
            commission_in_quote=None,
            fx_rate=None,
            fx_symbol=None,
            fx_timestamp=None,
            status="unresolved_external_asset",
        )

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        upper_symbol = symbol.upper()
        for quote_asset in COMMON_QUOTE_ASSETS:
            if upper_symbol.endswith(quote_asset) and len(upper_symbol) > len(quote_asset):
                base_asset = upper_symbol[: -len(quote_asset)]
                return base_asset, quote_asset
        raise ValueError(f"Unsupported symbol format for fee normalization: {symbol}")
