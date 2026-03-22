from decimal import Decimal

import pytest

from src.analytics.execution_ledger import ExecutionLedger
from src.core.fee_normalizer import FeeNormalizer
from src.domain.execution import Execution
from src.engine.execution_service import ExecutionService
from src.engine.execution_store import ExecutionStore
from src.exchange.order_manager import OrderManager
from src.journal.execution_journal import ExecutionJournal


class InMemoryExecutionJournal(ExecutionJournal):
    def __init__(self):
        self.rows = []

    def record_execution(self, execution: Execution) -> None:
        self.rows.append(execution)


class FakeOrderManager:
    def __init__(self, pages=None):
        self.pages = pages or []
        self.calls = []

    def get_my_trades(
        self,
        symbol: str,
        limit: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        from_id: int | None = None,
        order_id: int | None = None,
    ) -> list[dict]:
        self.calls.append(
            {
                "symbol": symbol,
                "limit": limit,
                "start_time": start_time,
                "end_time": end_time,
                "from_id": from_id,
                "order_id": order_id,
            }
        )

        if not self.pages:
            return []

        return self.pages.pop(0)


def make_service(
    symbol: str = "BTCUSDT",
    account_name: str = "default",
    order_manager=None,
):
    return ExecutionService(
        symbol=symbol,
        account_name=account_name,
        order_manager=order_manager or FakeOrderManager(),
        execution_store=ExecutionStore(),
        execution_journal=InMemoryExecutionJournal(),
        ledger=ExecutionLedger(
            journal_path="data/test/execution_ledger_test.csv",
            snapshot_path="data/test/execution_ledger_snapshot_test.json",
            snapshot_every=0,
        ),
        fee_normalizer=FeeNormalizer(),
    )


def make_execution(
    *,
    exchange: str = "binance",
    account: str = "default",
    symbol: str = "BTCUSDT",
    trade_id: int = 1001,
    order_id: int = 2001,
    side: str = "BUY",
    price: str = "100",
    qty: str = "1",
    quote_qty: str = "100",
    commission: str = "0",
    commission_asset: str = "USDT",
    commission_in_quote: str | None = None,
    commission_fx_rate: str | None = None,
    commission_fx_symbol: str | None = None,
    commission_fx_timestamp: str | None = None,
    is_maker: bool = True,
    executed_at: str = "2026-03-18T17:12:25.199000+00:00",
    source: str = "stream",
) -> Execution:
    return Execution(
        exchange=exchange,
        account=account,
        symbol=symbol,
        trade_id=trade_id,
        order_id=order_id,
        client_order_id="",
        side=side,
        price=Decimal(price),
        qty=Decimal(qty),
        quote_qty=Decimal(quote_qty),
        commission=Decimal(commission),
        commission_asset=commission_asset,
        commission_in_quote=None if commission_in_quote is None else Decimal(commission_in_quote),
        commission_fx_rate=None if commission_fx_rate is None else Decimal(commission_fx_rate),
        commission_fx_symbol=commission_fx_symbol,
        commission_fx_timestamp=commission_fx_timestamp,
        is_maker=is_maker,
        executed_at=executed_at,
        source=source,
    )


def test_on_stream_execution_insert_applies_ledger_once(tmp_path):
    service = ExecutionService(
        symbol="BTCUSDT",
        account_name="default",
        order_manager=FakeOrderManager(),
        execution_store=ExecutionStore(),
        execution_journal=InMemoryExecutionJournal(),
        ledger=ExecutionLedger(
            journal_path=str(tmp_path / "execution_ledger.csv"),
            snapshot_path=str(tmp_path / "execution_ledger_snapshot.json"),
            snapshot_every=0,
        ),
        fee_normalizer=FeeNormalizer(),
    )

    execution = make_execution(
        trade_id=1,
        side="BUY",
        price="100",
        qty="2",
        quote_qty="200",
        commission_in_quote="0",
        source="stream",
    )

    result = service.on_stream_execution(execution)

    assert result.inserted is True
    assert result.updated is False
    assert service.get_position("BTCUSDT") == Decimal("2")
    assert service.get_avg_cost("BTCUSDT") == Decimal("100")
    assert service.get_realized_pnl("BTCUSDT") == Decimal("0")
    assert service.get_total_executions("BTCUSDT") == 1
    assert service.get_last_reconciled_trade_id("BTCUSDT") == 1

    journal = service.execution_journal
    assert len(journal.rows) == 1
    assert journal.rows[0].trade_id == 1


def test_duplicate_stream_execution_does_not_reapply_ledger(tmp_path):
    service = ExecutionService(
        symbol="BTCUSDT",
        account_name="default",
        order_manager=FakeOrderManager(),
        execution_store=ExecutionStore(),
        execution_journal=InMemoryExecutionJournal(),
        ledger=ExecutionLedger(
            journal_path=str(tmp_path / "execution_ledger.csv"),
            snapshot_path=str(tmp_path / "execution_ledger_snapshot.json"),
            snapshot_every=0,
        ),
        fee_normalizer=FeeNormalizer(),
    )

    execution = make_execution(
        trade_id=10,
        side="BUY",
        price="100",
        qty="1",
        quote_qty="100",
        commission_in_quote="0",
        source="stream",
    )

    first = service.on_stream_execution(execution)
    second = service.on_stream_execution(execution)

    assert first.inserted is True
    assert second.inserted is False
    assert second.updated is False

    assert service.get_position("BTCUSDT") == Decimal("1")
    assert service.get_avg_cost("BTCUSDT") == Decimal("100")
    assert service.get_total_executions("BTCUSDT") == 1

    journal = service.execution_journal
    assert len(journal.rows) == 1


def test_rest_enrichment_updates_store_but_does_not_duplicate_financial_application(tmp_path):
    service = ExecutionService(
        symbol="BTCUSDT",
        account_name="default",
        order_manager=FakeOrderManager(),
        execution_store=ExecutionStore(),
        execution_journal=InMemoryExecutionJournal(),
        ledger=ExecutionLedger(
            journal_path=str(tmp_path / "execution_ledger.csv"),
            snapshot_path=str(tmp_path / "execution_ledger_snapshot.json"),
            snapshot_every=0,
        ),
        fee_normalizer=FeeNormalizer(),
    )

    stream_execution = make_execution(
        trade_id=20,
        side="BUY",
        price="100",
        qty="1.5",
        quote_qty="150",
        commission="0",
        commission_asset="USDT",
        commission_in_quote=None,
        source="stream",
    )

    rest_execution = make_execution(
        trade_id=20,
        side="BUY",
        price="100",
        qty="1.5",
        quote_qty="150",
        commission="0.15",
        commission_asset="USDT",
        commission_in_quote="0.15",
        commission_fx_rate="1",
        commission_fx_symbol="USDT",
        commission_fx_timestamp="2026-03-18T17:12:25.199000+00:00",
        source="rest",
    )

    first = service.on_stream_execution(stream_execution)
    second = service.on_rest_execution(rest_execution)

    assert first.inserted is True
    assert second.inserted is False
    assert second.updated is True

    stored = service.execution_store.get("binance", "default", "BTCUSDT", 20)
    assert stored is not None
    assert stored.commission_in_quote == Decimal("0.15")
    assert stored.source == "rest"

    # El impacto financiero se aplica una sola vez.
    assert service.get_position("BTCUSDT") == Decimal("1.5")
    assert service.get_avg_cost("BTCUSDT") == Decimal("100")
    assert service.get_total_executions("BTCUSDT") == 1

    # Journal esperado: 1 fila por insert + 1 fila por enrichment actualizado.
    journal = service.execution_journal
    assert len(journal.rows) == 2
    assert journal.rows[-1].commission_in_quote == Decimal("0.15")


def test_reconcile_symbol_fetches_incrementally_from_last_trade_id(tmp_path):
    page_1 = [
        {
            "id": 101,
            "orderId": 5001,
            "price": "100",
            "qty": "1",
            "quoteQty": "100",
            "commission": "0",
            "commissionAsset": "USDT",
            "time": 1710781945199,
            "isBuyer": True,
            "isMaker": True,
            "clientOrderId": "",
        },
        {
            "id": 102,
            "orderId": 5002,
            "price": "110",
            "qty": "1",
            "quoteQty": "110",
            "commission": "0",
            "commissionAsset": "USDT",
            "time": 1710781945200,
            "isBuyer": False,
            "isMaker": True,
            "clientOrderId": "",
        },
    ]

    fake_order_manager = FakeOrderManager(pages=[page_1, []])

    service = ExecutionService(
        symbol="BTCUSDT",
        account_name="default",
        order_manager=fake_order_manager,
        execution_store=ExecutionStore(),
        execution_journal=InMemoryExecutionJournal(),
        ledger=ExecutionLedger(
            journal_path=str(tmp_path / "execution_ledger.csv"),
            snapshot_path=str(tmp_path / "execution_ledger_snapshot.json"),
            snapshot_every=0,
        ),
        fee_normalizer=FeeNormalizer(),
    )

    summary_1 = service.reconcile_symbol("BTCUSDT", limit=1000, max_pages=1)

    assert summary_1.fetched == 2
    assert summary_1.inserted == 2
    assert summary_1.updated == 0
    assert summary_1.duplicates == 0
    assert service.get_last_reconciled_trade_id("BTCUSDT") == 102

    # Segunda llamada: debe pedir desde 103
    fake_order_manager.pages = [[]]
    summary_2 = service.reconcile_symbol("BTCUSDT", limit=1000, max_pages=1)

    assert summary_2.fetched == 0
    assert fake_order_manager.calls[-1]["from_id"] == 103


def test_realized_pnl_updates_correctly_on_close(tmp_path):
    service = ExecutionService(
        symbol="BTCUSDT",
        account_name="default",
        order_manager=FakeOrderManager(),
        execution_store=ExecutionStore(),
        execution_journal=InMemoryExecutionJournal(),
        ledger=ExecutionLedger(
            journal_path=str(tmp_path / "execution_ledger.csv"),
            snapshot_path=str(tmp_path / "execution_ledger_snapshot.json"),
            snapshot_every=0,
        ),
        fee_normalizer=FeeNormalizer(),
    )

    buy = make_execution(
        trade_id=1,
        side="BUY",
        price="100",
        qty="1",
        quote_qty="100",
        commission_in_quote="0",
        source="stream",
    )
    sell = make_execution(
        trade_id=2,
        order_id=2002,
        side="SELL",
        price="110",
        qty="1",
        quote_qty="110",
        commission_in_quote="0",
        source="stream",
    )

    service.on_stream_execution(buy)
    service.on_stream_execution(sell)

    assert service.get_position("BTCUSDT") == Decimal("0")
    assert service.get_avg_cost("BTCUSDT") == Decimal("0")
    assert service.get_realized_pnl("BTCUSDT") == Decimal("10")
    assert service.get_total_executions("BTCUSDT") == 2


def test_symbol_mismatch_raises(tmp_path):
    service = ExecutionService(
        symbol="BTCUSDT",
        account_name="default",
        order_manager=FakeOrderManager(),
        execution_store=ExecutionStore(),
        execution_journal=InMemoryExecutionJournal(),
        ledger=ExecutionLedger(
            journal_path=str(tmp_path / "execution_ledger.csv"),
            snapshot_path=str(tmp_path / "execution_ledger_snapshot.json"),
            snapshot_every=0,
        ),
        fee_normalizer=FeeNormalizer(),
    )

    execution = make_execution(symbol="ETHUSDT")

    with pytest.raises(ValueError, match="ExecutionService is bound to symbol=BTCUSDT"):
        service.on_stream_execution(execution)

def test_reconcile_symbol_uses_start_time_only_before_cursor_exists(tmp_path):
    page_1 = [
        {
            "id": 201,
            "orderId": 7001,
            "price": "100",
            "qty": "1",
            "quoteQty": "100",
            "commission": "0",
            "commissionAsset": "USDT",
            "time": 1710781945199,
            "isBuyer": True,
            "isMaker": True,
            "clientOrderId": "",
        }
    ]

    fake_order_manager = FakeOrderManager(pages=[page_1, []])

    service = ExecutionService(
        symbol="BTCUSDT",
        account_name="default",
        order_manager=fake_order_manager,
        execution_store=ExecutionStore(),
        execution_journal=InMemoryExecutionJournal(),
        ledger=ExecutionLedger(
            journal_path=str(tmp_path / "execution_ledger.csv"),
            snapshot_path=str(tmp_path / "execution_ledger_snapshot.json"),
            snapshot_every=0,
        ),
        fee_normalizer=FeeNormalizer(),
    )

    summary_1 = service.reconcile_symbol(
        "BTCUSDT",
        start_time_ms=1234567890000,
        limit=1000,
        max_pages=1,
    )

    assert summary_1.fetched == 1
    assert summary_1.inserted == 1
    assert summary_1.used_start_time_ms == 1234567890000
    assert summary_1.used_from_id is None

    first_call = fake_order_manager.calls[0]
    assert first_call["start_time"] == 1234567890000
    assert first_call["from_id"] is None

    fake_order_manager.pages = [[]]

    summary_2 = service.reconcile_symbol(
        "BTCUSDT",
        start_time_ms=9999999999999,
        limit=1000,
        max_pages=1,
    )

    assert summary_2.fetched == 0
    assert summary_2.used_start_time_ms is None
    assert summary_2.used_from_id == 202

    second_call = fake_order_manager.calls[-1]
    assert second_call["start_time"] is None
    assert second_call["from_id"] == 202