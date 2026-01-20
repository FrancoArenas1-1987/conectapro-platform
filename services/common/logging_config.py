import logging
import os
import sys
from typing import Optional


def setup_logging(name: str, level: Optional[str] = None) -> logging.Logger:
    """Create (or reuse) a logger that always logs to stdout.

    LOG_LEVEL env var controls default. Examples: DEBUG, INFO, WARNING.
    """
    lvl = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric = getattr(logging, lvl, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(numeric)

    # Avoid duplicate handlers when re-imported
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        h = logging.StreamHandler(sys.stdout)
        h.setLevel(numeric)
        fmt = os.getenv(
            "LOG_FORMAT",
            "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s"
        )
        h.setFormatter(logging.Formatter(fmt))
        logger.addHandler(h)

    # Make sure uvicorn loggers also show up
    for uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(uv_name)
        uv.setLevel(numeric)
        if not any(isinstance(h, logging.StreamHandler) for h in uv.handlers):
            h = logging.StreamHandler(sys.stdout)
            h.setLevel(numeric)
            fmt = os.getenv(
                "LOG_FORMAT",
                "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s"
            )
            h.setFormatter(logging.Formatter(fmt))
            uv.addHandler(h)

    logger.propagate = False
    return logger
