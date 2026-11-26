"""Local PII detection service (Presidio analyzer + anonymizer, spaCy en_core_web_lg).
POST /analyze {"text", "patterns": [{"entity", "regex"}]} -> {"spans": [{"start","end","entity","score"}]}
GET /health -> ok. Single-threaded, deterministic, no network use after start."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer

ENGINE = AnalyzerEngine()          # loads en_core_web_lg once
ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "US_SSN", "DATE_TIME", "US_BANK_NUMBER",
            "CREDIT_CARD", "LOCATION", "IP_ADDRESS"]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send(200 if self.path == "/health" else 404, {"ok": self.path == "/health"})

    def do_POST(self):
        if self.path != "/analyze":
            return self._send(404, {"error": "not found"})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        adhoc = [PatternRecognizer(supported_entity=p["entity"], patterns=[Pattern(p["entity"], p["regex"], 0.9)])
                 for p in req.get("patterns") or []]
        ents = ENTITIES + [p["entity"] for p in req.get("patterns") or []]
        res = ENGINE.analyze(text=req.get("text", ""), language="en", entities=ents, ad_hoc_recognizers=adhoc)
        spans = sorted(({"start": r.start, "end": r.end, "entity": r.entity_type, "score": round(r.score, 3)}
                        for r in res), key=lambda s: (s["start"], -s["end"]))
        self._send(200, {"spans": spans})


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 5002), H).serve_forever()
