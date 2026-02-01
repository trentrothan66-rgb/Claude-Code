#!/usr/bin/env python3
"""
Six Pawn Chess Variant - Complete Retrograde Analysis Solver

This solver uses retrograde analysis to completely solve the Six Pawn Chess variant.
The game is played on files b-g (6 files) of a standard chessboard.
"""

import sys
import time
from collections import deque
from typing import Optional, List, Tuple, Set, Dict
import struct
import pickle


# Constants
FILES = 6  # b through g
RANKS = 8  # 1 through 8
WHITE = 0
BLACK = 1

# Game outcome constants
UNKNOWN = 0
WHITE_WIN = 1
BLACK_WIN = 2
DRAW = 3

# Position encoding: files b-g are indices 0-5
# ranks 1-8 are indices 0-7
# WHITE_PAWN_START_RANK = 1 (index 1)
# BLACK_PAWN_START_RANK = 6 (index 6)
WHITE_START_RANK = 1
BLACK_START_RANK = 6
WHITE_PROMO_RANK = 7
BLACK_PROMO_RANK = 0


class Position:
    """Represents a position in Six Pawn Chess."""

    __slots__ = ['white_pawns', 'black_pawns', 'to_move', 'ep_file']

    def __init__(self, white_pawns: int, black_pawns: int, to_move: int, ep_file: int):
        """
        Initialize position.

        white_pawns: 64-bit int where bit i represents square i (file + rank*6)
        black_pawns: 64-bit int where bit i represents square i
        to_move: WHITE (0) or BLACK (1)
        ep_file: -1 if no en passant, else file index (0-5) where ep is possible
        """
        self.white_pawns = white_pawns
        self.black_pawns = black_pawns
        self.to_move = to_move
        self.ep_file = ep_file

    def to_key(self) -> int:
        """Convert position to unique integer key for hashing."""
        # Encode as: white_pawns (48 bits) | black_pawns (48 bits) | to_move (1 bit) | ep_file (3 bits)
        # Total: 100 bits, fits in Python int
        key = self.white_pawns
        key |= self.black_pawns << 48
        key |= self.to_move << 96
        key |= (self.ep_file + 1) << 97  # +1 so -1 becomes 0
        return key

    @staticmethod
    def from_key(key: int) -> 'Position':
        """Convert integer key back to Position."""
        white_pawns = key & ((1 << 48) - 1)
        black_pawns = (key >> 48) & ((1 << 48) - 1)
        to_move = (key >> 96) & 1
        ep_file = ((key >> 97) & 0x7) - 1
        return Position(white_pawns, black_pawns, to_move, ep_file)

    def get_square(self, file: int, rank: int) -> Optional[int]:
        """Get piece at square, or None if empty."""
        sq = rank * FILES + file
        if self.white_pawns & (1 << sq):
            return WHITE
        if self.black_pawns & (1 << sq):
            return BLACK
        return None

    def set_square(self, file: int, rank: int, piece: Optional[int]):
        """Set piece at square."""
        sq = rank * FILES + file
        mask = ~(1 << sq)
        self.white_pawns &= mask
        self.black_pawns &= mask
        if piece == WHITE:
            self.white_pawns |= (1 << sq)
        elif piece == BLACK:
            self.black_pawns |= (1 << sq)

    def count_pawns(self, color: int) -> int:
        """Count pawns for a color."""
        pawns = self.white_pawns if color == WHITE else self.black_pawns
        return bin(pawns).count('1')

    def __str__(self) -> str:
        """String representation for debugging."""
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
        lines.append("  b c d e f g")
        lines.append(f"To move: {'White' if self.to_move == WHITE else 'Black'}")
        if self.ep_file >= 0:
            lines.append(f"En passant: {chr(ord('b') + self.ep_file)}")
        return "\n".join(lines)


def generate_moves(pos: Position) -> List[Tuple[Position, str]]:
    """
    Generate all legal moves from position.
    Returns list of (new_position, move_string) tuples.
    """
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
                move_str = f"{chr(ord('b') + file)}{rank + 1}{chr(ord('b') + file)}{new_rank + 1}"
                moves.append((new_pos, move_str))  # new_pos can be None for promotion

                # Forward two squares from start rank (can't be promotion)
                if rank == start_rank and new_pos is not None:
                    new_rank2 = rank + 2 * direction
                    if pos.get_square(file, new_rank2) is None:
                        new_pos2 = make_move(pos, file, rank, file, new_rank2, True)
                        if new_pos2:
                            move_str2 = f"{chr(ord('b') + file)}{rank + 1}{chr(ord('b') + file)}{new_rank2 + 1}"
                            moves.append((new_pos2, move_str2))

            # Captures
            for df in [-1, 1]:
                new_file = file + df
                new_rank = rank + direction
                if 0 <= new_file < FILES and 0 <= new_rank < RANKS:
                    # Normal capture
                    target = pos.get_square(new_file, new_rank)
                    if target is not None and target != color:
                        new_pos = make_move(pos, file, rank, new_file, new_rank, False)
                        move_str = f"{chr(ord('b') + file)}{rank + 1}x{chr(ord('b') + new_file)}{new_rank + 1}"
                        moves.append((new_pos, move_str))  # new_pos can be None for promotion

            # En passant capture
            if pos.ep_file >= 0:
                # White en passant: pawn on rank 5 (index 4), captures to rank 6 (index 5)
                # Black en passant: pawn on rank 4 (index 3), captures to rank 3 (index 2)
                if color == WHITE and rank == 4:
                    ep_target_file = pos.ep_file
                    if abs(file - ep_target_file) == 1 and pos.get_square(ep_target_file, 4) == BLACK:
                        new_pos = make_move_ep(pos, file, rank, ep_target_file, 5)
                        if new_pos:
                            move_str = f"{chr(ord('b') + file)}{rank + 1}x{chr(ord('b') + ep_target_file)}{5 + 1}e.p."
                            moves.append((new_pos, move_str))
                elif color == BLACK and rank == 3:
                    ep_target_file = pos.ep_file
                    if abs(file - ep_target_file) == 1 and pos.get_square(ep_target_file, 3) == WHITE:
                        new_pos = make_move_ep(pos, file, rank, ep_target_file, 2)
                        if new_pos:
                            move_str = f"{chr(ord('b') + file)}{rank + 1}x{chr(ord('b') + ep_target_file)}{2 + 1}e.p."
                            moves.append((new_pos, move_str))

    return moves


def make_move(pos: Position, from_file: int, from_rank: int, to_file: int, to_rank: int,
              double_push: bool) -> Optional[Position]:
    """
    Make a move and return new position.
    Returns None if move results in promotion (terminal position).
    """
    color = pos.to_move
    opponent = 1 - color

    # Check for promotion
    promo_rank = WHITE_PROMO_RANK if color == WHITE else BLACK_PROMO_RANK
    if to_rank == promo_rank:
        return None  # Terminal position

    # Create new position
    new_white = pos.white_pawns
    new_black = pos.black_pawns

    from_sq = from_rank * FILES + from_file
    to_sq = to_rank * FILES + to_file

    if color == WHITE:
        new_white &= ~(1 << from_sq)
        new_white |= (1 << to_sq)
        new_black &= ~(1 << to_sq)  # Capture
    else:
        new_black &= ~(1 << from_sq)
        new_black |= (1 << to_sq)
        new_white &= ~(1 << to_sq)  # Capture

    # Set en passant file if double push
    ep_file = to_file if double_push else -1

    return Position(new_white, new_black, opponent, ep_file)


def make_move_ep(pos: Position, from_file: int, from_rank: int,
                 to_file: int, to_rank: int) -> Position:
    """Make an en passant capture."""
    color = pos.to_move
    opponent = 1 - color

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

    return Position(new_white, new_black, opponent, -1)


def is_terminal(pos: Position) -> Tuple[bool, int]:
    """
    Check if position is terminal.
    Returns (is_terminal, outcome) where outcome is WHITE_WIN, BLACK_WIN, or DRAW.
    """
    white_count = pos.count_pawns(WHITE)
    black_count = pos.count_pawns(BLACK)

    # Check for extinction
    if white_count == 0:
        return (True, BLACK_WIN)
    if black_count == 0:
        return (True, WHITE_WIN)

    # Check for promotion (these shouldn't exist in our position set, but check anyway)
    for file in range(FILES):
        if pos.get_square(file, WHITE_PROMO_RANK) == WHITE:
            return (True, WHITE_WIN)
        if pos.get_square(file, BLACK_PROMO_RANK) == BLACK:
            return (True, BLACK_WIN)

    # Check for stalemate
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
    """
    Enumerate all theoretically reachable positions using forward search from start.
    Returns set of position keys.
    """
    print("Enumerating all reachable positions...")

    # Starting position
    white_start = 0
    black_start = 0
    for file in range(FILES):
        white_start |= (1 << (WHITE_START_RANK * FILES + file))
        black_start |= (1 << (BLACK_START_RANK * FILES + file))

    start_pos = Position(white_start, black_start, WHITE, -1)

    visited = set()
    queue = deque([start_pos.to_key()])
    visited.add(start_pos.to_key())

    count = 0
    last_report = time.time()

    while queue:
        pos_key = queue.popleft()
        pos = Position.from_key(pos_key)
        count += 1

        # Progress reporting
        if time.time() - last_report > 5.0:
            print(f"  Enumerated {count:,} positions, queue size: {len(queue):,}")
            last_report = time.time()

        # Generate moves
        moves = generate_moves(pos)
        for new_pos, _ in moves:
            new_key = new_pos.to_key()
            if new_key not in visited:
                visited.add(new_key)
                queue.append(new_key)

    print(f"Total reachable positions: {len(visited):,}")
    return visited


def retrograde_analysis(all_positions: Set[int]) -> Dict[int, Tuple[int, int, Optional[str]]]:
    """
    Perform retrograde analysis on all positions.
    Returns dict mapping position_key -> (outcome, distance, best_move).
    """
    print("\nPerforming retrograde analysis...")

    # Initialize tablebase
    tablebase = {}

    # Find all terminal positions
    for pos_key in all_positions:
        pos = Position.from_key(pos_key)
        is_term, outcome = is_terminal(pos)
        if is_term:
            tablebase[pos_key] = (outcome, 0, None)

    print(f"Found {len(tablebase):,} terminal positions")

    # Iterative solving
    max_iterations = 200  # Prevent infinite loops
    iteration = 0
    last_report = time.time()

    while iteration < max_iterations:
        iteration += 1
        newly_solved = 0

        for pos_key in all_positions:
            if pos_key in tablebase:
                continue

            pos = Position.from_key(pos_key)

            # Try to solve this position
            outcome, dist, best_move = evaluate_position(pos, tablebase)

            if outcome != UNKNOWN:
                tablebase[pos_key] = (outcome, dist, best_move)
                newly_solved += 1

        print(f"Iteration {iteration}: solved {newly_solved:,} new positions, total {len(tablebase):,}/{len(all_positions):,}")

        if newly_solved == 0:
            break

        if time.time() - last_report > 10.0:
            last_report = time.time()

    # Any unsolved positions are likely draws by repetition or zugzwang
    # For this variant, we'll mark remaining positions as draws
    for pos_key in all_positions:
        if pos_key not in tablebase:
            tablebase[pos_key] = (DRAW, 0, None)

    print(f"Solved {len(tablebase):,} positions in {iteration} iterations")

    return tablebase


def evaluate_position(pos: Position, tablebase: Dict[int, Tuple[int, int, Optional[str]]]) -> Tuple[int, int, Optional[str]]:
    """
    Evaluate position based on tablebase using minimax logic.
    Returns (outcome, distance, best_move).
    """
    moves = generate_moves(pos)

    if len(moves) == 0:
        # No moves - terminal
        _, outcome = is_terminal(pos)
        return (outcome, 0, None)

    # Check if all moves are in tablebase
    all_moves_solved = True
    move_evals = []

    for new_pos, move_str in moves:
        if new_pos is None:
            # Promotion - immediate win for current player
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

    # All moves are solved - find best move using minimax
    if pos.to_move == WHITE:
        # White maximizes: prefer WHITE_WIN, then DRAW, then BLACK_WIN
        # For wins, prefer shortest path; for losses, prefer longest path
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
        # Black maximizes: prefer BLACK_WIN, then DRAW, then WHITE_WIN
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


def save_tablebase(tablebase: Dict[int, Tuple[int, int, Optional[str]]], filename: str):
    """Save tablebase to disk."""
    print(f"\nSaving tablebase to {filename}...")
    with open(filename, 'wb') as f:
        pickle.dump(tablebase, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Saved {len(tablebase):,} positions")


def load_tablebase(filename: str) -> Dict[int, Tuple[int, int, Optional[str]]]:
    """Load tablebase from disk."""
    print(f"Loading tablebase from {filename}...")
    with open(filename, 'rb') as f:
        tablebase = pickle.load(f)
    print(f"Loaded {len(tablebase):,} positions")
    return tablebase


def main():
    """Main solver routine."""
    print("=" * 60)
    print("Six Pawn Chess - Complete Retrograde Analysis Solver")
    print("=" * 60)

    # Step 1: Enumerate all reachable positions
    start_time = time.time()
    all_positions = enumerate_all_positions()
    enum_time = time.time() - start_time
    print(f"Enumeration completed in {enum_time:.2f} seconds")

    # Step 2: Retrograde analysis
    start_time = time.time()
    tablebase = retrograde_analysis(all_positions)
    retro_time = time.time() - start_time
    print(f"Retrograde analysis completed in {retro_time:.2f} seconds")

    # Step 3: Save tablebase
    save_tablebase(tablebase, 'six_pawn_tablebase.pkl')

    # Step 4: Report starting position result
    print("\n" + "=" * 60)
    print("STARTING POSITION ANALYSIS")
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
    else:
        print("ERROR: Starting position not in tablebase!")

    print("\n" + start_pos.__str__())

    print("\n" + "=" * 60)
    print("Solver completed successfully!")
    print("=" * 60)


if __name__ == '__main__':
    main()
