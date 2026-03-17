from src.exchange.binance_client import create_binance_client
from src.exchange.market_data import MarketDataService
from src.core.logger import setup_logger


def main():
    logger = setup_logger("test_order_book")
    client = create_binance_client()
    market_data = MarketDataService(client)

    symbol = "BTCUSDT"
    best_bid_ask = market_data.get_best_bid_ask(symbol)

    logger.info("Best bid/ask for %s:", symbol)
    logger.info("Bid: %s | Ask: %s | Spread: %s",
                best_bid_ask["best_bid_price"],
                best_bid_ask["best_ask_price"],
                best_bid_ask["spread"])


if __name__ == "__main__":
    main()