from decimal import Decimal
from src.domain.execution import Execution
from src.domain.execution_ledger import ExecutionLedger


def make_execution(trade_id, side, price, qty):
    return Execution(
        exchange="binance",
        account="test",
        symbol="BTCUSDT",
        trade_id=trade_id,
        order_id=1,
        client_order_id="x",
        side=side,
        price=Decimal(price),
        qty=Decimal(qty),
        quote_qty=Decimal(price) * Decimal(qty),
        commission=Decimal("0"),
        commission_asset="USDT",
        commission_in_quote=Decimal("0"),
        commission_fx_rate=None,
        commission_fx_symbol=None,
        commission_fx_timestamp=None,
        is_maker=True,
        executed_at="2024-01-01T00:00:00",
        source="test"
    )


def run_scenario():
    ledger = ExecutionLedger()

    executions = [
        make_execution(1, "BUY", "100", "1"),
        make_execution(2, "SELL", "101", "2"),
        make_execution(3, "BUY", "99", "1"),
    ]

    for e in executions:
        ledger.apply(e, Decimal("0"))

    state = ledger.states[("binance", "test", "BTCUSDT")]

    return (
        state.position,
        state.avg_cost,
        state.realized_pnl
    )


def test_repeatability():
    results = []

    for _ in range(10000):
        results.append(run_scenario())

    first = results[0]

    for r in results:
        assert r == first, f"Inconsistent result: {r} != {first}"