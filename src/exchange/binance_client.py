from binance.client import Client
from src.config.settings import get_settings


def create_binance_client() -> Client:
    settings = get_settings()

    return Client(
            api_key=settings.infrastructure.binance_api_key,
            api_secret=settings.infrastructure.binance_secret,
            testnet=settings.infrastructure.binance_testnet
        )