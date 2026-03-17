class TradingBotError(Exception):
    """Base exception for trading bot."""


class InvalidOrderRequestError(TradingBotError):
    """Raised when the order request does not satisfy exchange constraints."""