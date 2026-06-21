import logging
import sys
from pythonjsonlogger import jsonlogger


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("paysentinel")
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


logger = configure_logging()
