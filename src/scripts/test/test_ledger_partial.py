from decimal import Decimal
from src.domain.execution import Execution
from src.domain.execution_ledger import ExecutionLedger

def test_partial_close():
    ledger = ExecutionLedger()

    e1 = make_execution(1, "BUY", "100", "2")
    e2 = make_execution(2, "SELL", "101", "1")

    ledger.apply(e1, Decimal("0"))
    ledger.apply(e2, Decimal("0"))

    state = ledger.states[("binance", "test", "BTCUSDT")]

    assert state.position == Decimal("1")
    assert state.avg_cost == Decimal("100")
    assert state.realized_pnl == Decimal("1")