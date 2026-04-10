"""Шахматная логика на python-chess: отделено от Streamlit."""

from __future__ import annotations

import chess


def try_apply_uci_move(board: chess.Board, san_history: list[str], uci: str) -> str | None:
    """
    Парсит UCI, проверяет легальность через python-chess, обновляет доску и историю SAN.

    Returns:
        None при успехе; иначе короткое сообщение об ошибке для пользователя.
    """
    try:
        move = chess.Move.from_uci(uci)
    except chess.InvalidMoveError:
        return (
            "Некорректная строка UCI: нужен формат «откуда-куда» латиницей в нижнем регистре "
            "(например e2e4). Для превращения пешки укажите фигуру в конце: e7e8q."
        )

    if not board.is_legal(move):
        return (
            "В этой позиции такой ход недоступен: проверьте очередь хода, шах, рокировку "
            "и правила хода выбранной фигуры."
        )

    san = board.san(move)
    board.push(move)
    san_history.append(san)
    return None
