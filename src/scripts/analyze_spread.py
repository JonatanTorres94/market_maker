import time
from collections import Counter
from decimal import Decimal

from src.core.logger import setup_logger
from src.exchange.binance_client import create_binance_client
from src.exchange.market_data import MarketDataService


def main():
    logger = setup_logger("analyze_spread")

    client = create_binance_client()
    market_data = MarketDataService(client)

    symbol = "BTCUSDT"
    iterations = 30
    sleep_seconds = 2

    spreads: list[Decimal] = []

    logger.info(
        "Starting spread analysis for %s | iterations=%s | sleep=%ss",
        symbol,
        iterations,
        sleep_seconds,
    )

    for i in range(iterations):
        best_bid_ask = market_data.get_best_bid_ask(symbol)
        spreads.append(best_bid_ask.spread)

        logger.info(
            "[%s/%s] bid=%s ask=%s spread=%s",
            i + 1,
            iterations,
            best_bid_ask.best_bid_price,
            best_bid_ask.best_ask_price,
            best_bid_ask.spread,
        )

        time.sleep(sleep_seconds)

    min_spread = min(spreads)
    max_spread = max(spreads)
    avg_spread = sum(spreads) / Decimal(len(spreads))
    spread_counts = Counter(spreads)

    logger.info("Spread analysis finished.")
    logger.info("Min spread: %s", min_spread)
    logger.info("Max spread: %s", max_spread)
    logger.info("Avg spread: %s", avg_spread)

    logger.info("Spread frequency distribution:")
    for spread_value, count in sorted(spread_counts.items()):
        logger.info("spread=%s -> %s times", spread_value, count)


if __name__ == "__main__":
    main()