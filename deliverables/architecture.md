# Architecture — Mutual Fund FAQ Assistant (RAG Chatbot)

**Derived from:** `PRD.md` v1.0
**Version:** v1.0
**Last updated:** 01 Oct 2026
**Status:** Design agreed, ready to implement

---

## 0. Design Principles

Every structural choice below traces back to one of these five principles, which come
directly from PRD §1.1 and §8.

| # | Principle | Architectural consequence |
|---|---|---|
| **P1** | **Provenance over fluency** — a confidently wrong fee is worse than no answer | `source_url` is stored **on every chunk**; citations are generated from chunk metadata, never reconstructed by the LLM; NFR-5 extractive fallback |
| **P2** | **Refusal is a feature, not an error** | Guardrails are a **cross-cutting layer with its own exit path**, not a post-hoc string check on the answer |
| **P3** | **The corpus defines what can be said** | No return/performance figures ever enter the corpus (ingest-time exclusion, not prompt-time hope) |
| **P4** | **Ingest once, query many** | Two strictly separated processes; ChromaDB on disk; no re-embedding on restart (REQ-7, NFR-3) |
| **P5** | **Degrade, don't crash** | Missing API key, missing key, thin retrieval, changed page markup — each has a defined non-crashing behaviour |

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          OFFLINE · INGESTION · runs once                     │
│                                                                              │
│  config.SOURCES (5 URLs)                                                      │
│        │                                                                     │
│        ▼                                                                     │
│  ┌────────────┐   HTTP GET + disk cache                                      │
│  │   LOAD     │──────────────▶ data/raw/<slug>.html                          │
│  └────────────┘                                                                     │
│        │                                                                     │
│        ▼  (two parallel extractors over the SAME cached HTML)                │
│  ┌──────────────────────────┐        ┌──────────────────────────────────┐     │
│  │ EXTRACTOR A              │        │ EXTRACTOR B                      │     │
│  │ __NEXT_DATA__ JSON       │        │ rendered visible text            │     │
│  │ 97 flat keys / scheme    │        │ labelled prose sections          │     │
│  │ → atomic facts           │        │ (Minimum investments, Exit load, │     │
│  └──────────────────────────┘        │  Tax implication, Objective...) │     │
│                │                      └──────────────────────────────────┘     │
│                └──────────────┬───────────────────────────────────┘          │
│                               ▼                                              │
│                    ┌──────────────────────┐                                  │
│                    │  SCRUB  +  EXCLUDE   │  strip e-mail / phone / address   │
│                    │                      │  drop holdings, peers, returns    │
│                    └──────────┬───────────┘                                  │
│                               ▼                                              │
│                    ┌──────────────────────┐                                  │
│                    │  CHUNK               │  A: one card per fact           │
│                    │                      │  B: 380 chars / 80 overlap      │
│                    └──────────┬───────────┘                                  │
│                               ▼                                              │
│                    ┌──────────────────────┐                                  │
│                    │  EMBED               │  all-MiniLM-L6-v2 → 384-d       │
│                    └──────────┬───────────┘  (local, no API key)             │
│                               ▼                                              │
│                    ┌──────────────────────┐                                  │
│                    │  STORE                │  ChromaDB, cosine               │
│                    │                      │  data/chroma/  (persisted)       │
│                    └──────────┬───────────┘                                  │
│                               ▼                                              │
│                    data/chunks.txt  ·  data/chunks.jsonl  ·  ingest report   │
└───────────────────────────────────────────┬──────────────────────────────────┘
                                            │  (no runtime dependency;
                                            │   app reads the persisted index)
                                            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          ONLINE · QUERY · per question                       │
│                                                                              │
│  user question                                                                │
│        │                                                                     │
│        ▼                                                                     │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │ GUARDRAIL LAYER (cross-cutting, PRD §8.3)                             │   │
│  │  1. PII detect        → REQ-20  → refuse, never echo                  │   │
│  │  2. Advice detect     → REQ-18  → refuse + educational link  [EXIT]   │   │
│  │  3. Performance detect → REQ-19  → deflect to factsheet link  [EXIT]   │   │
│  └───────────────────────────────┬───────────────────────────────────────┘   │
│                                  │ clean, answerable question                 │
│                                  ▼                                             │
│                    ┌──────────────────────┐                                  │
│                    │  EMBED question      │  SAME MiniLM model                │
│                    └──────────┬───────────┘                                  │
│                               ▼                                              │
│                    ┌──────────────────────┐                                  │
│                    │  RETRIEVE            │  top-k = 5, cosine                │
│                    │  + similarity floor  │  floor = 0.18                     │
│                    └──────────┬───────────┘                                  │
│                               ▼                                              │
│                    ┌──────────────────────┐                                  │
│                    │  GENERATE (Groq)     │  facts-only, ≤3 sentences,       │
│                    │  prompt-hardened     │  1 citation, allow "not in        │
│                    │                      │  context" escape hatch            │
│                    └──────────┬───────────┘                                  │
│                               ▼                                              │
│                    ┌──────────────────────┐                                  │
│                    │  RENDER + CITE       │  citation from chunk metadata    │
│                    │                     │  + "Last updated from sources: …" │   │
│                    └──────────────────────┘                                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Layered Component Architecture

| Layer | Module | Stage | Responsibility | PRD refs |
|---|---|---|---|---|
| **L0 Config** | `config.py` | both | Single source of truth: sources, paths, chunk params, model ids, top-k, floor, refusal regexes, disclaimer. Prevents ingestion/query drift. | REQ-1..7, NFR-7 |
| **L1 Sources** | `ingest.load_pages()` | offline | HTTP fetch with browser UA, disk cache, `--refresh` to bust | REQ-1, R2 |
| **L2 Extract** | `ingest.extract_facts()` / `extract_prose()` | offline | Extractor A (JSON) + Extractor B (visible text) over the same HTML | **REQ-2**, PRD §7.2 |
| **L3 Chunk** | `ingest.build_chunks()` | offline | Fact-card normaliser + labelled-section splitter, scrub + exclusions | REQ-3..5, REQ-9, P3 |
| **L4 Index** | `ingest.embed_and_store()` | offline | MiniLM encode → Chroma upsert (idempotent, deterministic ids) | REQ-6, REQ-7, NFR-3, NFR-4 |
| **L5 Observe** | `ingest.write_dumps()` | offline | `chunks.txt`, `chunks.jsonl`, coverage report vs the 7 target facts | REQ-8, REQ-10 |
| **L6 Guard** | `guardrails.py` | online | PII / advice / performance classification + refusal & deflection copy | REQ-18..21 |
| **L7 Retrieve** | `rag.RAGEngine.retrieve()` | online | Embed question, cosine top-k, similarity floor, per-scheme grouping | REQ-11..13 |
| **L8 Generate** | `rag.RAGEngine.answer()` | online | Groq call, prompt contract, citation assembly, ≤3-sentence + as-of | REQ-14..17 |
| **L9 Present** | `app.py` | online | Streamlit chat, 3 examples, disclaimer, source links, scope panel | REQ-22..25 |

**Dependency rule (NFR-7):** L0 ← everything; L1–L5 never import L6–L9; L6–L9 never
import L1–L5. Ingestion and query are separate processes that share only the on-disk index
and `config.py`. This is what makes "ingestion runs once" structurally true rather than a
convention.

---

## 3. Stage 1 — Ingestion: Load → Chunk → Embed → Store

### 3.1 Load (REQ-1)

```
for source in config.SOURCES:
    cache = data/raw/<slug>.html
    if cache.exists() and not --refresh:  html = read(cache)
    else:                                 html = GET(url, UA=browser); write(cache)
```

* **Cache-first** so re-runs are offline and reproducible (P4).
* Browser `User-Agent` required — Groww returns a reduced shell to default agents.
* Raw HTML is the **system of record** for re-extraction: if the chunker changes, we re-chunk
  from cache without re-fetching.

### 3.2 Extract — the critical two-source design

Driven by PRD §7.2: **expense ratio and lock-in exist only in `__NEXT_DATA__`, never in the
rendered text.** So both extractors run over the same HTML and their outputs are merged.

#### Extractor A — structured facts (`__NEXT_DATA__.props.pageProps.mfServerSideData`)

97 flat keys per scheme. Each key maps to a **fact-card builder** that emits a
*self-contained declarative sentence* (REQ-3) naming the scheme, e.g.

> "The expense ratio of HDFC ELSS Tax Saver Fund Direct Plan Growth is **1.21 %**
> (base expense ratio 0.97 %)."

Restating values as sentences is deliberate: it embeds the entity even when the question
omits the fund name, and it fixes MiniLM's weak handling of bare numeric strings (PRD R10).

**Excluded from Extractor A** (P3): any return/ranking/peer field, the `About`-prose AMC-level
AUM, `fund_manager` (unreconciled conflict, PRD §7.4), and contact details (REQ-9).

#### Extractor B — labelled prose sections (rendered text)

Named sections located by anchor, each emitted as `Section header + body` so the header is
part of the embedded text and chunks are interpretable standalone:
`Minimum investments`, `Exit load`, `Exit Load`, `Tax implication`, `Investment Objective`,
`About`, `Fund benchmark`, `Scheme Information Document(SID)`,
`Registrar & Transfer Agent`, plus the expense-ratio / exit-load / stamp-duty **glossary
definitions**.

Excluded (PRD §7.4 / measured ~40 % boilerplate): nav chrome, footer, holdings tables,
peer-comparison tables, fund-manager bios.

### 3.3 Chunk (REQ-3, REQ-4, REQ-5)

| Producer | Unit | Size | Overlap | Rationale |
|---|---|---|---|---|
| **A — fact_card** | one atomic fact | 110–330 chars | n/a | One indivisible `label: value`; duplicating it would crowd *other* facts out of top-k |
| **B — prose_section** | labelled section | **380 chars** (~90 tok) | **80 chars** (~20 tok) | Holds label + value + ~1 sentence of context; overlap re-carries the header when a boundary lands mid-pair |

* Boundary: sentence/newline aware — **never cuts inside a `label: value` line**.
* Minimum viable chunk: **40 chars** (drops "See All", "IPO", "Stocks").

Full rationale and evidence: `deliverables/chunking_strategy.md`.

### 3.4 Chunk schema (REQ-5)

| Field | Type | Purpose |
|---|---|---|
| `chunk_id` | str | Deterministic `slug__section__idx` → idempotent re-ingest (NFR-4) |
| `text` | str | The embedded text |
| `source_url` | str | **Citation link — carried on every chunk (P1)** |
| `source_name` | str | "HDFC ELSS Tax Saver Fund - Direct Growth" |
| `amc` | str | "HDFC Mutual Fund" |
| `scheme_slug` / `scheme_name` / `scheme_code` | str | Entity identity + grouping |
| `category` | str | ELSS / Large Cap / Flexi Cap / Small Cap / Balanced Advantage |
| `section` | str | Fact key: `expense_ratio`, `exit_load`, `lock_in_period`, … |
| `producer` | str | `fact_card` \| `prose_section` |
| `extracted_from` | str | `__NEXT_DATA__` \| `visible_text` (provenance of the fact itself) |
| `as_of` | str | Source's own date (`30-Sep-2026`) — powers "Last updated from sources" |
| `ingested_at` | str | UTC ISO timestamp of the ingest run |
| `char_len` / `content_hash` | int / str | QA + drift/dedupe detection |

### 3.5 Embed → Store (REQ-6, REQ-7)

```
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")   # 384-dim, local
vectors = model.encode([c.text for c in chunks], normalize_embeddings=True)
collection = chromadb.PersistentClient(path="data/chroma").get_or_create_collection(
    "hdfc_mf_faqs", metadata={"hnsw:space": "cosine"})
collection.upsert(ids=..., documents=..., embeddings=..., metadatas=...)   # idempotent
```

* **Cosine** on normalised vectors — standard for MiniLM sentence embeddings.
* **`upsert` with deterministic ids** → running ingest twice does not duplicate (NFR-3).
* LLM and embedder are **independent services**; the embed stage needs **no API key** (NFR-1).

### 3.6 Observe (REQ-8, REQ-10)

`write_dumps()` produces:

* `data/chunks.txt` — every chunk, human-readable, with header block, section, metadata and
  source URL. This is the artifact a reviewer reads to audit the corpus.
* `data/chunks.jsonl` — same content, machine-readable, for evaluation scripts.
* **Coverage report** — asserts each of the 5 schemes has a chunk for each of the 7 target
  fact types, and that `lock_in_period` is non-null **only** for ELSS. **A coverage drop
  fails the ingest loudly** (PRD R1) instead of silently producing a thin corpus.

---

## 4. Stage 2 — Query: Guard → Embed → Retrieve → Generate → Render

### 4.1 Guardrail layer (first, cross-cutting)

Three classifiers run **before** retrieval. Cheap regex, no LLM call, deterministic.

```
question
   │
   ├─ detect_pii()      PAN / Aadhaar / acct no / OTP / email / phone   → REQ-20  [REFUSE, never echo]
   ├─ is_advice()       "should I", "best fund", "for me", "allocate"  → REQ-18  [REFUSE + edu link]
   └─ is_performance()  "returns", "best performing", "% gain"         → REQ-19  [DEFLECT → factsheet]
        │
        └──(clean)──▶ continue to retrieval
```

Each path returns a **complete `Answer` object** with `refused=True`, so the refusal flows
through the same render path as a normal answer — the UI never special-cases (P2).

* **PII**: the matched value is **never** echoed back or logged (REQ-20).
* **Advice**: refusal copy is polite + states the facts-only boundary + supplies a relevant
  educational link from `config.EDUCATIONAL_LINKS` (SEBI / AMFI / HDFC AMC FAQ).
* **Performance**: states plainly that the assistant does not provide or compare returns and
  points to the **official factsheet/SID** (REQ-19, P3).
* Layer 2 of defence: the same prohibitions are restated in the system prompt, so an
  unrecognised phrasing is still caught by the LLM (REQ-21).

### 4.2 Embed + Retrieve (REQ-11..13)

```
q_vec = embed(question)                       # SAME model as ingestion
hits  = collection.query(q_vec, n=TOP_K)      # TOP_K = 5, cosine
kept  = [h for h in hits if h.score >= MIN_SIMILARITY]   # floor = 0.18
```

* **Same model both sides** is mandatory — a mismatched embedder makes vectors incomparable
  (PRD §10.2). Enforced by importing `EMBED_MODEL` from `config`.
* **Similarity floor (REQ-13)** makes "nothing relevant" a legitimate outcome. If `kept` is
  empty the assistant says so honestly and links the official source — it must **never** fill
  the gap from model memory. This is the single most important anti-hallucination control.
* Hits carry their full metadata, so the renderer has everything needed for a citation
  without a second lookup.

**Scheme disambiguation (AT-4).** A question like "What is the minimum SIP?" names no fund.
Retrieval will surface chunks from several schemes. `RAGEngine` groups hits by
`scheme_slug`; when >1 scheme is represented and the question is singular, the answer
either reports per-scheme values or asks which scheme — it must not silently pick one.

### 4.3 Generate (REQ-14..17)

**Prompt contract** (system prompt enforces, in order):

1. You answer **only** from the provided context chunks. The context is the entire
   permitted knowledge base.
2. **Facts only.** No advice, no recommendation, no suitability, no buy/sell language.
3. If the answer is not fully supported by the context, say so and point to the official
   source. **Do not use prior knowledge.**
4. **Maximum 3 sentences.**
5. **Include exactly one** source URL, taken from the context metadata.
6. Never output PAN/Aadhaar/account numbers/OTPs; never request personal data.

Context is assembled as `[1] … [2] …` blocks, each prefixed with scheme, category, section
and `source_url`, so the model can cite from structure rather than memory.

**Citation assembly (P1).** The link in the answer is taken from **chunk metadata by the
application**, not parsed out of the model's prose. If the model omits or mangles a URL, the
renderer still attaches the correct one. The LLM can never invent a citation.

**Answer contract.** `rag.Answer` is a single dataclass for every path:

```python
@dataclass
class Answer:
    text: str                       # ≤3 sentences, or refusal copy
    sources: list[SourceRef]        # SourceRef: {title, url, scheme_slug, section, score, as_of}
    refused: bool
    refusal_kind: str | None        # "advice" | "performance" | "pii" | "no_context"
    as_of: str                      # -> "Last updated from sources: 30-Sep-2026"
    chunks_used: int
```

**Graceful degradation (NFR-5, P5).** If `GROQ_API_KEY` is missing, `answer()` builds the
response **extractively** from the top chunk instead of calling the LLM — the prototype stays
demoable and the pipeline stays demonstrable without a key.

### 4.4 Render (REQ-24, REQ-25)

Streamlit renders `Answer`: answer text, one clickable citation per source actually used, and
the `Last updated from sources:` line. Nothing else — no derived numbers, no charts, no
comparison tables.

---

## 5. Guardrail Defence-in-Depth (PRD R3, R4, R5, R6)

| Layer | Control | Failure it catches |
|---|---|---|
| **1. Ingest-time** | Return/performance figures excluded from corpus; PII/contact scrubbed | A bad fact never becomes retrievable (P3, REQ-9) |
| **2. Input-time** | PII / advice / performance regex before retrieval | Catches the request before it can influence retrieval (REQ-18..20) |
| **3. Retrieval-time** | Similarity floor + coverage assertion | Unanswerable question → honest "not in sources" instead of a guess (REQ-13) |
| **4. Prompt-time** | Facts-only, ≤3 sentences, one-citation contract; explicit "don't use prior knowledge" | Unrecognised phrasing the regex missed (REQ-21) |
| **5. Output-time** | Citation injected from metadata; answer-length check; refusal tests AT-6/AT-7/AT-8 | Model-invented citation or advice leakage (P1, REQ-15) |

The layers are independent on purpose: a single control failing must not produce a wrong or
unsourced answer.

---

## 6. Storage Layout

```
HDFC/
├── PRD.md                              # requirements
├── README.md                           # setup, scope, known limits
├── config.py                           # L0 — single source of truth
├── ingest.py                           # L1–L5 — offline pipeline
├── rag.py                              # L7–L8 — query engine
├── guardrails.py                       # L6 — cross-cutting
├── app.py                              # L9 — Streamlit UI
├── requirements.txt
├── .env.example                        # committed; documents GROQ_API_KEY
├── .env                                # git-ignored, never committed (NFR-2)
├── .gitignore
├── data/
│   ├── raw/<slug>.html                 # L1 cache — system of record
│   ├── chunks.txt                      # L5 human-readable chunk dump (REQ-8)
│   ├── chunks.jsonl                    # L5 machine-readable
│   └── chroma/                         # L4 persisted vector DB (REQ-7)
├── deliverables/
│   ├── architecture.md                 # this document
│   ├── chunking_strategy.md            # pre-code chunking proposal
│   ├── sources.csv / sources.md        # D2
│   ├── sample_qa.md                    # D4
│   └── disclaimer.md                   # D5
├── scripts/                            # data-inspection scripts (evidence for PRD §7)
│   ├── inspect_data.py
│   ├── explore_json.py
│   ├── dump_fields.py
│   └── …
└── tests/
    └── test_acceptance.py              # AT-1 … AT-12
```

`.gitignore` must exclude `.env` **and** `data/chroma/` (regenerable binary) while
**keeping** `data/raw/` and `data/chunks.txt` — the raw HTML and the chunk dump are the
audit trail that makes the corpus reviewable without re-running anything.

---

## 7. Runtime Modes

| Mode | Command | Network | API key | Purpose |
|---|---|---|---|---|
| **Ingest** | `python ingest.py` | first run only (cached after) | none | Build corpus + index |
| **Ingest refresh** | `python ingest.py --refresh` | yes | none | Re-fetch, pick up source changes (R2) |
| **Query (CLI)** | `python rag.py "expense ratio of ELSS?"` | Groq only | `GROQ_API_KEY` | Headless eval / demo recording |
| **UI** | `streamlit run app.py` | Groq only | `GROQ_API_KEY` (optional → extractive) | The prototype |
| **Tests** | `python -m pytest tests/` | none | none | AT-1 … AT-12 offline |

Ingestion and query never run in the same process — this keeps P4 honest and makes the
"runs once" claim verifiable by simply restarting the app.

---

## 8. Failure Modes & Degradation

| Failure | Detection | Behaviour | PRD ref |
|---|---|---|---|
| Page markup changed / fetch blocked | Coverage assertion at ingest | **Fail loudly** with the missing scheme×fact pairs. Never build a thin corpus | R1 |
| `GROQ_API_KEY` absent | Env check at init | Extractive fallback from top chunk; UI still works | NFR-5 |
| Groq unreachable / rate-limited | Exception in `answer()` | One retry, then extractive fallback + note | P5 |
| Embedding model not downloaded | Exception at load | Clear install instruction (first run downloads ~90 MB) | NFR-6 |
| Chroma dir deleted | Client re-create | Auto re-ingest prompt; app does **not** silently re-embed | NFR-3 |
| Question out of scope | Similarity floor | Honest "not in the collected sources" + official link | REQ-13 |
| User supplies PII | `detect_pii()` | Refuse; **do not echo the value**; do not log | REQ-20 |
| Source facts go stale | `as_of` + `ingested_at` surfaced | "Last updated from sources: …"; `--refresh` documented | R2 |

---

## 9. Key Interfaces

```python
# config.py  (L0)
SOURCES: list[dict]            # slug, name, category, url
CHUNK_SIZE = 380; CHUNK_OVERLAP = 80; MIN_CHUNK_CHARS = 40
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"; EMBED_DIM = 384
COLLECTION_NAME = "hdfc_mf_faqs"
TOP_K = 5; MIN_SIMILARITY = 0.18
GROQ_API_KEY: str; GROQ_MODEL = "llama-3.3-70b-versatile"
DISCLAIMER: str; REFUSAL_PATTERNS: list[str]; EDUCATIONAL_LINKS: list[dict]

# ingest.py  (L1–L5)
def load_pages(force_refresh: bool = False) -> dict[str, str]
def extract_facts(slug: str, html: str) -> list[Chunk]
def extract_prose(slug: str, html: str) -> list[Chunk]
def build_chunks(force_refresh: bool = False) -> list[Chunk]
def embed_and_store(chunks: list[Chunk]) -> None
def write_dumps(chunks: list[Chunk]) -> None
def coverage_report(chunks: list[Chunk]) -> dict      # scheme x target-fact matrix
def run_ingest(force_refresh: bool = False) -> None

# guardrails.py  (L6)
def detect_pii(text: str) -> PIIHit | None
def scrub_pii(text: str) -> str
def is_advice_request(text: str) -> bool
def is_performance_request(text: str) -> bool

# rag.py  (L7–L8)
@dataclass
class SourceRef:  title: str; url: str; scheme_slug: str; section: str; score: float; as_of: str
@dataclass
class Answer:      text: str; sources: list[SourceRef]; refused: bool
                   refusal_kind: str | None; as_of: str; chunks_used: int

class RAGEngine:
    def __init__(self) -> None
    def retrieve(self, question: str, top_k: int = TOP_K) -> list[Hit]
    def answer(self, question: str) -> Answer

# app.py  (L9)
def main() -> None
```

---

## 10. Architecture Decisions (ADR summary)

| # | Decision | Alternatives rejected | Why |
|---|---|---|---|
| A1 | Parse `__NEXT_DATA__` **and** rendered text | Text-only scraping | Text-only **cannot** see expense ratio or lock-in (PRD §7.2) — fails the two most-asked questions |
| A2 | Structure-first hybrid chunking (fact cards + labelled sections) | Single fixed-size splitter over raw HTML | Splits labels from values; embeds ~40 % boilerplate; misses JSON-only values |
| A3 | 380 chars / 80 overlap | 512-token default | A `label: value` pair is 110–330 chars; 380 holds pair + header + context without dilution |
| A4 | ChromaDB, cosine, normalised, `upsert` | FAISS; in-memory store | Required; free persistence (NFR-3); cosine is standard for MiniLM |
| A5 | Deterministic chunk ids + `upsert` | Random uuid / `add()` | Idempotent re-ingest; `chunks.txt` diffs cleanly (NFR-4) |
| A6 | Regex guardrails **before** retrieval, prompt as 2nd layer | LLM-only moderation | Deterministic, free, fast, and catches the common cases without a token spend |
| A7 | Citations injected from chunk metadata | Let the model write the link | The model can invent a URL; metadata cannot (P1) |
| A8 | Similarity floor → honest "not in sources" | Always pass top-k to the LLM | A weak match plus a fluent model is exactly how a wrong fee gets produced |
| A9 | Separate ingest/query processes, shared disk index | One always-on service | Makes "ingestion runs once" verifiable; restart-safe (P4, NFR-3) |
| A10 | Streamlit | React/Next | Brief asks for a *tiny* UI; native chat + clickable links, hours not days |
| A11 | Exclude return figures from the corpus | Keep them, instruct the LLM to ignore | Belt-and-braces: a fact not in the corpus cannot be quoted (P3) |
| A12 | Rendered risk badge over JSON `nfo_risk` | Either silently | Badge is what the page displays; conflict disclosed in README, escalated as PRD Q3 |

---

## 11. Requirement Traceability

| PRD req | Architecture element |
|---|---|
| REQ-1 | §3.1 Load — cache-first fetch |
| REQ-2 | §3.2 Extractor A + B |
| REQ-3 | §3.2 fact-card declarative sentences |
| REQ-4 | §3.3 380/80, boundary-aware |
| REQ-5 | §3.4 chunk schema |
| REQ-6 | §3.5 MiniLM 384-d |
| REQ-7 | §3.5 ChromaDB persisted + `upsert` |
| REQ-8 | §3.6 `chunks.txt` / `chunks.jsonl` |
| REQ-9 | §3.3 scrub; §5 layer 1 |
| REQ-10 | §3.6 coverage report |
| REQ-11 | §4.2 same-model embed |
| REQ-12 | §4.2 top-k = 5 |
| REQ-13 | §4.2 similarity floor |
| REQ-14 | §4.3 Groq via `config` |
| REQ-15 | §4.3 citation from metadata |
| REQ-16 | §4.3 prompt contract + as-of line |
| REQ-17 | §4.3 facts-only prompt |
| REQ-18..20 | §4.1 guardrail layer; §5 |
| REQ-21 | §4.3 prompt-level prohibition (layer 4) |
| REQ-22..25 | §4.4 Streamlit render |
| NFR-1..7 | §2 dependency rule, §6 storage, §7 modes, §8 degradation |
| AT-1..12 | §3.6 coverage report + `tests/test_acceptance.py` |

---

## 12. Extension Points (post-milestone, out of scope now)

| Extension | Architectural seam it would use |
|---|---|
| More AMCs / more schemes | Add to `config.SOURCES`; no code change. Corpus is keyed by `scheme_slug` |
| HDFC factsheet / SID PDFs | Keep Extractor A for the structured header, add a page-aware Extractor B (see chunking_strategy §5) |
| Multilingual (Hindi/Hinglish) | Question-side normalisation before embed; corpus stays English |
| Hosted REST API | `RAGEngine.answer()` is already a pure function — wrap in FastAPI without touching ingestion |
| Live NAV | New producer writing `as_of`-stamped chunks; P3 still holds since NAV is not a return |
| Re-ranking | Insert between §4.2 and §4.3 — `retrieve()` is the only seam |

Each of these is additive at a named seam, which is the main architectural payoff of
separating ingestion from query.
