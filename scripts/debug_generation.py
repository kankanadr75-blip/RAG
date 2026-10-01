"""Phase 8 verification: generation, citations, refusal routing, answer policy.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/debug_generation.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from guardrails import _sentence_count  # noqa: E402
from rag import (  # noqa: E402
    SYSTEM_PROMPT,
    RAGEngine,
    _as_of_line,
    _build_context,
    _extractive,
    _finalise,
    _sources_from_hits,
    _strip_disallowed,
    _truncate_sentences,
)

failures: list[str] = []
engine = RAGEngine()

AS_OF_MARKER = "Last updated from sources:"

print("=" * 78)
print("PHASE 8 VERIFICATION - generation & citations")
print("=" * 78)
print(f"model: {config.GROQ_MODEL}  |  LLM active: {engine.has_llm}")

# --- 1. AT-1 / AT-2 numerical correctness -------------------------------
print("\n-- AT-1, AT-2: answers are numerically correct --")
# Verified figures from implementation.md §0.3 (as_of 30-Sep-2026)
NUMERIC = [
    ("What is the expense ratio of HDFC ELSS Tax Saver Fund?",
     ["1.21"]),
    ("What is the expense ratio of HDFC Large Cap Fund?",
     ["1.03"]),
    ("What is the expense ratio of HDFC Flexi Cap Fund?",
     ["0.77"]),
    ("What is the expense ratio of HDFC Small Cap Fund?",
     ["0.78"]),
    ("What is the exit load of HDFC Flexi Cap Fund?",
     ["1%"]),
    ("What is the minimum SIP amount for HDFC ELSS Tax Saver Fund?",
     ["500"]),
    ("What is the minimum SIP amount for HDFC Large Cap Fund?",
     ["100"]),
]
for question, want in NUMERIC:
    ans = engine.answer(question)
    ok = ans.text is not None and all(w in ans.text for w in want)
    print(f"  [{'OK' if ok else 'FAIL'}] {question[:52]:<54} "
          f"want={want} refused={ans.refused}")
    if not ok:
        failures.append(f"{question!r} expected {want} in answer; "
                        f"got: {ans.text[:150]!r}")

# --- 2. AT-6, AT-7, AT-8 refusals ---------------------------------------
print("\n-- AT-6, AT-7, AT-8: refusals are correct --")
REFUSALS = [
    ("Should I buy HDFC Large Cap Fund?", "advice"),
    ("which fund should I choose", "advice"),
    ("is HDFC Flexi Cap a good scheme", "advice"),
    ("what are the returns of HDFC Large Cap Fund", "performance"),
    ("best performing HDFC scheme", "performance"),
    ("my pan is ABCDE1234F", "pii"),
    ("aadhaar 2345 6789 0123", "pii"),
]
for question, kind in REFUSALS:
    ans = engine.answer(question)
    ok = ans.refused and ans.refusal_kind == kind
    n = _sentence_count(ans.text)
    ok = ok and n <= 3 and bool(ans.refusal_links)
    print(f"  [{'OK' if ok else 'FAIL'}] {question[:46]:<48} "
          f"kind={ans.refusal_kind:<12} {n} sent, "
          f"{len(ans.refusal_links)} link(s)")
    if not ok:
        failures.append(
            f"{question!r} -> refused={ans.refused} "
            f"kind={ans.refusal_kind} sentences={n} "
            f"links={len(ans.refusal_links)}"
        )
    # A refusal must never claim chunks were used.
    if ans.chunks_used:
        failures.append(f"refusal {question!r} used {ans.chunks_used} chunks")

# --- 3. PAN is never echoed (REQ-20) ------------------------------------
print("\n-- PII never echoed --")
for secret_q, secret in [
    ("My PAN is ABCDE1234F, send my statement", "ABCDE1234F"),
    ("aadhaar 2345 6789 0123", "2345 6789 0123"),
    ("mail me at ravi.kumar@example.com", "ravi.kumar@example.com"),
    ("call me on +91 98765 43210", "98765 43210"),
]:
    ans = engine.answer(secret_q)
    blob = ans.text + " ".join(l["url"] for l in ans.refusal_links)
    # also check the full serialised form, in case a UI would render more
    blob += str(ans.to_dict())
    leaked = secret in blob
    print(f"  [{'OK' if not leaked else 'FAIL'}] no echo of {secret!r}")
    if leaked:
        failures.append(f"answer echoed PII {secret!r}")

# --- 4. no_context + out_of_scope paths --------------------------------
print("\n-- out_of_scope: a fund we do not hold must not be answered --")
# These are real HDFC funds that are NOT among the 5 collected schemes. The
# danger is specific: "HDFC Mid Cap" and "HDFC Large Cap" are near-identical,
# so retrieval answers the Mid Cap question with the Large Cap figure and cites
# the Large Cap page. A confident, wrong, wrongly-cited answer.
OFF_CORPUS = [
    "what is the expense ratio of HDFC Mid Cap Fund",
    "what is the NAV of HDFC Parag Parag Flexi Cap",
    "expense ratio of HDFC Value Fund",
    "exit load of HDFC Liquid Fund",
    "benchmark of HDFC Infrastructure Fund",
    "minimum SIP for HDFC Dividend Yield Fund",
    "expense ratio of HDFC-Mid-Cap-Fund",
]
for question in OFF_CORPUS:
    ans = engine.answer(question)
    ok = ans.refused and ans.refusal_kind in ("out_of_scope", "no_context")
    # Critically: a refusal must not cite a scheme page that cannot support it.
    ok = ok and not ans.sources
    print(f"  [{'OK' if ok else 'FAIL'}] {question[:48]:<50} "
          f"kind={ans.refusal_kind} sources={len(ans.sources)}")
    if not ok:
        failures.append(
            f"{question!r} -> kind={ans.refusal_kind} "
            f"sources={[s.url for s in ans.sources]}"
        )

print("\n-- in-scope questions are NOT caught by the scope guard --")
IN_SCOPE = [
    "what is the expense ratio of HDFC Large Cap Fund",
    "expense ratio of HDFC ELSS Tax Saver Fund",
    "exit load of HDFC Flexi Cap Fund",
    "minimum SIP HDFC Small Cap Fund",
    "benchmark of HDFC Balanced Advantage Fund",
    "riskometer of HDFC Flexi Cap",
    "what is the RTA for HDFC ELSS",
    "stamp duty on HDFC Small Cap",
]
for question in IN_SCOPE:
    ans = engine.answer(question)
    ok = not ans.refused
    print(f"  [{'OK' if ok else 'FAIL'}] {question[:48]:<50} "
          f"kind={ans.refusal_kind or 'fact'}")
    if not ok:
        failures.append(f"in-scope question wrongly refused: {question!r} "
                        f"({ans.refusal_kind})")

print("\n-- advisory routing still wins over scope --")
# advice/performance are checked before scope, so a Mid Cap question that is
# also advice must give the advice refusal, not a scope refusal.
PRECEDENCE = [
    ("is HDFC Mid Cap Fund a good scheme", "advice"),
    ("what are the returns of HDFC Mid Cap Fund", "performance"),
    ("my pan is ABCDE1234F, HDFC Mid Cap Fund", "pii"),
]
for question, kind in PRECEDENCE:
    ans = engine.answer(question)
    ok = ans.refusal_kind == kind
    print(f"  [{'OK' if ok else 'FAIL'}] {question[:48]:<50} "
          f"kind={ans.refusal_kind} (want {kind})")
    if not ok:
        failures.append(f"{question!r} -> {ans.refusal_kind}, want {kind}")

# --- 5. the as-of line is always present --------------------------------
print("\n-- every answer ends with the as-of line --")
for question in [
    "What is the expense ratio of HDFC ELSS Tax Saver Fund?",
    "What is the exit load of HDFC Flexi Cap Fund?",
    "what is the RTA for HDFC Small Cap Fund",
    "What is the benchmark of HDFC Large Cap Fund?",
]:
    ans = engine.answer(question)
    ok = AS_OF_MARKER in ans.text
    tail = ans.text.strip().splitlines()[-1] if ans.text.strip() else ""
    ok = ok and tail.startswith(AS_OF_MARKER)
    print(f"  [{'OK' if ok else 'FAIL'}] {question[:48]:<50} "
          f"tail={tail[:44]!r}")
    if not ok:
        failures.append(f"{question!r} missing/!misplaced as-of line")

# --- 6. <= 3 sentences on the BODY (as-of line excluded) ----------------
print("\n-- answers are <= 3 sentences (as-of line excluded) --")
LONG_SET = [
    "What is the expense ratio and exit load and lock-in period and "
    "benchmark and RTA of HDFC Large Cap Fund?",
    "explain the exit load, stamp duty, tax treatment, minimum investment, "
    "SIP, lumpsum, NAV and AUM for HDFC Flexi Cap Fund",
]
for question in LONG_SET:
    ans = engine.answer(question)
    body = ans.text.split(AS_OF_MARKER)[0].strip()
    n = _sentence_count(body)
    ok = n <= 3
    print(f"  [{'OK' if ok else 'FAIL'}] {n} sentence(s)  {question[:60]!r}")
    if not ok:
        failures.append(f"body had {n} sentences for {question[:60]!r}")

# --- 7. citations come from metadata, never from prose ------------------
print("\n-- citations are real, config-sourced URLs --")
valid_urls = {s["url"] for s in config.SOURCES}
for question in [
    "What is the expense ratio of HDFC ELSS Tax Saver Fund?",
    "What is the exit load of HDFC Flexi Cap Fund?",
    "what is the RTA for HDFC Small Cap Fund",
    "who is the custodian for HDFC Large Cap Fund",
]:
    ans = engine.answer(question)
    if ans.refused:
        print(f"  [skip] {question[:48]:<50} refused={ans.refusal_kind}")
        continue
    ok = bool(ans.sources) and all(s.url in valid_urls for s in ans.sources)
    ok = ok and ans.sources[0].url in valid_urls
    print(f"  [{'OK' if ok else 'FAIL'}] {question[:48]:<50} "
          f"{len(ans.sources)} citation(s)")
    if not ok:
        failures.append(f"{question!r} had invalid citations: "
                        f"{[s.url for s in ans.sources]}")
    # The model must not have written a URL into the body.
    body_urls = re.findall(r"https?://\S+", ans.text)
    if body_urls:
        failures.append(f"{question!r} body contains a URL: {body_urls}")
        print(f"  [FAIL] body contains URL(s) {body_urls}")

# --- 8. a fabricated URL cannot appear ----------------------------------
print("\n-- URL stripping / anti-fabrication helpers --")
cases = [
    ("The value is 1.21%. https://groww.in/mutual-funds/fake", "1.21%"),
    ("See [1] for details. The fee is 1%.", "1%"),
    ("- expense ratio: 1.21%\n- exit load: 1%", "expense ratio"),
    ("**Expense ratio** is 1.21%", "Expense ratio"),
]
for raw, keep in cases:
    out = _strip_disallowed(raw)
    ok = keep in out and "http" not in out and "[1]" not in out
    print(f"  [{'OK' if ok else 'FAIL'}] {raw[:44]!r:<46} -> {out[:40]!r}")
    if not ok:
        failures.append(f"_strip_disallowed failed on {raw!r} -> {out!r}")

# --- 9. sentence truncation --------------------------------------------
print("\n-- sentence truncation --")
TRUNC = [
    ("One. Two. Three. Four. Five.", 3, "One. Two. Three."),
    ("One only.", 3, "One only."),
    ("A. B", 3, "A. B"),
    ("No terminator here", 3, "No terminator here"),
]
for text, limit, want in TRUNC:
    got = _truncate_sentences(text, limit)
    ok = got == want
    print(f"  [{'OK' if ok else 'FAIL'}] {text[:30]!r:<34} -> {got!r}")
    if not ok:
        failures.append(f"_truncate_sentences({text!r}) -> {got!r}, "
                        f"want {want!r}")

# --- 10. extractive fallback (NFR-5) -----------------------------------
print("\n-- extractive fallback with no LLM --")
saved_client = engine.groq_client
try:
    engine.groq_client = None
    ans = engine.answer("What is the expense ratio of HDFC ELSS Tax Saver Fund?")
    ok = (ans.mode == "extractive" and "1.21" in ans.text
          and bool(ans.sources) and AS_OF_MARKER in ans.text)
    print(f"  [{'OK' if ok else 'FAIL'}] mode={ans.mode} sources="
          f"{len(ans.sources)} has_1.21={'1.21' in ans.text}")
    if not ok:
        failures.append(f"extractive fallback wrong: mode={ans.mode}, "
                        f"sources={len(ans.sources)}")
    # And it must still be <= 3 sentences.
    body = ans.text.split(AS_OF_MARKER)[0].strip()
    n = _sentence_count(body)
    ok = n <= 3
    print(f"  [{'OK' if ok else 'FAIL'}] extractive body is {n} sentence(s)")
    if not ok:
        failures.append(f"extractive body had {n} sentences")
finally:
    engine.groq_client = saved_client

# Simulated API failure must also degrade, not crash.
class _Boom:
    class chat:  # noqa: N801
        class completions:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("simulated 503")


try:
    engine.groq_client = _Boom()
    ans = engine.answer("What is the expense ratio of HDFC Small Cap Fund?")
    ok = ans.mode == "extractive" and "0.78" in ans.text
    print(f"  [{'OK' if ok else 'FAIL'}] API failure -> mode={ans.mode}, "
          f"still answers with 0.78={'0.78' in ans.text}")
    if not ok:
        failures.append(f"API failure path wrong: mode={ans.mode}")
finally:
    engine.groq_client = saved_client

# --- 11. system prompt contract (REQ-17, REQ-21) ----------------------
print("\n-- system prompt states all six rules --")
PROMPT_RULES = [
    ("only the provided source", r"ONLY the provided source"),
    ("no prior knowledge", r"prior knowledge"),
    ("facts only / no advice", r"Never give investment advice"),
    ("admit gaps", r"not fully supported|say plainly"),
    ("max 3 sentences", r"at most 3 sentences"),
    ("no URLs in output", r"Do not include source URLs"),
    ("no PII", r"Never output, request, or repeat personal data"),
]
for label, pattern in PROMPT_RULES:
    ok = bool(re.search(pattern, SYSTEM_PROMPT, re.I))
    print(f"  [{'OK' if ok else 'FAIL'}] {label}")
    if not ok:
        failures.append(f"system prompt missing rule: {label}")

# --- 12. context assembly is labelled ---------------------------------
print("\n-- context assembly is labelled --")
hits = engine.retrieve("What is the expense ratio of HDFC ELSS Tax Saver Fund?",
                       skip_guardrails=True)
ctx = _build_context(hits)
ok = "[1]" in ctx and "URL: https://groww.in/" in ctx
ok = ok and ctx.count("URL:") == len(hits)
print(f"  [{'OK' if ok else 'FAIL'}] {len(hits)} blocks, "
      f"{ctx.count('URL:')} URL lines, numbered")
if not ok:
    failures.append("context assembly missing numbering or URLs")

srcs = _sources_from_hits(hits)
ok = len({s.url for s in srcs}) == len(srcs)
ok = ok and all(s.url in valid_urls for s in srcs)
print(f"  [{'OK' if ok else 'FAIL'}] {len(srcs)} de-duplicated citation(s), "
      f"all in config.SOURCES")
if not ok:
    failures.append("_sources_from_hits produced bad citations")

# --- 13. no advice language leaks into factual answers -----------------
print("\n-- factual answers contain no advice language --")
BANNED = [
    r"\byou should\b", r"\bi recommend\b", r"\bwe suggest\b",
    r"\bis a good (fund|scheme|choice)\b", r"\bbest (fund|scheme) is\b",
    r"\bconsider buying\b", r"\bI would suggest\b",
    r"\bideally you\b", r"\bperfect for\b",
]
leaks = 0
for question, _ in NUMERIC:
    ans = engine.answer(question)
    for pattern in BANNED:
        if re.search(pattern, ans.text, re.I):
            failures.append(f"{question!r} answer contains advice {pattern!r}")
            leaks += 1
print(f"  [{'OK' if not leaks else 'FAIL'}] {len(NUMERIC)} answers checked, "
      f"{leaks} advice leak(s)")

# --- 14. determinism at temperature 0 ---------------------------------
print("\n-- same question twice gives the same answer --")
q = "What is the exit load of HDFC ELSS Tax Saver Fund?"
a1 = engine.answer(q)
a2 = engine.answer(q)
ok = a1.text == a2.text
print(f"  [{'OK' if ok else 'WARN'}] identical={ok} "
      f"(retrieval is deterministic; the LLM at temperature 0 usually is too, "
      f"but hosted inference can vary)")
if not ok:
    print(f"       run1: {a1.text[:90]!r}")
    print(f"       run2: {a2.text[:90]!r}")

# --- 15. empty input --------------------------------------------------
print("\n-- empty input --")
ans = engine.answer("")
ok = ans.refused and ans.refusal_kind == "empty"
print(f"  [{'OK' if ok else 'FAIL'}] refused={ans.refused} "
      f"kind={ans.refusal_kind!r}")
if not ok:
    failures.append("empty question was not refused")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 8 ASSERTIONS PASSED")
print("=" * 78)
