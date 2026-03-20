from decimal import Decimal
from src.domain.execution import Execution
from src.domain.execution_ledger import ExecutionLedger

def test_multi_symbol_isolation():
    ledger = ExecutionLedger()

    e1 = make_execution(1, "BUY", "100", "1")
    e2 = make_execution(2, "BUY", "200", "1")

    e1.symbol = "BTCUSDT"
    e2.symbol = "ETHUSDT"

    ledger.apply(e1, Decimal("0"))
    ledger.apply(e2, Decimal("0"))

    btc = ledger.states[("binance", "test", "BTCUSDT")]
    eth = ledger.states[("binance", "test", "ETHUSDT")]

    assert btc.position == Decimal("1")
    assert eth.position == Decimal("1")