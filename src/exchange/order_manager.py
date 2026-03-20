from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from typing import List, Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException

from src.core.exceptions import InvalidOrderRequestError
from src.domain.models import InventoryState, OrderRequest, OrderResult, SymbolFilters


class OrderManager:
    def __init__(self, client: Client):
        self.client = client

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _quantize(value: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            raise ValueError("Step must be > 0")

        units = (value / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
        return units * step

    def normalize_price(self, price: Decimal, filters: SymbolFilters) -> Decimal:
        return self._quantize(price, filters.tick_size)

    def normalize_quantity(self, quantity: Decimal, filters: SymbolFilters) -> Decimal:
        return self._quantize(quantity, filters.step_size)

    def validate_order_request(
        self,
        order: OrderRequest,
        filters: SymbolFilters,
    ) -> OrderRequest:
        normalized_price = self.normalize_price(order.price, filters)
        normalized_qty = self.normalize_quantity(order.quantity, filters)

        if normalized_qty < filters.min_qty:
            raise InvalidOrderRequestError(
                f"Quantity {normalized_qty} is below min_qty {filters.min_qty}"
            )

        notional = normalized_price * normalized_qty
        if filters.min_notional > 0 and notional < filters.min_notional:
            raise InvalidOrderRequestError(
                f"Notional {notional} is below min_notional {filters.min_notional}"
            )

        return OrderRequest(
            symbol=order.symbol,
            side=order.side,
            quantity=normalized_qty,
            price=normalized_price,
        )

    def place_limit_order(
        self,
        order: OrderRequest,
        filters: SymbolFilters,
    ) -> OrderResult:
        validated = self.validate_order_request(order, filters)

        response = self.client.create_order(
            symbol=validated.symbol,
            side=validated.side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=str(validated.quantity),
            price=str(validated.price),
        )

        transact_time_ms = response.get("transactTime")
        if transact_time_ms is not None:
            placed_at = datetime.fromtimestamp(transact_time_ms / 1000, tz=UTC).isoformat()
        else:
            placed_at = self._utc_now_iso()

        return OrderResult(
            symbol=response["symbol"],
            order_id=response["orderId"],
            client_order_id=response["clientOrderId"],
            side=response["side"],
            status=response["status"],
            price=Decimal(response["price"]),
            orig_qty=Decimal(response["origQty"]),
            executed_qty=Decimal(response["executedQty"]),
            placed_at=placed_at,
        )

    def cancel_order(self, symbol: str, order_id: int) -> Optional[dict]:
        try:
            return self.client.cancel_order(symbol=symbol, orderId=order_id)
        except BinanceAPIException as exc:
            if exc.code == -2011:
                return None
            raise

    def get_open_orders(self, symbol: str) -> List[dict]:
        return self.client.get_open_orders(symbol=symbol)

    def cancel_all_open_orders(self, symbol: str) -> List[dict]:
        open_orders = self.get_open_orders(symbol)
        canceled = []

        for order in open_orders:
            result = self.cancel_order(symbol=symbol, order_id=order["orderId"])
            if result is not None:
                canceled.append(result)

        return canceled

    def get_inventory_state(self, symbol: str) -> InventoryState:
        account = self.client.get_account()

        base_asset = symbol[:-4] if symbol.endswith("USDT") else symbol
        quote_asset = "USDT" if symbol.endswith("USDT") else ""

        balances = {item["asset"]: item for item in account["balances"]}

        base_balance = balances.get(base_asset, {"free": "0", "locked": "0"})
        quote_balance = balances.get(quote_asset, {"free": "0", "locked": "0"})

        return InventoryState(
            base_asset=base_asset,
            quote_asset=quote_asset,
            base_free=Decimal(base_balance["free"]),
            base_locked=Decimal(base_balance.get("locked", "0")),
            quote_free=Decimal(quote_balance["free"]),
            quote_locked=Decimal(quote_balance.get("locked", "0")),
        )

    def get_order(self, symbol: str, order_id: int) -> dict:
        return self.client.get_order(symbol=symbol, orderId=order_id)

    def get_all_orders(
        self,
        symbol: str,
        limit: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        order_id: int | None = None,
    ) -> list[dict]:
        params = {"symbol": symbol}

        if limit is not None:
            params["limit"] = limit
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        if order_id is not None:
            params["orderId"] = order_id

        return self.client.get_all_orders(**params)


    def get_my_trades(
        self,
        symbol: str,
        limit: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        from_id: int | None = None,
        order_id: int | None = None,
    ) -> list[dict]:
        params = {"symbol": symbol}

        if limit is not None:
            params["limit"] = limit
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        if from_id is not None:
            params["fromId"] = from_id
        if order_id is not None:
            params["orderId"] = order_id

        return self.client.get_my_trades(**params)

    def get_order_safe(self, symbol: str, order_id: int) -> dict | None:
        try:
            return self.get_order(symbol=symbol, order_id=order_id)
        except BinanceAPIException as exc:
            if exc.code in {-2013, -2011}:
                return None
            raise