"""Central configuration: sources, paths, and model / retrieval settings.

All tunable knobs for the RAG pipeline live here so the ingestion and query
stages stay in sync (same embedding model, same collection name, same chunking
parameters).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
CHROMA_DIR = DATA_DIR / "chroma"
CHUNKS_TXT = DATA_DIR / "chunks.txt"
DOCS_JSONL = DATA_DIR / "chunks.jsonl"

for _d in (DATA_DIR, RAW_DIR, CHROMA_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Source registry  (AMC: HDFC Mutual Fund | 5 schemes, all Direct Growth)
# --------------------------------------------------------------------------
AMC_NAME = "HDFC Mutual Fund"
AMC_SHORT = "HDFC"
# The corpus is deliberately single-AMC. Retrieval cannot tell a lookalike fund
# apart from an in-scope one (see OUT_OF_SCOPE_SCHEMES), so widening the AMC
# without widening the guard is how you get confidently wrong answers.
SUPPORTED_PLAN = "Direct Growth"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SOURCES = [
    {
        "slug": "hdfc-large-cap-fund-direct-growth",
        "name": "HDFC Large Cap Fund - Direct Growth",
        "category": "Large Cap",
        "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    },
    {
        "slug": "hdfc-equity-fund-direct-growth",
        "name": "HDFC Flexi Cap Fund - Direct Growth",
        "category": "Flexi Cap",
        "url": "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    },
    {
        "slug": "hdfc-elss-tax-saver-fund-direct-plan-growth",
        "name": "HDFC ELSS Tax Saver Fund - Direct Growth",
        "category": "ELSS",
        "url": (
            "https://groww.in/mutual-funds/"
            "hdfc-elss-tax-saver-fund-direct-plan-growth"
        ),
    },
    {
        "slug": "hdfc-small-cap-fund-direct-growth",
        "name": "HDFC Small Cap Fund - Direct Growth",
        "category": "Small Cap",
        "url": "https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth",
    },
    {
        "slug": "hdfc-balanced-advantage-fund-direct-growth",
        "name": "HDFC Balanced Advantage Fund - Direct Growth",
        "category": "Balanced Advantage (Hybrid)",
        "url": (
            "https://groww.in/mutual-funds/"
            "hdfc-balanced-advantage-fund-direct-growth"
        ),
    },
]

SOURCE_BY_SLUG = {s["slug"]: s for s in SOURCES}

# --------------------------------------------------------------------------
# Chunking strategy  (see deliverables/chunking_strategy.md for rationale)
# --------------------------------------------------------------------------
CHUNK_SIZE = 380  # characters - small enough to stay on one fact cluster
CHUNK_OVERLAP = 80  # characters - keeps definitions attached to their term
MIN_CHUNK_CHARS = 40  # minimum size of an EMITTED chunk (drops nav crumbs)

# Minimum size of a SOURCE line. Must stay small: label lines such as
# "Min. for SIP" (12 chars) or the risk badge "Very High Risk" (14 chars) are
# exactly the anchors the prose extractor needs, so the 40-char chunk
# threshold must never be applied at line level.
MIN_LINE_CHARS = 2

# --------------------------------------------------------------------------
# Embedding + vector store
# --------------------------------------------------------------------------
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
COLLECTION_NAME = "hdfc_mf_faqs"

# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
# Chunks handed to the LLM as context.
#
# Raised from 5 to 10 to widen recall: several target facts (notably the
# lock_in_period cards) have one near-identical instance per scheme, so a
# scheme-qualified question and the wrong scheme's card can sit close together in
# rank. Ten chunks reliably includes the intended one.
#
# The cost is context dilution - 10 passages compete for the model's attention -
# so this is verified, not assumed. scripts/debug_generation.py asserts that
# answers stay numerically correct and that no out-of-scope scheme leaks in, and
# scripts/stress_terse_queries.py asserts the terse-query path is unaffected.
# Verified against qwen/qwen3.8-27b (131k context, so 10 short chunks is a
# small fraction of the window).
TOP_K = 10

# Similarity floor for "we actually found something relevant".
#
# CALIBRATED, not guessed. Re-derive with `python scripts/calibrate_floor.py`.
# Measured over 32 in-domain queries (every target fact type, plus 9 other
# fact sections) and 20 off-topic queries:
#
#   in-domain  top-1 similarity : min 0.660  max 0.928
#   off-topic  best-nearest     : min 0.000  max 0.421
#   separation gap              : 0.239 wide, NO overlap
#
# Any floor in (0.421, 0.660] is correct. 0.54 is the midpoint, maximising
# distance from both observed clusters.
#
# The original provisional 0.18 was too low: it admitted 14 of 20 off-topic
# queries (weather, Tokyo's population, biryani recipes) because MiniLM cosine
# similarity between short unrelated English sentences sits around 0.2-0.3.
# 0.18 was never validated against negatives - it was a placeholder.
MIN_SIMILARITY = 0.54

# --------------------------------------------------------------------------
# LLM (Groq)
# --------------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Verified against this account's live /models endpoint (2026-10-01).
# Groq serves a per-account model subset, so a model that works for one person
# 404s for another. The previous default, llama-3.3-70b-versatile, is NOT in
# this account's list and would have failed at call time with a 404 rather
# than a clear config error. Verified served models:
#   allam-2-7b, canopylabs/orpheus-arabic-saudi, canopylabs/orpheus-v1-english,
#   meta-llama/llama-prompt-guard-2-22m, meta-llama/llama-prompt-guard-2-86m,
#   openai/gpt-oss-120b, openai/gpt-oss-20b, openai/gpt-oss-safeguard-20b,
#   qwen/qwen3.8-27b, whisper-large-v3, whisper-large-v3-turbo
# Override in .env if your account differs.
#
# WHY THIS ONE. qwen/qwen3.8-27b was chosen by measurement, not preference
# (scripts/compare_models.py, same SYSTEM_PROMPT over the same retrieved
# context). Re-measured 2026-10-02; see GROQ_FALLBACK_MODELS below for the
# current table, including why gpt-oss-20b is no longer disqualified.
#
# Original 2026-10-01 run, BEFORE `_strip_disallowed` was hardened:
#
#   model                  figures   invisible chars   completion tokens
#   qwen/qwen3.8-27b        5/5       none                    53
#   openai/gpt-oss-20b      3/5       U+202F in 4/5         548
#   openai/gpt-oss-120b     3/5       U+202F in 3/5         540
#
# The gpt-oss "misses" there were not wrong facts - they were U+202F NARROW
# NO-BREAK SPACE emitted instead of a normal space, so "BSE 250" arrived as
# "BSE<NBSP>250" and "3 years" as "3<NBSP>years". Once `_strip_disallowed`
# normalised those characters they scored 5/5 and 4/5 respectively. The
# lesson is recorded rather than deleted: a measurement is only valid for the
# code it was taken against.
#
# qwen remains the default because it is far cheaper on completion tokens - the
# gpt-oss models bill their reasoning scratchpad to the same output budget.
#
# REASONING MODELS. qwen/qwen3.8-27b is itself reasoning-capable but was verified
# to return content-only responses here (no `reasoning` / `reasoning_content`
# keys) at temperature 0. gpt-oss models DO emit `reasoning`, which must never
# reach the user - `rag.py` reads `content` only and ignores reasoning fields
# defensively, so a reasoning model is safe but wasteful here.
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

# Models to try, IN ORDER, when the one above cannot serve the request.
#
# Groq's free tier applies its 200,000 tokens/day budget PER MODEL, not per
# account. When qwen's daily budget is spent, the gpt-oss models still have
# their own untouched budget - the models fail independently. Without a
# fallback, a spent quota collapsed every answer to a verbatim quote even
# though a perfectly usable model was sitting right there, and the user saw
# "the language model could not be reached" for what was really one model
# being out of tokens for the day.
#
# Re-measured 2026-10-02 (scripts/compare_models.py) after `_strip_disallowed`
# was hardened to normalise invisible Unicode. Figures are checked against the
# FINALISED text, which is what the user actually receives:
#
#   model                  figures   invisible chars          completion tokens
#   qwen/qwen3.8-27b        5/5       none                              53
#   openai/gpt-oss-20b      5/5       U+202F in 4/5, stripped          541
#   openai/gpt-oss-120b     4/5       U+202F in 3/5, stripped          534
#
# gpt-oss-20b was previously rejected at 3/5, but those "misses" were U+202F
# narrow no-break spaces ("BSE<NBSP>250"), not wrong facts, and the hardening
# above now removes them before the answer is shown. It is a legitimate
# fallback today - not a downgrade in answer correctness.
#
# It is not free, though: gpt-oss bills its reasoning scratchpad, so completion
# tokens are ~10x. The retrieved context dominates the request, so the real
# cost is closer to ~1.5x per answer. That is why it is the fallback and not
# the default - it only pays that price when qwen cannot answer at all.
#
# Comma-separated; set to "" to disable fallback entirely.
GROQ_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b").split(",")
    if m.strip()
]

# Output budget. Only the final answer is wanted, so this is deliberately small.
# A reasoning model can exhaust it before emitting any content and fall back to
# the extractive path; verified not to happen with the default model.
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "1024"))

# --------------------------------------------------------------------------
# Answer policy
# --------------------------------------------------------------------------
# DISCLAIMER
#
# Two forms on purpose. SHORT is the prominent note required on the welcome
# screen and beside every answer; LONG is the fuller statement shown once at the
# top of the app and appended to the system prompt. Both live here so the UI,
# the CLI and the prompt can never disagree about what the assistant promises.
# --------------------------------------------------------------------------
DISCLAIMER_SHORT = "Facts-only. No investment advice."

DISCLAIMER = (
    "Facts-only. No investment advice. Answers are sourced from public "
    "Groww scheme pages and may be incomplete - always verify with the "
    "official HDFC Mutual Fund SID / factsheet."
)

# Topics we deliberately refuse (opinion / advice / personalised).
REFUSAL_PATTERNS = [
    r"\bshould i\b",
    r"\bshould we\b",
    r"\bis it (a )?good\b",
    r"\bbest (fund|scheme|mutual fund|elss)\b",
    r"\brecommend\b",
    r"\bsuggest\b",
    r"\badvise\b",
    r"\bworth (it|buying|investing)\b",
    r"\bwhich (one|should|is better)\b",
    r"\bmy portfolio\b",
    r"\bfor me\b",
    r"\bopinion\b",
    r"\bcompare .{0,20}(better|superior|outperform)\b",
    r"\bwill .{0,25}(return|grow|give)\b",
    r"\bhow much (will|money) .{0,20}(return|grow)\b",
    r"\bshould i (buy|sell|exit|switch|redeem|invest)\b",
    r"\bwhich (fund|scheme) (do|should) i\b",
    r"\ballocate\b",
    r"\bplan my\b",
]

# --------------------------------------------------------------------------
# Corpus scope
# --------------------------------------------------------------------------
# The corpus covers exactly 5 schemes. A question naming a *different* HDFC fund
# cannot be answered from it, and must not be answered from a lookalike scheme's
# chunk. "HDFC Mid Cap Fund" and "HDFC Large Cap Fund" are near-identical strings
# and near-identical embeddings, so retrieval alone will happily answer a Mid Cap
# question with the Large Cap expense ratio - a confident, wrong, wrongly-cited
# answer. The scheme-name check below catches that before it can happen.
#
# Deliberately biased towards strictness: saying "not in my sources" is honest,
# whereas answering about a fund we do not hold is neither.
SCHEME_MARKERS = [
    "large cap", "flexi cap", "tax saver", "elss", "small cap",
    "balanced advantage", "equity fund",
]

# HDFC funds that exist but are NOT in this corpus. Listed rather than inferred,
# because a false negative here produces a confidently wrong answer.
OUT_OF_SCOPE_SCHEMES = [
    "mid cap", "midcap", "large and mid", "small and mid", "parag parag",
    "value", "dynamic", "infrastructure", "banking", "psu", "pension",
    "income", "liquid", "overnight", "money market", "arbitrage",
    "equity savings", "corporate bond", "government securities", "gold",
    "silver", "global", "foreign", "international", "sector", "theme",
    "momentum", "dividend yield", "first", "alpha", "cap", "tax",
]

EDUCATIONAL_LINKS = [
    {
        "label": "SEBI - Mutual Fund Regulations & disclosures",
        "url": "https://www.sebi.gov.in/",
    },
    {
        "label": "AMFI - Mutual fund education & NAV",
        "url": "https://www.amfiindia.com/",
    },
    {
        "label": "HDFC Mutual Fund - Investor education / FAQs",
        "url": "https://www.hdfcfund.com/faqs",
    },
    {
        "label": "SEBI - Mutual Fund Rules (regulations)",
        "url": "https://www.sebi.gov.in/legal/mutual-funds",
    },
]


def corpus_fingerprint(*, raw_dir=None, ingest_source=None) -> str:
    """Hash of everything that determines the corpus, as 16 hex chars.

    The vector index is committed to the repo, so it has to be possible to tell
    a CURRENT index from a STALE one. A stale index is not a crash, it is worse:
    it answers confidently from chunks that no longer match the source pages,
    and nothing anywhere reports an error.

    Two inputs are hashed. ``data/raw/*.html`` covers the sources themselves.
    ``ingest.py`` covers the extraction and chunking rules, so editing a chunk
    rule invalidates the index even though the HTML is untouched - which is
    exactly the case that would otherwise go unnoticed.

    This lives in ``config.py`` rather than ``ingest.py`` on purpose: the app
    calls it on every start to validate the committed index, and importing
    ``ingest`` there would pull in BeautifulSoup and requests just to hash a
    file. Reading ~5 MB of HTML plus one source file takes a few milliseconds.

    Line endings are normalised before hashing. Git's ``core.autocrlf=true``
    rewrites LF to CRLF on checkout on Windows, so the same commit checks out
    as different bytes on different machines. Hashing verbatim would make every
    Windows clone report a stale index and trigger a pointless full re-embed,
    while the Linux deploy - where the file stays LF - silently worked. That is
    not a fingerprint change anyone should be able to make by cloning a repo, so
    the hash covers the content rather than the checkout policy.

    The arguments are only overridden by the tests, which point this at a CRLF
    copy of the corpus to prove the invariance.
    """
    raw_dir = RAW_DIR if raw_dir is None else raw_dir
    if ingest_source is None:
        ingest_source = Path(__file__).resolve().parent / "ingest.py"

    def _normalise(data: bytes) -> bytes:
        return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    digest = hashlib.sha256()
    digest.update(b"corpus-v2\n")
    digest.update(_normalise(Path(ingest_source).read_bytes()))
    for page in sorted(Path(raw_dir).glob("*.html")):
        digest.update(page.name.encode("utf-8"))
        digest.update(_normalise(page.read_bytes()))
    return digest.hexdigest()[:16]
