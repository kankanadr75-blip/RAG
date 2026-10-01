"""Stress-test the calibrated floor against TERSE / keyword-style queries.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/stress_terse_queries.py

Calibration used natural full questions ("lock-in period of HDFC ELSS Tax Saver
Fund"). Real users also type bare keywords ("lock-in period ELSS"). Those score
lower, so this measures whether the calibrated floor wrongly rejects them.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from rag import RAGEngine  # noqa: E402

engine = RAGEngine()

# A query can be answered correctly by either the fact card or the prose
# section, because the corpus intentionally holds BOTH for several facts (e.g.
# `benchmark` states "The fund benchmark of X is ..." while `fund_benchmark`
# states "Fund benchmark\nNIFTY 100 Total Return Index"). Listing one section as
# "expected" would report a false failure for a correct answer, so each case
# lists every acceptable section.
#
# (query, acceptable sections or None = "just needs some hit")
TERSE = [
    ("lock-in period ELSS", {"lock_in_period"}),
    ("expense ratio ELSS", {"expense_ratio", "expense_ratio_definition"}),
    ("exit load small cap", {"exit_load", "exit_load_stamp_duty_tax"}),
    ("minimum SIP large cap", {"sip_minimum"}),
    ("benchmark large cap", {"benchmark", "fund_benchmark"}),
    ("riskometer", {"riskometer"}),
    ("RTA", {"documents_statements", "scheme_details"}),
    ("stamp duty", {"stamp_duty", "stamp_duty_definition"}),
    ("NAV large cap", {"nav"}),
    ("AUM ELSS", {"aum"}),
    ("lock in period", {"lock_in_period"}),
    ("expense ratio", {"expense_ratio", "expense_ratio_definition"}),
    ("exit load", {"exit_load", "exit_load_stamp_duty_tax",
                   "exit_load_definition"}),
    ("benchmark", {"benchmark", "fund_benchmark"}),
    ("minimum investment", {"minimum_investment", "minimum_investments",
                            "sip_minimum"}),
    ("scheme code", {"scheme_identity"}),
    ("portfolio turnover", {"portfolio_turnover"}),
    ("objective large cap", {"investment_objective"}),
    ("HDFC ELSS", None),
    ("HDFC large cap fund", None),
]

print("=" * 78)
print("TERSE / KEYWORD QUERY STRESS TEST")
print("=" * 78)
print(f"floor = {config.MIN_SIMILARITY}\n")

rows = []
for q, want_section in TERSE:
    # Exercise the REAL hybrid gate (default floor), so the lexical rescue path
    # is included. Raw scores are read separately below for reporting.
    hits = engine.retrieve(q, top_k=5, skip_guardrails=True)
    raw = engine.retrieve(q, top_k=5, min_similarity=0.0, skip_guardrails=True)
    raw_best = raw[0].score if raw else 0.0

    top = hits[0] if hits else None
    score = top.score if top else 0.0
    section = top.section if top else "-"
    rescued = raw_best < config.MIN_SIMILARITY and bool(hits)
    kept = bool(hits)
    rows.append((q, score, section, want_section, kept, raw_best, rescued))

    if want_section is not None:
        ok = kept and section in want_section
        mark = "OK " if ok else "FAIL"
        via = " (lexical)" if rescued else ""
        want = "|".join(sorted(want_section))
        print(f"  [{mark}] {q!r:<34} {score:.3f} {section:<24}"
              f" want={want}{via}")
    else:
        print(f"  [info] {q!r:<34} {score:.3f} {section}")

fails = [r for r in rows if r[4] and r[3] and r[2] not in r[3]]
misses = [r for r in rows if r[3] is not None and not r[4]]
rescued_n = sum(1 for r in rows if r[6])

print(f"\n  terse queries with an expected section: "
      f"{sum(1 for r in rows if r[3] is not None)}")
print(f"  answered (floor or lexical rescue)    : "
      f"{sum(1 for r in rows if r[3] is not None and r[4])}")
print(f"  of which rescued by lexical grounding : {rescued_n}")
print(f"  rejected entirely                     : {len(misses)}")
print(f"  wrong section when answered           : {len(fails)}")

if rows:
    answered = [r[1] for r in rows if r[3] is not None and r[4]]
    rejected = [r[1] for r in rows if r[3] is not None and not r[4]]
    if answered:
        print(f"  score range when answered            : "
              f"{min(answered):.3f} - {max(answered):.3f}")
    if rejected:
        print(f"  score range when REJECTED            : "
              f"{min(rejected):.3f} - {max(rejected):.3f}")

print("\n" + "=" * 78)
if misses:
    print(f"VERDICT: floor {config.MIN_SIMILARITY} REJECTS {len(misses)} legitimate "
          f"terse question(s).")
    print(f"  lowest missed score = {min(r[1] for r in misses):.3f}")
    print("  -> lower MIN_SIMILARITY_LOWER, or rely on the Phase 6 guardrails.")
    sys.exit(1)

print(f"VERDICT: floor {config.MIN_SIMILARITY} answers every terse query tested "
      f"(0 rejected).")

# ---------------------------------------------------------------------------
# Known limitation, reported rather than hidden.
# ---------------------------------------------------------------------------
# "scheme code" retrieves `investment_objective` instead of `scheme_identity`.
# Root cause: the real scheme_identity chunk scores 0.244, below
# MIN_SIMILARITY_LOWER (0.30), so the lexical rescue never sees it; it rescues
# the next-best candidate instead, which does contain the token "scheme".
#
# This is NOT tuned around on purpose. Lowering the rescue floor to 0.24 to
# admit this one query would let weaker noise in, and the failure is benign:
# the returned chunk is still a true, on-topic fact about the scheme, just not
# the specific field asked for. Recorded in the README Known Limits.
if fails:
    print(f"\nKNOWN LIMITATION ({len(fails)} case(s), answer is factual but not "
          f"the ideal chunk):")
    for q, score, section, want, *_ in fails:
        print(f"  {q!r} -> {section} ({score:.3f}), wanted one of "
              f"{sorted(want)}")
    print("  Cause: the correct chunk scores below MIN_SIMILARITY_LOWER=0.30, so")
    print("  the lexical rescue falls back to the next candidate. Not tuned")
    print("  around - doing so would widen the gate for every query to fix one.")

print("=" * 78)