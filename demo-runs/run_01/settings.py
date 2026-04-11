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
# Репозиторий GitHub для POST /v0/agents (должен быть доступен ключу Cloud Agents).
CURSOR_CLOUD_AGENT_REPOSITORY: str = (os.getenv("CURSOR_CLOUD_AGENT_REPOSITORY") or "").strip()
CURSOR_CLOUD_AGENT_REF: str = (os.getenv("CURSOR_CLOUD_AGENT_REF") or "").strip()


def _float_env_fallback(name: str, fallback: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


# Опрос Cloud Agent при объяснении позиции (отдельно от быстрого CURSOR_CLOUD_TIMEOUT_SEC для /v0/me).
CURSOR_CLOUD_EXPLAIN_MAX_WAIT_SEC: float = max(
    1.0, _float_env_fallback("CURSOR_CLOUD_EXPLAIN_MAX_WAIT_SEC", CURSOR_CLOUD_TIMEOUT_SEC)
)
CURSOR_CLOUD_EXPLAIN_POLL_SEC: float = max(
    0.5, min(60.0, _float_env_fallback("CURSOR_CLOUD_EXPLAIN_POLL_SEC", 2.0))
)
CURSOR_CLOUD_EXPLAIN_HTTP_TIMEOUT_SEC: float = max(
    30.0,
    _float_env_fallback(
        "CURSOR_CLOUD_EXPLAIN_HTTP_TIMEOUT_SEC", max(120.0, CURSOR_CLOUD_TIMEOUT_SEC)
    ),
)
