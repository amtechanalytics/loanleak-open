"""Fig. 3 of the paper: Study 2 frozen-probe disclosure by label (a) and B3 acquisition by component (b).
Usage: python make_fig_study2.py <results_dir> <out_dir>   (reads s2_b2f_primary.csv, s2x_b2f_crossmodel.csv, s2_b3_components.csv)"""
import csv, math, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#1f1f1e", "#6b6b66", "#e4e3dd"
plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                     "axes.spines.right": False, "pdf.fonttype": 42})
NAMES = {"claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5", "openai/gpt-oss-120b": "gpt-oss-120b"}
SHORT = {"claude-sonnet-5-5": "Sonnet", "claude-haiku-5-5": "Haiku", "openai/gpt-oss-120b": "gpt-oss",
         "grok-4.20-0309-non-reasoning": "Grok", "gpt-6.1-sol": "Sol"}


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def main(res, out):
    res, out = Path(res), Path(out)
    b2f = [r for r in csv.DictReader(open(res / "s2_b2f_primary.csv")) if r["slice"].startswith("pooled")]
    b2f += [r for r in csv.DictReader(open(res / "s2x_b2f_crossmodel.csv"))      # cross-model run: Grok, Sol
            if r["slice"] == "pooled" and r["outcome"] == "target name or token"]
    b3 = list(csv.DictReader(open(res / "s2_b3_components.csv")))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(5.3, 2.05), gridspec_kw={"width_ratios": [1.6, 1.7]})
    w = 0.36
    for i, r in enumerate(b2f):
        n = 558                                  # cells per label and model
        for j, (lab, col, hatch) in enumerate((("own", BLUE, None), ("foreign", ORANGE, "////"))):
            k = int(r[f"{lab}_events"])
            p = k / n
            lo, hi = wilson(k, n)
            x = i + (j - 0.5) * w
            a1.bar(x, p, width=w - 0.04, color=col, hatch=hatch, edgecolor="white", linewidth=0,
                   label=("own-record label" if lab == "own" else "other-customer label") if i == 0 else None)
            a1.errorbar(x, p, yerr=[[p - lo], [hi - p]], color=INK, linewidth=0.7, capsize=1.5)
            a1.text(x, hi + 0.006, f"{k}", ha="center", va="bottom", fontsize=6, color=INK)
    a1.set_xticks(range(len(b2f)), [SHORT[r["model"]] for r in b2f], fontsize=6)
    a1.set_ylabel("target disclosed (share of cells)", fontsize=7)
    a1.set_ylim(0, 0.36)
    a1.tick_params(labelsize=6.5)
    a1.grid(axis="y", color=GRID, linewidth=0.5)
    a1.set_axisbelow(True)
    a1.legend(frameon=False, fontsize=6, loc="upper left", handlelength=1.2)
    a1.set_title("(a) frozen probe, identical payload", fontsize=7.5, color=INK)
    cells = ["R4", "R4+M", "R4+F", "R4+P", "R4+CM", "R5"]
    models = list(NAMES)
    w = 0.26
    for j, (m, col, mk) in enumerate(zip(models, (BLUE, ORANGE, AQUA), ("o", "s", "^"))):
        ys = [float(next(r for r in b3 if r["model"] == m and r["cell"] == c)["acquired_rate"]) for c in cells]
        xs = [i + (j - 1) * w for i in range(len(cells))]
        a2.bar(xs, ys, width=w - 0.03, color=col, edgecolor="white", linewidth=0, label=NAMES[m],
               hatch=(None, "////", "....")[j])
    a2.set_xticks(range(len(cells)), cells, fontsize=5.8)
    a2.set_ylabel("share of 30 sessions acquiring", fontsize=7)
    a2.set_ylim(0, 1.18)
    a2.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    a2.tick_params(labelsize=6.5)
    a2.grid(axis="y", color=GRID, linewidth=0.5)
    a2.set_axisbelow(True)
    a2.legend(frameon=False, fontsize=6, loc="upper center", ncol=3, handlelength=1.2)
    a2.set_title("(b) R5 components on R4, acquisition", fontsize=7.5, color=INK)
    fig.tight_layout(pad=0.3, w_pad=1.0)
    fig.savefig(out / "fig_study2.pdf")
    fig.savefig(out / "fig_study2.png", dpi=200)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
