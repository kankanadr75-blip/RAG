"""Guardrails for the HDFC Mutual Fund FAQ assistant.

Two responsibilities, deliberately separated by phase:

* **Ingestion-time** (``scrub_pii``) - used by ``ingest.py`` to strip contact
  and personal data out of the corpus so a PII string is never retrievable
  (PRD REQ-9, layer 1 of architecture.md §5).
* **Query-time** (``detect_pii``) - used by ``rag.py`` to refuse a user request
  that contains personal data (PRD REQ-20, layer 2).

Phase 6 adds the advice / performance classifiers plus the refusal copy
builders, all of which run **before** retrieval (architecture.md §5 layer 2).
The ordering is deliberate: refusing first means a personal or advice-seeking
question never reaches the embedder at all, so it can never influence retrieval.

DESIGN RULE: a detected PII value is never stored on the returned object in a
form that could be logged or echoed back to the user. ``PIIHit`` records only
the *kind* of PII, never the matched substring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import config

# --------------------------------------------------------------------------
# PII patterns
# --------------------------------------------------------------------------
# Order matters, because the patterns overlap. The rules used:
#   * an unbroken run of 9-18 digits is an ACCOUNT number;
#   * digit runs broken by spaces/dashes ("98765 43210", "022-66316333")
#     are PHONE numbers.
# So the account-number test must be tried before the phone test, otherwise a
# 13-digit account number gets mislabelled as a phone number.

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("pan", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("aadhaar", re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # 4-6 digit one-time passcode near the word otp
    ("otp", re.compile(r"\b(?:otp|passcode|verification code)\b\D{0,12}\b\d{4,6}\b", re.I)),
    # unbroken long digit run -> account / demat number (must precede phone)
    ("account_number", re.compile(r"\b\d{9,18}\b")),
    # 9-13 digits, optionally spaced/dashed or +91-prefixed, e.g.
    # "+91 98765 43210", "98765 43210", "022 - 66316333".
    ("phone", re.compile(r"(?<!\d)(?:\+?91[\s-]?)?(?:\d[\s-]?){9,13}(?!\d)")),
]

# Contact / address data that must never be stored in the corpus.
#
# NOTE: there is deliberately NO money/AUM pattern here. An earlier version
# redacted figures like "39,933.37 crore", which silently destroyed the
# legitimate *scheme-level* AUM fact. The AMC-level AUM that appears in the
# page's "About" prose is instead removed structurally, by the prose deny-list
# in ingest.py ("Total AUM", and the repeated 9,86,23x total), so the real
# scheme-level figure survives. Redaction is for PII only.
_CONTACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b\d{2}\s*[–—-]\s*\d{8}\b"),          # 022 - 66316333
    re.compile(r"\+?\d[\d\s\-()]{9,}\d"),               # phone-ish
    re.compile(r"\b\d{12}\b"),                           # aadhaar-like
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),           # PAN
    # Remove the e-mail/phone we already caught, plus explicit AMC-level AUM.
    re.compile(r"Total AUM is .*?(?:Cr|Crore)\b", re.I),
]

_REDACTED = "[redacted]"


@dataclass(frozen=True)
class PIIHit:
    """What kind of PII was found - deliberately NOT the value itself.

    Keeping the raw value out of this object is what guarantees a PII string
    cannot be echoed back to the user or written to a log (PRD REQ-20).
    """

    kind: str
    count: int


def detect_pii(text: str) -> PIIHit | None:
    """Return the first kind of personal data found in ``text``, else ``None``."""
    if not text:
        return None
    for kind, pattern in _PII_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            return PIIHit(kind=kind, count=len(matches))
    return None


def scrub_pii(text: str) -> str:
    """Replace personal data and contact details in corpus text.

    Used at ingestion time on every chunk before it is stored, so no PII ever
    reaches the vector DB (PRD REQ-9, architecture.md §5 layer 1).
    """
    if not text:
        return text
    out = text
    for pattern in _CONTACT_PATTERNS:
        out = pattern.sub(_REDACTED, out)
    return out


# --------------------------------------------------------------------------
# PHASE 6 - Online classifiers + refusal copy  (REQ-16 .. REQ-21)
# --------------------------------------------------------------------------


def _normalise_query(text: str) -> str:
    """Lowercase and unify separators so scheme-name matching is spelling-robust.

    Mirrors ``rag._normalise``. "Small-Cap", "small_cap" and "small cap" must all
    compare equal, otherwise a user can slip an out-of-scope scheme past the
    scope check just by hyphenating it.
    """
    text = text.lower()
    for ch in "-_/":
        text = text.replace(ch, " ")
    return re.sub(r"\s+", " ", text)

# Advice / personalised requests: "what should I do?" rather than "what is X?".
#
# Beyond config.REFUSAL_PATTERNS, these catch the phrasings a user actually
# types. Two shapes matter especially:
#   * the bare comparative adjective - "is HDFC Flexi Cap a good scheme?"
#   * allocation / planning language - "how should I split 50000 across funds?"
_ADVICE_EXTRA_PATTERNS = [
    r"\bshould i\b",
    r"\bshould we\b",
    r"\bi want to\b",
    r"\bi am thinking of\b",
    r"\bi plan to\b",
    r"\bplan my\b",
    r"\bhelp me (choose|pick|select|decide)\b",
    r"\bwhich .{0,25}\b(should|do) i\b",
    r"\bwhat should i\b",
    r"\bis .{0,40}\b(a )?(good|bad|best|safe|risky)\b",
    r"\bare .{0,30}\b(any )?(good|bad|risky|safe) (fund|scheme|option)s?\b",
    r"\b(good|bad|safe|risky) (fund|scheme)s? (to|for)\b",
    r"\bsuitable for me\b",
    r"\bhow much should i\b",
    r"\bhow do i (choose|pick|start|invest)\b",
    r"\bwhere (do|should) i\b",
    r"\ballocate\b",
    r"\basset allocation\b",
    # NB: not a bare \bportfolio\b. A bare match refused the legitimate
    # factual question "what is the portfolio turnover ratio of X?", which is
    # a disclosed SEBI metric we do answer. The personalised senses -
    # "my portfolio", "rebalance my portfolio", "review my portfolio" - are
    # covered by config.REFUSAL_PATTERNS plus the explicit patterns below.
    r"\b(my|our|your) portfolio\b",
    r"\b(rebalance|review|reallocate|restructure) (my|our|your)\b",
    r"\bportfolio (diversification|allocation|rebalancing|review|checkup|check-up)\b",
    r"\bgoal planning\b",
    r"\bsip amount should\b",
    r"\bwhat if i invest\b",
]

_ADVICE_RE = re.compile(
    "|".join(config.REFUSAL_PATTERNS + _ADVICE_EXTRA_PATTERNS), re.I
)

# Performance / return questions. Enforced as a refusal rather than an answer
# because the brief forbids computing or comparing returns (PRD P3, risk R5).
#
# The corpus contains no return figures at all (they are dropped at ingest), so
# the honest answer would always be "not in sources" - but a friendly, explicit
# refusal plus the official factsheet link is far more useful than that.
_PERFORMANCE_PATTERNS = [
    r"\breturns?\b",
    r"\bhow much (will|would|can|does)\b",
    r"\bhow much (money|invest)\b",
    r"\b(perform|performance|performing)\w*\b",
    r"\bperformers?\b",
    r"\bbest performing\b",
    r"\btop performing\b",
    r"\boutperform\w*\b",
    r"\bunderperform\w*\b",
    r"\bbeat the (index|market|nifty)\b",
    r"\bvs\.? (the )?(index|nifty|market)\b",
    r"\bversus the (index|nifty|market)\b",
    r"\b(cagr|xirr|irr|nav change)\b",
    r"\bcompounding\b",
    r"\b(pct|percent|%) gain\b",
    r"\bgain of\b",
    r"\bprofit(able)?\b",
    r"\bmake (money|returns?)\b",
    r"\bdouble\b",
    r"\bmultipl(y|ied)\b",
    r"\bsince (inception|launch)\b",
    r"\bcompare returns\b",
    r"\bvs\.? (hdfc|other)\b",
    r"\bwhich (fund|scheme) (gave|gives|returned|returns)\b",
    r"\bexpect(ed)? return\b",
    r"\bproject(ed)? return\b",
    r"\b5 ?y|3 ?y|1 ?y|10 ?y\b",
    r"\bsip (return|growth)\b",
    r"\binflation\b",
    r"\btax (saving|benefit|return)\b.*\breturn\b",
]

_PERFORMANCE_RE = re.compile("|".join(_PERFORMANCE_PATTERNS), re.I)

# Words that legitimately contain a banned substring but are NOT advice or
# performance questions. Checked before a match is allowed to win.
#
#   "returns" inside "return load"? -> no; but "Total AUM" vs "AUM returns" is a
#   real query. More importantly, factual questions must never be refused just
#   because they mention a word like "risk" or "performance" in a descriptive
#   sense. Each exemption below was found by running the classifier against the
#   sample Q&A set in Phase 11.
_ALLOW_EXCEPTIONS = [
    # Riskometer / risk disclosure questions are core FAQs, not performance asks.
    r"\briskometer\b",
    r"\brisk (rating|level|ometer)\b",
    r"\bwhat is the risk\b",
    r"\bhow risky\b",
]


def _is_exempt(text: str) -> bool:
    return any(re.search(p, text, re.I) for p in _ALLOW_EXCEPTIONS)


def is_advice_request(text: str) -> bool:
    """True when ``text`` asks what the user *should do* rather than asking a fact.

    Politeness check: the classifier errs toward refusing only genuine
    recommendation requests. A purely factual question - "what is the expense
    ratio of HDFC ELSS?" - must return ``False`` so the factual path still runs.
    """
    if not text or _is_exempt(text):
        return False
    return bool(_ADVICE_RE.search(text))


def is_performance_request(text: str) -> bool:
    """True when ``text`` asks about returns, growth or fund rankings."""
    if not text or _is_exempt(text):
        return False
    return bool(_PERFORMANCE_RE.search(text))


# --------------------------------------------------------------------------
# Refusal copy
# --------------------------------------------------------------------------
# REQ-16 applies to refusals as well as answers: every refusal is at most three
# sentences and carries one genuinely relevant link. Each builder returns
# ``(message, links)`` where ``links`` is a list of ``{"label", "url"}`` dicts.

_MAX_REFUSAL_SENTENCES = 3


def _sentence_count(text: str) -> int:
    """Count sentences without needing a second NLP dependency."""
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def _link(label_key: str) -> dict:
    for link in config.EDUCATIONAL_LINKS:
        if label_key in link["label"]:
            return link
    return config.EDUCATIONAL_LINKS[0]


def advice_refusal(question: str = "") -> tuple[str, list[dict]]:
    """Polite refusal for "which should I buy?" style questions."""
    message = (
        "I only share published facts about HDFC Mutual Fund schemes, so I "
        "can't tell you which scheme to choose or what to do with your money - "
        "that depends on your goals, time horizon and risk tolerance, which "
        "only you and a SEBI-registered investment adviser can assess. "
        "Here's where you can learn the concepts yourself."
    )
    return message, [_link("SEBI - Mutual Fund Regulations")]


def performance_refusal(question: str = "") -> tuple[str, list[dict]]:
    """Refusal for return / ranking questions, pointing at official factsheets."""
    message = (
        "I don't provide, calculate or compare returns or rankings - that "
        "information is published directly by the fund house, and I'd rather "
        "point you at the source than risk stating a stale or misleading "
        "figure. Please check the official monthly factsheet and SID for the "
        "scheme, which carry the SEBI-mandated performance disclosures."
    )
    return message, [_link("SEBI - Mutual Fund Regulations")]


def pii_refusal(hit: "PIIHit | None" = None) -> tuple[str, list[dict]]:
    """Refusal for a question containing personal data.

    The message deliberately names the *kind* of data detected and nothing
    more. The user's actual value is never echoed back - see the module
    docstring's design rule, and the Phase 6 assertion that the output contains
    no substring of the input.
    """
    kind = hit.kind if hit is not None else "personal"
    friendly = {
        "pan": "a PAN number",
        "aadhaar": "an Aadhaar number",
        "email": "an e-mail address",
        "phone": "a phone number",
        "otp": "a one-time passcode",
        "account_number": "an account number",
    }.get(kind, "personal information")

    message = (
        f"This assistant only answers questions about publicly published HDFC "
        f"Mutual Fund scheme facts, and it does not accept or store {friendly}. "
        f"Please remove it from your question - you never need to share "
        f"personal or login details here to look up a scheme fact."
    )
    return message, [_link("HDFC Mutual Fund - Investor education")]


def is_out_of_scope_scheme(text: str) -> bool:
    """True when the question names an HDFC fund this corpus does not hold.

    Needed because retrieval alone cannot tell these apart. "HDFC Mid Cap Fund"
    and "HDFC Large Cap Fund" are near-identical strings, and the embedded
    question for the first retrieves the second's expense-ratio chunk at 0.88.
    Without this check the assistant answers a Mid Cap question with the Large
    Cap figure and cites the Large Cap page - a confident, wrong, wrongly-cited
    answer, which is worse than admitting the gap.

    Implemented on character SPANS rather than an early "is any in-scope marker
    present" return, because a foreign fund can contain an in-scope marker:
    "HDFC Parag Parag Flexi Cap" is a different fund from "HDFC Flexi Cap", and
    a naive check would treat it as in scope. An out-of-scope marker only counts
    when its span does not overlap an in-scope one - so the bare "cap" inside
    "large cap" is suppressed, while an adjacent "parag parag" is not.
    """
    if not text:
        return False
    q = _normalise_query(text)

    def spans(markers: list[str]) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for marker in markers:
            for m in re.finditer(rf"(?<!\w){re.escape(marker)}(?!\w)", q):
                out.append((m.start(), m.end()))
        return out

    in_spans = spans(config.SCHEME_MARKERS)
    out_spans = spans(config.OUT_OF_SCOPE_SCHEMES)

    if not out_spans:
        return False

    for start, end in out_spans:
        if any(s < end and start < e for s, e in in_spans):
            continue  # the marker is part of an in-scope scheme name
        # "cap" alone is far too generic to act on; it needs a fund word nearby.
        if q[start:end] == "cap" and not re.search(r"\b(fund|scheme)\b", q):
            continue
        return True
    return False


def no_context_refusal(question: str = "") -> tuple[str, list[dict]]:
    """Honest "not in the collected sources" answer with an official link.

    Distinct from the other refusals in an important way: this is not a policy
    decision, it is a *capability* limit. The question may be perfectly
    reasonable and simply fall outside the 5 collected pages, so the copy must
    not imply the user asked something wrong. It also must not apologise for the
    scope in a way that invites them to assume the answer exists elsewhere.

    Being explicit about the scope is the whole point: the corpus covers 5
    Direct-Growth schemes only, so a correct "not in my sources" is far more
    useful than a plausible guess.
    """
    message = (
        "I couldn't find that in the sources I hold, which cover five HDFC "
        "Mutual Fund Direct Growth scheme pages only - so I won't guess. "
        "For the authoritative answer, check the official monthly factsheet "
        "and Scheme Information Document for the scheme, which are published by "
        "the fund house."
    )
    return message, [_link("HDFC Mutual Fund - Investor education")]


def refusal_for(question: str) -> tuple[str, list[dict]] | None:
    """Single entry point used by the query pipeline.

    Returns ``None`` when the question is safe to answer, otherwise
    ``(message, links)``. Order matters: PII is checked first because personal
    data must never reach a log or an LLM regardless of what else was asked.
    """
    hit = detect_pii(question)
    if hit is not None:
        return pii_refusal(hit)
    if is_performance_request(question):
        return performance_refusal(question)
    if is_advice_request(question):
        return advice_refusal(question)
    return None
