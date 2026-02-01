#!/usr/bin/env python3
"""
Four Pawn Chess Variant - Validator

This validates our solver logic against the known solution for the four-pawn variant.
Expected: White wins, with 1.d4 as the winning first move.
"""

import sys
import time
from collections import deque
from typing import Optional, List, Tuple, Set, Dict

# Constants
FILES = 4  # c through f (indices 0-3)
RANKS = 8
WHITE = 0
BLACK = 1

UNKNOWN = 0
WHITE_WIN = 1
BLACK_WIN = 2
DRAW = 3

WHITE_START_RANK = 1
BLACK_START_RANK = 6
WHITE_PROMO_RANK = 7
BLACK_PROMO_RANK = 0


class Position:
    __slots__ = ['white_pawns', 'black_pawns', 'to_move', 'ep_file']

    def __init__(self, white_pawns: int, black_pawns: int, to_move: int, ep_file: int):
        self.white_pawns = white_pawns
        self.black_pawns = black_pawns
        self.to_move = to_move
        self.ep_file = ep_file

    def to_key(self) -> int:
        key = self.white_pawns
        key |= self.black_pawns << 32
        key |= self.to_move << 64
        key |= (self.ep_file + 1) << 65
        return key

    @staticmethod
    def from_key(key: int) -> 'Position':
        white_pawns = key & ((1 << 32) - 1)
        black_pawns = (key >> 32) & ((1 << 32) - 1)
        to_move = (key >> 64) & 1
        ep_file = ((key >> 65) & 0x7) - 1
        return Position(white_pawns, black_pawns, to_move, ep_file)

    def get_square(self, file: int, rank: int) -> Optional[int]:
        sq = rank * FILES + file
        if self.white_pawns & (1 << sq):
            return WHITE
        if self.black_pawns & (1 << sq):
            return BLACK
        return None

    def set_square(self, file: int, rank: int, piece: Optional[int]):
        sq = rank * FILES + file
        mask = ~(1 << sq)
        self.white_pawns &= mask
        self.black_pawns &= mask
        if piece == WHITE:
            self.white_pawns |= (1 << sq)
        elif piece == BLACK:
            self.black_pawns |= (1 << sq)

    def count_pawns(self, color: int) -> int:
        pawns = self.white_pawns if color == WHITE else self.black_pawns
        return bin(pawns).count('1')

    def __str__(self) -> str:
        lines = []
        for rank in range(RANKS - 1, -1, -1):
            line = f"{rank + 1} "
            for file in range(FILES):
                piece = self.get_square(file, rank)
                if piece == WHITE:
                    line += "♙ "
                elif piece == BLACK:
                    line += "♟ "
                else:
                    line += ". "
            lines.append(line)
        lines.append("  c d e f")
        lines.append(f"To move: {'White' if self.to_move == WHITE else 'Black'}")
        if self.ep_file >= 0:
            lines.append(f"En passant: {chr(ord('c') + self.ep_file)}")
        return "\n".join(lines)


def generate_moves(pos: Position) -> List[Tuple[Position, str]]:
    moves = []
    color = pos.to_move
    direction = 1 if color == WHITE else -1
    start_rank = WHITE_START_RANK if color == WHITE else BLACK_START_RANK

    for file in range(FILES):
        for rank in range(RANKS):
            if pos.get_square(file, rank) != color:
                continue

            # Forward one square
            new_rank = rank + direction
            if 0 <= new_rank < RANKS and pos.get_square(file, new_rank) is None:
                new_pos = make_move(pos, file, rank, file, new_rank, False)
                move_str = f"{chr(ord('c') + file)}{rank + 1}{chr(ord('c') + file)}{new_rank + 1}"
                moves.append((new_pos, move_str))  # new_pos can be None for promotion

                # Forward two squares from start rank (can't be promotion)
                if rank == start_rank and new_pos is not None:
                    new_rank2 = rank + 2 * direction
                    if pos.get_square(file, new_rank2) is None:
                        new_pos2 = make_move(pos, file, rank, file, new_rank2, True)
                        if new_pos2:
                            move_str2 = f"{chr(ord('c') + file)}{rank + 1}{chr(ord('c') + file)}{new_rank2 + 1}"
                            moves.append((new_pos2, move_str2))

            # Captures
            for df in [-1, 1]:
                new_file = file + df
                new_rank = rank + direction
                if 0 <= new_file < FILES and 0 <= new_rank < RANKS:
                    target = pos.get_square(new_file, new_rank)
                    if target is not None and target != color:
                        new_pos = make_move(pos, file, rank, new_file, new_rank, False)
                        move_str = f"{chr(ord('c') + file)}{rank + 1}x{chr(ord('c') + new_file)}{new_rank + 1}"
                        moves.append((new_pos, move_str))  # new_pos can be None for promotion

            # En passant capture
            if pos.ep_file >= 0:
                if color == WHITE and rank == 4:
                    ep_target_file = pos.ep_file
                    if abs(file - ep_target_file) == 1 and pos.get_square(ep_target_file, 4) == BLACK:
                        new_pos = make_move_ep(pos, file, rank, ep_target_file, 5)
                        if new_pos:
                            move_str = f"{chr(ord('c') + file)}{rank + 1}x{chr(ord('c') + ep_target_file)}{5 + 1}e.p."
                            moves.append((new_pos, move_str))
                elif color == BLACK and rank == 3:
                    ep_target_file = pos.ep_file
                    if abs(file - ep_target_file) == 1 and pos.get_square(ep_target_file, 3) == WHITE:
                        new_pos = make_move_ep(pos, file, rank, ep_target_file, 2)
                        if new_pos:
                            move_str = f"{chr(ord('c') + file)}{rank + 1}x{chr(ord('c') + ep_target_file)}{2 + 1}e.p."
                            moves.append((new_pos, move_str))

    return moves


def make_move(pos: Position, from_file: int, from_rank: int, to_file: int, to_rank: int,
              double_push: bool) -> Optional[Position]:
    color = pos.to_move
    promo_rank = WHITE_PROMO_RANK if color == WHITE else BLACK_PROMO_RANK
    if to_rank == promo_rank:
        return None

    new_white = pos.white_pawns
    new_black = pos.black_pawns

    from_sq = from_rank * FILES + from_file
    to_sq = to_rank * FILES + to_file

    if color == WHITE:
        new_white &= ~(1 << from_sq)
        new_white |= (1 << to_sq)
        new_black &= ~(1 << to_sq)
    else:
        new_black &= ~(1 << from_sq)
        new_black |= (1 << to_sq)
        new_white &= ~(1 << to_sq)

    ep_file = to_file if double_push else -1
    return Position(new_white, new_black, 1 - color, ep_file)


def make_move_ep(pos: Position, from_file: int, from_rank: int,
                 to_file: int, to_rank: int) -> Position:
    color = pos.to_move
    new_white = pos.white_pawns
    new_black = pos.black_pawns

    from_sq = from_rank * FILES + from_file
    to_sq = to_rank * FILES + to_file
    victim_rank = 4 if color == WHITE else 3
    victim_sq = victim_rank * FILES + to_file

    if color == WHITE:
        new_white &= ~(1 << from_sq)
        new_white |= (1 << to_sq)
        new_black &= ~(1 << victim_sq)
    else:
        new_black &= ~(1 << from_sq)
        new_black |= (1 << to_sq)
        new_white &= ~(1 << victim_sq)

    return Position(new_white, new_black, 1 - color, -1)


def is_terminal(pos: Position) -> Tuple[bool, int]:
    white_count = pos.count_pawns(WHITE)
    black_count = pos.count_pawns(BLACK)

    if white_count == 0:
        return (True, BLACK_WIN)
    if black_count == 0:
        return (True, WHITE_WIN)

    for file in range(FILES):
        if pos.get_square(file, WHITE_PROMO_RANK) == WHITE:
            return (True, WHITE_WIN)
        if pos.get_square(file, BLACK_PROMO_RANK) == BLACK:
            return (True, BLACK_WIN)

    moves = generate_moves(pos)
    if len(moves) == 0:
        if white_count > black_count:
            return (True, WHITE_WIN)
        elif black_count > white_count:
            return (True, BLACK_WIN)
        else:
            return (True, DRAW)

    return (False, UNKNOWN)


def enumerate_all_positions() -> Set[int]:
    print("Enumerating all reachable positions (4-pawn variant)...")

    white_start = 0
    black_start = 0
    for file in range(FILES):
        white_start |= (1 << (WHITE_START_RANK * FILES + file))
        black_start |= (1 << (BLACK_START_RANK * FILES + file))

    start_pos = Position(white_start, black_start, WHITE, -1)

    visited = set()
    queue = deque([start_pos.to_key()])
    visited.add(start_pos.to_key())

    while queue:
        pos_key = queue.popleft()
        pos = Position.from_key(pos_key)

        moves = generate_moves(pos)
        for new_pos, _ in moves:
            new_key = new_pos.to_key()
            if new_key not in visited:
                visited.add(new_key)
                queue.append(new_key)

    print(f"Total reachable positions: {len(visited):,}")
    return visited


def evaluate_position(pos: Position, tablebase: Dict[int, Tuple[int, int, Optional[str]]]) -> Tuple[int, int, Optional[str]]:
    moves = generate_moves(pos)

    if len(moves) == 0:
        _, outcome = is_terminal(pos)
        return (outcome, 0, None)

    all_moves_solved = True
    move_evals = []

    for new_pos, move_str in moves:
        if new_pos is None:
            if pos.to_move == WHITE:
                move_evals.append((WHITE_WIN, 1, move_str))
            else:
                move_evals.append((BLACK_WIN, 1, move_str))
        else:
            new_key = new_pos.to_key()
            if new_key in tablebase:
                outcome, dist, _ = tablebase[new_key]
                move_evals.append((outcome, dist + 1, move_str))
            else:
                all_moves_solved = False

    if not all_moves_solved:
        return (UNKNOWN, 0, None)

    if pos.to_move == WHITE:
        best = None
        for outcome, dist, move_str in move_evals:
            if best is None:
                best = (outcome, dist, move_str)
            elif outcome == WHITE_WIN and best[0] != WHITE_WIN:
                best = (outcome, dist, move_str)
            elif outcome == WHITE_WIN and best[0] == WHITE_WIN and dist < best[1]:
                best = (outcome, dist, move_str)
            elif outcome == DRAW and best[0] == BLACK_WIN:
                best = (outcome, dist, move_str)
            elif outcome == BLACK_WIN and best[0] == BLACK_WIN and dist > best[1]:
                best = (outcome, dist, move_str)
        return best
    else:
        best = None
        for outcome, dist, move_str in move_evals:
            if best is None:
                best = (outcome, dist, move_str)
            elif outcome == BLACK_WIN and best[0] != BLACK_WIN:
                best = (outcome, dist, move_str)
            elif outcome == BLACK_WIN and best[0] == BLACK_WIN and dist < best[1]:
                best = (outcome, dist, move_str)
            elif outcome == DRAW and best[0] == WHITE_WIN:
                best = (outcome, dist, move_str)
            elif outcome == WHITE_WIN and best[0] == WHITE_WIN and dist > best[1]:
                best = (outcome, dist, move_str)
        return best


def retrograde_analysis(all_positions: Set[int]) -> Dict[int, Tuple[int, int, Optional[str]]]:
    print("\nPerforming retrograde analysis...")

    tablebase = {}

    for pos_key in all_positions:
        pos = Position.from_key(pos_key)
        is_term, outcome = is_terminal(pos)
        if is_term:
            tablebase[pos_key] = (outcome, 0, None)

    print(f"Found {len(tablebase):,} terminal positions")

    max_iterations = 200
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        newly_solved = 0

        for pos_key in all_positions:
            if pos_key in tablebase:
                continue

            pos = Position.from_key(pos_key)
            outcome, dist, best_move = evaluate_position(pos, tablebase)

            if outcome != UNKNOWN:
                tablebase[pos_key] = (outcome, dist, best_move)
                newly_solved += 1

        print(f"Iteration {iteration}: solved {newly_solved:,} new positions, total {len(tablebase):,}/{len(all_positions):,}")

        if newly_solved == 0:
            break

    for pos_key in all_positions:
        if pos_key not in tablebase:
            tablebase[pos_key] = (DRAW, 0, None)

    print(f"Solved {len(tablebase):,} positions in {iteration} iterations")
    return tablebase


def main():
    print("=" * 60)
    print("Four Pawn Chess - Validation Solver")
    print("=" * 60)

    start_time = time.time()
    all_positions = enumerate_all_positions()
    enum_time = time.time() - start_time
    print(f"Enumeration completed in {enum_time:.2f} seconds")

    start_time = time.time()
    tablebase = retrograde_analysis(all_positions)
    retro_time = time.time() - start_time
    print(f"Retrograde analysis completed in {retro_time:.2f} seconds")

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    white_start = 0
    black_start = 0
    for file in range(FILES):
        white_start |= (1 << (WHITE_START_RANK * FILES + file))
        black_start |= (1 << (BLACK_START_RANK * FILES + file))

    start_pos = Position(white_start, black_start, WHITE, -1)
    start_key = start_pos.to_key()

    if start_key in tablebase:
        outcome, dist, best_move = tablebase[start_key]
        outcome_str = {WHITE_WIN: "White wins", BLACK_WIN: "Black wins", DRAW: "Draw"}[outcome]
        print(f"Result: {outcome_str}")
        print(f"Distance to terminal: {dist} moves")
        print(f"Best first move: {best_move}")

        print("\nExpected: White wins, best move d4")
        if outcome == WHITE_WIN:
            print("✓ Result matches!")
        else:
            print("✗ Result does NOT match!")

        if best_move and 'd4' in best_move:
            print("✓ Best move matches!")
        else:
            print(f"✗ Best move does NOT match! Got: {best_move}")
    else:
        print("ERROR: Starting position not in tablebase!")

    print("\n" + start_pos.__str__())


if __name__ == '__main__':
    main()
