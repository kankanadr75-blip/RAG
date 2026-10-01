"""Central configuration: sources, paths, and model / retrieval settings.

All tunable knobs for the RAG pipeline live here so the ingestion and query
stages stay in sync (same embedding model, same collection name, same chunking
parameters).
"""

from __future__ import annotations

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
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

# qwen/qwen3.8-27b is a reasoning-capable model. It was verified to return
# content-only responses here (no `reasoning` / `reasoning_content` keys) at
# temperature 0, so no special handling is needed - but `rag.py` must still read
# reasoning fields defensively if the model or a future variant starts
# emitting them, or the reasoning text would be shown to the user as the answer.
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "1024"))

# --------------------------------------------------------------------------
# Answer policy
# --------------------------------------------------------------------------
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
