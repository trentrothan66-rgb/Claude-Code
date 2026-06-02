"""AlphaZero self-play training loop for the six pawn game."""

import os
import time
import random
import numpy as np
import torch
import torch.optim as optim
import torch.nn.functional as F
from collections import deque

from six_pawn_env import (
    initial_position, pos_to_tensor, get_legal_moves, check_terminal,
    mover_value, ACTION_SIZE, WHITE, BLACK
)
from six_pawn_net import PawnNet
from six_pawn_mcts import run_mcts

# ── Hyperparameters ──────────────────────────────────────────────────────────
N_SIMS          = 100    # MCTS simulations per move
N_GAMES         = 25     # self-play games per training iteration
N_TRAIN_STEPS   = 200    # gradient steps per iteration
BATCH_SIZE      = 256
REPLAY_SIZE     = 20_000
TEMP_CUTOFF     = 10     # move number after which play becomes greedy
MAX_GAME_LEN    = 300    # half-moves; exceed → draw
LR              = 1e-3
WEIGHT_DECAY    = 1e-4
CHECKPOINT_DIR  = "checkpoints"
# ─────────────────────────────────────────────────────────────────────────────


def self_play_game(net, n_sims=N_SIMS):
    """
    Play one game via MCTS self-play.
    Returns (examples, white_value) where examples is a list of (tensor, policy, value).
    value in each example is from that position's mover's perspective.
    """
    pos = initial_position()
    history = []   # (tensor, policy, to_move)
    white_val = 0.0

    for move_num in range(MAX_GAME_LEN):
        done, white_val = check_terminal(pos)
        if done:
            break

        legal = get_legal_moves(pos)
        # (check_terminal already handles the no-legal-moves case, so legal is non-empty here)

        visit_policy, _ = run_mcts(pos, net, n_sims=n_sims)

        history.append((pos_to_tensor(pos), visit_policy.copy(), pos.to_move))

        # Temperature: sample proportional to visits early; greedy later
        if move_num < TEMP_CUTOFF:
            probs = visit_policy.copy()
        else:
            probs = np.zeros(ACTION_SIZE, dtype=np.float32)
            probs[int(np.argmax(visit_policy))] = 1.0

        if probs.sum() == 0:
            legal_actions = [a for _, a in legal]
            probs[legal_actions] = 1.0 / len(legal_actions)

        action = int(np.random.choice(ACTION_SIZE, p=probs / probs.sum()))

        # Execute chosen action
        game_ended = False
        next_pos = None
        for new_pos, act in legal:
            if act == action:
                if new_pos is None:
                    # Promotion: current mover wins
                    white_val = 1.0 if pos.to_move == WHITE else -1.0
                    game_ended = True
                else:
                    next_pos = new_pos
                break

        if game_ended:
            break

        if next_pos is None:
            # Fallback: sampled action not found (shouldn't happen)
            next_pos, _ = legal[0]

        pos = next_pos
    else:
        white_val = 0.0  # draw by move limit

    examples = [
        (tensor, policy, np.float32(white_val if to_move == WHITE else -white_val))
        for tensor, policy, to_move in history
    ]
    return examples, white_val


def train_step(net, optimizer, batch):
    net.train()
    tensors, policies, values = batch
    tensors  = torch.from_numpy(tensors)
    policies = torch.from_numpy(policies)
    values   = torch.from_numpy(values).unsqueeze(1)

    logits, v_pred = net(tensors)

    policy_loss = -(policies * F.log_softmax(logits, dim=1)).sum(dim=1).mean()
    value_loss  = F.mse_loss(v_pred, values)
    loss = policy_loss + value_loss

    optimizer.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
    optimizer.step()

    return policy_loss.detach().item(), value_loss.detach().item()


def load_checkpoint(net, optimizer):
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    path = os.path.join(CHECKPOINT_DIR, "latest.pt")
    if os.path.exists(path):
        ckpt = torch.load(path, weights_only=True)
        net.load_state_dict(ckpt['model'])
        optimizer.load_state_dict(ckpt['optimizer'])
        print(f"Resumed from iteration {ckpt.get('iteration', 0)}")
        return ckpt.get('iteration', 0)
    return 0


def save_checkpoint(net, optimizer, iteration):
    state = {'model': net.state_dict(), 'optimizer': optimizer.state_dict(), 'iteration': iteration}
    torch.save(state, os.path.join(CHECKPOINT_DIR, "latest.pt"))
    torch.save(net.state_dict(), os.path.join(CHECKPOINT_DIR, f"iter_{iteration:04d}.pt"))


def main():
    net = PawnNet()
    optimizer = optim.Adam(net.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    start_iter = load_checkpoint(net, optimizer)
    replay = deque(maxlen=REPLAY_SIZE)

    print(f"Parameters: {sum(p.numel() for p in net.parameters()):,}")
    print(f"Starting from iteration {start_iter}")
    print(f"MCTS sims={N_SIMS}  games/iter={N_GAMES}  train_steps/iter={N_TRAIN_STEPS}")
    print()

    for iteration in range(start_iter, 10_000):
        t0 = time.time()
        results = []

        # ── Self-play ────────────────────────────────────────────────────────
        for g in range(N_GAMES):
            examples, result = self_play_game(net)
            replay.extend(examples)
            results.append(result)

        w = sum(1 for r in results if r >  0.5)
        d = sum(1 for r in results if r == 0.0)
        b = sum(1 for r in results if r < -0.5)

        # ── Training ─────────────────────────────────────────────────────────
        p_losses, v_losses = [], []
        if len(replay) >= BATCH_SIZE:
            for _ in range(N_TRAIN_STEPS):
                samples = random.sample(list(replay), BATCH_SIZE)
                t_np = np.stack([s[0] for s in samples])
                p_np = np.stack([s[1] for s in samples])
                v_np = np.array([s[2] for s in samples], dtype=np.float32)
                pl, vl = train_step(net, optimizer, (t_np, p_np, v_np))
                p_losses.append(pl)
                v_losses.append(vl)

        elapsed = time.time() - t0
        pl_mean = np.mean(p_losses) if p_losses else float('nan')
        vl_mean = np.mean(v_losses) if v_losses else float('nan')
        print(
            f"Iter {iteration:4d} | buf {len(replay):5d} | "
            f"W/D/B {w}/{d}/{b} | "
            f"pLoss {pl_mean:.4f} | vLoss {vl_mean:.4f} | "
            f"{elapsed:.1f}s"
        )

        if iteration % 5 == 0:
            save_checkpoint(net, optimizer, iteration)

    save_checkpoint(net, optimizer, 9999)
    print("Training complete.")


if __name__ == '__main__':
    main()
