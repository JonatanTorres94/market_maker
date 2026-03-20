#src/engine/execution_store.py
from collections import defaultdict
from dataclasses import dataclass

from src.domain.execution import Execution


@dataclass(frozen=True)
class ExecutionUpsertResult:
    inserted: bool
    updated: bool
    changed_fields: tuple[str, ...]


class ExecutionStore:
    def __init__(self):
        self._by_key: dict[tuple[str, str, str, int], Execution] = {}
        self._keys_by_order: dict[tuple[str, int], set[tuple[str, str, str, int]]] = defaultdict(set)

    def upsert(self, execution: Execution) -> ExecutionUpsertResult:
        key = execution.unique_key
        existing = self._by_key.get(key)

        if existing is None:
            self._by_key[key] = execution
            self._keys_by_order[(execution.symbol, execution.order_id)].add(key)
            return ExecutionUpsertResult(
                inserted=True,
                updated=False,
                changed_fields=(),
            )

        merged, changed_fields = self._merge_execution(existing, execution)

        if not changed_fields:
            return ExecutionUpsertResult(
                inserted=False,
                updated=False,
                changed_fields=(),
            )

        self._by_key[key] = merged
        return ExecutionUpsertResult(
            inserted=False,
            updated=True,
            changed_fields=tuple(changed_fields),
        )

    def _merge_execution(self, existing: Execution, incoming: Execution) -> tuple[Execution, list[str]]:
        changed_fields: list[str] = []

        commission_in_quote = existing.commission_in_quote
        if commission_in_quote is None and incoming.commission_in_quote is not None:
            commission_in_quote = incoming.commission_in_quote
            changed_fields.append("commission_in_quote")

        commission_fx_rate = existing.commission_fx_rate
        if commission_fx_rate is None and incoming.commission_fx_rate is not None:
            commission_fx_rate = incoming.commission_fx_rate
            changed_fields.append("commission_fx_rate")

        commission_fx_symbol = existing.commission_fx_symbol
        if commission_fx_symbol is None and incoming.commission_fx_symbol is not None:
            commission_fx_symbol = incoming.commission_fx_symbol
            changed_fields.append("commission_fx_symbol")

        commission_fx_timestamp = existing.commission_fx_timestamp
        if commission_fx_timestamp is None and incoming.commission_fx_timestamp is not None:
            commission_fx_timestamp = incoming.commission_fx_timestamp
            changed_fields.append("commission_fx_timestamp")

        source = existing.source
        if existing.source != "rest" and incoming.source == "rest":
            source = incoming.source
            changed_fields.append("source")

        if not changed_fields:
            return existing, changed_fields

        merged = Execution(
            exchange=existing.exchange,
            account=existing.account,
            symbol=existing.symbol,
            trade_id=existing.trade_id,
            order_id=existing.order_id,
            client_order_id=existing.client_order_id,
            side=existing.side,
            price=existing.price,
            qty=existing.qty,
            quote_qty=existing.quote_qty,
            commission=existing.commission,
            commission_asset=existing.commission_asset,
            commission_in_quote=commission_in_quote,
            commission_fx_rate=commission_fx_rate,
            commission_fx_symbol=commission_fx_symbol,
            commission_fx_timestamp=commission_fx_timestamp,
            is_maker=existing.is_maker,
            executed_at=existing.executed_at,
            source=source,
        )
        return merged, changed_fields

    def get(self, exchange: str, account: str, symbol: str, trade_id: int) -> Execution | None:
        return self._by_key.get((exchange, account, symbol, trade_id))

    def list_by_symbol(self, symbol: str) -> list[Execution]:
        return [execution for execution in self._by_key.values() if execution.symbol == symbol]

    def list_by_order(self, symbol: str, order_id: int) -> list[Execution]:
        keys = self._keys_by_order.get((symbol, order_id), set())
        return [self._by_key[key] for key in sorted(keys, key=lambda item: item[3])]

    def total_count(self) -> int:
        return len(self._by_key)