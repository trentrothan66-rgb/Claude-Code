"""Small ResNet with policy + value heads for six pawn AlphaZero."""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from six_pawn_env import ACTION_SIZE


class ResBlock(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(channels)

    def forward(self, x):
        residual = x
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.bn2(self.conv2(x))
        return F.relu(x + residual)


class PawnNet(nn.Module):
    def __init__(self, n_filters=64, n_res_blocks=4):
        super().__init__()
        # Input: (batch, 4, 8, 6)
        self.stem = nn.Sequential(
            nn.Conv2d(4, n_filters, 3, padding=1, bias=False),
            nn.BatchNorm2d(n_filters),
            nn.ReLU()
        )
        self.res_blocks = nn.Sequential(*[ResBlock(n_filters) for _ in range(n_res_blocks)])

        # Policy head: 2-filter conv → flatten → linear(192)
        self.policy_conv = nn.Sequential(
            nn.Conv2d(n_filters, 2, 1, bias=False),
            nn.BatchNorm2d(2),
            nn.ReLU()
        )
        self.policy_fc = nn.Linear(2 * 8 * 6, ACTION_SIZE)

        # Value head: 1-filter conv → flatten → 64 hidden → tanh
        self.value_conv = nn.Sequential(
            nn.Conv2d(n_filters, 1, 1, bias=False),
            nn.BatchNorm2d(1),
            nn.ReLU()
        )
        self.value_fc = nn.Sequential(
            nn.Linear(1 * 8 * 6, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Tanh()
        )

    def forward(self, x):
        x = self.stem(x)
        x = self.res_blocks(x)
        p = self.policy_conv(x).flatten(1)
        p = self.policy_fc(p)
        v = self.value_conv(x).flatten(1)
        v = self.value_fc(v)
        return p, v

    @torch.no_grad()
    def predict(self, tensor):
        """Single-position inference. tensor: numpy (4,8,6). Returns (policy_np, value_float)."""
        self.eval()
        t = torch.from_numpy(tensor).unsqueeze(0)
        logits, v = self(t)
        policy = torch.softmax(logits, dim=1).squeeze(0).numpy()
        return policy, float(v.item())
