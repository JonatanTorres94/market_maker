from decimal import Decimal

from src.core.fee_normalizer import FeeNormalizer


class FakePriceProvider:
    def __init__(self, prices: dict[str, Decimal | None]):
        self.prices = prices
        self.calls = []

    def get_price(self, symbol: str, at_iso: str | None = None):
        self.calls.append((symbol, at_iso))
        return self.prices.get(symbol)


def test_fee_in_quote_is_resolved_directly():
    normalizer = FeeNormalizer(price_provider=FakePriceProvider({}))

    result = normalizer.normalize(
        symbol="BTCUSDT",
        execution_price=Decimal("70000"),
        commission=Decimal("0.12"),
        commission_asset="USDT",
        executed_at="2026-03-22T16:10:20.519000+00:00",
    )

    assert result.commission_in_quote == Decimal("0.12")
    assert result.fx_rate == Decimal("1")
    assert result.status == "direct_quote"


def test_fee_in_base_uses_execution_price():
    normalizer = FeeNormalizer(price_provider=FakePriceProvider({}))

    result = normalizer.normalize(
        symbol="BTCUSDT",
        execution_price=Decimal("70000"),
        commission=Decimal("0.00001"),
        commission_asset="BTC",
        executed_at="2026-03-22T16:10:20.519000+00:00",
    )

    assert result.commission_in_quote == Decimal("0.7")
    assert result.fx_rate == Decimal("70000")
    assert result.status == "base_via_execution_price"


def test_fee_in_external_asset_uses_direct_symbol():
    provider = FakePriceProvider({"BNBUSDT": Decimal("600")})
    normalizer = FeeNormalizer(price_provider=provider)

    result = normalizer.normalize(
        symbol="BTCUSDT",
        execution_price=Decimal("70000"),
        commission=Decimal("0.001"),
        commission_asset="BNB",
        executed_at="2026-03-22T16:10:20.519000+00:00",
    )

    assert result.commission_in_quote == Decimal("0.600")
    assert result.fx_rate == Decimal("600")
    assert result.fx_symbol == "BNBUSDT"
    assert result.status == "external_direct"


def test_fee_in_external_asset_uses_inverse_symbol():
    provider = FakePriceProvider({"USDTBNB": Decimal("0.002")})
    normalizer = FeeNormalizer(price_provider=provider)

    result = normalizer.normalize(
        symbol="BTCUSDT",
        execution_price=Decimal("70000"),
        commission=Decimal("0.001"),
        commission_asset="BNB",
        executed_at="2026-03-22T16:10:20.519000+00:00",
    )

    assert result.commission_in_quote == Decimal("0.5")
    assert result.fx_rate == Decimal("0.002")
    assert result.fx_symbol == "USDTBNB"
    assert result.status == "external_inverse"


def test_fee_in_external_asset_returns_unresolved_when_no_price_exists():
    provider = FakePriceProvider({})
    normalizer = FeeNormalizer(price_provider=provider)

    result = normalizer.normalize(
        symbol="BTCUSDT",
        execution_price=Decimal("70000"),
        commission=Decimal("0.001"),
        commission_asset="BNB",
        executed_at="2026-03-22T16:10:20.519000+00:00",
    )

    assert result.commission_in_quote is None
    assert result.status == "unresolved_external_asset"