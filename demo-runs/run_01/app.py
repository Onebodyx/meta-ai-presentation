"""Точка входа Streamlit: доска, ход пользователя (python-chess), ответ и анализ Stockfish (UCI)."""

from __future__ import annotations

import asyncio
import sys

# До импорта streamlit: на Windows UCI в python-chess использует asyncio subprocess (нужен Proactor).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from pathlib import Path

import chess
import chess.svg
import streamlit as st

import chess_logic
import cursor_cloud
import settings
import stockfish_engine

st.set_page_config(page_title="Chess Coach", layout="centered")


def _ensure_session() -> None:
    if "board" not in st.session_state:
        st.session_state.board = chess.Board()
    if "move_history" not in st.session_state:
        st.session_state.move_history = []
    if "last_engine_analysis" not in st.session_state:
        st.session_state.last_engine_analysis = None


def _reset_game() -> None:
    st.session_state.board = chess.Board()
    st.session_state.move_history = []
    st.session_state.last_engine_analysis = None


def _board_svg(board: chess.Board) -> str:
    """SVG-разметка доски; вывод через markdown — совместимо с версиями без format= у st.image."""
    return chess.svg.board(board, size=400)


def _format_eval(evaluation: dict | None) -> str:
    if not evaluation:
        return "—"
    mate = evaluation.get("mate_white")
    if mate is not None:
        return f"мат за белых: {mate}" if mate > 0 else f"мат за чёрных: {-mate}"
    cp = evaluation.get("cp_white")
    if cp is None:
        return "—"
    pawns = cp / 100.0
    sign = "+" if pawns >= 0 else ""
    return f"{sign}{pawns:.2f} пешки (перспектива белых), глубина {evaluation.get('depth', 0)}"


_ensure_session()
board: chess.Board = st.session_state.board
move_history: list[str] = st.session_state.move_history
last_analysis: dict | None = st.session_state.last_engine_analysis

st.title("Chess Coach")
st.caption(
    "Партия в сессии браузера: ходы в UCI. Легальность хода проверяет python-chess; "
    "ответ соперника, оценка и топ вариантов — только Stockfish (см. `STOCKFISH_PATH` в `.env`). "
    "Облачный LLM — отдельный этап."
)

st.markdown(_board_svg(board), unsafe_allow_html=True)
turn_side = "белых" if board.turn == chess.WHITE else "чёрных"
st.caption(f"Ходят {turn_side}.")

stockfish_ok = bool(settings.STOCKFISH_PATH) and Path(settings.STOCKFISH_PATH).is_file()

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
    elif not stockfish_ok:
        st.error(
            "Задайте в `.env` переменную `STOCKFISH_PATH` на исполняемый файл Stockfish "
            "и перезапустите приложение."
        )
    else:
        err = chess_logic.try_apply_uci_move(board, move_history, uci)
        if err is not None:
            st.error(err)
        else:
            user_san = move_history[-1]
            if board.is_game_over():
                st.session_state.last_engine_analysis = stockfish_engine.build_analysis_after_user_only(
                    board, uci, user_san
                )
            else:
                try:
                    limit = stockfish_engine.search_limit_from_settings()
                    st.session_state.last_engine_analysis = stockfish_engine.play_engine_reply_and_analyse(
                        board,
                        move_history,
                        uci,
                        user_san,
                        settings.STOCKFISH_PATH,
                        limit,
                        multipv=3,
                    )
                except stockfish_engine.EngineError as ex:
                    chess_logic.undo_last_move(board, move_history)
                    st.session_state.last_engine_analysis = None
                    st.error(str(ex))
            st.rerun()

if st.button("Новая партия", type="primary"):
    _reset_game()
    st.rerun()

if last_analysis:
    st.subheader("Последний обмен и анализ")
    uc = last_analysis.get("user_move") or {}
    er = last_analysis.get("engine_reply")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Ваш ход**")
        st.write(f"UCI: `{uc.get('uci', '—')}` · SAN: **{uc.get('san', '—')}**")
    with c2:
        st.markdown("**Ответ Stockfish**")
        if er:
            st.write(f"UCI: `{er.get('uci', '—')}` · SAN: **{er.get('san', '—')}**")
        else:
            st.caption("Нет (партия завершилась до ответа движка).")

    gr = last_analysis.get("game_result")
    if gr and gr != "*":
        st.info(f"Итог партии: **{gr}**")
    else:
        st.markdown("**Оценка позиции** (после ответа движка, перспектива белых в cp/mate)")
        st.write(_format_eval(last_analysis.get("evaluation")))

    cands = last_analysis.get("player_candidates") or []
    if cands:
        st.markdown("**Топ-{n} продолжения для вас** (multiPV Stockfish)".format(n=len(cands)))
        tbl: list[dict[str, str | int | None]] = []
        for row in cands:
            cpw = row.get("cp_white")
            mw = row.get("mate_white")
            score_s = "—"
            if mw is not None:
                score_s = f"mate {mw}"
            elif cpw is not None:
                score_s = f"{cpw / 100:.2f}"
            tbl.append(
                {
                    "Ранг": row.get("rank"),
                    "1-й ход": row.get("first_move_san") or row.get("first_move_uci"),
                    "Оценка (бел.)": score_s,
                    "Линия SAN": " ".join(row.get("line_san") or [])[:120],
                }
            )
        st.dataframe(tbl, hide_index=True, use_container_width=True)

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

    st.caption(
        f"Параметры поиска: depth={settings.STOCKFISH_DEPTH}, "
        f"STOCKFISH_MOVETIME_MS={settings.STOCKFISH_MOVETIME_MS}."
    )

    if st.session_state.last_engine_analysis:
        st.subheader("Последний пакет анализа (JSON для LLM)")
        st.json(st.session_state.last_engine_analysis)

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
