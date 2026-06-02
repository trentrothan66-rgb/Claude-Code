"""Game environment wrapper for AlphaZero training."""

import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from six_pawn_solver import (
    Position, generate_moves, is_terminal as _solver_terminal,
    WHITE, BLACK, FILES, RANKS, WHITE_START_RANK, BLACK_START_RANK,
    WHITE_WIN, BLACK_WIN, DRAW
)

ACTION_SIZE = 48 * 4  # 192: 48 squares × 4 move types (fwd1, fwd2, cap_left, cap_right)


def initial_position():
    w = sum(1 << (WHITE_START_RANK * FILES + f) for f in range(FILES))
    b = sum(1 << (BLACK_START_RANK * FILES + f) for f in range(FILES))
    return Position(w, b, WHITE, -1)


def _parse_move_str(move_str):
    """Extract (from_file, from_rank, to_file, to_rank) from solver move string."""
    from_file = ord(move_str[0]) - ord('b')
    from_rank = int(move_str[1]) - 1
    if 'x' in move_str:
        xi = move_str.index('x')
        to_file = ord(move_str[xi + 1]) - ord('b')
        to_rank = int(move_str[xi + 2]) - 1
    else:
        to_file = ord(move_str[2]) - ord('b')
        to_rank = int(move_str[3]) - 1
    return from_file, from_rank, to_file, to_rank


def _coords_to_action(from_file, from_rank, to_file, to_rank, color):
    """Convert move coordinates to canonical action index (mover always moves 'upward')."""
    if color == BLACK:
        from_rank = 7 - from_rank
        to_rank = 7 - to_rank
    from_sq = from_rank * FILES + from_file
    dr = to_rank - from_rank
    df = to_file - from_file
    if   dr == 1 and df ==  0: mtype = 0
    elif dr == 2 and df ==  0: mtype = 1
    elif dr == 1 and df == -1: mtype = 2
    elif dr == 1 and df ==  1: mtype = 3
    else: raise ValueError(f"Unrecognized pawn delta dr={dr} df={df}")
    return from_sq * 4 + mtype


def get_legal_moves(pos):
    """
    Returns list of (result, action_idx).
    result is a Position for normal moves, or None for promotion (immediate win for mover).
    """
    result = []
    for new_pos, move_str in generate_moves(pos):
        coords = _parse_move_str(move_str)
        action = _coords_to_action(*coords, pos.to_move)
        result.append((new_pos, action))
    return result


def pos_to_tensor(pos):
    """
    Returns (4, 8, 6) float32 array, canonicalized so the current player's pawns
    are in channel 0 moving toward rank 7.
    Ch0: mover pawns, Ch1: opponent pawns, Ch2: ep target square, Ch3: side-to-move flag.
    """
    board = np.zeros((4, RANKS, FILES), dtype=np.float32)
    for rank in range(RANKS):
        for file in range(FILES):
            sq = rank * FILES + file
            if pos.white_pawns & (1 << sq):
                board[0, rank, file] = 1.0
            if pos.black_pawns & (1 << sq):
                board[1, rank, file] = 1.0

    # En passant target square (rank 5 for white mover, rank 2 for black mover)
    if pos.ep_file >= 0:
        ep_rank = 5 if pos.to_move == WHITE else 2
        board[2, ep_rank, pos.ep_file] = 1.0

    board[3] = 1.0 if pos.to_move == WHITE else 0.0

    if pos.to_move == BLACK:
        board = board[:, ::-1, :].copy()  # flip ranks
        board[0], board[1] = board[1].copy(), board[0].copy()  # swap player channels

    return board


def check_terminal(pos):
    """Returns (is_terminal, white_value). white_value: +1.0 white win, -1.0 black win, 0.0 draw."""
    done, outcome = _solver_terminal(pos)
    if not done:
        return False, 0.0
    return True, {WHITE_WIN: 1.0, BLACK_WIN: -1.0, DRAW: 0.0}[outcome]


def mover_value(white_value, to_move):
    """Convert white-centric value to current-mover-centric value."""
    return white_value if to_move == WHITE else -white_value
