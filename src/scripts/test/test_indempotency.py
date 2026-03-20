from decimal import Decimal
from src.domain.execution import Execution
from src.domain.execution_ledger import ExecutionLedger

def test_idempotency():
    ledger = ExecutionLedger()

    e1 = make_execution(1, "BUY", "100", "1")

    ledger.apply(e1, Decimal("0"))
    ledger.apply(e1, Decimal("0"))  # repetir

    state = ledger.states[("binance", "test", "BTCUSDT")]

    assert state.position == Decimal("1")