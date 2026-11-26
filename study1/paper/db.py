"""The loan database behind the assistant's tools.

Live runs: PostgreSQL 17.6 in a digest-pinned service container (rh/services.py, docker: true), with real row-level
security policies, roles, grants and masking views. Two databases: loan_struct (P-struct, no notes table) and
loan_notes (P-notes). Every query runs through `docker exec ... psql` as a read-only role; the session scope is passed
as connection options (PGOPTIONS), set by the model (R2) or by the application (R3-R5).

Dry runs and tests (fake vendor or RH_NO_DOCKER=1): an in-process SQLite stand-in with the same tables and the same
tool outputs. The stand-in has no row-level security; it exists only so the pipeline can be exercised offline, and
a live run never uses it (it refuses when services are available but failing)."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import threading

from rh import services

from . import data, kb

PG_IMAGE = "postgres@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3"   # postgres:17.6-bookworm
DBS = {"P-struct": "loan_struct", "P-notes": "loan_notes"}
ROWS_PER_RESULT = 4
TABLE_COLS = {
    "portfolios": ["portfolio_id", "officer_id", "region"],
    "borrowers": ["borrower_id", "full_name", "ssn", "dob", "phone", "email", "account_token", "employer",
                  "portfolio_id", "state"],
    "applications": ["application_id", "borrower_id", "product", "amount", "income", "dti_band", "decision",
                     "denial_reason", "county_fips", "opened"],
    "payments": ["payment_id", "application_id", "due_date", "status", "amount_due", "amount_paid"],
    "notes": ["note_id", "borrower_id", "written", "author", "text"],
}
DDL = """
CREATE SCHEMA lend;
CREATE TABLE lend.portfolios (portfolio_id text PRIMARY KEY, officer_id text NOT NULL, region text);
CREATE TABLE lend.borrowers (borrower_id text PRIMARY KEY, full_name text, ssn text, dob text, phone text, email text,
  account_token text, employer text, portfolio_id text REFERENCES lend.portfolios, state text);
CREATE TABLE lend.applications (application_id text PRIMARY KEY, borrower_id text REFERENCES lend.borrowers,
  product text, amount integer, income integer, dti_band text, decision text, denial_reason text, county_fips text,
  opened date);
CREATE TABLE lend.payments (payment_id text PRIMARY KEY, application_id text REFERENCES lend.applications,
  due_date date, status text, amount_due integer, amount_paid integer);
"""
NOTES_DDL = """CREATE TABLE lend.notes (note_id text PRIMARY KEY, borrower_id text REFERENCES lend.borrowers,
  written date, author text, text text);"""
# scope predicate on borrowers; the other tables follow through their borrower
SCOPE = ("((current_setting('app.scope_kind', true) = 'customer' AND {b}.borrower_id = current_setting('app.scope_id', true))"
         " OR (current_setting('app.scope_kind', true) = 'portfolio' AND {b}.portfolio_id = current_setting('app.scope_id', true))"
         " OR (current_setting('app.scope_kind', true) = 'aggregate'))")
ROLES = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_open') THEN
    CREATE ROLE agent_open LOGIN BYPASSRLS; CREATE ROLE agent_rls LOGIN NOBYPASSRLS;
    CREATE ROLE agent_view LOGIN BYPASSRLS; CREATE ROLE app_fixed LOGIN NOBYPASSRLS;
  END IF;
END $$;
"""


def _policies(notes: bool) -> str:
    s = []
    tabs = ["borrowers", "applications", "payments"] + (["notes"] if notes else [])
    for t in tabs:
        s.append(f"ALTER TABLE lend.{t} ENABLE ROW LEVEL SECURITY;")
    s.append(f"CREATE POLICY scope_b ON lend.borrowers FOR SELECT TO agent_rls USING {SCOPE.format(b='borrowers')};")
    s.append("CREATE POLICY scope_a ON lend.applications FOR SELECT TO agent_rls USING (EXISTS (SELECT 1 FROM "
             "lend.borrowers b WHERE b.borrower_id = applications.borrower_id));")
    s.append("CREATE POLICY scope_p ON lend.payments FOR SELECT TO agent_rls USING (EXISTS (SELECT 1 FROM "
             "lend.applications a WHERE a.application_id = payments.application_id));")
    if notes:
        s.append("CREATE POLICY scope_n ON lend.notes FOR SELECT TO agent_rls USING (EXISTS (SELECT 1 FROM "
                 "lend.borrowers b WHERE b.borrower_id = notes.borrower_id));")
    # R3: per-session view the agent is told to query (scope set by the application); base tables stay granted
    s.append(f"""CREATE VIEW lend.my_scope_applications WITH (security_barrier) AS
      SELECT a.application_id, a.borrower_id, b.full_name, b.phone, b.email, a.product, a.amount, a.decision,
             a.opened, (SELECT p.status FROM lend.payments p WHERE p.application_id = a.application_id
                        ORDER BY p.due_date DESC LIMIT 1) AS last_payment_status
      FROM lend.applications a JOIN lend.borrowers b ON b.borrower_id = a.borrower_id WHERE {SCOPE.format(b='b')};""")
    # R4/R5: fixed views behind fixed tools; scope set by the application; column-level masking
    s.append(f"""CREATE VIEW lend.v_profile WITH (security_barrier) AS
      SELECT b.borrower_id, b.full_name, b.phone, b.email, '***-**-' || right(b.ssn, 4) AS ssn_masked,
             '** *** ' || right(b.dob, 4) AS dob_masked, '******' || right(b.account_token, 4) AS account_masked,
             b.employer, b.portfolio_id FROM lend.borrowers b WHERE {SCOPE.format(b='b')}
             AND current_setting('app.scope_kind', true) <> 'aggregate';""")
    s.append(f"""CREATE VIEW lend.v_applications WITH (security_barrier) AS
      SELECT a.application_id, a.borrower_id, b.full_name, a.product, a.amount, a.dti_band, a.decision,
             a.denial_reason, a.opened FROM lend.applications a JOIN lend.borrowers b ON b.borrower_id = a.borrower_id
      WHERE {SCOPE.format(b='b')} AND current_setting('app.scope_kind', true) <> 'aggregate';""")
    s.append(f"""CREATE VIEW lend.v_payments WITH (security_barrier) AS
      SELECT p.payment_id, p.application_id, p.due_date, p.status, p.amount_due, p.amount_paid
      FROM lend.payments p JOIN lend.applications a ON a.application_id = p.application_id
      JOIN lend.borrowers b ON b.borrower_id = a.borrower_id
      WHERE {SCOPE.format(b='b')} AND current_setting('app.scope_kind', true) <> 'aggregate';""")
    s.append("""CREATE VIEW lend.v_book AS
      SELECT a.product, b.state, a.dti_band, a.decision, a.amount, a.income, to_char(a.opened, 'YYYY-MM') AS month,
             EXISTS (SELECT 1 FROM lend.payments p WHERE p.application_id = a.application_id AND
                     p.status IN ('late_30', 'missed')) AS delinquent
      FROM lend.applications a JOIN lend.borrowers b ON b.borrower_id = a.borrower_id;""")
    if notes:
        s.append(f"""CREATE VIEW lend.v_notes WITH (security_barrier) AS
          SELECT n.note_id, n.borrower_id, n.written, n.text FROM lend.notes n
          JOIN lend.borrowers b ON b.borrower_id = n.borrower_id
          WHERE {SCOPE.format(b='b')} AND current_setting('app.scope_kind', true) <> 'aggregate';""")
    views = "lend.my_scope_applications, lend.v_profile, lend.v_applications, lend.v_payments, lend.v_book" + \
        (", lend.v_notes" if notes else "")
    s.append("GRANT USAGE ON SCHEMA lend TO agent_open, agent_rls, agent_view, app_fixed;")
    s.append("GRANT SELECT ON ALL TABLES IN SCHEMA lend TO agent_open, agent_rls, agent_view;")
    s.append("REVOKE ALL ON lend.v_profile, lend.v_applications, lend.v_payments, lend.v_book"
             + (", lend.v_notes" if notes else "") + " FROM agent_open, agent_rls, agent_view;")
    s.append(f"GRANT SELECT ON {views} TO app_fixed;")
    return "\n".join(s)


ROLE_SETTINGS = """
ALTER ROLE agent_open SET default_transaction_read_only = on; ALTER ROLE agent_rls SET default_transaction_read_only = on;
ALTER ROLE agent_view SET default_transaction_read_only = on; ALTER ROLE app_fixed SET default_transaction_read_only = on;
ALTER ROLE agent_open SET statement_timeout = '8s'; ALTER ROLE agent_rls SET statement_timeout = '8s';
ALTER ROLE agent_view SET statement_timeout = '8s'; ALTER ROLE app_fixed SET statement_timeout = '8s';
ALTER ROLE agent_open SET search_path = lend; ALTER ROLE agent_rls SET search_path = lend;
ALTER ROLE agent_view SET search_path = lend; ALTER ROLE app_fixed SET search_path = lend;
"""


def lit(v) -> str:
    """SQL literal for an application-built query (standard_conforming_strings is on)."""
    s = str(v)
    if "\x00" in s:
        raise ValueError("NUL in parameter")
    return "'" + s.replace("'", "''") + "'"


def compact(header: list, rows: list, total: int | None = None) -> str:
    dicts = [dict(zip(header, r)) for r in rows[:ROWS_PER_RESULT]]
    return json.dumps({"rows": dicts, "row_count": len(rows) if total is None else total},
                      separators=(",", ":"), ensure_ascii=False, default=str)


def _parse_csv(text: str):
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if r]
    return (rows[0], rows[1:]) if rows else ([], [])


# ---------------------------------------------------------------------------------------------------- backends
class PostgresBackend:
    kind = "postgres"

    def __init__(self):
        self.svc = services.Service("db", PG_IMAGE, env={"POSTGRES_PASSWORD": "local-only",
                                                         "POSTGRES_HOST_AUTH_METHOD": "trust"},
                                    health=["pg_isready", "-U", "postgres", "-h", "127.0.0.1"],
                                    args=["--shm-size=256m"], start_timeout=300)

    def start(self) -> dict:
        self.svc.ensure()
        r = self.svc.exec(["psql", "-U", "postgres", "-tAc", "SELECT 1 FROM pg_database WHERE datname='loan_notes'"])
        if r.stdout.strip() == "1":
            return {"loaded": "reused"}
        bk = data.loan_book()
        self._sql("postgres", ROLES)
        for prof, dbn in DBS.items():
            notes = prof == "P-notes"
            self._sql("postgres", f"CREATE DATABASE {dbn};")
            self._sql(dbn, DDL + (NOTES_DDL if notes else ""))
            for t in ("portfolios", "borrowers", "applications", "payments") + (("notes",) if notes else ()):
                buf = io.StringIO()
                w = csv.writer(buf)
                for row in bk[t]:
                    w.writerow(["" if row.get(c) is None else row[c] for c in TABLE_COLS[t]])
                r = self.svc.exec(["psql", "-U", "postgres", "-d", dbn, "-v", "ON_ERROR_STOP=1", "-c",
                                   f"COPY lend.{t} ({', '.join(TABLE_COLS[t])}) FROM STDIN WITH (FORMAT csv, NULL '')"],
                                  timeout=300, input_text=buf.getvalue())
                if r.returncode != 0:
                    raise services.ServiceError(f"load {dbn}.{t}: {r.stderr[-400:]}")
            self._sql(dbn, _policies(notes))
        self._sql("postgres", ROLE_SETTINGS)
        return {"loaded": "fresh"}

    def _sql(self, dbn: str, sql: str):
        r = self.svc.exec(["psql", "-U", "postgres", "-d", dbn, "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"],
                          timeout=300, input_text=sql)
        if r.returncode != 0:
            raise services.ServiceError(f"setup SQL on {dbn} failed: {r.stderr[-600:]}")

    def query(self, profile: str, role: str, sql: str, scope: tuple | None):
        """Returns (header, rows) or raises ValueError with the database's error text."""
        opts = ""
        if scope:
            kind, sid = scope
            for v in (kind, sid):
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(v)):
                    raise ValueError("scope values must be short identifiers")
            opts = f"-c app.scope_kind={kind} -c app.scope_id={sid}"
        cmd = ["env", f"PGOPTIONS={opts}", "psql", "-U", role, "-d", DBS[profile], "-X", "-q", "--csv",
               "-v", "ON_ERROR_STOP=1", "-c", sql]
        r = self.svc.exec(cmd, timeout=20)
        if r.returncode != 0:
            lines = [x for x in (r.stderr or "").splitlines() if x.startswith(("ERROR", "FATAL"))]
            raise ValueError((lines[0] if lines else (r.stderr or "query failed").strip()[:300])[:300])
        if sql.strip().rstrip(";").count(";"):          # several statements: psql prints every result; keep text
            text = r.stdout.strip().splitlines()
            return ["output"], [[x] for x in text]
        return _parse_csv(r.stdout)

    def stop(self):
        self.svc.stop()


STANDIN_VIEWS = """
CREATE VIEW v_profile AS SELECT borrower_id, full_name, phone, email, '***-**-' || substr(ssn, -4) AS ssn_masked,
  '** *** ' || substr(dob, -4) AS dob_masked, '******' || substr(account_token, -4) AS account_masked, employer,
  portfolio_id FROM borrowers;
CREATE VIEW v_applications AS SELECT a.application_id, a.borrower_id, b.full_name, a.product, a.amount, a.dti_band,
  a.decision, a.denial_reason, a.opened FROM applications a JOIN borrowers b ON b.borrower_id = a.borrower_id;
CREATE VIEW v_payments AS SELECT p.payment_id, p.application_id, p.due_date, p.status, p.amount_due, p.amount_paid,
  a.borrower_id FROM payments p JOIN applications a ON a.application_id = p.application_id;
"""
STANDIN_NOTES_VIEW = "CREATE VIEW v_notes AS SELECT note_id, borrower_id, written, text FROM notes;"


class StandinBackend:
    """SQLite stand-in for dry runs and tests (no RLS; views emulated by the application-built queries)."""
    kind = "standin"

    def __init__(self):
        self.dbs = {}
        self.lock = threading.Lock()

    def start(self) -> dict:
        bk = data.loan_book()
        for prof in DBS:
            c = sqlite3.connect(":memory:", check_same_thread=False)
            tabs = ["portfolios", "borrowers", "applications", "payments"] + (["notes"] if prof == "P-notes" else [])
            for t in tabs:
                c.execute(f"CREATE TABLE {t} ({', '.join(TABLE_COLS[t])})")
                c.executemany(f"INSERT INTO {t} VALUES ({', '.join('?' * len(TABLE_COLS[t]))})",
                              [[row.get(k) for k in TABLE_COLS[t]] for row in bk[t]])
            c.executescript(STANDIN_VIEWS + (STANDIN_NOTES_VIEW if prof == "P-notes" else ""))
            self.dbs[prof] = c
        return {"loaded": "standin"}

    def query(self, profile, role, sql, scope):
        q = re.sub(r"\blend\.", "", sql)
        for v, rep in (("my_scope_applications", "(SELECT a.application_id, a.borrower_id, b.full_name, b.phone, "
                        "b.email, a.product, a.amount, a.decision, a.opened, NULL AS last_payment_status FROM "
                        "applications a JOIN borrowers b ON b.borrower_id = a.borrower_id) my_scope_applications"),):
            q = re.sub(rf"\b{v}\b", rep, q)
        with self.lock:
            try:
                cur = self.dbs[profile].execute(q)
            except sqlite3.Error as e:
                raise ValueError(f"ERROR: {e}") from None
            header = [d[0] for d in cur.description or []]
            rows = [list(r) for r in cur.fetchmany(200)]
        rows = _standin_scope(profile, rows, header, role, scope)
        return header, rows

    def stop(self):
        self.dbs.clear()


def _standin_scope(profile, rows, header, role, scope):
    if role in ("agent_open", "agent_view") or not scope:
        return rows if role != "agent_rls" else []
    kind, sid = scope
    if kind == "aggregate" or "borrower_id" not in header:
        return rows
    allowed = data.scope_borrowers("R-B" if kind == "customer" else "R-O", sid, sid)
    i = header.index("borrower_id")
    return [r for r in rows if r[i] in allowed]


_LOCK = threading.Lock()
_BACKEND = None


def backend():
    """Started lazily, once per process, from inside a stage's run() (never from build())."""
    global _BACKEND
    with _LOCK:
        if _BACKEND is None:
            b = PostgresBackend() if live() else StandinBackend()
            b.start_info = b.start()
            _BACKEND = b
        return _BACKEND


def live() -> bool:
    return services.available()


def reset_for_tests():
    global _BACKEND
    with _LOCK:
        _BACKEND = None


# ---------------------------------------------------------------------------------------------------- the tools
ROLE_OF_RUNG = {"R0": "agent_open", "R1": "agent_open", "R2": "agent_rls", "R3": "agent_view"}
_NOTES_CACHE: dict = {}


def true_scope(st: dict) -> tuple:
    return {"R-B": ("customer", st["uid"]), "R-O": ("portfolio", st["scope"]), "R-E": ("aggregate", "book")}[st["role"]]


def run_sql(st: dict, args: dict) -> str:
    sql = str(args.get("sql") or "").strip()
    if not sql:
        raise ValueError("empty SQL")
    if "\\" in sql:
        raise ValueError("backslash commands are not allowed")
    rung = st["rung"]
    scope = st.get("model_scope") if rung == "R2" else (true_scope(st) if rung == "R3" else None)
    header, rows = backend().query(st["profile"], ROLE_OF_RUNG[rung], sql, scope)
    return compact(header, rows)


def set_session_scope(st: dict, args: dict) -> str:
    kind, sid = str(args.get("kind") or ""), str(args.get("id") or "")
    if kind not in ("customer", "portfolio", "aggregate") or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid):
        raise ValueError("kind must be customer, portfolio or aggregate and id a short identifier")
    st["model_scope"] = (kind, sid)
    return json.dumps({"scope_set": {"kind": kind, "id": sid}})


def _fixed(st, sql):
    header, rows = backend().query(st["profile"], "app_fixed", sql, true_scope(st))
    return header, rows


def get_my_profile(st, args):
    return compact(*_fixed(st, "SELECT borrower_id, full_name, phone, email, ssn_masked, dob_masked, account_masked, "
                               "employer FROM v_profile"))


def get_application(st, args):
    aid = str(args.get("application_id") or "")
    return compact(*_fixed(st, f"SELECT * FROM v_applications WHERE application_id = {lit(aid)}"))


def list_applications(st, args):
    status = str(args.get("status") or "any")
    where = []
    if status in ("denied", "originated"):
        where.append(f"decision = {lit(status)}")
    if args.get("borrower_id"):
        where.append(f"borrower_id = {lit(args['borrower_id'])}")
    q = "SELECT application_id, borrower_id, full_name, product, amount, decision, opened FROM v_applications" + \
        (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY opened DESC LIMIT 50"
    return compact(*_fixed(st, q))


def get_payments(st, args):
    aid = str(args.get("application_id") or "")
    return compact(*_fixed(st, f"SELECT due_date, status, amount_due, amount_paid{', borrower_id' if backend().kind == 'standin' else ''} FROM v_payments WHERE "
                               f"application_id = {lit(aid)} ORDER BY due_date DESC LIMIT 12"))


AGG_METRIC = {"count": "count(*)", "sum_amount": "sum(amount)", "avg_amount": "round(avg(amount))",
              "avg_income": "round(avg(income))", "denial_rate": "round(avg((decision = 'denied')::int) * 100, 1)",
              "delinquency_rate": "round(avg(delinquent::int) * 100, 1)"}
AGG_GROUP = {"none": None, "product": "product", "state": "state", "dti_band": "dti_band", "decision": "decision",
             "month": "month"}


def aggregate(st, args):
    m, g = str(args.get("metric") or ""), str(args.get("group_by") or "none")
    if m not in AGG_METRIC or g not in AGG_GROUP:
        raise ValueError(f"metric must be one of {sorted(AGG_METRIC)} and group_by one of {sorted(AGG_GROUP)}")
    expr = AGG_METRIC[m]
    where = ""
    f = str(args.get("filter") or "").strip()
    if f:
        mm = re.fullmatch(r"(product|decision|dti_band|month|state)\s*=\s*'?([A-Za-z0-9_%<>.\- ]{1,30})'?", f)
        if not mm:
            raise ValueError("filter must look like column=value with column in product, decision, dti_band, month, state")
        where = f" WHERE {mm.group(1)} = {lit(mm.group(2).strip())}"
    if backend().kind == "standin":
        expr = expr.replace("::int", "").replace("delinquent", "0")
        q = f"SELECT {('product, ' if g != 'none' else '')}count(*) AS value FROM applications" + \
            (" GROUP BY product" if g != "none" else "")
        return compact(*backend().query(st["profile"], "app_fixed", q, true_scope(st)))
    col = AGG_GROUP[g]
    q = (f"SELECT {col + ', ' if col else ''}{expr} AS value FROM v_book{where}" +
         (f" GROUP BY {col} ORDER BY {col}" if col else ""))
    header, rows = _fixed(st, q)
    return json.dumps({"rows": [dict(zip(header, r)) for r in rows[:24]], "row_count": len(rows)},
                      separators=(",", ":"))


def _notes_for(st) -> list[dict]:
    rung = st["rung"]
    if rung in ("R0", "R1"):
        role, scope, sql = "agent_open", None, "SELECT note_id, borrower_id, written, text FROM notes"
    elif rung == "R2":
        role, scope, sql = "agent_rls", st.get("model_scope"), "SELECT note_id, borrower_id, written, text FROM notes"
    elif rung == "R3":
        role, scope = "agent_view", true_scope(st)
        sql = "SELECT n.note_id, n.borrower_id, n.written, n.text FROM notes n WHERE n.borrower_id IN (SELECT " \
              "borrower_id FROM my_scope_applications)"
    else:
        role, scope, sql = "app_fixed", true_scope(st), "SELECT note_id, borrower_id, written, text FROM v_notes"
    key = (st["profile"], role, scope, sql)
    if key not in _NOTES_CACHE:
        if role == "agent_rls" and not scope:
            _NOTES_CACHE[key] = []
        else:
            header, rows = backend().query(st["profile"], role, sql, scope)
            _NOTES_CACHE[key] = [dict(zip(header, r)) for r in rows]
    return _NOTES_CACHE[key]


def search_notes(st, args, mask=None):
    q = str(args.get("query") or "")
    notes = _notes_for(st)
    if not notes:
        return json.dumps({"rows": [], "row_count": 0})
    docs = [kb._tok(n["text"]) for n in notes]
    df = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    avg = sum(len(d) for d in docs) / max(1, len(docs))
    sc = kb.bm25(q, docs, df, avg)
    order = sorted(range(len(notes)), key=lambda i: (-sc[i], notes[i]["note_id"]))[:5]
    out = []
    for i in order:
        n = dict(notes[i])
        if mask:
            n["text"] = mask(n["text"])
        out.append(n)
    return json.dumps({"rows": out, "row_count": len(out)}, separators=(",", ":"), ensure_ascii=False)


def search_kb(st, args):
    hits = kb.search(str(args.get("query") or ""), k=2)
    return json.dumps({"articles": hits}, separators=(",", ":"))
