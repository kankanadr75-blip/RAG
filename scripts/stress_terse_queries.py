"""Stress-test the calibrated floor against TERSE / keyword-style queries.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/stress_terse_queries.py

Calibration used natural full questions ("lock-in period of HDFC ELSS Tax Saver
Fund"). Real users also type bare keywords ("lock-in period ELSS"). Those score
lower, so this measures whether the calibrated floor wrongly rejects them.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from rag import RAGEngine  # noqa: E402

engine = RAGEngine()


@dataclass(frozen=True)
class Case:
    """One terse query and what counts as correct for it.

    Three expectation kinds, because conflating them is how a suite ends up
    printing a red FAIL and exiting 0:

    ``expect``   - sections that legitimately answer this query. The corpus
                   intentionally holds BOTH a fact card and a prose section for
                   several facts (`benchmark` states "The fund benchmark of X
                   is ..." while `fund_benchmark` states "Fund benchmark\\nNIFTY
                   100 Total Return Index"), so a case lists every acceptable
                   section. Answering with anything else is a REAL retrieval
                   defect and fails the run.

    ``any_hit``  - the query must retrieve something, but the section is not
                   assertable (used where any of several chunks would do).

    ``ambiguous``- the query does not identify enough to have one right answer,
                   so asserting a section would be asserting an implementation
                   detail of the embedding model. Reported, never fatal, and
                   `why` is mandatory so the boundary is justified in place
                   rather than explained in a footnote that can drift.
    """

    query: str
    expect: frozenset[str] = field(default_factory=frozenset)
    any_hit: bool = False
    ambiguous: bool = False
    why: str = ""


def _wrap(text: str, width: int) -> list[str]:
    """Greedy wrap, so a long justification prints as prose not one long line."""
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


TERSE = [
    Case("lock-in period ELSS", frozenset({"lock_in_period"})),
    Case("expense ratio ELSS", frozenset({"expense_ratio",
                                          "expense_ratio_definition"})),
    Case("exit load small cap", frozenset({"exit_load",
                                           "exit_load_stamp_duty_tax"})),
    Case("minimum SIP large cap", frozenset({"sip_minimum"})),
    Case("benchmark large cap", frozenset({"benchmark", "fund_benchmark"})),
    Case("riskometer", frozenset({"riskometer"})),
    Case("RTA", frozenset({"documents_statements", "scheme_details"})),
    Case("stamp duty", frozenset({"stamp_duty",
                                  "stamp_duty_definition"})),
    Case("NAV large cap", frozenset({"nav"})),
    Case("AUM ELSS", frozenset({"aum"})),
    Case("lock in period", frozenset({"lock_in_period"})),
    Case("expense ratio", frozenset({"expense_ratio",
                                     "expense_ratio_definition"})),
    Case("exit load", frozenset({"exit_load", "exit_load_stamp_duty_tax",
                                 "exit_load_definition"})),
    Case("benchmark", frozenset({"benchmark", "fund_benchmark"})),
    Case("minimum investment", frozenset({"minimum_investment",
                                          "minimum_investments",
                                          "sip_minimum"})),
    # AMBIGUOUS, not a retrieval defect - see `why`. Measured, not assumed.
    Case("scheme code",
         ambiguous=True,
         why="names no scheme, and the corpus holds 5 scheme_identity chunks "
             "with 5 different codes (119018/118955/119060/130503/118968). "
             "All 5 score 0.162-0.244, below MIN_SIMILARITY_LOWER=0.30, so no "
             "threshold admits the RIGHT one - the top scorer wins by embedding "
             "noise. Asserting a section here would assert noise, and admitting "
             "one would answer with the wrong scheme's code (119060 for ELSS "
             "when the user asked in general), i.e. a confident error instead "
             "of a non-answer. Reclassifying the query needs a scope-"
             "clarification affordance, not a threshold."),
    Case("portfolio turnover", frozenset({"portfolio_turnover"})),
    Case("objective large cap", frozenset({"investment_objective"})),
    Case("HDFC ELSS", any_hit=True),
    Case("HDFC large cap fund", any_hit=True),
]

print("=" * 78)
print("TERSE / KEYWORD QUERY STRESS TEST")
print("=" * 78)
print(f"floor = {config.MIN_SIMILARITY}\n")

rows = []
for case in TERSE:
    q = case.query
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
    rows.append((case, score, section, kept, raw_best, rescued))

    via = " (lexical)" if rescued else ""
    if case.ambiguous:
        # Never "FAIL". Not assertable, so reporting a pass/fail here would be
        # reporting a verdict on the embedding model, not on the system.
        print(f"  [note] {q!r:<34} {score:.3f} {section:<24} ambiguous{via}")
    elif case.any_hit:
        mark = "OK " if kept else "FAIL"
        print(f"  [{mark}] {q!r:<34} {score:.3f} {section}")
    else:
        ok = kept and section in case.expect
        mark = "OK " if ok else "FAIL"
        want = "|".join(sorted(case.expect))
        print(f"  [{mark}] {q!r:<34} {score:.3f} {section:<24}"
              f" want={want}{via}")

# Classification. A wrong section is a defect only where a right section was
# assertable in the first place.
fails = [r for r in rows
         if r[3] and not r[0].ambiguous and not r[0].any_hit
         and r[2] not in r[0].expect]
misses = [r for r in rows
          if r[3] is False and (r[0].expect or r[0].any_hit)]
rescued_n = sum(1 for r in rows if r[5])
asserted = [r for r in rows if not r[0].ambiguous and r[0].expect]
ambiguous_n = sum(1 for r in rows if r[0].ambiguous)

print(f"\n  cases with an assertable section        : {len(asserted)}")
print(f"  answered (floor or lexical rescue)      : "
      f"{sum(1 for r in asserted if r[3])}")
print(f"  of which rescued by lexical grounding   : {rescued_n}")
print(f"  rejected entirely (REGRESSION)          : {len(misses)}")
print(f"  wrong section when answered (REGRESSION): {len(fails)}")
print(f"  ambiguous by design (not asserted)      : {ambiguous_n}")

if asserted:
    answered = [r[1] for r in asserted if r[3]]
    rejected = [r[1] for r in asserted if not r[3]]
    if answered:
        print(f"  score range when answered              : "
              f"{min(answered):.3f} - {max(answered):.3f}")
    if rejected:
        print(f"  score range when REJECTED              : "
              f"{min(rejected):.3f} - {max(rejected):.3f}")

print("\n" + "=" * 78)

if misses:
    print(f"VERDICT: FAIL - floor {config.MIN_SIMILARITY} REJECTS {len(misses)} "
          f"legitimate terse question(s).")
    print(f"  lowest missed score = {min(r[1] for r in misses):.3f}")
    print("  -> lower MIN_SIMILARITY_LOWER, or rely on the Phase 6 guardrails.")
    for case, score, section, *_ in misses:
        print(f"    {case.query!r} -> nothing retrieved")
    sys.exit(1)

if fails:
    print(f"VERDICT: FAIL - {len(fails)} terse question(s) answered with the "
          f"wrong section.")
    print("  These queries have exactly one right section, so returning a")
    print("  different one is a genuine retrieval defect, not a boundary.")
    for case, score, section, *_ in fails:
        print(f"    {case.query!r} -> {section} ({score:.3f}), wanted one of "
              f"{sorted(case.expect)}")
    sys.exit(1)

print(f"VERDICT: PASS - every assertable terse query is answered by an "
      f"acceptable section.")
print(f"  {len(asserted)} asserted, 0 rejected, 0 wrong section, "
      f"{ambiguous_n} ambiguous by design (reported below, not scored).")

# ---------------------------------------------------------------------------
# By-design boundaries, reported rather than hidden.
# ---------------------------------------------------------------------------
# "scheme code" is the one ambiguous query. It is NOT a retrieval defect and
# was previously mis-documented as a benign "wrong chunk" case. Corrected
# account, from measurement:
#
#   * The lexical classifier is NOT at fault. "scheme code" is a domain term
#     and matches verbatim in the scheme_identity chunk ("Groww scheme code:
#     119060"), so _lexical_grounding returns grounded=True. It identified the
#     right chunk and was then overruled by the score floor.
#   * All 5 scheme_identity chunks score 0.162-0.244, every one below
#     MIN_SIMILARITY_LOWER=0.30. The spread is embedding noise, not signal:
#     the cards are structurally identical and are dominated by ISINs, dates
#     and "Direct plan, Growth option", which embed weakly against a 2-token
#     query. No threshold admits the RIGHT one.
#   * End to end the user gets a non-answer ("The provided source excerpts do
#     not state the scheme code...") behind an arbitrarily chosen scheme's
#     citation. That is a non-answer, NOT the "true, on-topic fact" an earlier
#     version of this comment claimed.
#   * Admitting a scheme_identity chunk would return 119060 (ELSS) for a
#     question that named no scheme. That trades a non-answer for a confident
#     error, so the current behaviour is the safer one.
#
# Fixing this needs a scope-clarification affordance ("which scheme?"), which
# is a product change, not a threshold. Tracked in README Known Limits.
amb = [r for r in rows if r[0].ambiguous]
if amb:
    print(f"\nBY-DESIGN BOUNDARY ({len(amb)} case(s), not scored, not a defect):")
    for case, score, section, *_ in amb:
        print(f"  {case.query!r} -> {section} ({score:.3f})")
        for line in _wrap(case.why, 70):
            print(f"      {line}")


print("=" * 78)