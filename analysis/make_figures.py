"""Build the manuscript figures from the run's result tables.

Usage: python make_figures.py <results_dir> <out_dir>
Reads t1_session_rates.csv only. Writes fig_ladder.pdf/.png and fig_funnel.pdf/.png.
"""
import csv
import collections
import math
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES, OUT = sys.argv[1], sys.argv[2]
MODELS = [("claude-sonnet-5-5", "Claude Sonnet 5.5"),
          ("claude-haiku-5-5", "Claude Haiku 5.5"),
          ("openai/gpt-oss-120b", "gpt-oss-120b")]
RUNGS = ["R0", "R1", "R2", "R3", "R4", "R5"]
BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, MUTED, GRID = "#1f1f1e", "#6b6b66", "#e4e3dd"

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False,
})


def wilson(k, n, z=1.959964):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


rows = list(csv.DictReader(open(f"{RES}/t1_session_rates.csv")))
cell = collections.defaultdict(lambda: [0, 0, 0])      # n, acquired, disclosed
tot = collections.defaultdict(lambda: [0, 0, 0])
for r in rows:
    if r["mode"] != "multi":
        continue
    n, a, d = int(r["n"]), int(r["acquired"]), int(r["disclosed"])
    if r["population"] == "benign":
        c = cell[(r["model"], r["profile"], r["rung"])]
        c[0] += n; c[1] += a; c[2] += d
    t = tot[r["model"]]
    t[0] += n; t[1] += a; t[2] += d

# Figure 1: acquisition (top) and disclosure (bottom) by rung, small multiples
fig, axes = plt.subplots(2, 3, figsize=(6.6, 3.6), sharex=True, sharey="row")
for j, (mid, mname) in enumerate(MODELS):
    for i, (idx, label) in enumerate([(1, "Sessions acquiring"), (2, "Sessions disclosing")]):
        ax = axes[i][j]
        for prof, col, mk, ls in [("P-notes", BLUE, "o", "-"), ("P-struct", ORANGE, "s", "--")]:
            ys = []
            for rg in RUNGS:
                n = cell[(mid, prof, rg)][0]
                ys.append(cell[(mid, prof, rg)][idx] / n if n else 0)
            ax.plot(range(6), ys, color=col, marker=mk, markersize=4, linewidth=1.6,
                    linestyle=ls, label=prof, clip_on=False)
        ax.grid(axis="y", color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_xticks(range(6)); ax.set_xticklabels(RUNGS)
        if i == 0:
            ax.set_title(mname, fontsize=8.5, color=INK)
            ax.set_ylim(0, 0.8)
        else:
            ax.set_ylim(0, 0.4)
        if j == 0:
            ax.set_ylabel(label + "\n(share of 30 benign)")
axes[0][0].legend(frameon=False, loc="lower left", fontsize=7)
fig.tight_layout()
for ext in ("pdf", "png"):
    fig.savefig(f"{OUT}/fig_ladder.{ext}", dpi=300, bbox_inches="tight")
plt.close(fig)

# Figure 2: acquisition vs disclosure, all multi sessions, with Wilson intervals
fig, ax = plt.subplots(figsize=(3.4, 2.3))
w = 0.36
for j, (mid, mname) in enumerate(MODELS):
    n, a, d = tot[mid]
    for k, (val, col, hatch, lab) in enumerate([(a, BLUE, None, "Acquired"),
                                                 (d, ORANGE, "////", "Disclosed")]):
        p = val / n
        lo, hi = wilson(val, n)
        x = j + (k - 0.5) * w
        ax.bar(x, p, width=w - 0.04, color=col, hatch=hatch, edgecolor="white",
               linewidth=0.5, label=lab if j == 0 else None)
        ax.errorbar(x, p, yerr=[[p - lo], [hi - p]], color=INK, linewidth=0.8, capsize=2)
        ax.text(x, hi + 0.012, f"{val}/{n}", ha="center", va="bottom", fontsize=6, color=INK)
ax.set_xticks(range(3)); ax.set_xticklabels(["Sonnet 5.5", "Haiku 5.5", "gpt-oss-120b"], fontsize=7)
ax.set_ylabel("Share of multi-turn sessions")
ax.set_ylim(0, 0.36)
ax.grid(axis="y", color=GRID, linewidth=0.6); ax.set_axisbelow(True)
ax.legend(frameon=False, fontsize=7, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
fig.tight_layout()
for ext in ("pdf", "png"):
    fig.savefig(f"{OUT}/fig_funnel.{ext}", dpi=300, bbox_inches="tight")
plt.close(fig)

for mid, _ in MODELS:
    print(mid, tot[mid], [cell[(mid, p, r)] for p in ("P-notes", "P-struct") for r in RUNGS])
