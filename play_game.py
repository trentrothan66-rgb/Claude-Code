#!/usr/bin/env python3
"""Interactive play against the trained six-pawn AlphaZero agent."""

import os
import sys
import argparse
import numpy as np
import torch

from six_pawn_env import (
    initial_position, get_legal_moves, check_terminal,
    ACTION_SIZE, WHITE, BLACK
)
from six_pawn_net import PawnNet
from six_pawn_mcts import run_mcts
from six_pawn_solver import generate_moves, FILES, RANKS


# ── Display ──────────────────────────────────────────────────────────────────

def board_str(pos):
    lines = []
    for rank in range(RANKS - 1, -1, -1):
        line = f"  {rank + 1} │"
        for file in range(FILES):
            sq = rank * FILES + file
            if pos.white_pawns & (1 << sq):
                line += " ♙"
            elif pos.black_pawns & (1 << sq):
                line += " ♟"
            else:
                line += " ·"
        lines.append(line)
    lines.append("    └─────────────")
    lines.append("      b  c  d  e  f  g")
    lines.append(f"  {'White' if pos.to_move == WHITE else 'Black'} to move"
                 + (f"  [ep: {chr(ord('b') + pos.ep_file)}]" if pos.ep_file >= 0 else ""))
    return "\n".join(lines)


def print_move_list(pos):
    """Print numbered legal moves with descriptive strings."""
    raw = generate_moves(pos)
    legal = get_legal_moves(pos)
    print()
    for i, ((raw_pos, move_str), (new_pos, _)) in enumerate(zip(raw, legal)):
        suffix = " (promotion win!)" if new_pos is None else ""
        print(f"    {i + 1:2d}.  {move_str}{suffix}")
    return raw, legal


# ── AI ────────────────────────────────────────────────────────────────────────

def load_net(checkpoint_path):
    net = PawnNet()
    if checkpoint_path and os.path.exists(checkpoint_path):
        ckpt = torch.load(checkpoint_path, weights_only=True)
        state = ckpt.get('model', ckpt)
        net.load_state_dict(state)
        iteration = ckpt.get('iteration', '?') if isinstance(ckpt, dict) and 'iteration' in ckpt else '?'
        print(f"  Loaded: {checkpoint_path}  (iteration {iteration})")
    else:
        print("  No checkpoint found — AI plays with random weights.")
    return net


def ai_move(pos, net, n_sims):
    print(f"\n  AI thinking ({n_sims} sims)…", end="", flush=True)
    visit_policy, q_mover = run_mcts(pos, net, n_sims=n_sims, add_dirichlet=False)
    print(f"  eval = {q_mover:+.3f}")

    raw = generate_moves(pos)
    legal = get_legal_moves(pos)

    best_action = int(np.argmax(visit_policy))
    for (raw_pos, move_str), (new_pos, act) in zip(raw, legal):
        if act == best_action:
            return new_pos, move_str, q_mover

    # Fallback (shouldn't reach here)
    new_pos, move_str = raw[0]
    return new_pos, move_str, q_mover


# ── Main game loop ────────────────────────────────────────────────────────────

def play(human_color, net, ai_sims):
    pos = initial_position()
    move_history = []

    color_name = {WHITE: "White", BLACK: "Black"}
    print(f"\n  You play as {color_name[human_color]}.")
    print("  Win by promoting a pawn, capturing all opponent pawns,")
    print("  or having more pawns when no moves remain.\n")

    while True:
        print("\n" + board_str(pos))

        done, white_val = check_terminal(pos)
        if done:
            print()
            if white_val > 0:
                result = "WHITE wins!"
            elif white_val < 0:
                result = "BLACK wins!"
            else:
                result = "DRAW."
            print(f"  ═══ {result} ═══")
            print(f"  Game length: {len(move_history)} half-moves")

            human_won = (white_val > 0 and human_color == WHITE) or \
                        (white_val < 0 and human_color == BLACK)
            if human_won:
                print("  You beat the AI!")
            elif white_val == 0:
                pass
            else:
                print("  The AI beat you.")
            break

        if pos.to_move == human_color:
            # ── Human turn ───────────────────────────────────────────────
            raw, legal = print_move_list(pos)

            while True:
                try:
                    choice = input("\n  Your move (number, or q to quit): ").strip()
                    if choice.lower() == 'q':
                        print("  Quit.")
                        return
                    idx = int(choice) - 1
                    if 0 <= idx < len(legal):
                        new_pos, act = legal[idx]
                        _, move_str = raw[idx]
                        move_history.append(move_str)
                        if new_pos is None:
                            # Promotion win
                            print(f"\n  You played: {move_str} — PROMOTION!")
                            print("\n" + board_str(pos))
                            winner = "WHITE" if human_color == WHITE else "BLACK"
                            print(f"\n  ═══ {winner} wins! ═══")
                            return
                        pos = new_pos
                        break
                    else:
                        print(f"  Enter a number from 1 to {len(legal)}.")
                except (ValueError, EOFError):
                    print("  Enter a number.")
                except KeyboardInterrupt:
                    print("\n  Quit.")
                    return
        else:
            # ── AI turn ──────────────────────────────────────────────────
            new_pos, move_str, q = ai_move(pos, net, ai_sims)
            move_history.append(move_str)
            print(f"  AI played: {move_str}")
            if new_pos is None:
                winner = "WHITE" if pos.to_move == WHITE else "BLACK"
                print("\n" + board_str(pos))
                print(f"\n  ═══ {winner} wins! (promotion) ═══")
                break
            pos = new_pos


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Play six-pawn chess against the AlphaZero agent.")
    parser.add_argument("--color", choices=["white", "black", "w", "b"],
                        default="white", help="Your color (default: white)")
    parser.add_argument("--sims", type=int, default=200,
                        help="MCTS simulations for AI (default: 200)")
    parser.add_argument("--checkpoint", type=str,
                        default="checkpoints/latest.pt",
                        help="Path to model checkpoint")
    args = parser.parse_args()

    human_color = WHITE if args.color.startswith("w") else BLACK

    print("\n  ══════════════════════════════════════")
    print("    Six Pawn Chess — AlphaZero Agent")
    print("  ══════════════════════════════════════")
    net = load_net(args.checkpoint)

    play(human_color, net, args.sims)


if __name__ == "__main__":
    main()
