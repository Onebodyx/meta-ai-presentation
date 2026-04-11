"""Узкая подготовка данных и текста промпта для объяснения вариантов через LLM (без HTTP)."""

from __future__ import annotations

import json
from typing import Any

# Сколько полуходов SAN из расчёта передаём в модель (без полного JSON анализа).
_MAX_CONTINUATION_PLIES = 8


def can_request_explanation(analysis: dict | None) -> bool:
    if not analysis:
        return False
    cands = analysis.get("player_candidates") or []
    return bool(cands)


def _score_for_model(row: dict[str, Any]) -> dict[str, Any]:
    """Входные метки для сравнения вариантов; в ответе модель не должна их цитировать."""
    out: dict[str, Any] = {"rank": row.get("rank")}
    mw = row.get("mate_white")
    cpw = row.get("cp_white")
    if mw is not None:
        out["mate_for_white"] = mw
    elif cpw is not None:
        out["centipawns_white"] = cpw
    return out


def build_explanation_payload(analysis: dict) -> dict[str, Any]:
    cands = analysis.get("player_candidates") or []
    variants: list[dict[str, Any]] = []
    for row in cands:
        line = list(row.get("line_san") or [])
        short = line[:_MAX_CONTINUATION_PLIES]
        variants.append(
            {
                **_score_for_model(row),
                "first_move": row.get("first_move_san") or row.get("first_move_uci"),
                "continuation_san": short,
            }
        )
    return {
        "fen": analysis.get("fen"),
        "side_to_move": analysis.get("side_to_move"),
        "ranked_variants": variants,
    }


def build_agent_prompt(analysis: dict) -> str:
    payload = build_explanation_payload(analysis)
    data_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""Ты помощник по шахматам. Тебе даны только заранее отобранные продолжения в формате JSON.

Жёсткие правила:
- Объясняй только ходы и продолжения из поля ranked_variants. Не предлагай других ходов и не выдавай себя за расчёт позиции.
- Не упоминай шахматный движок, программы анализа и числовые оценки позиции в своём ответе (ни явно, ни «оценка говорит»).
- Пиши по-русски, кратко и структурированно: общая идея позиции, затем по каждому варианту из списка — замысел, плюсы, минусы, риски. Сверяйся с обозначениями ходов SAN из данных.
- Используй ранг варианта (rank) только как порядок в переданном списке, без ссылок на «оценку» или «движок».

Данные для объяснения (JSON):
{data_json}
"""


def reset_explanation_session_keys(session_state: Any) -> None:
    """Сброс сохранённого объяснения (новая позиция или новая партия)."""
    session_state.llm_explanation_text = None
    session_state.llm_explanation_fen = None
    session_state.llm_explanation_error = None


def ensure_explanation_session_keys(session_state: Any) -> None:
    if "llm_explanation_text" not in session_state:
        reset_explanation_session_keys(session_state)
