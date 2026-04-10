"""UCI Stockfish: ответный ход, оценка позиции, multiPV для кандидатов. Отдельно от Streamlit и LLM."""

from __future__ import annotations

import asyncio
import sys

# На Windows asyncio по умолчанию может использовать цикл без subprocess; python-chess тогда падает с
# NotImplementedError в BaseEventLoop._make_subprocess_transport. Proactor поддерживает subprocess.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import chess
import chess.engine

import settings


class EngineError(Exception):
    """Ошибка запуска или ответа движка (сообщение для UI)."""


SCHEMA_VERSION = 1


def search_limit_from_settings() -> chess.engine.Limit:
    depth = settings.STOCKFISH_DEPTH
    ms = settings.STOCKFISH_MOVETIME_MS
    if ms > 0:
        return chess.engine.Limit(depth=depth, time=ms / 1000.0)
    return chess.engine.Limit(depth=depth)


def _white_cp_mate(score: chess.engine.PovScore | None) -> tuple[int | None, int | None]:
    if score is None:
        return None, None
    w = score.white()
    if w.is_mate():
        m = w.mate()
        return None, m
    return w.score(), None


def _normalize_multipv(infos: chess.engine.Info | list[chess.engine.Info] | None) -> list[chess.engine.Info]:
    if infos is None:
        return []
    if isinstance(infos, list):
        return infos
    return [infos]


def _pv_sans(board: chess.Board, pv: list[chess.Move]) -> list[str]:
    b = board.copy(stack=False)
    out: list[str] = []
    for m in pv:
        out.append(b.san(m))
        b.push(m)
    return out


def build_analysis_after_user_only(board: chess.Board, user_uci: str, user_san: str) -> dict:
    """Партия завершилась сразу после хода пользователя — движок не вызывается."""
    return {
        "schema_version": SCHEMA_VERSION,
        "fen": board.fen(),
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "user_move": {"uci": user_uci, "san": user_san},
        "engine_reply": None,
        "game_result": board.result(),
        "evaluation": None,
        "player_candidates": [],
        "limits": None,
    }


def play_engine_reply_and_analyse(
    board: chess.Board,
    move_history: list[str],
    user_uci: str,
    user_san: str,
    engine_path: str,
    limit: chess.engine.Limit,
    multipv: int = 3,
) -> dict:
    """
    Доска уже с ходом пользователя. Запрашивает у Stockfish ответный ход, применяет его,
    затем multiPV-анализ для стороны игрока (кому сейчас ход).

    При ошибке движка доска и история не меняются сверх уже сделанного хода пользователя —
    вызывающий код должен откатить ход пользователя при перехвате EngineError.
    """
    limits_payload: dict[str, int | float] = {
        "depth": settings.STOCKFISH_DEPTH,
        "movetime_ms": settings.STOCKFISH_MOVETIME_MS,
    }

    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            play_result = engine.play(board, limit)
            eng_move = play_result.move
            if eng_move is None:
                raise EngineError("Stockfish не вернул ход (bestmove пуст).")
            if not board.is_legal(eng_move):
                raise EngineError("Stockfish предложил нелегальный ход — проверьте бинарник и версию.")

            eng_san = board.san(eng_move)
            eng_uci = eng_move.uci()
            board.push(eng_move)
            move_history.append(eng_san)

            if board.is_game_over():
                return {
                    "schema_version": SCHEMA_VERSION,
                    "fen": board.fen(),
                    "side_to_move": "white" if board.turn == chess.WHITE else "black",
                    "user_move": {"uci": user_uci, "san": user_san},
                    "engine_reply": {"uci": eng_uci, "san": eng_san},
                    "game_result": board.result(),
                    "evaluation": None,
                    "player_candidates": [],
                    "limits": limits_payload,
                }

            infos = engine.analyse(board, limit, multipv=multipv)
            rows = _normalize_multipv(infos)

            eval_depth = 0
            cp0: int | None = None
            mate0: int | None = None
            if rows:
                eval_depth = int(rows[0].get("depth") or 0)
                sc = rows[0].get("score")
                if isinstance(sc, chess.engine.PovScore):
                    cp0, mate0 = _white_cp_mate(sc)

            candidates: list[dict] = []
            for i, row in enumerate(rows[:multipv], start=1):
                pv = list(row.get("pv") or [])
                if not pv:
                    continue
                first = pv[0]
                sc = row.get("score")
                cp_i, mate_i = _white_cp_mate(sc) if isinstance(sc, chess.engine.PovScore) else (None, None)
                candidates.append(
                    {
                        "rank": i,
                        "first_move_uci": first.uci(),
                        "first_move_san": board.san(first),
                        "line_uci": [m.uci() for m in pv],
                        "line_san": _pv_sans(board, pv),
                        "cp_white": cp_i,
                        "mate_white": mate_i,
                        "depth": int(row.get("depth") or 0),
                    }
                )

            return {
                "schema_version": SCHEMA_VERSION,
                "fen": board.fen(),
                "side_to_move": "white" if board.turn == chess.WHITE else "black",
                "user_move": {"uci": user_uci, "san": user_san},
                "engine_reply": {"uci": eng_uci, "san": eng_san},
                "game_result": "*",
                "evaluation": {
                    "cp_white": cp0,
                    "mate_white": mate0,
                    "depth": eval_depth,
                },
                "player_candidates": candidates,
                "limits": limits_payload,
            }
    except chess.engine.EngineTerminatedError as e:
        raise EngineError(f"Процесс Stockfish завершился неожиданно: {e}") from e
    except OSError as e:
        raise EngineError(f"Не удалось запустить Stockfish по пути «{engine_path}»: {e}") from e
