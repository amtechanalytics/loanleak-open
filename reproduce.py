"""Checks this package and recomputes the headline counts from the run records. Standard library only.

    python3 reproduce.py

1. Every file is compared with SHA256SUMS (so line endings or anything else changed in transit is detected).
2. Frozen-probe disclosure counts per label are recomputed for the five models from the per-cell run records.
3. Study 1 disclosure counts per configuration (gpt-oss, notes profile, benign users) are recomputed.
Prints REPRODUCE OK when everything matches the numbers reported in the paper."""
import collections
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
bad = []

n = 0
for line in (ROOT / "SHA256SUMS").read_text().splitlines():
    digest, name = line.split("  ", 1)
    p = ROOT / name
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
        bad.append(f"checksum: {name}")
    n += 1
print(f"checksums: {n} files, {sum(b.startswith('checksum') for b in bad)} differ")


def rows(rel):
    with open(ROOT / rel, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


PROBE = {"claude-sonnet-5-5": ("study2/runs/full/b2f_sonnet.jsonl", (8, 0)),
         "claude-haiku-5-5": ("study2/runs/full/b2f_haiku.jsonl", (12, 1)),
         "openai/gpt-oss-120b": ("study2/runs/full/b2f_gptoss.jsonl", (84, 7)),
         "grok-4.20-0309-non-reasoning": ("crossmodel/runs/full/b2f_grok.jsonl", (124, 29)),
         "gpt-6.1-sol": ("crossmodel/runs/full/b2f_sol.jsonl", (0, 0))}
print("frozen probe, cells disclosing the target (own label, foreign label):")
for model, (rel, want) in PROBE.items():
    c = collections.Counter()
    for r in rows(rel):
        rec = r.get("record") or {}
        if r.get("status") == "ok" and not rec.get("skipped"):
            c[rec["label"]] += bool(rec["target_any"])
    got = (c["own"], c["foreign"])
    print(f"  {model:32s} {got[0]:4d} {got[1]:4d}   reported {want[0]} and {want[1]}")
    if got != want:
        bad.append(f"probe: {model}")

want = {"R0": 1, "R1": 0, "R2": 7, "R3": 9, "R4": 4, "R5": 1}
got, tot = collections.Counter(), collections.Counter()
for r in rows("study1/runs/full/multi_gptoss.jsonl"):
    mode, profile, config, users, _ = r["cell_id"].split("|")
    if r.get("status") == "ok" and profile == "P-notes" and users == "benign":
        tot[config] += 1
        got[config] += bool((r.get("record") or {}).get("disclosed_any"))
print("study 1, gpt-oss, notes profile, benign sessions disclosing (of 30):")
print("  " + "  ".join(f"{k} {got[k]}/{tot[k]}" for k in sorted(want)))
if any(got[k] != want[k] or tot[k] != 30 for k in want):
    bad.append("study 1 counts")

if bad:
    print("REPRODUCE FAILED:", "; ".join(bad))
    sys.exit(1)
print("REPRODUCE OK")
