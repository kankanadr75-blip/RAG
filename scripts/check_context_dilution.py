"""Does TOP_K=10 cause cross-scheme bleed?

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/check_context_dilution.py

Raising TOP_K from 5 to 10 widens recall, but it also puts the *same fact type
for all five schemes* into one context window. For "expense ratio of HDFC ELSS"
that means five near-identical cards - 1.21, 1.03, 0.77, 0.78, 0.78 - all in the
prompt at once. The failure mode this guards against is the model reading the
wrong card and answering confidently with another scheme's number.

Verified facts (implementation.md §0.3, as_of 30-Sep-2026, Direct Growth):
  Large Cap 1.03 | Flexi Cap 0.77 | ELSS 1.21 | Small Cap 0.78 |
  Balanced Advantage 0.78
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from rag import RAGEngine  # noqa: E402

failures: list[str] = []
engine = RAGEngine()

print("=" * 78)
print(f"CONTEXT DILUTION CHECK  (TOP_K = {config.TOP_K})")
print("=" * 78)

# The five expense ratios, all present in context simultaneously at TOP_K=10.
# Any answer containing a foreign scheme's number is a bleed.
ALL_RATIOS = {
    "1.21": "ELSS",
    "1.03": "Large Cap",
    "0.77": "Flexi Cap",
    "0.78": "Small Cap / Balanced Advantage",
}

# (question, scheme whose figure is correct, correct figure, figures that must
#  NOT appear)
EXPENSE = [
    ("What is the expense ratio of HDFC ELSS Tax Saver Fund?",
     "ELSS", "1.21", ["1.03", "0.77"]),
    ("What is the expense ratio of HDFC Large Cap Fund?",
     "Large Cap", "1.03", ["1.21", "0.77"]),
    ("What is the expense ratio of HDFC Flexi Cap Fund?",
     "Flexi Cap", "0.77", ["1.21", "1.03"]),
    ("What is the expense ratio of HDFC Small Cap Fund?",
     "Small Cap", "0.78", ["1.21", "1.03"]),
    ("What is the expense ratio of HDFC Balanced Advantage Fund?",
     "Balanced Advantage", "0.78", ["1.21", "1.03"]),
]

# --- 1. every scheme resolves to its OWN figure ------------------------
print("\n-- each scheme gets its own expense ratio --")
for question, scheme, right, forbidden in EXPENSE:
    answer = engine.answer(question)
    body = answer.text
    has_right = right in body
    # A foreign figure is only a bleed if it is presented as *this* scheme's
    # answer. "base expense ratio of 0.97%" style mentions of a second, correct
    # number are legitimate, so only flag the specific competing TER ratios.
    bled = [f for f in forbidden if f in body]

    ok = has_right and not bled
    print(f"  [{'OK' if ok else 'FAIL'}] {scheme:<22} want={right:<5} "
          f"foreign={bled or 'none'}")
    if not ok:
        failures.append(
            f"{question!r}: want {right}, got {bled or 'no correct figure'}. "
            f"Answer: {body[:130]!r}"
        )

    # The citation must be the right scheme's page, not a neighbour's.
    primary = answer.primary_source
    if primary is not None:
        slug_ok = True
        expected_slug = {
            "ELSS": "elss", "Large Cap": "large-cap", "Flexi Cap": "equity",
            "Small Cap": "small-cap", "Balanced Advantage": "balanced",
        }[scheme]
        slug_ok = expected_slug in primary.url
        print(f"       cited: {primary.url.rsplit('/', 1)[-1][:44]}"
              f"{'' if slug_ok else '  <-- WRONG SCHEME'}")
        if not slug_ok:
            failures.append(
                f"{question!r} cited {primary.url}, expected {expected_slug}"
            )

# --- 2. the answer must name the right scheme --------------------------
print("\n-- answers name the scheme that was asked about --")
NAME_CASES = [
    ("What is the exit load of HDFC ELSS Tax Saver Fund?",
     ["ELSS", "Tax Saver"], ["Balanced Advantage", "15%"]),
    ("What is the exit load of HDFC Balanced Advantage Fund?",
     ["Balanced Advantage"], ["Tax Saver"]),
    ("Is there a lock-in period on HDFC ELSS Tax Saver Fund?",
     ["ELSS"], []),
    ("What is the lock-in period of HDFC Large Cap Fund?",
     ["Large Cap"], []),
    ("What is the minimum SIP for HDFC ELSS Tax Saver Fund?",
     ["ELSS"], []),
    ("Which benchmark does HDFC Small Cap Fund use?",
     ["Small Cap", "BSE 250"], ["NIFTY 100", "NIFTY 500"]),
    ("What is the RTA for HDFC Flexi Cap Fund?",
     ["Flexi Cap", "CAMS"], []),
]
for question, expected, forbidden in NAME_CASES:
    answer = engine.answer(question)
    body = answer.text
    missing = [e for e in expected if e.lower() not in body.lower()]
    bled = [f for f in forbidden if f.lower() in body.lower()]
    ok = not missing and not bled
    print(f"  [{'OK' if ok else 'FAIL'}] {question[:50]:<52} "
          f"missing={missing or 'none'} foreign={bled or 'none'}")
    if not ok:
        failures.append(
            f"{question!r} missing={missing} foreign={bled}. "
            f"Answer: {body[:130]!r}"
        )

# --- 3. chunk count actually increased --------------------------------
print("\n-- TOP_K is really in effect --")
hits = engine.retrieve("What is the expense ratio of HDFC ELSS Tax Saver Fund?",
                       skip_guardrails=True)
ok = len(hits) == config.TOP_K
print(f"  [{'OK' if ok else 'FAIL'}] {len(hits)} chunks retrieved "
      f"(TOP_K={config.TOP_K})")
if not ok:
    failures.append(f"expected {config.TOP_K} chunks, got {len(hits)}")

distinct_schemes = {h.scheme_slug for h in hits}
print(f"  [info] {len(distinct_schemes)} distinct schemes in context - this is "
      f"the dilution the test above guards against")
sections = [h.section for h in hits]
same_section = sum(1 for s in sections if s == "expense_ratio")
print(f"  [info] {same_section} of {len(hits)} chunks are the SAME field "
      f"(expense_ratio) across different schemes")

# --- 4. terse queries still resolve ----------------------------------
print("\n-- terse single-fact queries unaffected by the wider context --")
TERSE = [
    ("expense ratio ELSS", "1.21"),
    ("expense ratio large cap", "1.03"),
    ("exit load small cap", "1%"),
    ("AUM ELSS", None),
    ("riskometer", None),
]
for question, want in TERSE:
    answer = engine.answer(question)
    ok = not answer.refused
    if want:
        ok = ok and want in answer.text
    print(f"  [{'OK' if ok else 'FAIL'}] {question!r:<28} "
          f"refused={answer.refused}"
          + (f" contains {want}={want in answer.text}" if want else ""))
    if not ok:
        failures.append(f"terse {question!r} -> {answer.text[:110]!r}")

# --- 5. context size is within the model's window --------------------
print("\n-- context fits the model window --")
from rag import _build_context  # noqa: E402

hits = engine.retrieve("What is the expense ratio and exit load of HDFC ELSS?",
                       skip_guardrails=True)
context = _build_context(hits)
# ~4 chars/token is a safe upper bound for this mix of text and URLs.
approx_tokens = len(context) // 4
limit = 131072
ok = approx_tokens < limit * 0.1
print(f"  [{'OK' if ok else 'FAIL'}] context ~{len(context)} chars "
      f"(~{approx_tokens} tokens) vs {limit:,} window "
      f"({approx_tokens / limit * 100:.2f}%)")
if not ok:
    failures.append(f"context {approx_tokens} tokens is too large")

# --- 6. no advice or performance language leaked in ------------------
print("\n-- answer policy still holds at the wider context --")
BANNED = [
    r"\byou should\b", r"\bi recommend\b", r"\bwe suggest\b",
    r"\bis a good (fund|scheme|choice)\b", r"\bbest (fund|scheme) is\b",
    r"\bconsider buying\b", r"\bI would suggest\b",
    r"\bI would\b", r"\bideally you\b",
]
leaks = 0
for question, _, _, _ in EXPENSE:
    answer = engine.answer(question)
    for pattern in BANNED:
        if re.search(pattern, answer.text, re.I):
            failures.append(f"{question!r} contains {pattern!r}")
            leaks += 1
print(f"  [{'OK' if not leaks else 'FAIL'}] {len(EXPENSE)} answers, "
      f"{leaks} policy leak(s)")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"RESULT: NO CROSS-SCHEME BLEED AT TOP_K={config.TOP_K}")
print("=" * 78)
