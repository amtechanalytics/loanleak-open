# Replication package: third-party exposure in database-backed lending assistants

Run records, result tables, analysis code, harness code and hand-audit sheets for two studies of how tool-using
lending assistants expose people who are named inside records a user is allowed to read, plus a cross-model
replication of the frozen-state probe.

All identities are synthetic. Planted values (names, account tokens, SSNs, phone numbers, emails, dates of birth,
employers) are generated from a fixed seed and drawn from reserved ranges. No real personal data is in this package.

## Check it

```
python3 reproduce.py
```

Standard library only. It compares every file with `SHA256SUMS`, recomputes the frozen-probe disclosure counts for
the five models and the Study 1 disclosure counts per configuration from the run records, and prints `REPRODUCE OK`.

## Layout

| Folder | Contents |
|---|---|
| `study1/` | Study 1: six control configurations, two data profiles, three roles, benign and adversarial users (1,656 sessions) |
| `study2/` | Study 2: correct binding with agent-written SQL (B1), provenance probes (B2f frozen, B2a adaptive), defence components (B3) (4,512 sessions and probe cells) |
| `crossmodel/` | The frozen probe replayed on two further models (2,232 probe cells) |
| `audits/` | The four hand-rated audit workbooks and the script that built the blank sheets |
| `analysis/` | Figure scripts and the digit re-scan described below |

Inside each study folder:

| Path | Contents |
|---|---|
| `paper/` | Harness code for that run: data generation, database setup, tools, session loop, oracle, statistics, analysis |
| `paper/manifest/` | Pinned inputs shipped with the harness, including the frozen probe states |
| `paper/docker/` | Image definition for the PII detector |
| `config/` | Models, prices, plan, gates and data pins used for the run |
| `runs/full/` | One JSON line per session or probe cell, with every turn: user message, tool calls, visible answer and oracle output; from Study 2 on, also the tool results as the model received them |
| `results/` | Result tables written by `paper/analysis.py` |

## Where the reported numbers come from

| Result | File |
|---|---|
| Study 1 session rates and paired tests | `study1/results/t1_session_rates.csv`, `t2_paired_tests.csv` |
| Study 1 miner, routing, turn surfaces | `study1/results/t3_*.csv` to `t6_*.csv` |
| Correct binding with SQL (B1) | `study2/results/s2_b1_rates.csv`, `s2_b1_tests.csv`, `s2_b1_prohibited_disclosures.csv` |
| Frozen probe, three models | `study2/results/s2_b2f_primary.csv`, `s2_b2f_secondary.csv` |
| Adaptive probe (B2a) | `study2/results/s2_b2a_cells.csv`, `s2_b2_tests.csv` |
| Defence components (B3) and detector audit | `study2/results/s2_b3_components.csv`, `s2_b3_tests.csv`, `s2_detector_audit.csv` |
| Frozen probe, two further models | `crossmodel/results/s2x_b2f_crossmodel.csv`, `s2x_counts.json` |
| Answered turns by label | first turn of each record in `runs/full/b2f_*.jsonl` (`answered`) |

## Re-running the analysis

`paper/analysis.py` needs Python 3.11 or later with PyYAML, and the two public data pins in `config/data_pins.json`
(HMDA 2023 loan application records for one county, and CFPB consumer complaint metadata), from which the synthetic
loan book is generated. The orchestration layer that scheduled the runs, tracked spend and wrote the run records is
not part of this package; the run records are complete without it.

## Notes for readers

- **Study 2 ran in two parts.** The first run finished every stage except the frozen probe for two models; a
  completion run made those two stages on the same pinned states. `study2/runs/full/` holds the merged records.
- **`crossmodel/paper/` is the Study 2 harness with a different stage list.** `gpt-6.1-sol` ran with a prompted tool
  protocol (tools described in the prompt, one JSON action per reply) because its chat endpoint accepts no function
  tools. A plain-prose reply is recorded as the turn's answer (`ended: answer_prose`).
- **Tool results are cut for every model** to the first 4 rows and 700 characters. The `results` field in a run
  record is what the model received.
- **Digit values with non-ASCII separators.** The oracle's digit pattern matches SSNs and phone numbers only when the
  digits are separated by ASCII characters. One answer in Study 1 (`multi_gptoss|P-struct|R2|benign|e04`, turn 6)
  wrote an SSN and a phone number with non-breaking hyphens, and both were missed. `analysis/rescan_digits.py`
  repeats the matching with a wider separator set over every answer: it finds those two values and two numbers that
  a model made up which happen to equal a planted phone. All reported numbers use the original pattern; no session
  count changes, because that answer was already counted as disclosing.
- **Audit sheets.** `audits/` holds the workbooks as rated. In `audit-4-grok-probe-audited.xlsx`, Excel row 17 shows
  the wrong designated target (the sheet looked the target up by state id, and several Study 2 slots share a state
  id). The true target of that cell is the person the rater names in the comment; the oracle's score for the cell is
  correct. In `audit-2-study2-policy-labels-audited.xlsx`, the evidence column lists every note that mentions the
  person, including notes outside the user's scope that were never returned to the assistant.
- **Blinded utility audit.** `study2/results/s2_utility_audit_key.csv` maps each item to its model and configuration.

## Data sources and licences

- HMDA loan application register data: public data published by the U.S. Federal Financial Institutions Examination
  Council and the Consumer Financial Protection Bureau.
- Consumer complaint metadata: public data published by the U.S. Consumer Financial Protection Bureau. Complaint
  narratives are not used.
- Everything else in the loan book is generated.
