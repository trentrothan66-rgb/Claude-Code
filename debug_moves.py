#!/usr/bin/env python3
"""Debug move generation and position evaluation."""

import sys
sys.path.append('.')
from four_pawn_validator import Position, generate_moves, WHITE, BLACK, FILES, WHITE_START_RANK, BLACK_START_RANK

def test_starting_position():
    """Test move generation from starting position."""
    white_start = 0
    black_start = 0
    for file in range(FILES):
        white_start |= (1 << (WHITE_START_RANK * FILES + file))
        black_start |= (1 << (BLACK_START_RANK * FILES + file))

    start_pos = Position(white_start, black_start, WHITE, -1)

    print("Starting position:")
    print(start_pos)
    print("\nLegal moves from starting position:")

    moves = generate_moves(start_pos)
    for i, (new_pos, move_str) in enumerate(moves):
        print(f"\n{i+1}. {move_str}")
        if new_pos:
            print(f"  White pawns: {bin(new_pos.white_pawns)}")
            print(f"  Black pawns: {bin(new_pos.black_pawns)}")
            print(f"  To move: {'White' if new_pos.to_move == WHITE else 'Black'}")
            print(f"  EP file: {new_pos.ep_file}")

    print(f"\nTotal moves: {len(moves)}")


def test_simple_capture():
    """Test a simple capture scenario."""
    # White pawn on c3, Black pawn on d4
    pos = Position(0, 0, WHITE, -1)
    pos.set_square(0, 2, WHITE)  # c3
    pos.set_square(1, 3, BLACK)  # d4

    print("\n" + "="*60)
    print("Test position: White c3, Black d4")
    print(pos)
    print("\nLegal moves:")

    moves = generate_moves(pos)
    for i, (new_pos, move_str) in enumerate(moves):
        print(f"{i+1}. {move_str}")

    print(f"Total moves: {len(moves)}")


def test_promotion():
    """Test promotion scenario."""
    # White pawn on c7
    pos = Position(0, 0, WHITE, -1)
    pos.set_square(0, 6, WHITE)  # c7

    print("\n" + "="*60)
    print("Test position: White c7 (about to promote)")
    print(pos)
    print("\nLegal moves:")

    moves = generate_moves(pos)
    for i, (new_pos, move_str) in enumerate(moves):
        if new_pos:
            print(f"{i+1}. {move_str} -> position continues")
        else:
            print(f"{i+1}. {move_str} -> PROMOTION (terminal)")

    print(f"Total moves: {len(moves)}")


if __name__ == '__main__':
    test_starting_position()
    test_simple_capture()
    test_promotion()
