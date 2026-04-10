"""Загрузка локальной конфигурации из `.env` в корне проекта."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

STOCKFISH_PATH: str = (os.getenv("STOCKFISH_PATH") or "").strip()


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


STOCKFISH_DEPTH: int = max(1, min(64, _int_env("STOCKFISH_DEPTH", 16)))
STOCKFISH_MOVETIME_MS: int = max(0, _int_env("STOCKFISH_MOVETIME_MS", 0))


def _float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


CURSOR_CLOUD_AGENTS_API_KEY: str = (os.getenv("CURSOR_CLOUD_AGENTS_API_KEY") or "").strip()
CURSOR_CLOUD_BASE_URL: str = (os.getenv("CURSOR_CLOUD_BASE_URL") or "").strip().rstrip("/")
CURSOR_CLOUD_MODEL: str = (os.getenv("CURSOR_CLOUD_MODEL") or "").strip()
CURSOR_CLOUD_TIMEOUT_SEC: float = _float_env("CURSOR_CLOUD_TIMEOUT_SEC", 30.0)
