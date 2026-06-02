"""Monte Carlo Tree Search with PUCT for six pawn AlphaZero.

Value convention: every node stores total_value from WHITE's absolute perspective.
This avoids sign-flip errors — the only sign work happens in select_child.
"""

import numpy as np
from six_pawn_env import (
    get_legal_moves, pos_to_tensor, check_terminal, ACTION_SIZE, WHITE, BLACK
)


class MCTSNode:
    __slots__ = ['pos', 'prior', 'children', 'visit_count', 'total_value',
                 'is_expanded', 'terminal_white_value']

    def __init__(self, pos, prior=0.0, terminal_white_value=None):
        self.pos = pos
        self.prior = prior
        self.children = {}            # action_idx -> MCTSNode
        self.visit_count = 0
        self.total_value = 0.0       # sum of white-perspective values
        self.is_expanded = False
        # Set for terminal nodes (promotion wins captured at expansion time)
        self.terminal_white_value = terminal_white_value

    @property
    def is_terminal(self):
        return self.terminal_white_value is not None

    @property
    def q_white(self):
        """Mean value from WHITE's perspective."""
        if self.visit_count == 0:
            # Unvisited terminal: return its known value; unvisited non-terminal: 0
            return self.terminal_white_value if self.is_terminal else 0.0
        return self.total_value / self.visit_count

    def select_child(self, c_puct):
        """
        PUCT selection from THIS node's mover's perspective.
        Returns (action, child_node).
        """
        sqrt_n = self.visit_count ** 0.5
        to_move = self.pos.to_move
        best_score = -float('inf')
        best_action, best_child = None, None

        for action, child in self.children.items():
            # Convert white-perspective Q to current-mover-perspective
            q_mover = child.q_white if to_move == WHITE else -child.q_white
            u = c_puct * child.prior * sqrt_n / (1 + child.visit_count)
            score = q_mover + u
            if score > best_score:
                best_score = score
                best_action, best_child = action, child

        return best_action, best_child

    def expand(self, policy, legal_moves, parent_to_move):
        """
        Create child nodes. Promotion moves become terminal nodes with a virtual
        visit so they have valid Q values from the first selection onward.
        """
        for new_pos, action in legal_moves:
            if new_pos is None:
                # Promotion: current mover wins
                win_white = 1.0 if parent_to_move == WHITE else -1.0
                child = MCTSNode(None, prior=float(policy[action]),
                                 terminal_white_value=win_white)
                # Virtual visit so q_white is defined without special-casing
                child.visit_count = 1
                child.total_value = win_white
            else:
                child = MCTSNode(new_pos, prior=float(policy[action]))
            self.children[action] = child
        self.is_expanded = True


def _masked_policy(raw_policy, legal_moves):
    """Zero out illegal actions and renormalize."""
    legal_actions = [a for _, a in legal_moves]
    mask = np.zeros(ACTION_SIZE, dtype=np.float32)
    mask[legal_actions] = 1.0
    p = raw_policy * mask
    s = p.sum()
    if s > 0:
        return p / s
    p[legal_actions] = 1.0 / len(legal_actions)
    return p


def run_mcts(root_pos, net, n_sims=100, c_puct=1.5, add_dirichlet=True,
             dir_alpha=0.3, dir_eps=0.25):
    """
    Run MCTS from root_pos.
    Returns (visit_policy, root_q_mover) where visit_policy sums to 1 over legal actions
    and root_q_mover is the root value from root's mover's perspective.
    """
    done, white_val = check_terminal(root_pos)
    if done:
        pol = np.zeros(ACTION_SIZE, dtype=np.float32)
        q = white_val if root_pos.to_move == WHITE else -white_val
        return pol, q

    legal_moves = get_legal_moves(root_pos)
    raw_policy, v_mover = net.predict(pos_to_tensor(root_pos))
    policy = _masked_policy(raw_policy, legal_moves)

    if add_dirichlet:
        legal_actions = [a for _, a in legal_moves]
        noise = np.random.dirichlet([dir_alpha] * len(legal_actions))
        for i, a in enumerate(legal_actions):
            policy[a] = (1 - dir_eps) * policy[a] + dir_eps * noise[i]

    root = MCTSNode(root_pos)
    root.expand(policy, legal_moves, root_pos.to_move)
    root.visit_count = 1  # virtual root visit for PUCT denominator

    # Convert NN value from mover's perspective to white's perspective
    v_white = v_mover if root_pos.to_move == WHITE else -v_mover
    root.total_value = v_white

    for _ in range(n_sims):
        node = root
        search_path = [node]

        # Selection: descend until an unexpanded non-terminal node
        while node.is_expanded:
            action, child = node.select_child(c_puct)
            search_path.append(child)
            node = child
            if node.is_terminal:
                break

        # Evaluation
        if node.is_terminal:
            # Terminal node (promotion): value already known
            value_white = node.terminal_white_value
        else:
            done, white_val = check_terminal(node.pos)
            if done:
                value_white = white_val
            else:
                legal = get_legal_moves(node.pos)
                raw_p, v_m = net.predict(pos_to_tensor(node.pos))
                p = _masked_policy(raw_p, legal)
                node.expand(p, legal, node.pos.to_move)
                value_white = v_m if node.pos.to_move == WHITE else -v_m

        # Backup: add white-perspective value to every node in path (no sign flip)
        for n in search_path:
            n.visit_count += 1
            n.total_value += value_white

    # Collect visit counts (subtract 1 from root's virtual visit when computing policy)
    visit_counts = np.zeros(ACTION_SIZE, dtype=np.float32)
    for action, child in root.children.items():
        # For terminal children, subtract the 1 virtual visit to get MCTS-only visits
        vc = child.visit_count - (1 if child.is_terminal else 0)
        visit_counts[action] = max(0, vc)

    total = visit_counts.sum()
    if total > 0:
        visit_policy = visit_counts / total
    else:
        # All moves are terminal wins — pick uniformly
        legal_actions = [a for _, a in legal_moves]
        visit_policy = np.zeros(ACTION_SIZE, dtype=np.float32)
        visit_policy[legal_actions] = 1.0 / len(legal_actions)

    root_q_mover = root.q_white if root_pos.to_move == WHITE else -root.q_white
    return visit_policy, root_q_mover
