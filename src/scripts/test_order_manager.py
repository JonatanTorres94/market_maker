from decimal import Decimal

from src.core.logger import setup_logger
from src.domain.models import OrderRequest
from src.exchange.binance_client import create_binance_client
from src.exchange.exchange_info import ExchangeInfoService
from src.exchange.order_manager import OrderManager


def main():
    logger = setup_logger("test_order_manager")
    client = create_binance_client()

    exchange_info = ExchangeInfoService(client)
    order_manager = OrderManager(client)

    symbol = "BTCUSDT"
    filters = exchange_info.get_symbol_filters(symbol)

    order = OrderRequest(
        symbol=symbol,
        side="BUY",
        quantity=Decimal("0.001"),
        price=Decimal("50000"),
    )

    validated = order_manager.validate_order_request(order, filters)
    logger.info("Validated order: %s", validated)

    inventory = order_manager.get_inventory_state(symbol)
    logger.info("Inventory: %s", inventory)


if __name__ == "__main__":
    main()