"""Phase 7 verification: retrieval, similarity floor, citation metadata.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/debug_retrieval.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import rag  # noqa: E402
from rag import RAGEngine, RetrievalResult, _distance_to_similarity  # noqa: E402

failures: list[str] = []

print("=" * 78)
print("PHASE 7 VERIFICATION - retrieval")
print("=" * 78)

# --- 1. construction without an API key must not raise -------------------
print("\n-- construction (NFR-5: no key must not raise) --")
engine = RAGEngine()
ok = engine.groq_client is None or engine.has_llm
print(f"  [OK] RAGEngine() constructed; has_llm={engine.has_llm}")
print(f"  [OK] index present: {engine.is_indexed()}")

count = engine._store().count()
ok = count > 0
print(f"  [{'OK' if ok else 'FAIL'}] vector store holds {count} chunks")
if not ok:
    failures.append("vector store is empty - run `python ingest.py`")

# --- 2. same embedding model as ingestion --------------------------------
print("\n-- embedder identity --")
m1 = engine._embedder().id2word if hasattr(engine._embedder(), "id2word") else None
probe = engine._embedder().encode(["dimension probe"], normalize_embeddings=True)
dim = len(probe[0])
ok = dim == config.EMBED_DIM
print(f"  [{'OK' if ok else 'FAIL'}] query embedder dim = {dim} "
      f"(ingestion used {config.EMBED_DIM})")
if not ok:
    failures.append(f"query embedder dim {dim} != {config.EMBED_DIM}")

# same instance reused across calls (no reload cost)
ok = engine._embedder() is engine._embedder()
print(f"  [{'OK' if ok else 'FAIL'}] embedder is a cached singleton")
if not ok:
    failures.append("embedder reloaded between calls")

# --- 3. distance -> similarity conversion --------------------------------
print("\n-- distance -> similarity --")
CONV = [(0.0, "cosine", 1.0), (0.5, "cosine", 0.5), (1.0, "cosine", 0.0)]
for dist, space, want in CONV:
    got = _distance_to_similarity(dist, space)
    ok = abs(got - want) < 1e-6
    print(f"  [{'OK' if ok else 'FAIL'}] {space} d={dist} -> {got:.3f} "
          f"(want {want:.3f})")
    if not ok:
        failures.append(f"conversion d={dist} -> {got}, want {want}")

out_of_range = [
    _distance_to_similarity(d, "cosine") for d in (-1.0, 2.0, 5.0)
]
ok = all(0.0 <= s <= 1.0 for s in out_of_range)
print(f"  [{'OK' if ok else 'FAIL'}] out-of-range distances clamped to [0,1]: "
      f"{out_of_range}")
if not ok:
    failures.append("similarity not clamped to [0,1]")

# --- 4. relevant questions retrieve the right fact ----------------------
print("\n-- relevant questions hit the correct section --")
# (question, expected scheme slug fragment, expected section)
CASES = [
    ("expense ratio of HDFC ELSS Tax Saver Fund",
     "elss", "expense_ratio"),
    ("lock-in period of HDFC ELSS Tax Saver Fund",
     "elss", "lock_in_period"),
    ("minimum SIP amount for HDFC Large Cap Fund",
     "large-cap", "sip_minimum"),
    ("exit load on HDFC Small Cap Fund",
     "small-cap", "exit_load"),
    ("benchmark used by HDFC Balanced Advantage Fund",
     "balanced", "benchmark"),
    ("riskometer level of HDFC Flexi Cap Fund",
     "equity", "riskometer"),
    ("who is the RTA for HDFC ELSS Tax Saver Fund",
     "elss", "documents_statements"),
]
for q, want_slug, want_section in CASES:
    hits = engine.retrieve(q, skip_guardrails=True)
    if not hits:
        failures.append(f"no hits for {q!r}")
        print(f"  [FAIL] {q!r:<52} -> 0 hits")
        continue
    top = hits[0]
    ok = want_slug in top.scheme_slug and top.section == want_section
    print(f"  [{'OK' if ok else 'FAIL'}] {q[:50]:<52} "
          f"top={top.score:.3f} {top.section}")
    if not ok:
        failures.append(
            f"{q!r} -> top hit {top.scheme_slug}/{top.section}, "
            f"want *{want_slug}*/*{want_section}*"
        )

# --- 5. off-topic -> [] (guardrails bypassed so the FLOOR is tested) ----
print("\n-- off-topic questions must fall below the floor --")
OFF_TOPIC = [
    "which crypto should I buy",
    "what is the weather in Mumbai tomorrow",
    "how do I cook biryani",
    "who won the 2024 world cup",
    "best stocks to trade on the NSE",
    "what is the population of Tokyo",
    "python list comprehension syntax",
    "bitcoin price prediction 2027",
]
for q in OFF_TOPIC:
    hits = engine.retrieve(q, skip_guardrails=True)
    ok = len(hits) == 0
    print(f"  [{'OK' if ok else 'FAIL'}] {q!r:<44} -> {len(hits)} hit(s)"
          + ("" if ok else f" top={hits[0].score:.3f}"))
    if not ok:
        failures.append(f"off-topic {q!r} returned {len(hits)} hits above floor")

# --- 6. the floor is meaningful, not vacuous ----------------------------
print("\n-- floor sanity --")
hits = engine.retrieve("what is the expense ratio of HDFC Large Cap Fund",
                       skip_guardrails=True)
scores = [h.score for h in hits]
ok = bool(scores) and scores[0] > config.MIN_SIMILARITY
print(f"  [OK] in-domain top score {scores[0]:.3f} >> floor {config.MIN_SIMILARITY}"
      if ok else "  [FAIL] no in-domain score cleared the floor")
if not ok:
    failures.append("floor may be too high for in-domain questions")

# A high floor must disable BOTH acceptance paths. The lexical rescue has its
# own lower gate (MIN_SIMILARITY_LOWER), so it has to be suppressed too -
# otherwise an unreachable-by-similarity query still leaks in through the
# lexical path and the "floor filters everything" guarantee does not hold.
hits_strict = engine.retrieve(
    "what is the expense ratio of HDFC Large Cap Fund",
    skip_guardrails=True, min_similarity=0.99, use_lexical_rescue=False,
)
ok = len(hits_strict) == 0
print(f"  [{'OK' if ok else 'FAIL'}] a 0.99 floor filters everything "
      f"({len(hits_strict)})")
if not ok:
    failures.append("a 0.99 floor should return nothing")

hits_strict_lex = engine.retrieve(
    "what is the expense ratio of HDFC Large Cap Fund",
    skip_guardrails=True, min_similarity=0.99,
)
ok = len(hits_strict_lex) == 0
print(f"  [{'OK' if ok else 'FAIL'}] a 0.99 floor also blocks the lexical path "
      f"({len(hits_strict_lex)})")
if not ok:
    failures.append("a 0.99 floor leaked through the lexical rescue")

# --- 7. metadata: every hit carries a citation --------------------------
print("\n-- citation metadata on every hit --")
hits = engine.retrieve("what is the exit load and lock-in of HDFC ELSS?",
                       skip_guardrails=True)
missing = []
for h in hits:
    if not h.source_url or not h.source_url.startswith("https://groww.in/"):
        missing.append(h.meta.get("chunk_id"))
    if not h.section or not h.scheme_slug:
        missing.append(h.meta.get("chunk_id"))
ok = not missing
print(f"  [{'OK' if ok else 'FAIL'}] all {len(hits)} hits carry "
      f"source_url + section + scheme_slug")
if not ok:
    failures.append(f"hits missing citation metadata: {missing}")

urls = {h.source_url for h in hits}
print(f"  [OK] distinct source URLs among hits: {len(urls)}")

# --- 8. RetrievalResult.sources() de-duplicates -------------------------
print("\n-- sources() de-duplication --")
res = engine.ask("what is the expense ratio and exit load of HDFC Large Cap Fund")
srcs = res.sources()
url_list = [s.url for s in srcs]
ok = len(url_list) == len(set(url_list))
print(f"  [{'OK' if ok else 'FAIL'}] {len(srcs)} source(s), no duplicate URLs")
if not ok:
    failures.append("sources() returned duplicate URLs")
for s in srcs:
    print(f"       {s.label[:56]:<58} {s.as_of or '(no date)'}")

# --- 9. ask() short-circuits guardrails ---------------------------------
print("\n-- ask() refusal routing --")
for q, expect_refused in [
    ("Should I buy HDFC Large Cap Fund?", True),
    ("what are the returns of HDFC Large Cap Fund", True),
    ("my pan is ABCDE1234F", True),
    ("what is the expense ratio of HDFC ELSS", False),
]:
    r = engine.ask(q)
    ok = r.refused is expect_refused
    print(f"  [{'OK' if ok else 'FAIL'}] refused={r.refused} (want {expect_refused}) "
          f"{q!r}")
    if not ok:
        failures.append(f"ask({q!r}) refused={r.refused}, want {expect_refused}")
    if r.refused and not r.refusal_links:
        failures.append(f"refusal for {q!r} carried no link")

# --- 10. score distribution for the README ------------------------------
print("\n-- observed score ranges (feeds MIN_SIMILARITY decision) --")
IN_DOMAIN = [
    "expense ratio of HDFC ELSS Tax Saver Fund",
    "lock-in period of HDFC Small Cap Fund",
    "minimum SIP for HDFC Large Cap Fund",
    "exit load of HDFC Balanced Advantage Fund",
    "riskometer of HDFC Flexi Cap Fund",
    "benchmark of HDFC Large Cap Fund",
    "stamp duty on HDFC Small Cap Fund",
    "RTA for HDFC ELSS",
    "investment objective of HDFC Flexi Cap Fund",
    "portfolio turnover ratio of HDFC Large Cap Fund",
]
top_in, all_in = [], []
for q in IN_DOMAIN:
    for h in engine.retrieve(q, skip_guardrails=True):
        all_in.append(h.score)
        top_in.append(h.score)

top_off, all_off = [], []
for q in OFF_TOPIC:
    hits = engine.retrieve(q, skip_guardrails=True)
    if hits:
        top_off.append(hits[0].score)
    else:
        # no hits: use the raw nearest by querying with a floor of 0
        all_off.append(0.0)
    raw = engine.retrieve(q, skip_guardrails=True, min_similarity=0.0)
    if raw:
        all_off.append(raw[0].score)

if top_in and all_in:
    print(f"  in-domain  : top-1 min={min(top_in):.3f} "
          f"max={max(top_in):.3f} mean={sum(top_in)/len(top_in):.3f}")
    print(f"              all-hit min={min(all_in):.3f} max={max(all_in):.3f}")
if all_off:
    print(f"  off-topic  : best-nearest min={min(all_off):.3f} "
          f"max={max(all_off):.3f}")
    print(f"  (none of these clear the {config.MIN_SIMILARITY} floor)")

margin = (min(top_in) - max(all_off)) if (top_in and all_off) else None
if margin is not None:
    ok = margin > 0
    print(f"  [{'OK' if ok else 'WARN'}] separation margin = {margin:.3f} "
          f"(worst in-domain top-1 minus best off-topic)")
    if not ok:
        failures.append("off-topic scores overlap in-domain scores")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 7 ASSERTIONS PASSED")
print("=" * 78)