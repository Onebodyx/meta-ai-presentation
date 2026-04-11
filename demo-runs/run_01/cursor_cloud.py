"""Узкий слой Cursor Cloud (Cloud Agents API): настройки, HTTP-клиент, проверка ключа.

Документация: https://cursor.com/docs/cloud-agent/api/endpoints
Аутентификация: HTTP Basic, имя пользователя — API key, пароль пустой.
"""

from __future__ import annotations

import base64
import json
import sys
import time
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
    explain_max_wait_sec: float
    explain_poll_sec: float
    explain_http_timeout_sec: float

    @classmethod
    def from_settings(cls) -> CursorCloudConfig:
        return cls(
            api_key=settings.CURSOR_CLOUD_AGENTS_API_KEY,
            base_url=effective_base_url(settings.CURSOR_CLOUD_BASE_URL),
            model_raw=settings.CURSOR_CLOUD_MODEL,
            timeout_sec=settings.CURSOR_CLOUD_TIMEOUT_SEC,
            explain_max_wait_sec=settings.CURSOR_CLOUD_EXPLAIN_MAX_WAIT_SEC,
            explain_poll_sec=settings.CURSOR_CLOUD_EXPLAIN_POLL_SEC,
            explain_http_timeout_sec=settings.CURSOR_CLOUD_EXPLAIN_HTTP_TIMEOUT_SEC,
        )


@dataclass(frozen=True)
class VerifyOk:
    api_key_name: str
    user_email: str
    created_at: str


@dataclass(frozen=True)
class VerifyErr:
    message: str


@dataclass(frozen=True)
class AgentRunErr:
    message: str


# Статусы агента Cursor Cloud (верхний регистр для сравнения).
_AGENT_STATUS_FAILURE = frozenset({"FAILED", "ERROR", "CANCELLED", "STOPPED"})
_AGENT_STATUS_SUCCESS = frozenset({"FINISHED", "COMPLETED", "DONE", "SUCCESS", "SUCCEEDED"})
_AGENT_STATUS_RUNNING = frozenset(
    {"CREATING", "RUNNING", "PENDING", "QUEUED", "IN_PROGRESS", "WORKING", "ACTIVE"}
)


def build_agent_request_body(
    *,
    prompt_text: str,
    repository_url: str,
    ref: str | None = None,
    model_raw: str | None = None,
    auto_create_pr: bool = False,
) -> dict[str, Any]:
    """Заготовка тела POST /v0/agents; ключ model добавляется только при явном ID модели."""
    source: dict[str, Any] = {"repository": repository_url}
    if ref:
        source["ref"] = ref
    body: dict[str, Any] = {
        "prompt": {"text": prompt_text},
        "source": source,
        "target": {"autoCreatePr": auto_create_pr},
    }
    m = normalize_model(model_raw)
    if m:
        body["model"] = m
    return body


def _normalize_agent_status(raw: Any) -> str:
    return str(raw or "").strip().upper()


_SKIP_CONV_ROLES = frozenset(
    {"user", "human", "system", "tool", "function", "developer", "client"}
)
_ASSISTANT_ROLES = frozenset(
    {"assistant", "agent", "model", "ai", "bot", "narrator", "cursor"}
)


def _conversation_message_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    root_content = data.get("content")
    if isinstance(root_content, list):
        return root_content
    for key in ("messages", "conversation", "data", "items", "history"):
        v = data.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            inner = v.get("messages")
            if isinstance(inner, list):
                return inner
    return []


def _message_role_lower(m: dict) -> str:
    r = (
        m.get("role")
        or m.get("author")
        or m.get("sender")
        or m.get("from")
        or m.get("type")
        or m.get("kind")
        or ""
    )
    return str(r).strip().lower()


def _is_assistant_message(m: dict) -> bool:
    r = _message_role_lower(m)
    if not r:
        return False
    if r in _SKIP_CONV_ROLES:
        return False
    if r in _ASSISTANT_ROLES:
        return True
    if "assistant" in r or r.endswith("_assistant"):
        return True
    if r in ("message", "item", "entry"):  # часто вложенный тип, не роль
        return False
    return False


def _text_from_content(c: Any) -> str | None:
    if c is None:
        return None
    if isinstance(c, str) and c.strip():
        return c.strip()
    if isinstance(c, dict):
        if isinstance(c.get("text"), str) and c["text"].strip():
            return c["text"].strip()
        if c.get("type") == "text" and isinstance(c.get("text"), str):
            return c["text"].strip()
        if isinstance(c.get("content"), str) and c["content"].strip():
            return c["content"].strip()
        nested = c.get("content") or c.get("body") or c.get("value")
        if nested is not None and nested is not c:
            t = _text_from_content(nested)
            if t:
                return t
        return None
    if isinstance(c, list):
        parts: list[str] = []
        for part in c:
            t = _text_from_content(part)
            if t:
                parts.append(t)
        return "\n".join(parts).strip() or None
    return None


def _extract_text_from_message_dict(m: dict) -> str | None:
    parts = m.get("parts")
    if isinstance(parts, list):
        acc: list[str] = []
        for p in parts:
            if isinstance(p, str) and p.strip():
                acc.append(p.strip())
            elif isinstance(p, dict):
                t = _text_from_content(p)
                if t:
                    acc.append(t)
        joined = "\n".join(acc).strip()
        if joined:
            return joined

    for key in ("text", "body", "markdown", "value", "output", "result", "answer", "summary"):
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    c = m.get("content")
    if c is None:
        c = m.get("message") or m.get("payload") or m.get("data")
    txt = _text_from_content(c)
    if txt:
        return txt
    for key in ("message", "delta", "assistantMessage", "response"):
        nested = m.get(key)
        if isinstance(nested, dict):
            t = _extract_text_from_message_dict(nested)
            if t:
                return t
    return None


def _last_assistant_text_from_conversation(data: Any) -> str | None:
    messages = _conversation_message_list(data)
    if not messages:
        return None

    last_strict: str | None = None
    for m in messages:
        if not isinstance(m, dict):
            continue
        if not _is_assistant_message(m):
            continue
        txt = _extract_text_from_message_dict(m)
        if txt:
            last_strict = txt

    if last_strict:
        return last_strict

    # Fallback: последнее сообщение не от пользователя/системы с извлекаемым текстом (разные схемы API).
    for m in reversed(messages):
        if not isinstance(m, dict):
            continue
        r = _message_role_lower(m)
        if r in _SKIP_CONV_ROLES:
            continue
        txt = _extract_text_from_message_dict(m)
        if txt:
            return txt

    return None


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

    def list_models(self) -> Any | VerifyErr:
        """GET /v0/models — список доступных облачных моделей для Cloud Agents API."""
        if not self._config.api_key.strip():
            return VerifyErr(
                "Не задан CURSOR_CLOUD_AGENTS_API_KEY в `.env`. "
                "Создайте ключ: Cursor Dashboard → Cloud Agents → My Settings → API keys."
            )
        url = f"{self._config.base_url}/v0/models"
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
            snippet = (r.text or "")[:800]
            extra = f" Тело ответа: {snippet}" if snippet else ""
            return VerifyErr(f"HTTP {r.status_code} от Cursor Cloud при GET /v0/models.{extra}")
        try:
            return r.json()
        except ValueError:
            return VerifyErr("Ответ GET /v0/models не удалось разобрать как JSON.")

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        timeout_display_sec: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response | AgentRunErr:
        td = self._config.timeout_sec if timeout_display_sec is None else timeout_display_sec
        try:
            return client.request(
                method,
                url,
                headers={"Authorization": basic_auth_header(self._config.api_key)},
                **kwargs,
            )
        except httpx.TimeoutException:
            return AgentRunErr(
                f"Таймаут HTTP ({td:g} с) при обращении к {url}. "
                "Увеличьте CURSOR_CLOUD_EXPLAIN_HTTP_TIMEOUT_SEC или CURSOR_CLOUD_TIMEOUT_SEC."
            )
        except httpx.RequestError as e:
            return AgentRunErr(f"Сетевая ошибка ({url}): {e}")

    def run_prompt_and_collect_reply(
        self,
        prompt_text: str,
        *,
        repository_url: str,
        ref: str | None = None,
    ) -> str | AgentRunErr:
        """POST /v0/agents, ожидание завершения, GET /v0/agents/{{id}}/conversation — текст ответа."""
        if not self._config.api_key.strip():
            return AgentRunErr(
                "Не задан CURSOR_CLOUD_AGENTS_API_KEY в `.env` — объяснение через Cursor Cloud недоступно."
            )
        repo = (repository_url or "").strip()
        if not repo:
            return AgentRunErr(
                "Не задан CURSOR_CLOUD_AGENT_REPOSITORY — для запуска агента нужен URL репозитория GitHub."
            )

        body = build_agent_request_body(
            prompt_text=prompt_text,
            repository_url=repo,
            ref=(ref or "").strip() or None,
            model_raw=self._config.model_raw,
            auto_create_pr=False,
        )
        url_launch = f"{self._config.base_url}/v0/agents"
        per_req_timeout = httpx.Timeout(self._config.explain_http_timeout_sec)
        http_td = self._config.explain_http_timeout_sec
        poll = self._config.explain_poll_sec
        max_wait = self._config.explain_max_wait_sec

        with httpx.Client(timeout=per_req_timeout) as client:
            post = self._request(
                client, "POST", url_launch, json=body, timeout_display_sec=http_td
            )
            if isinstance(post, AgentRunErr):
                return post
            if post.status_code not in (200, 201):
                snippet = (post.text or "")[:500]
                extra = f" Тело: {snippet}" if snippet else ""
                return AgentRunErr(f"HTTP {post.status_code} при POST /v0/agents.{extra}")
            try:
                launch_data = post.json()
            except ValueError:
                return AgentRunErr("Ответ POST /v0/agents не является JSON.")
            raw_id = launch_data.get("id")
            agent_id = str(raw_id).strip() if raw_id is not None else ""
            if not agent_id:
                return AgentRunErr("В ответе POST /v0/agents нет поля id.")

            deadline = time.monotonic() + max_wait
            status_upper = ""
            while time.monotonic() < deadline:
                url_status = f"{self._config.base_url}/v0/agents/{agent_id}"
                st = self._request(client, "GET", url_status, timeout_display_sec=http_td)
                if isinstance(st, AgentRunErr):
                    return st
                if st.status_code != 200:
                    snippet = (st.text or "")[:400]
                    return AgentRunErr(f"HTTP {st.status_code} при GET агента.{snippet}")
                try:
                    agent_doc = st.json()
                except ValueError:
                    return AgentRunErr("Ответ GET /v0/agents/{{id}} не является JSON.")
                status_upper = _normalize_agent_status(agent_doc.get("status"))
                if status_upper in _AGENT_STATUS_FAILURE:
                    return AgentRunErr(f"Агент Cursor Cloud завершился со статусом «{status_upper}».")
                if status_upper in _AGENT_STATUS_SUCCESS:
                    break
                if status_upper in _AGENT_STATUS_RUNNING or not status_upper:
                    time.sleep(poll)
                    continue
                # неизвестный статус — продолжаем опрос
                time.sleep(poll)
            else:
                return AgentRunErr(
                    f"Таймаут ({max_wait:g} с) ожидания готовности агента Cursor Cloud "
                    f"(CURSOR_CLOUD_EXPLAIN_MAX_WAIT_SEC)."
                )

            url_conv = f"{self._config.base_url}/v0/agents/{agent_id}/conversation"
            text: str | None = None
            conv_data: Any = None
            for conv_try in range(4):
                conv = self._request(client, "GET", url_conv, timeout_display_sec=http_td)
                if isinstance(conv, AgentRunErr):
                    return conv
                if conv.status_code != 200:
                    snippet = (conv.text or "")[:500]
                    return AgentRunErr(f"HTTP {conv.status_code} при GET conversation.{snippet}")
                try:
                    conv_data = conv.json()
                except ValueError:
                    return AgentRunErr("Ответ conversation не является JSON.")
                text = _last_assistant_text_from_conversation(conv_data)
                if text:
                    break
                if conv_try < 3:
                    time.sleep(min(poll, 3.0))

            if not text:
                hint = ""
                if isinstance(conv_data, dict):
                    keys = list(conv_data.keys())[:12]
                    if keys:
                        hint = f" Ключи корня ответа: {keys}."
                return AgentRunErr(
                    "В ответе агента не найдено текста ассистента — попробуйте позже или проверьте настройки."
                    + hint
                )
            return text


def main() -> None:
    result = CursorCloudClient().verify_credentials()
    if isinstance(result, VerifyErr):
        print(result.message)
        raise SystemExit(1)
    print("Подключение к Cursor Cloud: OK")
    print(f"  Имя ключа: {result.api_key_name}")
    print(f"  Email: {result.user_email}")


def _main_models() -> None:
    raw = CursorCloudClient().list_models()
    if isinstance(raw, VerifyErr):
        print(raw.message)
        raise SystemExit(1)
    print(json.dumps(raw, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "models":
        _main_models()
    else:
        main()
