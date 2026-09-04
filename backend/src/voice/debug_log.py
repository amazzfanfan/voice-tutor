"""Readable per-turn logging for the voice tutoring pipeline."""

from __future__ import annotations

import logging
import os


_VOICE_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
_VOICE_LOG_PATH = os.path.join(_VOICE_LOG_DIR, "voice_debug.log")


def _build_logger() -> logging.Logger:
    os.makedirs(_VOICE_LOG_DIR, exist_ok=True)
    logger = logging.getLogger("voice_debug")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(_VOICE_LOG_PATH, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger


voice_logger = _build_logger()


def flow_log(stage: str, message: str, *, level: int = logging.INFO) -> None:
    """Write one consistently formatted pipeline-stage entry."""

    voice_logger.log(level, f"{stage:<9} | {message}")


def compact_log_text(text: str, limit: int = 180) -> str:
    """Keep user-visible snippets on one readable log line."""

    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 1, 0)].rstrip() + "…"
