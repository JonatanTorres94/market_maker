from src.exchange.binance_client import create_binance_client
from src.exchange.market_data import MarketDataService
from src.core.logger import setup_logger


def main():
    logger = setup_logger("test_ticker")
    client = create_binance_client()
    market_data = MarketDataService(client)

    symbol = "BTCUSDT"
    ticker = market_data.get_symbol_ticker(symbol)

    logger.info("Ticker for %s: %s", symbol, ticker)


if __name__ == "__main__":
    main()