from src.exchange.binance_client import create_binance_client
from src.exchange.exchange_info import ExchangeInfoService
from src.core.logger import setup_logger


def main():
    logger = setup_logger("test_exchange_filters")
    client = create_binance_client()
    exchange_info = ExchangeInfoService(client)

    symbol = "BTCUSDT"
    filters = exchange_info.get_symbol_filters(symbol)

    logger.info(
        "Filters for %s | tick_size=%s | step_size=%s | min_qty=%s | min_notional=%s",
        symbol,
        filters.tick_size,
        filters.step_size,
        filters.min_qty,
        filters.min_notional,
    )


if __name__ == "__main__":
    main()