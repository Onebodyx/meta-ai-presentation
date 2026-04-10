"""Узкий слой Cursor Cloud (Cloud Agents API): настройки, HTTP-клиент, проверка ключа.

Документация: https://cursor.com/docs/cloud-agent/api/endpoints
Аутентификация: HTTP Basic, имя пользователя — API key, пароль пустой.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

import settings

CURSOR_CLOUD_DEFAULT_BASE_URL = "https://api.cursor.com"


def basic_auth_header(api_key: str) -> str:
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    return f"Basic {token}"


def normalize_model(raw: str | None) -> str | None:
    """None / пусто / default (без учёта регистра) — не передавать поле model в JSON."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if s.lower() == "default":
        return None
    return s


def effective_base_url(raw_from_env: str) -> str:
    u = (raw_from_env or "").strip().rstrip("/")
    return u if u else CURSOR_CLOUD_DEFAULT_BASE_URL


@dataclass(frozen=True)
class CursorCloudConfig:
    api_key: str
    base_url: str
    model_raw: str
    timeout_sec: float

    @classmethod
    def from_settings(cls) -> CursorCloudConfig:
        return cls(
            api_key=settings.CURSOR_CLOUD_AGENTS_API_KEY,
            base_url=effective_base_url(settings.CURSOR_CLOUD_BASE_URL),
            model_raw=settings.CURSOR_CLOUD_MODEL,
            timeout_sec=settings.CURSOR_CLOUD_TIMEOUT_SEC,
        )


@dataclass(frozen=True)
class VerifyOk:
    api_key_name: str
    user_email: str
    created_at: str


@dataclass(frozen=True)
class VerifyErr:
    message: str


def build_agent_request_body(
    *,
    prompt_text: str,
    repository_url: str,
    ref: str | None = None,
    model_raw: str | None = None,
) -> dict[str, Any]:
    """Заготовка тела POST /v0/agents; ключ model добавляется только при явном ID модели."""
    source: dict[str, Any] = {"repository": repository_url}
    if ref:
        source["ref"] = ref
    body: dict[str, Any] = {"prompt": {"text": prompt_text}, "source": source}
    m = normalize_model(model_raw)
    if m:
        body["model"] = m
    return body


class CursorCloudClient:
    def __init__(self, config: CursorCloudConfig | None = None) -> None:
        self._config = config or CursorCloudConfig.from_settings()

    def verify_credentials(self) -> VerifyOk | VerifyErr:
        if not self._config.api_key.strip():
            return VerifyErr(
                "Не задан CURSOR_CLOUD_AGENTS_API_KEY в `.env`. "
                "Создайте ключ: Cursor Dashboard → Cloud Agents → My Settings → API keys."
            )
        url = f"{self._config.base_url}/v0/me"
        try:
            with httpx.Client(timeout=self._config.timeout_sec) as client:
                r = client.get(url, headers={"Authorization": basic_auth_header(self._config.api_key)})
        except httpx.TimeoutException:
            return VerifyErr(
                f"Таймаут запроса ({self._config.timeout_sec} с) к {url}. "
                "Проверьте сеть и при необходимости увеличьте CURSOR_CLOUD_TIMEOUT_SEC."
            )
        except httpx.RequestError as e:
            return VerifyErr(f"Сетевая ошибка при обращении к Cursor Cloud ({url}): {e}")
        if r.status_code == 401:
            return VerifyErr("HTTP 401: неверный, отозванный или неподходящий CURSOR_CLOUD_AGENTS_API_KEY.")
        if r.status_code != 200:
            snippet = (r.text or "")[:500]
            extra = f" Тело ответа: {snippet}" if snippet else ""
            return VerifyErr(f"HTTP {r.status_code} от Cursor Cloud при GET /v0/me.{extra}")
        try:
            data = r.json()
        except ValueError:
            return VerifyErr(
                "Ответ `/v0/me` не удалось разобрать как JSON. "
                "Проверьте CURSOR_CLOUD_BASE_URL (ожидается API Cursor Cloud)."
            )
        return VerifyOk(
            api_key_name=str(data.get("apiKeyName", "")),
            user_email=str(data.get("userEmail", "")),
            created_at=str(data.get("createdAt", "")),
        )


def main() -> None:
    result = CursorCloudClient().verify_credentials()
    if isinstance(result, VerifyErr):
        print(result.message)
        raise SystemExit(1)
    print("Подключение к Cursor Cloud: OK")
    print(f"  Имя ключа: {result.api_key_name}")
    print(f"  Email: {result.user_email}")


if __name__ == "__main__":
    main()
