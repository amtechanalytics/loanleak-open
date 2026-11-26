"""PII-free knowledge base of general lending and servicing workflow articles, with a stdlib BM25 search.
Sixty articles: twenty topics in three variants (overview, how to, timing and rights). Seeded, deterministic."""
from __future__ import annotations

import math
import re
from functools import lru_cache

ORG = "Prairie Ridge Lending"
TOPICS = {
    "late fees": "A late fee applies when a scheduled installment is not received within the 15-day grace period. The "
                 "fee is 5% of the installment or $25, whichever is less, and appears on the next statement. A borrower "
                 "on autopay whose debit failed because of a bank error can ask for a one-time waiver.",
    "grace period": "Every installment has a 15-day grace period after its due date. Payments received inside the grace "
                    "period are on time for fees and for credit reporting.",
    "autopay": "Autopay debits the installment on the due date from a checking or savings account. Enrolment or changes "
               "take effect from the next cycle if made at least five business days before the due date.",
    "payoff quote": "A payoff quote states the amount needed to close a loan on a given date, including accrued interest "
                    "and any unpaid fees. Quotes are valid for ten calendar days and are sent to the contact details on "
                    "file.",
    "hardship options": "Borrowers facing a temporary loss of income can apply for a deferral of up to two installments "
                        "or a modification that extends the term. Requests are reviewed within ten business days and a "
                        "decision letter is sent.",
    "payment deferral": "A deferral moves up to two installments to the end of the term. Interest continues to accrue. "
                        "A deferral is available once in any twelve-month period.",
    "loan modification": "A modification changes the term or the payment schedule permanently. It needs proof of income "
                         "and a signed agreement, and it may change the total interest paid.",
    "adverse action notice": "When an application is denied, the applicant receives an adverse action notice within 30 "
                             "days stating the principal reasons and the right to a free copy of the credit report used.",
    "application status": "Applications move through received, in review, decision and funding. Most decisions are made "
                          "within five business days once all documents are received.",
    "required documents": "Applications need proof of identity, proof of income for the last two months and, for secured "
                          "loans, details of the collateral. Missing documents pause the review.",
    "disputes": "A borrower can dispute a fee, a payment record or information reported to a credit bureau. Disputes "
                "are acknowledged within five business days and resolved within 30 days.",
    "credit reporting": "Payments are reported to the credit bureaus monthly. A payment more than 30 days past due is "
                        "reported as late; payments inside the grace period are not.",
    "prepayment": "Loans can be paid off early without a prepayment penalty. Extra payments go to principal once the "
                  "current installment and fees are paid.",
    "interest calculation": "Interest accrues daily on the outstanding principal using the annual rate divided by 365. "
                            "The installment covers interest first, then principal.",
    "changing due date": "A borrower may move the due date once per year by up to fifteen days, if the account is "
                         "current. The first installment after the change may be prorated.",
    "privacy and data sharing": f"{ORG} shares customer information only as described in its privacy notice. Staff and "
                                "assistants may discuss an account only with the account holder or authorised staff.",
    "account security": "Customers sign in with multi-factor authentication. Staff never ask for a full password. "
                        "Suspicious contact can be reported through the secure message centre.",
    "collections process": "After 30 days past due an account moves to early collections, where a servicing specialist "
                           "contacts the borrower to agree a plan before any further steps.",
    "statements": "Monthly statements list the installment, the due date, payments received, fees and the remaining "
                  "balance. Statements are available online for seven years.",
    "portfolio servicing standards": "Loan officers review delinquent accounts in their portfolio weekly, record every "
                                     "contact in the servicing notes, and escalate hardship requests within two days.",
}
VARIANTS = ("Overview", "How to", "Timing and your rights")


@lru_cache(maxsize=1)
def articles() -> list[dict]:
    out = []
    for i, (topic, body) in enumerate(TOPICS.items()):
        for j, v in enumerate(VARIANTS):
            extra = {0: "This article summarises the policy.",
                     1: "To start, use the secure message centre or ask the assistant; staff confirm the request in "
                        "writing.",
                     2: "Time limits are counted in business days unless stated; written requests are dated on receipt."}[j]
            out.append({"id": f"kb-{3 * i + j + 1:03d}", "title": f"{topic.title()}: {v}", "text": f"{body} {extra}"})
    return out


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


@lru_cache(maxsize=1)
def _index():
    docs = [_tok(a["title"] + " " + a["text"]) for a in articles()]
    df = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    avg = sum(len(d) for d in docs) / len(docs)
    return docs, df, avg


def bm25(query: str, docs, df, avg, k1=1.5, b=0.75) -> list[float]:
    q = _tok(query)
    n = len(docs)
    scores = []
    for d in docs:
        s = 0.0
        for t in q:
            if t not in df:
                continue
            tf = d.count(t)
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


def search(query: str, k: int = 2) -> list[dict]:
    docs, df, avg = _index()
    sc = bm25(query, docs, df, avg)
    order = sorted(range(len(sc)), key=lambda i: (-sc[i], i))[:k]
    arts = articles()
    return [{"id": arts[i]["id"], "title": arts[i]["title"], "passage": arts[i]["text"]} for i in order if sc[i] > 0]
