"""Phase 6 verification: online classifiers + refusal copy.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/debug_online_guardrails.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guardrails import (  # noqa: E402
    _sentence_count,
    advice_refusal,
    detect_pii,
    is_advice_request,
    is_performance_request,
    performance_refusal,
    pii_refusal,
    refusal_for,
)

failures: list[str] = []

print("=" * 78)
print("PHASE 6 VERIFICATION - online guardrails")
print("=" * 78)

# --- 1. advice requests: the 4 spec phrasings must be True ----------------
print("\n-- is_advice_request --")
ADVICE_TRUE = [
    "Should I buy HDFC Large Cap?",
    "best mutual fund for me",
    "which fund should I choose",
    "is it a good scheme",
]
ADVICE_TRUE += [
    "help me choose a mutual fund",
    "how should I split 50000 across two funds",
    "I want to start investing, where do I begin",
    "is HDFC Balanced Advantage Fund a good scheme for me",
    "what should I do with my lump sum",
    "rebalance my portfolio please",
    "what is my portfolio diversification like",
]
for q in ADVICE_TRUE:
    got = is_advice_request(q)
    ok = got is True
    print(f"  [{'OK' if ok else 'FAIL'}] {q!r:<42} -> {got}")
    if not ok:
        failures.append(f"advice should be True: {q!r}")

# --- 2. factual questions must be False -----------------------------------
print("\n-- factual questions must NOT be refused --")
FACTUAL_FALSE = [
    "what is the expense ratio of HDFC ELSS",
    "What is the exit load of HDFC Large Cap Fund?",
    "Is there a lock-in period on HDFC Small Cap Fund?",
    "what is the minimum SIP amount for HDFC Flexi Cap",
    "what is the riskometer level of HDFC Balanced Advantage Fund",
    "which benchmark does HDFC Large Cap Fund use",
    "who is the RTA for HDFC ELSS Tax Saver Fund",
    "what is the NAV of HDFC Large Cap Fund",
    "expense ratio",
    "lock in period",
    "benchmark of HDFC Small Cap Fund",
    "what documents are published for HDFC Large Cap",
    "stamp duty on HDFC Flexi Cap",
    "portfolio turnover ratio of HDFC Small Cap",
    "what is the AUM of HDFC ELSS Tax Saver Fund",
    "investment objective of HDFC Large Cap Fund",
    "what is the stamp duty on HDFC Flexi Cap",
    "scheme code of HDFC ELSS Tax Saver Fund",
    "launch date of HDFC Balanced Advantage Fund",
]
for q in FACTUAL_FALSE:
    got_advice = is_advice_request(q)
    got_perf = is_performance_request(q)
    ok = got_advice is False and got_perf is False
    print(f"  [{'OK' if ok else 'FAIL'}] {q!r:<52} advice={got_advice} perf={got_perf}")
    if not ok:
        failures.append(f"factual question misrouted: {q!r}")

# --- 3. performance requests ----------------------------------------------
print("\n-- is_performance_request --")
PERF_TRUE = [
    "best performing fund",
    "what are the returns of HDFC Large Cap Fund",
    "how much will 10000 grow in HDFC Large Cap",
    "does HDFC ELSS outperform Nifty 500",
    "what is the CAGR of HDFC Small Cap Fund",
    "compare returns of HDFC Flexi Cap and HDFC Large Cap",
    "since inception return of HDFC Large Cap",
    "top performing HDFC scheme",
    "what is the 1 year return",
    "tax saving plus returns in ELSS",
]
for q in PERF_TRUE:
    got = is_performance_request(q)
    ok = got is True
    print(f"  [{'OK' if ok else 'FAIL'}] {q!r:<58} -> {got}")
    if not ok:
        failures.append(f"performance should be True: {q!r}")

# --- 4. refusal copy shape ------------------------------------------------
print("\n-- refusal builders --")
BUILDERS = [
    ("advice", advice_refusal("should i buy")),
    ("performance", performance_refusal("what are the returns")),
    ("pii", pii_refusal(detect_pii("my pan is ABCDE1234F"))),
]
for name, (msg, links) in BUILDERS:
    n = _sentence_count(msg)
    ok_len = n <= 3
    ok_link = isinstance(links, list) and len(links) >= 1 and all(
        {"label", "url"} <= set(l) for l in links
    )
    print(f"  [{'OK' if ok_len else 'FAIL'}] {name:<12} {n} sentence(s)")
    print(f"  [{'OK' if ok_link else 'FAIL'}] {name:<12} link(s): "
          f"{[l['label'][:38] for l in links]}")
    if not ok_len:
        failures.append(f"{name} refusal is {n} sentences (max 3)")
    if not ok_link:
        failures.append(f"{name} refusal lacks a well-formed link")
    print(f"       message: {msg[:100]}...")

# --- 5. PII refusal must not echo the value -------------------------------
print("\n-- pii_refusal must not echo any part of the input --")
PII_INPUTS = [
    ("my pan is ABCDE1234F", "ABCDE1234F"),
    ("mail me at ravi.kumar@example.com", "ravi.kumar@example.com"),
    ("aadhaar 2345 6789 0123", "2345 6789 0123"),
    ("call me on +91 98765 43210", "98765 43210"),
]
for raw, secret in PII_INPUTS:
    hit = detect_pii(raw)
    msg, _ = pii_refusal(hit)
    leaked = secret in msg
    print(f"  [{'OK' if not leaked else 'FAIL'}] no echo of {secret!r}")
    if leaked:
        failures.append(f"pii_refusal echoed {secret!r}")

# --- 6. refusal_for routing -----------------------------------------------
print("\n-- refusal_for routing --")
ROUTES = [
    ("what is the expense ratio of HDFC ELSS", None),
    ("Should I buy HDFC Large Cap?", "advice"),
    ("what are the returns of HDFC Small Cap Fund", "performance"),
    ("my pan is ABCDE1234F", "pii"),
]
for q, expected in ROUTES:
    result = refusal_for(q)
    if expected is None:
        ok = result is None
        label = "None (answered normally)"
    else:
        ok = result is not None
        label = expected
    print(f"  [{'OK' if ok else 'FAIL'}] {q!r:<48} -> {label}")
    if not ok:
        failures.append(f"refusal_for({q!r}) expected {expected}")

# PII wins over everything else
result = refusal_for("Should I buy HDFC Large Cap? my pan is ABCDE1234F")
msg = result[0] if result else ""
ok = "PAN" in msg
print(f"  [{'OK' if ok else 'FAIL'}] PII takes precedence over advice")
if not ok:
    failures.append("PII should be checked before advice")

# --- 7. no advice language leaks into refusals ----------------------------
print("\n-- refusals must not give advice --")
BANNED_ADVICE = [
    r"\byou should\b", r"\bi recommend\b", r"\bwe suggest\b",
    r"\bis a good (fund|scheme|choice)\b", r"\bbest (fund|scheme) is\b",
    r"\bconsider buying\b", r"\bI would suggest\b",
]
for name, (msg, _) in BUILDERS:
    for pat in BANNED_ADVICE:
        if re.search(pat, msg, re.I):
            failures.append(f"{name} refusal contains advice pattern {pat!r}")
            print(f"  [FAIL] {name}: {pat!r}")
print("  [OK] no advice language in any refusal")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 6 ASSERTIONS PASSED")
print("=" * 78)