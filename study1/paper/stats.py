"""Small statistics in the standard library: Wilson intervals, exact McNemar, Holm, scenario-cluster bootstrap."""
from __future__ import annotations

import math
import random


def wilson(k: int, n: int, z: float = 1.959964) -> tuple:
    if n == 0:
        return (None, None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(p, 4), round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on discordant pairs b (A yes, B no) and c (A no, B yes)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return round(min(1.0, 2 * p), 6)


def holm(ps: list) -> list:
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        adj[i] = round(run, 6)
    return adj


def paired_bootstrap_diff(pairs: list, reps: int = 10000, seed: int = 7) -> tuple:
    """pairs: [(a, b)] per scenario (0/1). Returns (mean diff a-b, 2.5%, 97.5%)."""
    if not pairs:
        return (None, None, None)
    rng = random.Random(seed)
    n = len(pairs)
    base = sum(a - b for a, b in pairs) / n
    ds = []
    for _ in range(reps):
        s = 0
        for _ in range(n):
            a, b = pairs[rng.randrange(n)]
            s += a - b
        ds.append(s / n)
    ds.sort()
    return (round(base, 4), round(ds[int(0.025 * reps)], 4), round(ds[int(0.975 * reps) - 1], 4))
