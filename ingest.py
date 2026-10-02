"""Ingestion pipeline for the HDFC Mutual Fund FAQ assistant.

Stage order (PRD REQ-1 .. REQ-10):

    Load  ->  Extract  ->  Chunk  ->  Scrub/Exclude  ->  [Embed -> Store]

This module owns the OFFLINE half of the system. It never imports the query
engine (``rag``) or the UI (``app``) - see architecture.md §2 dependency rule.

Usage:
    python ingest.py                 # cache-first; embeds if the index is missing
    python ingest.py --refresh       # re-fetch the 5 pages, then rebuild
    python ingest.py --no-embed      # build + dump the corpus only (no vector DB)
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import config
from guardrails import scrub_pii

# ---------------------------------------------------------------------------
# Chunk schema  (architecture.md §3.4)
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """One retrievable unit of the corpus.

    ``source_url`` lives on every chunk on purpose: it is what lets the answer
    renderer attach a real citation without asking the LLM to write one
    (architecture.md principle P1).
    """

    text: str
    section: str
    source_url: str
    source_name: str
    scheme_slug: str
    scheme_name: str
    amc: str = "HDFC Mutual Fund"
    scheme_code: str = ""
    category: str = ""
    producer: str = ""          # "fact_card" | "prose_section"
    extracted_from: str = ""    # "__NEXT_DATA__" | "visible_text"
    as_of: str = ""             # source's own date, e.g. "30-Sep-2026"
    ingested_at: str = ""
    char_len: int = 0
    content_hash: str = ""
    chunk_id: str = ""

    def finalise(self) -> "Chunk":
        """Fill the derived fields. Call once, after ``text``/``section`` are set."""
        self.char_len = len(self.text)
        self.content_hash = hashlib.sha1(self.text.encode("utf-8")).hexdigest()[:10]
        self.ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return self

    def to_metadata(self) -> dict:
        """Flat, Chroma-safe metadata. Scalars only (no None / no nested dict)."""
        return {
            "chunk_id": self.chunk_id,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "amc": self.amc,
            "scheme_slug": self.scheme_slug,
            "scheme_name": self.scheme_name,
            "scheme_code": self.scheme_code,
            "category": self.category,
            "section": self.section,
            "producer": self.producer,
            "extracted_from": self.extracted_from,
            "as_of": self.as_of,
            "ingested_at": self.ingested_at,
            "char_len": int(self.char_len),
            "content_hash": self.content_hash,
        }


# ---------------------------------------------------------------------------
# PHASE 1 - Load  (REQ-1)
# ---------------------------------------------------------------------------


def load_pages(force_refresh: bool = False) -> dict[str, str]:
    """Fetch (or read from cache) the raw HTML for every configured source.

    Cache-first so re-runs are offline and reproducible (architecture.md §3.1).
    A failed fetch raises - it never silently skips a page, because a thin
    corpus is worse than a loud failure (PRD risk R1).
    """
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    pages: dict[str, str] = {}

    for src in config.SOURCES:
        slug = src["slug"]
        cache_path = config.RAW_DIR / f"{slug}.html"

        if cache_path.exists() and not force_refresh:
            html = cache_path.read_text(encoding="utf-8")
            state = "cached"
        else:
            try:
                resp = requests.get(
                    src["url"],
                    headers={"User-Agent": config.USER_AGENT},
                    timeout=45,
                )
                resp.raise_for_status()
            except requests.RequestException as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Failed to fetch source '{slug}' ({src['url']}): {exc}\n"
                    "Ingestion aborts rather than build an incomplete corpus."
                ) from exc
            html = resp.text
            cache_path.write_text(html, encoding="utf-8")
            state = "fetched"

        pages[slug] = html
        print(f"  {slug:<48} {state:<8} {len(html):>9,} bytes")

    return pages


# ---------------------------------------------------------------------------
# PHASE 2 - Extractor A: structured facts from __NEXT_DATA__
#           (REQ-2, REQ-3)
#
# WHY THIS EXISTS (verified, see deliverables/chunking_strategy.md §1):
# the values for expense ratio and lock-in do NOT appear in the page's
# visible text. The rendered DOM only contains the *word* "Expense ratio"
# (a tooltip definition). The numbers live solely in the embedded
# __NEXT_DATA__ JSON. A text-only scraper fails the two most-asked
# questions, so this extractor is mandatory, not an optimisation.
# ---------------------------------------------------------------------------

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)

# Values >= this are sentinel "no upper bound" numbers, not real facts.
_UNBOUNDED = 100_000_000

# The 7 fact types the assistant must be able to answer (PRD §6.1).
# Phase 4 asserts coverage of these across all 5 schemes.
TARGET_FACTS = [
    "expense_ratio",
    "exit_load",
    "minimum_investment",
    "lock_in_period",
    "riskometer",
    "benchmark",
    "documents",
]


def _server_data(html: str) -> dict:
    """Pull ``props.pageProps.mfServerSideData`` out of the page.

    Raises loudly if the shape changed - a silent empty dict would produce a
    thin corpus that still *looks* like it worked (PRD risk R1).
    """
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise RuntimeError(
            "No <script id=\"__NEXT_DATA__\"> found. Groww's page markup has "
            "probably changed - re-run scripts/explore_json.py to re-derive the path."
        )
    try:
        nd = json.loads(m.group(1))
        return nd["props"]["pageProps"]["mfServerSideData"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "Could not reach props.pageProps.mfServerSideData inside "
            f"__NEXT_DATA__ ({exc}). Page markup likely changed (PRD risk R1)."
        ) from exc


# --- value normalisers ------------------------------------------------------


def _clean(value) -> str | None:
    """Normalise a raw JSON value to a usable string, or None if it is empty."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip()
    if text in ("", "None", "null", "{}", "[]", "nan"):
        return None
    return text


def _as_dict(value) -> dict:
    """Several fields arrive as *stringified* python dicts, e.g.
    ``"{'years': 3, 'months': 0, 'days': 0}"``. Parse defensively."""
    if isinstance(value, dict):
        return value
    text = _clean(value)
    if not text:
        return {}
    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def _num(value) -> float | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _rupees(value) -> str | None:
    n = _num(value)
    if n is None or n >= _UNBOUNDED:
        return None
    return f"{int(n):,}" if n == int(n) else f"{n:,.2f}"


def _pct(value) -> str | None:
    n = _num(value)
    return None if n is None else f"{n:g}"


def _bool_yesno(value) -> str | None:
    text = (_clean(value) or "").lower()
    return {"true": "Yes", "false": "No"}.get(text)


# --- chunk factory ----------------------------------------------------------


def _card(src: dict, data: dict, section: str, text: str) -> Chunk:
    """Build one ``fact_card`` chunk: a self-contained sentence naming the scheme."""
    return Chunk(
        text=text,
        section=section,
        source_url=src["url"],
        source_name=src["name"],
        scheme_slug=src["slug"],
        scheme_name=_clean(data.get("scheme_name")) or src["name"],
        scheme_code=_clean(data.get("scheme_code")) or "",
        category=_clean(data.get("sub_category")) or src["category"],
        producer="fact_card",
        extracted_from="__NEXT_DATA__",
        as_of=_clean(data.get("nav_date")) or "",
    )


def extract_facts(src: dict, html: str) -> list[Chunk]:
    """Extractor A: one declarative, self-contained chunk per atomic fact.

    Every sentence names its scheme explicitly, so it still embeds correctly
    when the user's question omits the fund name (REQ-3).
    """
    data = _server_data(html)
    name = _clean(data.get("scheme_name")) or src["name"]
    the = f"The"
    out: list[Chunk] = []

    def add(section: str, text: str) -> None:
        out.append(_card(src, data, section, text))

    # 1. Expense ratio -----------------------------------------------------
    er = _pct(data.get("expense_ratio"))
    if er:
        base = _pct(data.get("base_expense_ratio"))
        extra = f" (base expense ratio {base} %)" if base else ""
        add(
            "expense_ratio",
            f"The expense ratio of {name} is {er} %{extra}. "
            "Expense ratio is the annual percentage of fund assets charged to "
            "the fund for management and administration.",
        )

    # 2. Exit load ---------------------------------------------------------
    el = _clean(data.get("exit_load"))
    if el:
        if el.lower() == "nil":
            add(
                "exit_load",
                f"The exit load of {name} is Nil - there is no exit load on "
                "redemption, full or partial.",
            )
        else:
            add(
                "exit_load",
                f"The exit load of {name} is: {el}. Exit load is a fee payable "
                "to the fund house for redeeming units before the specified "
                "period from the date of investment.",
            )

    # 3. Lock-in -----------------------------------------------------------
    # Emitted for ALL 5 schemes, including an explicit negative. A user asking
    # "is there a lock-in on HDFC Large Cap?" deserves "no", not "not found".
    lock = _as_dict(data.get("lock_in"))
    years = lock.get("years")
    months = lock.get("months") or 0
    extra_lock = _as_dict(data.get("additional_details"))
    if not years:
        years = extra_lock.get("lock_in_yrs")
    if years:
        span = f"{int(years)} year" + ("s" if int(years) != 1 else "")
        if int(months):
            span += f" and {int(months)} month" + ("s" if int(months) != 1 else "")
        add(
            "lock_in_period",
            f"The lock-in period of {name} is {span}. Units cannot be "
            "redeemed before the lock-in period ends.",
        )
    else:
        add(
            "lock_in_period",
            f"{name} has no lock-in period - units can be redeemed at any "
            "time after purchase.",
        )

    # 4. Minimum investment / SIP -----------------------------------------
    first = _rupees(data.get("min_investment_amount"))
    if first:
        bits = [f"The minimum for the 1st investment (lump sum) in {name} is INR {first}."]
        addl = _rupees(data.get("mini_additional_investment"))
        if addl:
            bits.append(f"The minimum additional investment is INR {addl}.")
        mult = _num(data.get("purchase_multiplier"))
        if mult and mult > 1:
            bits.append(f"Purchase amounts must be in multiples of INR {int(mult)}.")
        wd = _rupees(data.get("min_withdrawal"))
        if wd:
            bits.append(f"The minimum redemption/withdrawal amount is INR {wd}.")
        add("minimum_investment", " ".join(bits))

    sip = _rupees(data.get("min_sip_investment"))
    if sip:
        bits = [f"The minimum SIP investment in {name} is INR {sip}."]
        smult = _num(data.get("sip_multiplier"))
        if smult and smult > 1:
            bits.append(f"SIP instalments must be in multiples of INR {int(smult)}.")
        add("sip_minimum", " ".join(bits))

    # 5. Benchmark ---------------------------------------------------------
    bname = _clean(data.get("benchmark_name"))
    bshort = _clean(data.get("benchmark"))
    if bname or bshort:
        shown = bname or bshort
        tail = (
            f" (listed as {bshort})"
            if bname and bshort and bname.lower() != bshort.lower()
            else ""
        )
        add(
            "benchmark",
            f"The fund benchmark of {name} is {shown}{tail}.",
        )

    # 6. Riskometer --------------------------------------------------------
    # NOTE: the rendered risk badge ("Very High Risk") is the authoritative
    # value and is emitted by Extractor B (extract_prose). The JSON
    # `nfo_risk` field CONFLICTS with it ("Moderately High Riskometer"), so it
    # is deliberately NOT emitted here as an answerable fact - two
    # contradictory numbers must never both be retrievable. The conflict is
    # reported by coverage_report() and disclosed in the README.

    # 7. Objective ---------------------------------------------------------
    desc = _clean(data.get("description"))
    if desc:
        add(
            "investment_objective",
            f"Investment objective of {name}: {desc}",
        )

    # 8. Documents / statements -------------------------------------------
    # Emitted as THREE separate cards, not one merged blob: combined they ran to
    # ~510 chars, past the chunk ceiling, and mixing three distinct facts into a
    # single embedding blurs all three. Separate cards also mean a query about
    # statements retrieves the RTA card specifically.
    sid = _clean(data.get("sid_url"))
    if sid:
        add(
            "documents",
            f"The Scheme Information Document (SID), Key Information Memorandum "
            f"(KIM) and monthly factsheet for {name} are published by HDFC "
            f"Mutual Fund at {sid}.",
        )

    rta = _clean(data.get("registrar_agent"))
    if rta:
        add(
            "documents_statements",
            f"The Registrar and Transfer Agent (RTA) for {name} is {rta}. "
            f"Account statements, tax statements and capital-gains statements "
            f"are requested from the RTA or downloaded from the AMC/RTA website.",
        )

    amc_page = _clean(data.get("amc_page_url"))
    if amc_page:
        add(
            "documents_amc_page",
            f"All HDFC Mutual Fund schemes are listed at {amc_page}.",
        )

    # 9. Identity facts ----------------------------------------------------
    ident = [
        f"{name} is a {(_clean(data.get('category')) or 'mutual fund').lower()} "
        f"scheme, {(_clean(data.get('sub_category')) or '').lower()} category, "
        f"{_clean(data.get('plan_type')) or 'Direct'} plan, Growth option.",
        f"Fund house: {_clean(data.get('fund_house')) or 'HDFC Mutual Fund'}.",
    ]
    inception = _clean(data.get("allotment_date"))
    launch = _clean(data.get("launch_date"))
    if inception:
        ident.append(f"Date of incorporation of the scheme: {inception}.")
    if launch:
        ident.append(f"Plan launch date on Groww: {launch}.")
    isin = _clean(data.get("isin"))
    if isin:
        ident.append(f"ISIN: {isin}.")
    scode = _clean(data.get("scheme_code"))
    if scode:
        ident.append(f"Groww scheme code: {scode}.")
    add("scheme_identity", " ".join(ident))

    # 10. NAV / AUM / turnover / stamp duty / rating -----------------------
    nav = _num(data.get("nav"))
    nav_date = _clean(data.get("nav_date"))
    if nav is not None:
        add(
            "nav",
            f"The latest NAV of {name} is INR {nav:,.3f} as of "
            f"{nav_date or 'the date published on the source page'}.",
        )

    aum = _num(data.get("aum"))
    if aum is not None:
        add(
            "aum",
            f"The scheme-level Assets Under Management (AUM) of {name} is "
            f"INR {aum:,.2f} crore as of {nav_date or 'the date published on the source page'}. "
            "This is the scheme's own AUM, not the AMC-level total.",
        )

    turn = _clean(data.get("portfolio_turnover"))
    if turn:
        # Portfolio turnover is a disclosed non-performance metric (it measures
        # how often the portfolio is reshuffled, not what it earned), so it is
        # kept. The word "annualised" here is deliberate and is NOT treated as
        # a performance claim - see PERFORMANCE_PATTERNS in build_chunks.
        add(
            "portfolio_turnover",
            f"The portfolio turnover ratio of {name} is {turn} "
            "(annualised, as published on the source page).",
        )

    stamp = _clean(data.get("stamp_duty"))
    if stamp:
        add(
            "stamp_duty",
            f"Stamp duty on investment in {name}: {stamp}. Stamp duty is a tax "
            "payable on purchase of units.",
        )

    rating = _clean(data.get("groww_rating"))
    if rating:
        add(
            "groww_rating",
            f"Groww's platform rating for {name} is {rating} out of 5. This is "
            "a platform rating, not a regulatory risk indicator.",
        )

    fac = []
    if _bool_yesno(data.get("sip_allowed")) == "Yes":
        fac.append("SIP (systematic investment) is allowed")
    if _bool_yesno(data.get("lumpsum_allowed")) == "Yes":
        fac.append("lump sum investment is allowed")
    if fac:
        add(
            "investment_facility",
            f"For {name}: {' and '.join(fac)}.",
        )

    return [c.finalise() for c in out]


# ---------------------------------------------------------------------------
# PHASE 3 - Extractor B: labelled prose sections from rendered text
#           (REQ-2, REQ-4)
#
# Extractor A gives precise values but no human-facing explanation. Extractor B
# supplies the prose: the minimum-investments block, the exit-load/stamp-duty/
# tax block, the glossary definitions, the investment objective, the rendered
# risk badge, and the scheme-details label:value pairs.
#
# ~40% of the visible lines are boilerplate (nav, footer, holdings, peer
# comparison, fund-manager bios) plus blocks that must NOT enter the corpus:
#   * "About" prose      - repeats AMC-level AUM on every page and names a fund
#                          manager that contradicts the JSON field (PRD §7.4)
#   * "Fund management"  - manager bios with education/work history
#   * "Returns and rankings" / "Exit Load" history - performance figures and
#                          three different historical exit loads
# ---------------------------------------------------------------------------

# Lines that must never reach the corpus. Matched case-insensitively against the
# whole line, or as a substring for the bracketed patterns.
_DENY_EXACT = {
    # nav / footer
    "stocks", "invest in stocks", "intraday", "etf screener", "stock screener",
    "stock events", "demat account", "share market today", "f&o", "indexes",
    "terminal", "option chain", "mtfs", "ipo", "news updates",
    "invest in mutual funds", "mutual fund houses", "nfos",
    "track funds", "compare funds", "sip calculator", "brokerage calculator",
    "margin calculator", "swp calculator", "pricing", "blog",
    "home", "contact us", "download the app", "groww", "about us", "media & press",
    "careers", "help & support", "trust & safety", "investor relations",
    "products", "groww amc", "pms", "bonds", "see all", "more",
    "comprehensive", "view details", "compare",
    # section headings whose bodies are deliberately NOT ingested
    "about", "holdings", "portfolio", "performance", "fund management",
    "returns and rankings", "annualised returns", "absolute returns",
    "fund returns", "category average", "education", "experience",
    "also manages these schemes",
}

_DENY_SUBSTR = (
    "nav to", "© 2016-", "version:", "all rights reserved", "sarjapur main road",
    "vaishnavi tech park", "hdfc house", "churchgate", "backbay", "rayala towers",
    "anna salai", "tier ii", "tower ii", "7th floor", "email", "e-mail",
    "phone", "address", "website", "www.", "http://", "https://",
    "prior to joining", "has done pgdm", "has done b.com", "invest in stocks",
    "track returns", "buy now, pay later", "start sip", "one time",
    "monthly investment", "monthly sip", "return calculator",
    "total aum", "rank (total assets)", "sarjapur", "bengaluru", "mumbai",
)

# Glossary terms: heading line is followed by one long definition paragraph.
_GLOSSARY = {
    "Expense ratio": "expense_ratio_definition",
    "Tax": "tax_definition",
    "Exit load": "exit_load_definition",
    "Stamp duty": "stamp_duty_definition",
}

# Scheme-details label:value pairs that are safe and factual. Deliberately
# excludes Total AUM (AMC-level, wrong for a scheme), Rank, Phone, E-mail,
# Website and Address (contact data / not facts).
_SCHEME_DETAIL_LABELS = (
    "Fund house",
    "Date of Incorporation",
    "Launch Date",
    "Custodian",
    "Registrar & Transfer Agent",
)

# Windowed sections: (anchor line, stop line, section name)
_WINDOW_SECTIONS = (
    ("Minimum investments", "Understand terms", "minimum_investments"),
    ("Exit load, stamp duty and tax", "Check past data", "exit_load_stamp_duty_tax"),
    ("Investment Objective", "Fund benchmark", "investment_objective"),
    ("Fund benchmark", "Scheme Information Document(SID)", "fund_benchmark"),
)

_RISK_BADGE_RE = re.compile(
    r"^(Very High|High|Moderately High|Moderate|Low)\s*Risk$"
)

# split_section packs the *body* to config.CHUNK_SIZE; the section header is
# prepended afterwards. The longest anchor is "Exit load, stamp duty and tax"
# (28 chars), so the hard ceiling is CHUNK_SIZE + 40. Verified by
# scripts/debug_prose.py.
CHUNK_HARD_LIMIT = config.CHUNK_SIZE + 40


def _is_denied(line: str) -> bool:
    low = line.lower()
    if low in _DENY_EXACT:
        return True
    return any(pat in low for pat in _DENY_SUBSTR)


def _visible_lines(html: str) -> list[str]:
    """Rendered text as a clean list of lines.

    ``decompose()`` of script/style/noscript is essential: without it the
    embedded __NEXT_DATA__ JSON blob is treated as page text.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    raw = soup.get_text("\n")
    out: list[str] = []
    for line in raw.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) >= config.MIN_LINE_CHARS:
            out.append(line)
    return out


def _window(lines: list[str], anchor: str, stop: str) -> list[str]:
    """Lines between ``anchor`` (exclusive) and ``stop`` (exclusive)."""
    try:
        start = lines.index(anchor)
    except ValueError:
        return []
    collected: list[str] = []
    for line in lines[start + 1 :]:
        if line == stop:
            break
        collected.append(line)
    return collected


def _pair_after(lines: list[str], label: str) -> str | None:
    """The single line following a ``label`` line - i.e. a label:value pair."""
    try:
        idx = lines.index(label)
    except ValueError:
        return None
    if idx + 1 < len(lines):
        return lines[idx + 1]
    return None


def _definition_after(lines: list[str], term: str, min_len: int = 45) -> str | None:
    """The glossary *definition* following a term.

    A term such as "Expense ratio" appears more than once on the page - once as
    a stat tile whose value is e.g. "1.03%", and once as a glossary heading
    followed by a full-sentence definition. Scanning every occurrence and
    taking the first following line that *looks like a sentence* (long enough
    and sentence-terminated) picks the definition, not the stat tile.

    A length threshold alone is not enough: the shortest real definition here
    is "A form of tax payable for the purchase or sale of an asset or
    security." (69 chars), so the test is sentence-shaped rather than a
    hard-coded cutoff.
    """
    for i, line in enumerate(lines):
        if line == term and i + 1 < len(lines):
            nxt = lines[i + 1]
            if len(nxt) >= min_len and nxt.endswith((".", "!", "?")):
                return nxt
    return None


def _hard_wrap(line: str, size: int) -> list[str]:
    """Split one over-long line on sentence/word boundaries.

    Needed because a single source line can exceed the chunk size on its own
    (e.g. a long exit-load clause). Truncating would lose the fact, so the line
    is wrapped instead. Prefers a sentence end, then a word boundary near
    ``size``.
    """
    if len(line) <= size:
        return [line]

    out: list[str] = []
    rest = line
    while len(rest) > size:
        window = rest[:size]
        cut = max(window.rfind(". "), window.rfind("; "), window.rfind(", "))
        if cut < size // 3:  # no usable sentence boundary -> word boundary
            cut = window.rfind(" ")
        if cut < size // 3:  # one giant token -> hard cut
            cut = size
        out.append(rest[: cut + 1].strip())
        rest = rest[cut + 1 :].strip()
    if rest:
        out.append(rest)
    return out


def split_section(
    body_lines: list[str],
    size: int = config.CHUNK_SIZE,
    overlap: int = config.CHUNK_OVERLAP,
) -> list[list[str]]:
    """Pack lines into <= ``size``-char chunks with >= ``overlap`` chars of carry-over.

    Line-based rather than character-based, which is what guarantees a
    ``label: value`` pair is never cut in half (REQ-4). Any single line longer
    than ``size`` is wrapped on a sentence/word boundary first, so no fact is
    truncated and the size limit still holds.
    """
    prepared: list[str] = []
    for line in body_lines:
        prepared.extend(_hard_wrap(line, size))

    chunks: list[list[str]] = []
    buf: list[str] = []
    length = 0

    for line in prepared:
        add = len(line) + (1 if buf else 0)
        if buf and length + add > size:
            chunks.append(buf)
            # Carry trailing lines forward to reach the overlap budget, but
            # only while the carried text plus the incoming line still fits in
            # ``size``. Without this cap, carrying a long line (e.g. a wrapped
            # 271-char sentence) would rebuild an over-size chunk.
            carry: list[str] = []
            carry_len = 0
            for prev in reversed(buf):
                if carry_len >= overlap:
                    break
                candidate = prev + " "
                if carry_len + len(candidate) + len(line) > size:
                    break
                carry.insert(0, prev)
                carry_len += len(candidate)
            buf = carry
            length = carry_len
            add = len(line) + (1 if buf else 0)
        buf.append(line)
        length += add

    if buf:
        chunks.append(buf)
    return chunks


def extract_prose(src: dict, html: str) -> list[Chunk]:
    """Extractor B: labelled, self-contained prose sections.

    Anchors and stop markers are located in the RAW line list (deny-filtering
    must never remove a boundary), and the deny-list is applied to the
    collected body afterwards.
    """
    lines = _visible_lines(html)
    out: list[Chunk] = []
    seen: set[str] = set()

    def emit(section: str, text: str) -> None:
        text = text.strip()
        if len(text) < config.MIN_CHUNK_CHARS:
            return
        if text in seen:
            return
        seen.add(text)
        out.append(
            Chunk(
                text=text,
                section=section,
                source_url=src["url"],
                source_name=src["name"],
                scheme_slug=src["slug"],
                scheme_name=src["name"],
                category=src["category"],
                producer="prose_section",
                extracted_from="visible_text",
                as_of="",
            ).finalise()
        )

    for anchor, stop, section in _WINDOW_SECTIONS:
        body = [
            ln for ln in _window(lines, anchor, stop) if not _is_denied(ln)
        ]
        if not body:
            continue
        # Reserve room for the "{anchor}\n" prefix so the emitted chunk, header
        # included, still respects the hard limit.
        budget = CHUNK_HARD_LIMIT - len(anchor) - 1
        for pack in split_section(body, size=budget):
            emit(section, f"{anchor}\n" + "\n".join(pack))

    # Glossary definitions: heading line is followed by one paragraph.
    for term, section in _GLOSSARY.items():
        definition = _definition_after(lines, term)
        if definition and not _is_denied(definition):
            emit(section, f"{term}\n{definition}")

    # Scheme-details label:value pairs (contact data and AMC-level AUM excluded).
    detail_bits = [
        f"{label}: {_pair_after(lines, label)}"
        for label in _SCHEME_DETAIL_LABELS
        if _pair_after(lines, label)
    ]
    if detail_bits:
        emit("scheme_details", "\n".join(detail_bits))

    # Rendered risk badge - the AUTHORITATIVE riskometer value. The JSON
    # `nfo_risk` field disagrees ("Moderately High Riskometer"); emitting both
    # would put two contradictory numbers in the corpus, so only the badge -
    # which is what the page actually displays - becomes an answerable fact.
    badge = next(
        (
            m.group(1).strip()
            for m in (_RISK_BADGE_RE.fullmatch(ln) for ln in lines)
            if m is not None
        ),
        None,
    )
    if badge:
        emit(
            "riskometer",
            f"Riskometer level of {src['name']}: {badge}. The source page "
            f"displays this badge as '{badge} Risk'. On SEBI's six-level "
            "riskometer scale (Very Low, Low, Moderate, Moderately High, High, "
            "Very High), this scheme sits at the "
            f"{badge} level.",
        )

    return out


# ---------------------------------------------------------------------------
# PHASE 4 - Assemble, scrub, exclude, dump, report  (REQ-5, REQ-8, REQ-9, REQ-10)
# ---------------------------------------------------------------------------

# Performance / ranking content that must never enter the corpus.
#
# The brief says: no performance claims, do not compute or compare returns.
# Enforcing that at INGEST time (rather than trusting a prompt) is what makes
# it a guarantee - a return figure that is not in the corpus cannot be quoted.
#
# NOTE the deliberate exclusions: "annualised" alone is NOT banned. It appears
# legitimately in the portfolio-turnover-ratio card, which is a disclosed
# non-performance metric. Only *return* contexts are blocked.
PERFORMANCE_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"annualised return",
        r"\b\d+Y\s+annualised\b",
        r"\breturns and rankings\b",
        r"\bfund returns\b",
        r"\babsolute returns\b",
        r"\bcategory average\b",
        r"\brank \(equity",
        r"\bcompare similar funds\b",
        r"\breturn calculator\b",
        r"\b1\s*Y\b.*%\s*\n?\s*3\s*Y\b",   # the 1Y/3Y/5Y/10Y return strip
    )
]

# Which chunk sections satisfy each of the 7 target fact types (PRD §6.1).
COVERAGE_MAP: dict[str, set[str]] = {
    "expense_ratio": {"expense_ratio", "expense_ratio_definition"},
    "exit_load": {"exit_load", "exit_load_stamp_duty_tax", "exit_load_definition"},
    "minimum_investment": {
        "minimum_investment", "sip_minimum", "minimum_investments",
    },
    "lock_in_period": {"lock_in_period"},
    "riskometer": {"riskometer"},
    "benchmark": {"benchmark", "fund_benchmark"},
    "documents": {
        "documents", "documents_statements", "documents_amc_page", "scheme_details",
    },
}

_LOCK_IN_NEGATIVE = "no lock-in period"


def _is_performance(text: str) -> bool:
    return any(p.search(text) for p in PERFORMANCE_PATTERNS)


def build_chunks(force_refresh: bool = False) -> tuple[list[Chunk], dict]:
    """Full offline corpus build.

    Returns ``(chunks, stats)``. Chunks are deterministic (stable chunk_id) so
    re-running ingestion produces a diffable, idempotent result (NFR-4).
    """
    pages = load_pages(force_refresh=force_refresh)

    chunks: list[Chunk] = []
    stats = {
        "pages": len(pages),
        "raw_fact_cards": 0,
        "raw_prose": 0,
        "dropped_performance": 0,
        "dropped_short": 0,
        "dropped_duplicate": 0,
        "scrubbed": 0,
        "per_scheme": {},
    }

    counters: dict[str, dict[str, int]] = {}
    seen_ids: set[str] = set()

    for src in config.SOURCES:
        slug = src["slug"]
        produced = extract_facts(src, pages[slug]) + extract_prose(src, pages[slug])
        stats["raw_fact_cards"] += sum(
            1 for c in produced if c.producer == "fact_card"
        )
        stats["raw_prose"] += sum(
            1 for c in produced if c.producer == "prose_section"
        )

        kept_for_scheme = 0
        counters[slug] = {}

        for chunk in produced:
            # --- exclusion: performance / ranking figures (P3) -------------
            if _is_performance(chunk.text):
                stats["dropped_performance"] += 1
                continue

            # --- scrub: PII / contact data (REQ-9) ------------------------
            scrubbed = scrub_pii(chunk.text)
            if scrubbed != chunk.text:
                stats["scrubbed"] += 1
                chunk.text = scrubbed

            # --- minimum viable chunk -------------------------------------
            if len(chunk.text.strip()) < config.MIN_CHUNK_CHARS:
                stats["dropped_short"] += 1
                continue

            # --- deterministic id (NFR-4) ---------------------------------
            n = counters[slug].get(chunk.section, 0)
            counters[slug][chunk.section] = n + 1
            chunk.chunk_id = f"{slug}__{chunk.section}__{n:03d}"
            if chunk.chunk_id in seen_ids:
                stats["dropped_duplicate"] += 1
                continue
            seen_ids.add(chunk.chunk_id)

            chunk.finalise()
            chunks.append(chunk)
            kept_for_scheme += 1

        stats["per_scheme"][slug] = kept_for_scheme

    return chunks, stats


def _dump_header(chunks: list[Chunk], stats: dict) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines_out = [
        "=" * 100,
        "HDFC MUTUAL FUND FAQ CORPUS - INSPECTABLE CHUNK DUMP",
        "=" * 100,
        f"Generated (UTC)     : {now}",
        f"Chunks              : {len(chunks)}",
        f"  fact_card         : {sum(1 for c in chunks if c.producer == 'fact_card')}",
        f"  prose_section     : {sum(1 for c in chunks if c.producer == 'prose_section')}",
        f"Pages ingested      : {stats['pages']}",
        f"Dropped (performance): {stats['dropped_performance']}",
        f"Dropped (too short) : {stats['dropped_short']}",
        f"Dropped (duplicate) : {stats['dropped_duplicate']}",
        f"PII-scrubbed chunks : {stats['scrubbed']}",
        "",
        f"Chunking            : size={config.CHUNK_SIZE} chars, "
        f"overlap={config.CHUNK_OVERLAP} chars, min={config.MIN_CHUNK_CHARS} chars",
        f"Embedding model     : {config.EMBED_MODEL} ({config.EMBED_DIM}-dim)",
        f"Vector DB           : {config.COLLECTION_NAME} -> {config.CHROMA_DIR}",
        "",
        "SOURCES (the only 5 pages used; all public Groww scheme pages):",
    ]
    for i, s in enumerate(config.SOURCES, 1):
        lines_out.append(f"  {i}. [{s['category']}] {s['name']}")
        lines_out.append(f"     {s['url']}")
    lines_out += [
        "",
        "EXCLUSIONS BY DESIGN:",
        "  - No return, ranking, peer-comparison or performance figures.",
        "  - No fund-manager names (the JSON field and the page's own About",
        "    prose disagree; PRD section 7.4 - not answered until reconciled).",
        "  - No AMC-level AUM from the About prose (it repeats the same total on",
        "    every scheme page); scheme-level JSON AUM is used instead.",
        "  - No e-mail addresses, phone numbers or postal addresses.",
        "",
        "=" * 100,
        "",
    ]
    return "\n".join(lines_out)


def write_dumps(chunks: list[Chunk], stats: dict) -> None:
    """Write ``data/chunks.txt`` (human-readable) and ``data/chunks.jsonl``.

    ``chunks.txt`` is the artifact a reviewer reads to audit the corpus without
    running anything (PRD REQ-8).
    """
    out: list[str] = [_dump_header(chunks, stats)]
    for i, c in enumerate(chunks, 1):
        out.append("-" * 100)
        out.append(
            f"[{i:04d}] {c.chunk_id}\n"
            f"  section        : {c.section}\n"
            f"  producer       : {c.producer}  (from {c.extracted_from})\n"
            f"  scheme         : {c.scheme_name}  [{c.category}]"
            f"  code={c.scheme_code}\n"
            f"  as_of          : {c.as_of or '(not stated on page)'}\n"
            f"  char_len       : {c.char_len}   hash={c.content_hash}\n"
            f"  source_url     : {c.source_url}\n"
            f"  ingested_at    : {c.ingested_at}\n"
        )
        out.append("  " + "-" * 96)
        for text_line in c.text.split("\n"):
            out.append(f"  | {text_line}")
        out.append("")
    config.CHUNKS_TXT.write_text("\n".join(out), encoding="utf-8")

    with config.DOCS_JSONL.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps({"text": c.text, **c.to_metadata()},
                                ensure_ascii=False) + "\n")


def coverage_report(chunks: list[Chunk]) -> dict:
    """Scheme x target-fact matrix, plus known source conflicts.

    Raises ``RuntimeError`` when a target fact is missing for any scheme, so a
    thin corpus can never quietly pass (PRD risk R1).
    """
    by_scheme: dict[str, set[str]] = {}
    for c in chunks:
        by_scheme.setdefault(c.scheme_slug, set()).add(c.section)

    matrix: dict[str, dict[str, bool]] = {}
    for src in config.SOURCES:
        sections = by_scheme.get(src["slug"], set())
        matrix[src["slug"]] = {
            fact: bool(sections & allowed) for fact, allowed in COVERAGE_MAP.items()
        }

    gaps = [
        f"{slug} :: {fact}"
        for slug, row in matrix.items()
        for fact, present in row.items()
        if not present
    ]

    # Lock-in: a card must exist for every scheme, but only ELSS may state a
    # real duration. The other four state an explicit negative, which is the
    # correct answer to "is there a lock-in on <non-ELSS scheme>?".
    lock_real = [
        c.scheme_slug
        for c in chunks
        if c.section == "lock_in_period" and _LOCK_IN_NEGATIVE not in c.text
    ]
    expected_real = ["hdfc-elss-tax-saver-fund-direct-plan-growth"]
    lock_ok = sorted(lock_real) == expected_real

    report = {
        "matrix": matrix,
        "gaps": gaps,
        "lock_in_with_duration": lock_real,
        "lock_in_ok": lock_ok,
        # Disclosed, NOT resolved: the rendered badge and the JSON field
        # disagree. Only the badge is in the corpus; see README Known Limits.
        "conflicts": [
            {
                "field": "riskometer",
                "rendered_badge": "Very High (all 5 schemes)",
                "json_nfo_risk": "Moderately High / Moderately High Riskometer",
                "in_corpus": "rendered badge only",
                "status": "UNRESOLVED - confirm against HDFC's official "
                          "riskometer disclosure (PRD Q3)",
            },
            {
                "field": "fund_manager",
                "issue": "JSON fund_manager and the page's About prose name "
                         "different people",
                "in_corpus": "neither - not answered",
                "status": "excluded until reconciled against the official SID",
            },
            {
                "field": "aum",
                "issue": "About prose repeats the AMC-level AUM on every scheme "
                         "page",
                "in_corpus": "scheme-level JSON AUM only",
                "status": "resolved",
            },
        ],
    }
    return report


def _print_report(chunks: list[Chunk], stats: dict, report: dict) -> None:
    print("\n" + "=" * 78)
    print("INGESTION REPORT")
    print("=" * 78)
    print(f"  chunks total        : {len(chunks)}")
    print(f"    fact_card         : {sum(1 for c in chunks if c.producer == 'fact_card')}")
    print(f"    prose_section     : {sum(1 for c in chunks if c.producer == 'prose_section')}")
    print(f"  dropped performance : {stats['dropped_performance']}")
    print(f"  dropped too short   : {stats['dropped_short']}")
    print(f"  PII-scrubbed chunks : {stats['scrubbed']}")

    print("\n  Coverage (scheme x target fact)")
    facts = list(COVERAGE_MAP)
    abbrev = {
        "expense_ratio": "EXP_RATIO",
        "exit_load": "EXIT_LOAD",
        "minimum_investment": "MIN_INV",
        "lock_in_period": "LOCK_IN",
        "riskometer": "RISKOMETER",
        "benchmark": "BENCHMARK",
        "documents": "DOCUMENTS",
    }
    print("    " + "scheme".ljust(22) + "".join(abbrev[f].ljust(12) for f in facts))
    for src in config.SOURCES:
        row = report["matrix"][src["slug"]]
        cells = "".join(
            ("OK".ljust(12) if row[f] else "MISSING".ljust(12)) for f in facts
        )
        print("    " + src["category"][:20].ljust(22) + cells)

    print("\n  Lock-in")
    print(f"    schemes stating a real duration : {report['lock_in_with_duration']}")
    print(f"    expected                        : ['hdfc-elss-tax-saver-fund-direct-plan-growth']")
    print(f"    [{'OK' if report['lock_in_ok'] else 'FAIL'}] exactly the ELSS scheme")

    print("\n  Known source conflicts (disclosed, not silently resolved)")
    for c in report["conflicts"]:
        print(f"    - {c['field']}: {c['status']}")

    print("\n  Dumps")
    print(f"    {config.CHUNKS_TXT}")
    print(f"    {config.DOCS_JSONL}")


# ---------------------------------------------------------------------------
# PHASE 5 - Embed + Store  (REQ-6, REQ-7; NFR-1, NFR-3, NFR-4)
# ---------------------------------------------------------------------------

_MODEL = None


def _model():
    """Lazy singleton for the embedding model.

    Loading MiniLM is slow, and the query stage must use the *identical* model -
    a mismatched embedder makes stored and query vectors incomparable
    (architecture.md §4.2), so the id is read from config rather than hardcoded.
    """
    global _MODEL
    if _MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "sentence-transformers is not installed. Run "
                "`pip install -r requirements.txt`. The first run also "
                "downloads the model (~90 MB)."
            ) from exc
        print(f"  loading {config.EMBED_MODEL} (first run downloads it) ...")
        _MODEL = SentenceTransformer(config.EMBED_MODEL)
    return _MODEL


def drop_collection() -> None:
    """Delete the vector collection so the next store starts from empty.

    Necessary when the embedding model or the chunk parameters change:
    ``upsert`` keys on ``chunk_id``, so stale vectors from a previous
    configuration would survive and silently corrupt retrieval.
    """
    import chromadb

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    try:
        client.delete_collection(config.COLLECTION_NAME)
        print(f"  --reembed: dropped collection '{config.COLLECTION_NAME}'")
    except Exception:  # noqa: BLE001 - Chroma raises if it was absent
        print(f"  --reembed: no existing collection '{config.COLLECTION_NAME}' "
              f"to drop")


def embed_and_store(chunks: list[Chunk]) -> None:
    """Embed every chunk and upsert into the persisted Chroma collection.

    ``upsert`` with deterministic chunk ids makes this idempotent: running
    ingestion twice leaves the collection unchanged instead of doubling it
    (NFR-3, NFR-4). Vectors are L2-normalised and the space is cosine, which is
    the standard pairing for MiniLM sentence embeddings.
    """
    if not chunks:
        print("  no chunks to embed")
        return

    model = _model()
    print(f"  embedding {len(chunks)} chunks with {config.EMBED_MODEL} ...")
    vectors = model.encode(
        [c.text for c in chunks],
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=32,
    )
    dim = len(vectors[0])

    import chromadb

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    collection = client.get_or_create_collection(
        config.COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    before = collection.count()

    # Stamp the corpus fingerprint onto the collection so a deployed app can
    # tell a current index from a stale one without re-embedding anything.
    # `hnsw:space` is deliberately NOT repeated here: Chroma raises
    # "Changing the distance function of a collection once it is created is not
    # supported" if modify() carries that key, even with the identical value.
    # It is already recorded at creation and modify() merges the rest.
    fingerprint = config.corpus_fingerprint()
    collection.modify(metadata={
        "corpus_fingerprint": fingerprint,
        "embed_model": config.EMBED_MODEL,
        "embed_dim": config.EMBED_DIM,
    })

    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=[[float(x) for x in v] for v in vectors],
        metadatas=[c.to_metadata() for c in chunks],
    )

    after = collection.count()

    if after == before:
        print(f"  [{'OK' if before else 'INFO'}] collection holds {after} chunks "
              f"(upsert is idempotent - re-running changed nothing)")
    else:
        print(f"  [OK] collection {before} -> {after} chunks "
              f"(expected: an added/removed/re-embedded chunk changed the count)")
    if dim != config.EMBED_DIM:
        print(f"  [MISMATCH] embedding dim = {dim}, expected {config.EMBED_DIM}. "
              f"Re-run with --reembed after fixing config.EMBED_MODEL.")
    else:
        print(f"  [OK] embedding dim = {dim}")
    print(f"  [OK] persisted to {config.CHROMA_DIR}")
    print(f"  [OK] corpus fingerprint {fingerprint} "
          f"(sources + ingest.py, hashed)")



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest the HDFC MF FAQ corpus.")
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch the 5 pages instead of using the local cache.",
    )
    p.add_argument(
        "--no-embed",
        action="store_true",
        help="Build and dump the corpus but skip embedding / vector store.",
    )
    p.add_argument(
        "--reembed",
        action="store_true",
        help="Delete and rebuild the vector collection from scratch, even if "
             "it already holds data. Use after changing the embedding model "
             "or the chunking parameters.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    print("\n[1/4] Loading sources")
    chunks, stats = build_chunks(force_refresh=args.refresh)
    print(f"  -> {stats['pages']} pages, {len(chunks)} chunks after "
          f"scrub + exclusions")

    print("\n[2/4] Coverage check")
    report = coverage_report(chunks)
    if report["gaps"]:
        print(f"  [FAIL] {len(report['gaps'])} missing target fact(s):")
        for gap in report["gaps"]:
            print(f"         - {gap}")
        print("\n  Ingestion ABORTED: a thin corpus must not pass silently "
              "(PRD risk R1).")
        print("  Re-run with --refresh, or re-run scripts/probe_anchors.py if "
              "the page markup changed.")
        return 1

    print("\n[3/4] Writing dumps")
    write_dumps(chunks, stats)
    _print_report(chunks, stats, report)

    print("\n[4/4] Embedding + vector store")
    if args.no_embed:
        print("  --no-embed: skipped. The corpus was built and dumped, but no")
        print("  vectors were written, so the query stage will not find an index.")
        return 0

    try:
        if args.reembed:
            drop_collection()
        embed_and_store(chunks)
    except ImportError as exc:
        print(f"  [FAIL] {exc}")
        return 1

    print("\nINGESTION COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
