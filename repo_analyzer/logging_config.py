"""Structured logging configuration."""

import logging
import sys


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging with console handler.

    Returns the root logger for the package.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("repo_analyzer")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        fmt = logging.Formatter(
            "[%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    return logger
