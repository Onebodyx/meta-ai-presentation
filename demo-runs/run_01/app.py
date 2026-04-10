"""Точка входа Streamlit: доска в сессии, ввод хода UCI (проверка через python-chess), без движка и LLM."""

from __future__ import annotations

from pathlib import Path

import chess
import chess.svg
import streamlit as st

import chess_logic
import cursor_cloud
import settings

st.set_page_config(page_title="Chess Coach", layout="centered")


def _ensure_session() -> None:
    if "board" not in st.session_state:
        st.session_state.board = chess.Board()
    if "move_history" not in st.session_state:
        st.session_state.move_history = []


def _reset_game() -> None:
    st.session_state.board = chess.Board()
    st.session_state.move_history = []


def _board_svg(board: chess.Board) -> str:
    """SVG-разметка доски; вывод через markdown — совместимо с версиями без format= у st.image."""
    return chess.svg.board(board, size=400)


_ensure_session()
board: chess.Board = st.session_state.board
move_history: list[str] = st.session_state.move_history

st.title("Chess Coach")
st.caption(
    "Партия в сессии браузера: стартовая позиция, ходы в нотации UCI. "
    "Допустимость хода определяет python-chess. Stockfish и облачный LLM — позже."
)

st.markdown(_board_svg(board), unsafe_allow_html=True)
turn_side = "белых" if board.turn == chess.WHITE else "чёрных"
st.caption(f"Ходят {turn_side}.")

with st.form("move_form", clear_on_submit=True):
    uci_input = st.text_input(
        "Ход (UCI)",
        placeholder="например e2e4; превращение: e7e8q",
        help="Формат: откуда-куда, без пробелов, латиница в нижнем регистре. "
        "Превращение пешки — буква фигуры в конце: q, r, b, n.",
    )
    submitted = st.form_submit_button("Сделать ход")

if submitted:
    uci = (uci_input or "").strip().lower()
    if not uci:
        st.warning("Введите ход.")
    else:
        err = chess_logic.try_apply_uci_move(board, move_history, uci)
        if err is None:
            st.rerun()
        else:
            st.error(err)

if st.button("Новая партия", type="primary"):
    _reset_game()
    st.rerun()

st.subheader("История ходов")
if not move_history:
    st.caption("Пока ходов нет — начните с белых (например e2e4).")
else:
    rows: list[dict[str, str | int]] = []
    for i in range(0, len(move_history), 2):
        white = move_history[i]
        black = move_history[i + 1] if i + 1 < len(move_history) else ""
        rows.append({"Номер": i // 2 + 1, "Белые": white, "Чёрные": black})
    st.dataframe(rows, hide_index=True, use_container_width=True)

with st.expander("Диагностика: Stockfish и Cursor Cloud"):
    stockfish = settings.STOCKFISH_PATH
    if not stockfish:
        st.info("В `.env` не задан `STOCKFISH_PATH`.")
    else:
        path = Path(stockfish)
        if path.is_file():
            st.success("Путь к Stockfish задан, файл найден.")
        else:
            st.warning("Путь к Stockfish задан, но файл по этому пути не найден.")

    st.subheader("Cursor Cloud (конфигурация)")
    eff_base = cursor_cloud.effective_base_url(settings.CURSOR_CLOUD_BASE_URL)
    key_set = bool(settings.CURSOR_CLOUD_AGENTS_API_KEY)
    st.metric("CURSOR_CLOUD_AGENTS_API_KEY", "задан" if key_set else "пусто")
    st.caption(
        f"Эффективный базовый URL: `{eff_base}` "
        f"(из `CURSOR_CLOUD_BASE_URL` или значение по умолчанию для API Cursor)."
    )
    explicit_model = cursor_cloud.normalize_model(settings.CURSOR_CLOUD_MODEL)
    st.metric(
        "CURSOR_CLOUD_MODEL",
        explicit_model if explicit_model else "не передаётся (выбор на стороне Cursor Cloud)",
    )
    st.metric("CURSOR_CLOUD_TIMEOUT_SEC", f"{settings.CURSOR_CLOUD_TIMEOUT_SEC:g} с")

    if st.button("Проверить подключение к Cursor Cloud"):
        result = cursor_cloud.CursorCloudClient().verify_credentials()
        if isinstance(result, cursor_cloud.VerifyErr):
            st.error(result.message)
        else:
            st.success("Подключение к Cursor Cloud работает (GET /v0/me).")
            st.write(
                {
                    "apiKeyName": result.api_key_name,
                    "userEmail": result.user_email,
                    "createdAt": result.created_at,
                }
            )
