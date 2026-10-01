"""Calibrate config.MIN_SIMILARITY from observed score distributions.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/calibrate_floor.py

The provisional 0.18 was a guess. This measures the actual separation between
in-domain and off-topic queries so the floor is chosen from data, and records
the evidence for the README (Phase 7 DoD item 5).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from rag import RAGEngine  # noqa: E402

engine = RAGEngine(verbose=False)

# In-domain: real questions the assistant must answer. Grouped by the 7 target
# fact types plus the other sections that carry real facts.
IN_DOMAIN = {
    "expense_ratio": [
        "what is the expense ratio of HDFC ELSS Tax Saver Fund",
        "expense ratio of HDFC Large Cap Fund",
        "charges applied by HDFC Flexi Cap Fund",
        "base expense ratio of HDFC Small Cap Fund",
    ],
    "exit_load": [
        "exit load on HDFC Small Cap Fund",
        "is there any exit load on HDFC ELSS Tax Saver",
        "redemption charge on HDFC Balanced Advantage Fund",
    ],
    "lock_in": [
        "lock-in period of HDFC ELSS Tax Saver Fund",
        "how long must I stay invested in HDFC ELSS",
        "can I redeem HDFC Large Cap Fund immediately",
    ],
    "minimum": [
        "minimum SIP amount for HDFC Large Cap Fund",
        "how much can I start investing in HDFC Flexi Cap",
        "smallest first investment in HDFC Small Cap Fund",
        "minimum additional investment HDFC Balanced Advantage",
    ],
    "riskometer": [
        "riskometer level of HDFC Flexi Cap Fund",
        "what is the risk rating of HDFC Large Cap Fund",
        "how risky is HDFC Small Cap Fund",
    ],
    "benchmark": [
        "benchmark used by HDFC Balanced Advantage Fund",
        "which index does HDFC Large Cap Fund track",
        "benchmark of HDFC ELSS Tax Saver",
    ],
    "documents": [
        "who is the RTA for HDFC ELSS Tax Saver Fund",
        "where can I download the factsheet of HDFC Large Cap",
        "how do I get my account statement for HDFC Flexi Cap",
    ],
    "other_facts": [
        "investment objective of HDFC Large Cap Fund",
        "stamp duty on HDFC Small Cap Fund",
        "portfolio turnover ratio of HDFC Large Cap Fund",
        "AUM of HDFC ELSS Tax Saver Fund",
        "NAV of HDFC Flexi Cap Fund",
        "launch date of HDFC Balanced Advantage Fund",
        "scheme code and ISIN of HDFC Large Cap Fund",
        "custodian for HDFC Small Cap Fund",
        "is SIP allowed in HDFC ELSS Tax Saver Fund",
    ],
}

# Off-topic: must all return []. Deliberately includes finance-adjacent
# questions, which are the hard cases - "which crypto" shares vocabulary with
# "which scheme" and so is a genuine test of the floor, not a freebie.
OFF_TOPIC = [
    "which crypto should I buy",
    "bitcoin price prediction 2027",
    "best stocks to trade on the NSE",
    "what is the weather in Mumbai tomorrow",
    "what is the population of Tokyo",
    "how do I cook biryani",
    "who won the 2024 world cup",
    "python list comprehension syntax",
    "how to open a bank account online",
    "what is the GDP of India in 2025",
    "cricket score India vs Australia",
    "how do I apply for a passport",
    "best laptop under 50000",
    "what time does the market open",
    "how to file income tax return",
    "which car should I buy in India",
    "what is the price of gold today",
    "how to learn python programming",
    "tell me a joke",
    "what is the capital of France",
]

# Some off-topic queries overlap finance vocabulary but are still refusals.
# Recorded separately so the floor is tuned on *unanswered* questions, which is
# what the floor actually governs.
OFF_TOPIC_FINANCE = [
    "which crypto should I buy",
    "best stocks to trade on the NSE",
    "bitcoin price prediction 2027",
    "what is the price of gold today",
    "what time does the market open",
]

print("=" * 78)
print("MIN_SIMILARITY CALIBRATION")
print("=" * 78)

in_rows = []
for group, questions in IN_DOMAIN.items():
    for q in questions:
        hits = engine.retrieve(q, top_k=5, min_similarity=0.0,
                               skip_guardrails=True)
        if not hits:
            in_rows.append((group, q, 0.0, 0.0))
            continue
        in_rows.append((group, q, hits[0].score,
                        max(h.score for h in hits)))

off_rows = []
for q in OFF_TOPIC:
    hits = engine.retrieve(q, top_k=5, min_similarity=0.0,
                           skip_guardrails=True)
    best = hits[0].score if hits else 0.0
    off_rows.append((q, best))

print(f"\nIn-domain queries: {len(in_rows)}   Off-topic queries: {len(off_rows)}")

in_tops = [r[2] for r in in_rows]
off_bests = [r[1] for r in off_rows]

print("\n--- per-group top-1 score (should be comfortably high) ---")
for group, questions in IN_DOMAIN.items():
    scores = [r[2] for r in in_rows if r[0] == group]
    flag = "OK " if scores and min(scores) >= 0.45 else "LOW"
    print(f"  [{flag}] {group:<16} min={min(scores):.3f} max={max(scores):.3f}")

print("\n--- lowest-scoring in-domain queries (the binding constraint) ---")
for group, q, top, _ in sorted(in_rows, key=lambda r: r[2])[:8]:
    print(f"  {top:.3f}  [{group:<14}] {q}")

print("\n--- highest-scoring off-topic queries (the noise ceiling) ---")
for q, best in sorted(off_rows, key=lambda r: -r[1])[:10]:
    flag = " <-- high" if best >= 0.40 else ""
    print(f"  {best:.3f}  {q}{flag}")

print("\n--- candidate floors ---")
print(f"{'floor':>7} {'in-dom kept':>13} {'off-topic kept':>15} {'verdict':<22}")
best_floor = None
for floor in (0.18, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
    kept_in = sum(1 for t in in_tops if t >= floor)
    kept_off = sum(1 for b in off_bests if b >= floor)
    if kept_in == len(in_tops) and kept_off == 0:
        verdict = "clean separation"
        if best_floor is None:
            best_floor = floor
    elif kept_off == 0:
        verdict = f"misses {len(in_tops) - kept_in} in-domain"
    else:
        verdict = f"{kept_off} off-topic leak"
    print(f"{floor:>7.2f} {kept_in:>6}/{len(in_tops):<6} "
          f"{kept_off:>8}/{len(off_rows):<6} {verdict:<22}")

print("\n--- recommended ---")
worst_in = min(in_tops)
loudest_off = max(off_bests)
midpoint = (worst_in + loudest_off) / 2

if worst_in > loudest_off:
    print(f"  In-domain floor is {worst_in:.3f}; loudest off-topic is "
          f"{loudest_off:.3f}.")
    print(f"  They do NOT overlap, so any floor in "
          f"({loudest_off:.3f}, {worst_in:.3f}] is correct.")
    print(f"  Recommended: {midpoint:.3f}  (midpoint of the gap, maximising "
          f"distance from both sides)")
    print(f"  Current config.MIN_SIMILARITY = {config.MIN_SIMILARITY} "
          f"-> {'TOO LOW, admits off-topic' if config.MIN_SIMILARITY <= loudest_off else 'ok'}")
    print(f"\n  Gap width = {worst_in - loudest_off:.3f}")
else:
    print(f"  WARNING: in-domain and off-topic ranges OVERLAP "
          f"(in min {worst_in:.3f} vs off max {loudest_off:.3f}).")
    print("  A single similarity floor cannot separate these; Phase 8 needs a")
    print("  stronger lexical/keyword gate before retrieval.")

print("\n" + "=" * 78)