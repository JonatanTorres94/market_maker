import sys 
import logging

from src.config.settings import get_settings
from src.engine.market_making_engine import MarketMakingEngine
from src.exchange.binance_client import create_binance_client


def main():
    settings = get_settings()
    client = create_binance_client()

    if len(settings.infrastructure.enabled_symbols) != 1:
        raise ValueError(
            "This runner currently supports exactly one enabled symbol. "
            "Multi-symbol runtime orchestration is not implemented yet."
        )

    symbol = settings.infrastructure.enabled_symbols[0]
    symbol_config = settings.symbol_configs[symbol]

    engine = MarketMakingEngine(
        client=client,
        infrastructure=settings.infrastructure,
        symbol_config=symbol_config,
    )
    try:
        engine.run()
    except KeyboardInterrupt:
        print("\n[INFO] Shutdown signal received (Ctrl+C). Cleaning up...")
        pass
    except Exception as e:
        logging.getLogger("market_making_engine").error(f"Fatal error: {e}")
        # Solo llamamos a shutdown si ocurrió un error distinto a Ctrl+C
        engine.shutdown()
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()