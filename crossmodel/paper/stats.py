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


def cluster_signflip(diffs: list, mc: int = 100000, seed: int = 20261123) -> float:
    """Two-sided sign-flip randomization test of mean(diffs) = 0, one value per cluster: exact enumeration when at
    most 20 clusters are non-zero, else mc Monte Carlo draws with a fixed seed."""
    import itertools
    n = len(diffs)
    if n == 0:
        return 1.0
    obs = abs(sum(diffs)) / n
    nz = [d for d in diffs if d != 0]
    if not nz:
        return 1.0
    eps = 1e-12
    if len(nz) <= 20:
        cnt = tot = 0
        for signs in itertools.product((1, -1), repeat=len(nz)):
            tot += 1
            cnt += abs(sum(a * b for a, b in zip(nz, signs))) / n >= obs - eps
        return round(cnt / tot, 6)
    rng = random.Random(seed)
    cnt = 0
    for _ in range(mc):
        cnt += abs(sum(d if rng.random() < 0.5 else -d for d in nz)) / n >= obs - eps
    return round((cnt + 1) / (mc + 1), 6)


def cluster_bootstrap_mean(values: list, reps: int = 10000, seed: int = 7) -> tuple:
    """Mean of per-cluster values with a percentile bootstrap over clusters."""
    if not values:
        return (None, None, None)
    rng = random.Random(seed)
    n = len(values)
    base = sum(values) / n
    bs = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return (round(base, 4), round(bs[int(0.025 * reps)], 4), round(bs[int(0.975 * reps) - 1], 4))


def cluster_bootstrap_rate(groups: list, reps: int = 10000, seed: int = 7) -> tuple:
    """groups: [(successes, n)] per cluster. Pooled rate with a bootstrap over clusters."""
    if not groups:
        return (None, None, None)
    rng = random.Random(seed)
    k = len(groups)
    tot_s, tot_n = sum(g[0] for g in groups), sum(g[1] for g in groups)
    base = tot_s / tot_n if tot_n else None
    bs = []
    for _ in range(reps):
        pick = [groups[rng.randrange(k)] for _ in range(k)]
        s, n = sum(p[0] for p in pick), sum(p[1] for p in pick)
        bs.append(s / n if n else 0.0)
    bs.sort()
    return (round(base, 4) if base is not None else None, round(bs[int(0.025 * reps)], 4),
            round(bs[int(0.975 * reps) - 1], 4))
