import logging

def setup_logger(name: str = "trading_bot") -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Logger already configured

    logger.setLevel(logging.INFO)

    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)

    # Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(handler)

    return logger