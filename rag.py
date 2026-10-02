"""Query engine for the HDFC Mutual Fund FAQ assistant.

This module owns the ONLINE half of the system. It shares only two things with
``ingest.py``: the on-disk vector index, and ``config.py`` (architecture.md §2
dependency rule). Neither module imports the other, so ingestion and query can
be run as separate processes at different times.

Flow (architecture.md §4):

    question
      -> guardrails: PII -> advice -> performance   # refuse BEFORE retrieval
      -> embed question                              # SAME model as ingestion
      -> top-k cosine search + hybrid relevance gate # "nothing found" is valid
      -> generate from chunks, or quote verbatim      # NFR-5 extractive mode
      -> citation from chunk METADATA                 # never from LLM prose (P1)
      -> cap 3 sentences, append as-of line           # outside the LLM's text

Run a single question headlessly:
    python rag.py "What is the expense ratio of HDFC ELSS Tax Saver?"
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from guardrails import (  # noqa: E402
    advice_refusal,
    detect_pii,
    is_advice_request,
    is_out_of_scope_scheme,
    is_performance_request,
    no_context_refusal,
    performance_refusal,
    pii_refusal,
    refusal_for,
)


@dataclass(frozen=True)
class Hit:
    """One retrieved chunk, with the citation fields needed to answer.

    ``source_url`` is promoted out of the metadata dict deliberately: the answer
    renderer must attach a real citation without parsing anything the LLM wrote
    (architecture.md principle P1).
    """

    text: str
    score: float
    meta: dict

    @property
    def source_url(self) -> str:
        return self.meta.get("source_url", "")

    @property
    def scheme_slug(self) -> str:
        return self.meta.get("scheme_slug", "")

    @property
    def scheme_name(self) -> str:
        return self.meta.get("scheme_name", "")

    @property
    def section(self) -> str:
        return self.meta.get("section", "")

    @property
    def as_of(self) -> str:
        return self.meta.get("as_of", "")

    @property
    def producer(self) -> str:
        return self.meta.get("producer", "")

    @property
    def category(self) -> str:
        return self.meta.get("category", "")

    @property
    def source_name(self) -> str:
        return self.meta.get("source_name", "")


@dataclass(frozen=True)
class SourceRef:
    """A single citation, de-duplicated by URL."""

    title: str
    url: str
    scheme_slug: str = ""
    section: str = ""
    as_of: str = ""

    @property
    def label(self) -> str:
        return f"{self.title} - {self.section}" if self.section else self.title


@dataclass
class RetrievalResult:
    """Everything the answer layer needs, including the refusal short-circuit.

    ``refused`` is not an error state - it is a designed outcome carrying the
    refusal copy and its educational links (REQ-18..REQ-21).
    """

    question: str
    hits: list[Hit] = field(default_factory=list)
    refused: bool = False
    refusal_message: str = ""
    refusal_links: list[dict] = field(default_factory=list)

    @property
    def has_context(self) -> bool:
        return bool(self.hits)

    def sources(self) -> list[SourceRef]:
        """Distinct citations for the hits, best-scoring first.

        De-duplicated by URL: three chunks from one scheme page yield one
        citation, so a 3-sentence answer never carries 3 identical links.
        """
        out: list[SourceRef] = []
        seen: set[str] = set()
        for hit in self.hits:
            url = hit.source_url
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(
                SourceRef(
                    title=hit.meta.get("source_name", "") or hit.scheme_name,
                    url=url,
                    scheme_slug=hit.scheme_slug,
                    section=hit.section,
                    as_of=hit.as_of,
                )
            )
        return out


@dataclass
class Answer:
    """A complete response, whether factual, refusal, or a fallback.

    ``refused`` is True for pii / advice / performance / no_context / empty.
    ``sources`` is always built from chunk metadata, never from generated text
    (architecture.md principle P1), so a model cannot fabricate a citation.

    ``mode`` records how the text was produced: "generated" (LLM paraphrase),
    "extractive" (verbatim quote, NFR-5), or "refusal" (no retrieval at all).
    """

    text: str
    sources: list[SourceRef] = field(default_factory=list)
    refused: bool = False
    refusal_kind: str = ""
    refusal_links: list[dict] = field(default_factory=list)
    as_of: str = ""
    chunks_used: int = 0
    mode: str = "refusal"
    # Why the extractive fallback fired: "" (generated fine), "no_key" (no API
    # key configured) or "llm_error" (key present but the call failed, e.g. a
    # rate limit). The UI must not claim "no language model configured" for the
    # third case - that hides a real fault behind a benign-sounding label.
    fallback_reason: str = ""
    # Retained for the UI's "Sources used" transparency panel. Never rendered
    # as answer text - only chunk ids, sections and scores.
    hits: list["Hit"] = field(default_factory=list)

    @property
    def primary_source(self) -> SourceRef | None:
        """The single citation the UI should show first."""
        return self.sources[0] if self.sources else None

    @property
    def citation(self) -> SourceRef | None:
        """The ONE authoritative citation for this answer (REQ-15).

        ``sources`` lists every distinct scheme page that was retrieved as
        context, which at TOP_K=10 can be all five. Only ``sources[0]`` - the
        page of the top-ranked hit - is rendered as a link; the rest appear in
        the "Sources used" panel as plain text.

        Citing all of them would assert that every page supports the answer,
        which we cannot prove and which is usually false: for "exit load of HDFC
        Flexi Cap" only Flexi Cap's page states it. One link is the honest claim,
        and it is the rule the UI already enforced.
        """
        return self.sources[0] if self.sources else None

    @property
    def citation_links(self) -> list[SourceRef]:
        """Exactly the links an answer may render. Never more than one."""
        primary = self.citation
        return [primary] if primary is not None else []

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "sources": [
                {"title": s.title, "url": s.url, "section": s.section,
                 "as_of": s.as_of}
                for s in self.sources
            ],
            "refused": self.refused,
            "refusal_kind": self.refusal_kind,
            "refusal_links": self.refusal_links,
            "as_of": self.as_of,
            "chunks_used": self.chunks_used,
            "mode": self.mode,
            "fallback_reason": self.fallback_reason,
        }


# --------------------------------------------------------------------------
# Hybrid relevance gate
# --------------------------------------------------------------------------
# WHY THIS EXISTS - a pure similarity floor is not sufficient.
#
# Measured (scripts/stress_terse_queries.py): terse queries score LOWER than
# off-topic ones, because a 1-3 word query has little context to embed against.
#   "AUM ELSS"            -> 0.380   (legitimate, must be answered)
#   "which crypto should I buy" -> 0.316 ... "how to file income tax" -> 0.421
# So any single threshold is either too high (rejects real questions) or too
# low (admits noise). The two populations genuinely OVERLAP.
#
# The fix is a second, independent signal: lexical grounding. A terse question
# like "AUM ELSS" contains the literal domain terms "aum" and "elss", which
# appear verbatim in the matching chunk. An off-topic question contains none of
# them. So:
#
#   accept if  similarity >= MIN_SIMILARITY          (confident)
#   accept if  similarity >= MIN_SIMILARITY_LOWER and lexical grounding
#                                               (terse but on-topic)
#   otherwise reject
#
# This keeps the strong natural-language path from Phase 7 and adds precise
# short-query handling, instead of trading one failure for the other.

MIN_SIMILARITY_LOWER = 0.30  # floor for the lexical-override path

# Domain vocabulary that legitimately appears in an in-domain question.
#
# Two rules, both learned from failures during Phase 7 verification:
#   1. Prefer MULTI-WORD terms. Bare "scheme", "fund", "code", "min" appear in
#      almost every chunk, so they "ground" a match against anything and defeat
#      the purpose of this signal. They are excluded.
#   2. Matching is word-boundary based, not substring. As a substring, "ter"
#      matches "after"/"water"; "lock in" fails against the corpus spelling
#      "lock-in". Both bugs were caught by scripts/stress_terse_queries.py.
_DOMAIN_TERMS = [
    # target facts
    "expense ratio", "expense ratios", "charges", "ter",
    "exit load", "exit loads", "redemption charge", "redeem", "redemption",
    "lock in", "lockin", "lock-in",
    "sip", "lumpsum", "lump sum", "minimum investment", "minimum amount",
    "riskometer", "risk rating", "risk level", "risky",
    "benchmark", "nav", "aum", "assets under management",
    "rta", "registrar", "registrar and transfer agent",
    "custodian", "factsheet", "sid", "kim",
    # other scheme facts
    "stamp duty", "turnover", "portfolio turnover",
    "investment objective", "objective", "scheme code", "isin",
    "launch date", "inception", "incorporation", "incorporated",
    "fund house", "date of incorporation",
]

# Scheme aliases so "elss" / "small cap" / "flexi cap" count as lexical evidence.
_SCHEME_ALIASES = {
    "large cap": ("largecap", "large cap"),
    "flexi cap": ("flexi cap", "flexicap"),
    "equity fund": ("flexi cap",),
    "elss": ("elss", "tax saver"),
    "small cap": ("small cap", "smallcap"),
    "balanced advantage": ("balanced advantage",),
    "balanced": ("balanced advantage",),
}


def _normalise(text: str) -> str:
    """Lowercase and unify the separators that hide a genuine term match.

    The corpus writes "lock-in"; a user types "lock in". Both must normalise to
    the same token sequence, otherwise lexical grounding silently fails on a
    correctly-spelled question.
    """
    text = text.lower()
    # hyphens, underscores and slashes -> spaces
    for ch in "-_/":
        text = text.replace(ch, " ")
    return re.sub(r"\s+", " ", text)


# Pre-compiled word-boundary matchers, built once at import.
_DOMAIN_RE = [
    re.compile(rf"(?<!\w){re.escape(_normalise(t))}(?!\w)")
    for t in _DOMAIN_TERMS
]
_ALIAS_RE = {
    alias: re.compile(
        r"(?<!\w)(" + "|".join(re.escape(_normalise(v)) for v in variants) + r")(?!\w)"
    )
    for alias, variants in _SCHEME_ALIASES.items()
}


def _lexical_grounding(question: str, texts: list[str]) -> tuple[bool, list[str]]:
    """Does the question's own vocabulary appear verbatim in the candidate chunks?

    Returns ``(grounded, matched_terms)``. Deliberately simple literal overlap,
    not fuzzy matching: the purpose is to rescue short keyword queries that embed
    poorly while staying silent on prose that shares no domain vocabulary with the
    question. Matching is on word boundaries after normalising separators, so
    "lock in" matches the corpus spelling "lock-in" but "ter" does not match
    "after".
    """
    q = _normalise(question)
    hits: set[str] = set()

    for term, pattern in zip(_DOMAIN_TERMS, _DOMAIN_RE):
        if pattern.search(q):
            hits.add(_normalise(term))

    for alias, pattern in _ALIAS_RE.items():
        if pattern.search(q):
            hits.add(alias)

    if not hits:
        return False, []

    corpus = _normalise(" ".join(texts))
    # Require at least one question term to actually occur in the retrieved text.
    grounded = any(
        re.search(rf"(?<!\w){re.escape(t)}(?!\w)", corpus) for t in hits
    )
    return grounded, sorted(hits)


def _distance_to_similarity(distance: float, space: str) -> float:
    """Convert a vector distance to a 0..1 similarity.

    Chroma returns *distance*, not similarity, and the conversion depends on the
    metric:

    * cosine space: ``distance = 1 - cosine_similarity``, so ``sim = 1 - d``.
      Identical vectors give ``d = 0`` -> ``sim = 1``.
    * l2 space: ``d`` is the Euclidean norm, which does NOT linearise. There is
      no correct linear conversion, so a conservative normalisation is used and
      the fact is documented rather than silently approximated.

    Only cosine is configured (ingest.py sets ``hnsw:space="cosine"``), but this
    is handled explicitly so a config change cannot quietly corrupt every score.
    """
    if space == "cosine":
        return max(0.0, min(1.0, 1.0 - float(distance)))
    # Fallback: approximate. Flagged rather than hidden.
    return max(0.0, min(1.0, 1.0 - (float(distance) ** 2) / 2.0))


class RAGEngine:
    """Retrieval side of the assistant.

    Constructing this must NEVER raise when the Groq key is missing (NFR-5):
    retrieval works fully offline, and Phase 8 falls back to extractive mode.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._model = None
        self._collection = None
        self.groq_client = None
        self.space = "cosine"

        key = (config.GROQ_API_KEY or "").strip()
        self.has_llm = bool(key)
        if self.has_llm:
            try:
                from groq import Groq

                self.groq_client = Groq(api_key=key)
            except Exception as exc:  # noqa: BLE001
                # A broken/absent key degrades to extractive mode; it must not
                # take down retrieval.
                self.has_llm = False
                print(f"  [WARN] Groq client unavailable ({exc}); "
                      f"falling back to extractive mode.")
        else:
            print("  [INFO] No GROQ_API_KEY set - retrieval works, answers will "
                  "be extractive (NFR-5). Set it in .env for natural language.")

    # -- lazy loaders -------------------------------------------------------

    def _embedder(self):
        """Lazy singleton for the embedding model.

        MUST be the same model as ingestion (architecture.md §4.2). If these
        ever diverge, stored and query vectors are incomparable and every
        similarity score becomes meaningless - so the id comes from config,
        which both stages read.
        """
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(config.EMBED_MODEL)
        return self._model

    def _store(self):
        if self._collection is None:
            import chromadb

            client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
            self._collection = client.get_or_create_collection(
                config.COLLECTION_NAME,
                metadata={"hnsw:space": self.space},
            )
            self._read_space()
        return self._collection

    def _read_space(self) -> None:
        """Trust the store's configured metric, not our assumption."""
        try:
            meta = self._collection.metadata or {}
            self.space = meta.get("hnsw:space", "cosine")
        except Exception:  # noqa: BLE001
            self.space = "cosine"

    # -- retrieval ----------------------------------------------------------

    def is_indexed(self) -> bool:
        """False when ingestion has not been run yet."""
        try:
            return self._store().count() > 0
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] could not open the vector store: {exc}")
            return False

    def retrieve(
        self,
        question: str,
        top_k: int = config.TOP_K,
        min_similarity: float | None = None,
        skip_guardrails: bool = False,
        use_lexical_rescue: bool = True,
    ) -> list[Hit]:
        """Embed ``question``, search, and drop anything below the floor.

        Returns ``[]`` when nothing clears the floor. An empty result is a valid,
        meaningful outcome: "I couldn't find that in the sources" is the honest
        answer, and padding with the nearest chunk anyway would fabricate.

        Two acceptance paths: the similarity floor, and - for short queries that
        embed poorly - lexical grounding.

        ``min_similarity`` is a HARD ceiling: passing it explicitly disables the
        lexical rescue regardless of ``use_lexical_rescue``, because the caller
        is asserting "only return things at least this similar". Omit it to get
        the normal two-path behaviour driven by ``config.MIN_SIMILARITY``.
        """
        explicit_floor = min_similarity is not None
        floor = config.MIN_SIMILARITY if min_similarity is None else min_similarity
        rescue_enabled = use_lexical_rescue and not explicit_floor

        if not skip_guardrails:
            refusal = refusal_for(question)
            if refusal is not None:
                if self.verbose:
                    print("  [guardrail] refused before retrieval")
                return []

        collection = self._store()
        if collection.count() == 0:
            print("  [WARN] vector store is empty - run `python ingest.py` first.")
            return []

        vector = self._embedder().encode(
            [question], normalize_embeddings=True, show_progress_bar=False
        )

        raw = collection.query(
            query_embeddings=[list(map(float, vector[0]))],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        dists = (raw.get("distances") or [[]])[0]

        # Score everything first; the lexical pass needs to see all candidates,
        # not just the ones above the floor.
        scored = [
            (text, meta, _distance_to_similarity(dist, self.space))
            for text, meta, dist in zip(docs, metas, dists)
        ]

        # --- pass 1: the confident, purely-similarity path ------------------
        hits = [
            Hit(text=t, score=s, meta=dict(m or {}))
            for t, m, s in scored
            if s >= floor
        ]

        # --- pass 2: lexical grounding for short/low-similarity questions ----
        below = [(t, m, s) for t, m, s in scored if s < floor]
        rescued: list[Hit] = []
        if below and rescue_enabled:
            best = max(below, key=lambda r: r[2])
            grounded, terms = _lexical_grounding(
                question, [t for t, _, _ in below]
            )
            if grounded and best[2] >= MIN_SIMILARITY_LOWER:
                # Keep only candidates that themselves carry the matched terms,
                # so the fallback stays precise instead of admitting all 5.
                wanted = {w for t in terms
                          for w in _normalise(t).split()}
                for t, m, s in below:
                    if s < MIN_SIMILARITY_LOWER:
                        continue
                    # Match on normalised text. Testing the raw string here was a
                    # bug: the corpus writes "lock-in", the term is "lock in", so
                    # the one query that needed the lexical rescue was the one it
                    # silently failed to rescue.
                    low = _normalise(t)
                    if any(
                        re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low)
                        for w in wanted
                    ):
                        rescued.append(
                            Hit(text=t, score=s, meta=dict(m or {}))
                        )
                rescued.sort(key=lambda h: -h.score)
                if self.verbose:
                    print(f"  [lexical] {len(rescued)} hit(s) rescued on "
                          f"terms={terms} (best score {best[2]:.3f})")

        hits.extend(rescued)
        hits.sort(key=lambda h: -h.score)

        if self.verbose:
            all_scores = [s for _, _, s in scored]
            shown = ", ".join(f"{s:.3f}" for s in all_scores)
            print(f"  [retrieve] space={self.space} floor={floor} "
                  f"scores=[{shown}] -> {len(hits)} kept")

        return hits

    def ask(self, question: str, top_k: int = config.TOP_K) -> RetrievalResult:
        """Guardrails + retrieval, returning a result that may be a refusal."""
        question = (question or "").strip()
        if not question:
            return RetrievalResult(
                question=question,
                refused=True,
                refusal_message="Please type a question about an HDFC Mutual "
                                "Fund scheme.",
                refusal_links=[],
            )

        refusal = refusal_for(question)
        if refusal is not None:
            message, links = refusal
            return RetrievalResult(
                question=question,
                refused=True,
                refusal_message=message,
                refusal_links=links,
            )

        hits = self.retrieve(question, top_k=top_k, skip_guardrails=True)
        return RetrievalResult(question=question, hits=hits)

    # -- generation (Phase 8) ----------------------------------------------

    def _generate(self, question: str, hits: list[Hit]) -> str:
        """Call Groq once, retry once, return raw content. Never raises.

        Returns ``""`` on any failure so the caller can fall back to the
        extractive path. A generation failure must never lose the answer
        entirely - the retrieved chunk is still a valid factual answer.
        """
        if self.groq_client is None:
            return ""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{_build_context(hits)}\n\n"
                    f"Question: {question}\n\n"
                    "Answer in at most 3 sentences, using only the context above."
                ),
            },
        ]

        for attempt in (1, 2):
            try:
                resp = self.groq_client.chat.completions.create(
                    model=config.GROQ_MODEL,
                    messages=messages,
                    temperature=0,
                    max_tokens=config.GROQ_MAX_TOKENS,
                )
                msg = resp.choices[0].message
                # qwen3.8-27b is reasoning-capable. It was verified to return
                # content only, but if a variant ever emits `reasoning` /
                # `reasoning_content` we must NOT show that to the user - it is
                # scratchpad, and surfacing it would break the 3-sentence rule
                # and read as an incoherent answer.
                content = (getattr(msg, "content", None) or "").strip()
                if content:
                    return content
                if self.verbose:
                    print("  [generate] empty content on attempt "
                          f"{attempt}; falling back")
            except Exception as exc:  # noqa: BLE001
                if self.verbose:
                    print(f"  [generate] attempt {attempt} failed: "
                          f"{type(exc).__name__}: {exc}")
        return ""

    def answer(self, question: str, top_k: int = config.TOP_K) -> Answer:
        """Full pipeline: guardrails -> retrieval -> generation -> citation.

        Order is strict and matches implementation.md Phase 8 task 2. PII is
        checked first, before anything can log or transmit the input.
        """
        question = (question or "").strip()

        if not question:
            return Answer(
                text="Please type a question about an HDFC Mutual Fund scheme.",
                refused=True,
                refusal_kind="empty",
            )

        # 1. PII - refuse before the question reaches retrieval, the LLM, or any
        #    log. The refusal never echoes any part of the input.
        hit = detect_pii(question)
        if hit is not None:
            message, links = pii_refusal(hit)
            return Answer(text=message, refused=True, refusal_kind="pii",
                          refusal_links=links)

        # 2. advice, 3. performance - both refuse before retrieval.
        if is_advice_request(question):
            message, links = advice_refusal(question)
            return Answer(text=message, refused=True,
                          refusal_kind="advice", refusal_links=links)

        if is_performance_request(question):
            message, links = performance_refusal(question)
            return Answer(text=message, refused=True,
                          refusal_kind="performance", refusal_links=links)

        # 3b. corpus scope. A question about a fund we do not hold must be
        #     refused BEFORE retrieval, because retrieval cannot tell
        #     "HDFC Mid Cap" from "HDFC Large Cap" (it scores 0.88) and would
        #     otherwise answer with a lookalike scheme's figure and cite the
        #     wrong page.
        if is_out_of_scope_scheme(question):
            message, links = no_context_refusal(question)
            return Answer(text=message, refused=True,
                          refusal_kind="out_of_scope", refusal_links=links)

        # 4. retrieval. Empty is a valid, honest outcome - never pad it.
        hits = self.retrieve(question, top_k=top_k, skip_guardrails=True)
        if not hits:
            message, links = no_context_refusal(question)
            return Answer(text=message, refused=True, refusal_kind="no_context",
                          refusal_links=links)

        # 5. generate, with the extractive fallback.
        raw = self._generate(question, hits)
        as_of = next((h.as_of for h in hits if h.as_of), "")

        # Citation built from chunk METADATA, never from model prose (P1).
        sources = _sources_from_hits(hits)

        if raw:
            text = _finalise(raw, as_of)
            fallback_reason = ""
        else:
            # NFR-5: no key, or the call failed. Quote the source verbatim -
            # that is a factual answer, not a degraded one.
            text = _finalise(_extractive(hits[0], as_of), as_of)
            sources = _sources_from_hits(hits[:1])
            fallback_reason = "no_key" if self.groq_client is None else "llm_error"

        return Answer(
            text=text,
            sources=sources,
            as_of=as_of,
            chunks_used=len(hits),
            mode="extractive" if not raw else "generated",
            fallback_reason=fallback_reason,
            hits=list(hits),
        )


# --------------------------------------------------------------------------
# PHASE 8 - generation helpers
# --------------------------------------------------------------------------

# REQ-17 / REQ-21. Six rules, stated explicitly rather than implied.
#
# The "do not use prior knowledge" rule is load-bearing: the model has read
# thousands of HDFC pages during training and will happily answer "the expense
# ratio is 1.5%" from memory if the retrieved chunk is missing the field. Every
# number in an answer must trace to a context block.
SYSTEM_PROMPT = f"""\
You are a factual assistant for HDFC Mutual Fund scheme pages. You answer
questions using ONLY the source excerpts provided in the user's message.

Rules you must always follow:
1. Use ONLY the provided source excerpts. Do not use prior knowledge, and do
   not fill gaps from memory or from other mutual funds.
2. State facts only. Never give investment advice, recommendations, opinions,
   or any suggestion about whether to buy, sell, hold, or switch.
3. If the excerpts do not fully support an answer, say plainly what is not
   stated in the sources. Do not guess, estimate, or infer.
4. Answer in at most 3 sentences. Be concise and direct.
5. Do not include source URLs, markdown, or bullet points in your answer - the
   citation is added separately by the application.
6. Never output, request, or repeat personal data such as PAN, Aadhaar,
   account numbers, OTPs, phone numbers, or email addresses.

{config.DISCLAIMER}"""


def _build_context(hits: list[Hit]) -> str:
    """Assemble retrieved chunks as numbered, labelled blocks.

    Labelled so the model can attribute a fact to the right scheme and field.
    The URL is included for attribution context only - the model is instructed
    not to reproduce it, and the real citation comes from metadata regardless.
    """
    blocks = []
    for i, hit in enumerate(hits, start=1):
        scheme = hit.scheme_name or hit.source_name or hit.scheme_slug
        label = f"[{i}] {scheme}"
        if hit.category:
            label += f" - {hit.category}"
        if hit.section:
            label += f" - {hit.section.replace('_', ' ')}"
        blocks.append(f"{label}\n{hit.text}\nURL: {hit.source_url}")
    return "\n\n".join(blocks)


def _sources_from_hits(hits: list[Hit]) -> list[SourceRef]:
    """Build citations from chunk metadata.

    ARCHITECTURE PRINCIPLE P1: the model must never be able to invent or
    influence a citation. The URL here comes from the vector store's metadata,
    which came from ``config.SOURCES``. Nothing is read from generated prose.
    """
    out: list[SourceRef] = []
    seen: set[str] = set()
    for hit in hits:
        url = hit.source_url
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(
            SourceRef(
                title=hit.source_name or hit.scheme_name or "HDFC Mutual Fund",
                url=url,
                scheme_slug=hit.scheme_slug,
                section=hit.section,
                as_of=hit.as_of,
            )
        )
    return out


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _strip_disallowed(text: str) -> str:
    """Remove URLs, markdown and bullets the prompt asked the model not to emit.

    Defensive, not trusting. Even a well-behaved model occasionally emits a
    link, and a stray URL in the body would be a citation the application never
    validated.

    Also normalises invisible Unicode. Measured, not hypothetical: Groq's
    ``openai/gpt-oss-20b`` and ``-120b`` emit U+202F NARROW NO-BREAK SPACE where
    a normal space belongs, producing "BSE<NBSP>250<NBSP>SmallCap" and
    "3<NBSP>years". The answers are factually correct but the text no longer
    contains "BSE 250", so AT-5 fails on a correct answer - and the character
    renders as a gap in most viewers. Normalising here means the answer text is
    the same regardless of which model produced it, which is what lets the
    acceptance suite assert on substrings at all.
    """
    # Invisible / confusable whitespace -> plain ASCII space.
    for exotic in ("\u202f", "\u00a0", "\u2009", "\u2007", "\u200b"):
        text = text.replace(exotic, " ")
    # Non-breaking and figure hyphens -> ASCII hyphen, so "lock-in" is one word.
    for dash in ("\u2011", "\u2010", "\u2012", "\u2013"):
        text = text.replace(dash, "-")
    # Typographic quotes and primes that can appear inside a quoted figure.
    for quote in ("\u2018", "\u2019", "\u201c", "\u201d"):
        text = text.replace(quote, "'")
    text = text.replace("\u2032", "'").replace("\u2033", '"')

    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[(\d+)\]", "", text)          # citation markers like [1]
    # Bold BEFORE bullets: "**Expense ratio**" starts with "*", and the bullet
    # pattern would strip one asterisk and leave "**" unbalanced.
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
    text = re.sub(r"^\s*[-*•]\s*", "", text, flags=re.M)   # bullets
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _truncate_sentences(text: str, limit: int = 3) -> str:
    """Hard-cap at ``limit`` sentences (REQ-17).

    Truncation happens at a sentence boundary so the answer is never cut
    mid-clause, which would read as a rendering bug.
    """
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text.strip()) if p.strip()]
    if len(parts) <= limit:
        return " ".join(parts)
    return " ".join(parts[:limit]).rstrip(" ,;:")


def _as_of_line(as_of: str) -> str:
    return f"Last updated from sources: {as_of or 'date not published'}"


def _finalise(text: str, as_of: str) -> str:
    """Clean, cap at 3 sentences, then append the as-of line.

    The as-of line is appended HERE, outside the LLM's output, so the model can
    neither omit it nor fabricate a different date (task 6).
    """
    body = _truncate_sentences(_strip_disallowed(text))
    if not body:
        body = "I could not produce an answer from the collected sources."
    return f"{body}\n\n{_as_of_line(as_of)}"


def _extractive(hit: Hit, as_of: str) -> str:
    """Quote the source chunk verbatim when generation is unavailable (NFR-5).

    Quoted rather than paraphrased on purpose: with no LLM there is nothing to
    reword it, and a verbatim quote is maximally faithful. The opening clause
    makes the quoting explicit so the user is not misled about the provenance.
    """
    return (
        "Quoted directly from the source page, since no language model is "
        f"configured: \"{hit.text.strip()}\""
    )


def _print_answer(answer: Answer) -> None:
    """Render an Answer for the terminal (and reusable by later phases)."""
    print()
    print(answer.text)

    if answer.refusal_links:
        print("\n  Learn more:")
        for link in answer.refusal_links:
            print(f"    - {link['label']}: {link['url']}")
    elif answer.sources:
        print("\n  Source:")
        primary = answer.primary_source
        print(f"    {primary.title}")
        print(f"    {primary.url}")

    if answer.sources and len(answer.sources) > 1:
        others = [s for s in answer.sources[1:]]
        print(f"    (+{len(others)} more chunk(s) from "
              f"{len({s.url for s in others})} page(s))")

    tag = f"kind={answer.refusal_kind}" if answer.refused else (
        f"mode={answer.mode}, chunks={answer.chunks_used}")
    print(f"\n  [{tag}]")


def _main(argv: list[str]) -> int:
    # `python rag.py "question"` for headless eval/demo (task 9).
    # `python rag.py` with no args runs the spec's verification questions.
    engine = RAGEngine(verbose="-v" in argv)
    questions = [a for a in argv if not a.startswith("-")] or [
        "What is the expense ratio of HDFC ELSS Tax Saver?",
        "What is the exit load of HDFC Flexi Cap?",
        "Should I buy HDFC Large Cap?",
        "My PAN is ABCDE1234F, send my statement",
        "Which fund gives the best returns?",
    ]
    for question in questions:
        print("=" * 78)
        print(f"Q: {question}")
        _print_answer(engine.answer(question))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(_main(_sys.argv[1:]))