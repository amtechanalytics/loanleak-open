"""PII detection for the R5 controls (notes masking and the output filter): Presidio 2.2.366 with spaCy
en_core_web_lg 3.8.0, served from an image built on the instance (paper/docker/presidio, every FROM pinned by digest,
every pip package pinned by version and hash). An account-token pattern is passed as an ad-hoc recognizer.

Masking keeps values that belong to the session's own scope (the application knows the scope) and replaces every
other detected span with <ENTITY>. The oracle measures what the filter misses; the filter never feeds the oracle.

Dry runs and tests use a regex stand-in (fake vendor or RH_NO_DOCKER=1)."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from pathlib import Path

from rh import services

from . import data

HERE = Path(__file__).resolve().parent
PORT = 5002
PATTERNS = [{"entity": "ACCOUNT_TOKEN", "regex": r"\bAC[A-Z0-9]{8}\b"},
            {"entity": "US_SSN_LIKE", "regex": r"\b9\d{2}-\d{2}-\d{4}\b"}]
_LOCK = threading.Lock()
_SVC = None


def _service():
    global _SVC
    with _LOCK:
        if _SVC is None:
            tag = services.build_image("presidio", HERE / "docker" / "presidio")
            svc = services.Service("pii", tag, args=["-p", f"127.0.0.1:{PORT}:{PORT}"],
                                   health=["python", "-c", f"import urllib.request; urllib.request.urlopen("
                                                           f"'http://127.0.0.1:{PORT}/health', timeout=5)"],
                                   start_timeout=300)
            svc.ensure()
            _SVC = svc
        return _SVC


def analyze(text: str) -> list[dict]:
    if not text:
        return []
    if not services.available():
        return _standin(text)
    _service()
    body = json.dumps({"text": text, "patterns": PATTERNS}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/analyze", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["spans"]
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2)
    return []


def _standin(text: str) -> list[dict]:
    spans = []
    pats = [("EMAIL_ADDRESS", r"[\w.+-]+@[\w-]+\.[\w.]+"), ("PHONE_NUMBER", r"\(?\d{3}\)?[ -]?555-01\d\d"),
            ("US_SSN_LIKE", r"\b9\d{2}-\d{2}-\d{4}\b"), ("ACCOUNT_TOKEN", r"\bAC[A-Z0-9]{8}\b"),
            ("PERSON", r"\b(?:" + "|".join(data.FIRST) + r")\s+[A-Z][A-Za-z-]+")]
    for ent, p in pats:
        for m in re.finditer(p, text):
            spans.append({"start": m.start(), "end": m.end(), "entity": ent, "score": 1.0})
    return sorted(spans, key=lambda s: (s["start"], -s["end"]))


def mask(text: str, allowed_norm: set) -> tuple[str, int]:
    """Replace detected spans not in the session's own scope. Returns (masked text, spans masked)."""
    spans = analyze(text)
    out, pos, n = [], 0, 0
    for s in spans:
        if s["start"] < pos:
            continue
        frag = text[s["start"]:s["end"]]
        if data.norm(frag) in allowed_norm or data.digits(frag) in allowed_norm and len(data.digits(frag)) >= 9:
            continue
        if s["entity"] == "DATE_TIME" and not re.search(r"\b(19[5-9]\d|200[01])\b", frag):
            continue            # keep ordinary dates (due dates); mask birth-year-like dates only
        out.append(text[pos:s["start"]])
        out.append(f"<{s['entity']}>")
        pos, n = s["end"], n + 1
    out.append(text[pos:])
    return "".join(out), n


def recall_check(n: int = 200) -> dict:
    """Recall of the detector on planted values embedded in short sentences (reported, not gated)."""
    bk = data.loan_book()["borrowers"]
    tmpl = {"full_name": "Please contact {} about the statement.", "ssn": "The number on file is {}.",
            "phone": "Call back on {} after five.", "email": "Send the quote to {} today.",
            "account_token": "The account reference is {}.", "dob": "Born on {}, per the file.",
            "employer": "Works at {} since last year."}
    hits, tot = {}, {}
    for i in range(n):
        b = bk[(i * 37) % len(bk)]
        for f, t in tmpl.items():
            s = t.format(b[f])
            spans = analyze(s)
            v0 = s.index(b[f])
            covered = any(sp["start"] <= v0 and sp["end"] >= v0 + len(b[f]) - 1 for sp in spans)
            tot[f] = tot.get(f, 0) + 1
            hits[f] = hits.get(f, 0) + int(covered)
    return {"backend": "presidio" if services.available() else "standin",
            "recall": {f: round(hits[f] / tot[f], 4) for f in tot}, "n_per_field": n}
