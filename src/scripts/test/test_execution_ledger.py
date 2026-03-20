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


def run():
    ledger = ExecutionLedger()

    # BUY 1 @ 100
    e1 = make_execution(1, "BUY", "100", "1")
    ledger.apply(e1, Decimal("0"))

    # SELL 2 @ 101 (crossing)
    e2 = make_execution(2, "SELL", "101", "2")
    ledger.apply(e2, Decimal("0"))

    # BUY 1 @ 99
    e3 = make_execution(3, "BUY", "99", "1")
    ledger.apply(e3, Decimal("0"))

    state = ledger.states[("binance", "test", "BTCUSDT")]

    print("Position:", state.position)
    print("Avg Cost:", state.avg_cost)
    print("Realized PnL:", state.realized_pnl)


if __name__ == "__main__":
    run()