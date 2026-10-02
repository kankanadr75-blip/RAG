# HDFC Mutual Fund — facts-only RAG chatbot

A retrieval-augmented assistant that answers **published facts** about five HDFC
Mutual Fund schemes. It cites one source per answer, refuses anything that
would be investment advice, and never reports returns.

```
INGEST (run once)                      QUERY (per question)
─────────────────────                  ──────────────────────
5 public Groww pages                    guardrails: PII → advice →
  ├─ __NEXT_DATA__ → fact cards          performance → out-of-scope
  └─ rendered prose → sections            ↓
        ↓                               embed question (same model)
   130 chunks                           top-10 cosine search
        ↓                               + similarity floor / lexical gate
   all-MiniLM-L6-v2 (384-dim)            ↓
        ↓                               Groq (qwen/qwen3.8-27b)
   ChromaDB → data/chroma/               ↓
                                       answer + 1 citation from metadata
```

Everything runs locally except the one LLM call. No API key is required: without
one the assistant quotes the source verbatim instead of paraphrasing.

---

## Scope

**One AMC — HDFC Mutual Fund. Five schemes, Direct Growth plan only.**

| # | Scheme | Category | Scheme code | Benchmark |
|---|--------|----------|-------------|-----------|
| 1 | HDFC Large Cap Fund – Direct Growth | Large Cap | 119018 | NIFTY 100 TRI |
| 2 | HDFC Flexi Cap Fund – Direct Growth | Flexi Cap | 118955 | NIFTY 500 TRI |
| 3 | HDFC ELSS Tax Saver Fund – Direct Growth | ELSS (Tax) | 119060 | NIFTY 500 TRI |
| 4 | HDFC Small Cap Fund – Direct Growth | Small Cap | 130503 | BSE 250 SmallCap TRI |
| 5 | HDFC Balanced Advantage Fund – Direct Growth | Balanced Advantage | 118968 | NIFTY 50 Hybrid Composite Debt 50:50 |

**Facts only. No advice.** The assistant states what is published and refuses
the rest: no recommendations, no opinions, no returns or rankings, no
comparison between schemes. Full policy: [`deliverables/disclaimer.md`](deliverables/disclaimer.md).

All five sources are public **Groww** scheme pages. Nothing is taken from
third-party blogs, forums or aggregators. Full list:
[`deliverables/sources.md`](deliverables/sources.md) ·
[`sources.csv`](deliverables/sources.csv).

---

## Setup

Python 3.11+ (verified on 3.13, Windows, CPU-only — no GPU needed).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-File .env.example .env      # then add your key
notepad .env
```

```ini
# .env
GROQ_API_KEY=gsk_...
GROQ_MODEL=qwen/qwen3.8-27b      # optional, this is the default
```

Get a key at <https://console.groq.com/keys> (free tier: 200k tokens/day —
enough for a few hundred questions, see [Known limits](#known-limits)).

**On the model.** `qwen/qwen3.8-27b` is the default because it was chosen by
measurement (`scripts/compare_models.py`, same prompt over the same context).
Figures are checked against the finalised text — what the user actually sees:

| model | figures stated | invisible chars | completion tokens |
|---|---|---|---|
| **`qwen/qwen3.8-27b`** | **5/5** | **none** | **53** |
| `openai/gpt-oss-20b` | 5/5 | U+202F in 4/5, stripped | 541 |
| `openai/gpt-oss-120b` | 4/5 | U+202F in 3/5, stripped | 534 |

gpt-oss-20b first measured 3/5 and was rejected. Those misses were **not wrong
facts** — the models emit U+202F narrow no-break space instead of a normal
space, so `BSE 250` arrives as `BSE<NBSP>250`, which breaks substring tests and
renders with odd gaps. `_strip_disallowed` now normalises that, so the same
model scores 5/5 and is a legitimate fallback rather than a downgrade.

It is not free: a gpt-oss reasoning scratchpad is billed to the same output
budget, so completion tokens are ~10x. The retrieved context dominates the
request, so the real cost is closer to ~1.5x per answer. That is why it is the
fallback, not the default.

**On quota.** Groq's 200k tokens/day limit is **per model**, not per account, so
exhausting `qwen` leaves `gpt-oss` untouched. `rag.py` therefore walks a model
chain — `GROQ_MODEL` then `GROQ_FALLBACK_MODELS` — and only drops to the
extractive quote when every model fails. A 429 is not retried on the same model
(a daily quota cannot recover inside a retry) and a 4xx is not retried at all,
since repeating an identical request cannot change the outcome; a `401` aborts
the chain immediately, because one bad key fails identically on every model.

```ini
GROQ_FALLBACK_MODELS=openai/gpt-oss-20b   # comma-separated; "" disables
```

Override in `.env` if your account serves a different subset — `config.py`
records the verified list for this one.

### Build the index (once)

```powershell
python ingest.py              # fetch → extract → chunk → embed → store
python ingest.py --refresh    # re-fetch the pages and update the as-of date
python ingest.py --no-embed   # fast audit path, skips the model entirely
python ingest.py --reembed    # drop and rebuild the vector store
```

The first run downloads `all-MiniLM-L6-v2` (~90 MB) and takes a few minutes on
CPU. Pages are cached in `data/raw/`, so later runs are offline.

**The index is committed**, so you do not normally need to run this at all —
`data/chroma/chroma.sqlite3` (~5 MB of portable SQLite) is in the repo and the
app opens it directly. Only the `hnsw/` binaries beside it are ignored; those
are a rebuildable cache and Chroma regenerates them on first query.

You must re-run `python ingest.py --reembed` after editing **either** `ingest.py`
**or** `data/raw/*.html`. Both are hashed into a fingerprint stored on the
collection, and `_index_ready()` compares it at every app start — a mismatch is
treated as "no index" and rebuilt, so the app can never quietly answer from
chunks that no longer match the sources. `tests/test_acceptance.py` asserts the
fingerprint matches, which is what stops the rebuild from being forgotten.

Only `chroma.sqlite3` is tracked, because SQLite is portable and the HNSW
binaries are not. That was verified rather than assumed: deleting every
non-SQLite file from a copy of the index and then querying it returns correct
hits, with Chroma rebuilding the HNSW structure from the vectors in SQLite.

### Run it

```powershell
streamlit run app.py          # the UI  → http://localhost:8501
python rag.py "What is the expense ratio of HDFC ELSS Tax Saver Fund?"
```

The CLI is the fastest way to check a change. A refusal, captured verbatim:

```
$ python rag.py "Should I buy HDFC Large Cap?"
==============================================================================
Q: Should I buy HDFC Large Cap?

I only share published facts about HDFC Mutual Fund schemes, so I can't tell you
which scheme to choose or what to do with your money - that depends on your
goals, time horizon and risk tolerance, which only you and a SEBI-registered
investment adviser can assess. Here's where you can learn the concepts yourself.

  Learn more:
    - SEBI - Mutual Fund Regulations & disclosures: https://www.sebi.gov.in/

  [kind=advice]
```

Refusal copy is fixed in `guardrails.py`, so that output is deterministic. A
factual answer is generated, so its wording varies — see
[`deliverables/sample_qa.md`](deliverables/sample_qa.md) for real captured
answers covering AT-1…AT-9.

### Verify

```powershell
python scripts/verify_all.py      # everything: 13 suites, exit 0 on success
python -m pytest tests/ -q       # just the AT-1..AT-12 acceptance suite
```

---

## Deploying

`render.yaml` is a Render blueprint, so the whole service is version-controlled
rather than living in dashboard settings. Connect the repo as a **Blueprint** and
Render will prompt once for `GROQ_API_KEY`, which is never committed
(`sync: false`).

Three things in it are load-bearing and easy to get wrong if you configure this
by hand instead:

**Instance type is currently set to Free (512 MB), which is over budget.**
Measured peak working set is **563 MB** — torch, chromadb, streamlit and the
embedding model together. Thread and arena tuning was tried and made no material
difference (563 MB → 562 MB); the bulk is model weights and the torch runtime, not
per-thread arenas, so it cannot be tuned away. Switch the blueprint to
`plan: standard` (2 GB) before deploying anything you care about.

The failure mode on Free is worth knowing, because it does not look like a bug:
the embedding model is built lazily on the *first query*, so the service boots,
health-checks fine, renders the Streamlit UI — and is then OOM-killed when
someone first asks a question. Check the logs for a **killed process**, not an
exception.

**`torch` must be installed from the CPU index.** The default Linux wheel for
`torch==2.14.0` declares `nvidia-cudnn`, `nvidia-nccl`, `nvidia-cusparselt`,
`nvidia-nvshmem` and `triton` — several GB of CUDA on a CPU-only host, which fails
the build. The build command installs `2.14.0+cpu` first; `requirements.txt` then
sees the pin satisfied and skips the CUDA wheel.

**The build does not build the vector DB.** The index is committed, so a deploy
starts from a working index rather than an empty one. The build still installs
CPU `torch` and still runs `ingest.py --reembed` as a verification step: it is
idempotent, it re-checks the corpus against the sources, and it aborts with a
non-zero exit if any target fact has gone missing, so a broken corpus fails the
build loudly instead of shipping. Remove it from `render.yaml` if you would
rather have a faster build — the committed index makes it unnecessary, and the
fingerprint guard would catch a stale one at runtime either way.

`PYTHON_VERSION` is pinned to 3.13.5 in both `.python-version` and the blueprint,
because Render's default Python is not the version this was verified against.

### Streamlit Community Cloud (free)

Also supported, and unlike the Render Free tier its memory budget is not a
problem — the documented ceiling is **2.7 GB** against a measured 563 MB peak.

There is **no build command** on Community Cloud, which is the one real
difference from Render and is why the index is committed: with nothing to build
with, a git-ignored index would force a full model download and re-embed on
every cold start, and would greet the first visitor with a build message.

`app.py::_index_ready()` now validates the committed index instead of merely
checking it exists — non-empty, and its stored fingerprint must equal
`config.corpus_fingerprint()` (a hash of `data/raw/*.html` + `ingest.py`). It
costs ~23 ms warm. Only if that fails does `get_engine()` fall back to
`ingest.main([])`, which reads the committed pages in `data/raw/` and so needs
no network for the corpus — only the one-time embedding-model download.

Set the key in **Advanced settings → Secrets** as a single line:

```toml
GROQ_API_KEY = "gsk_..."
```

Community Cloud injects root-level secrets into the environment, so
`config.py`'s `os.getenv("GROQ_API_KEY")` reads it with no code change.

Pick **3.13** in the Python version dropdown. Community Cloud ignores
`.python-version`, so the dropdown is the only thing that sets it.

> **Set this before the first deploy.** It is not cosmetic. Community Cloud's
> install image carries no compiler, so any dependency that can only be
> installed from a source tarball fails the whole deploy. `numpy==2.1.3`,
> `pydantic==2.10.3` and `lxml==5.3.0` publish no `cp314` wheel, and their
> source builds need Fortran, Rust and `libxml2` headers respectively. The
> error is:
>
> ```
> ERROR: Could not build wheels for numpy, which is required to install
> pyproject.toml-based projects
> ```
>
> `requirements.txt` now carries environment markers so 3.14 also installs
> cleanly, but **3.13 is still the version to choose** — it keeps the exact
> versions the 39-test suite was validated against.

`.streamlit/config.toml` sits at the repository root because Community Cloud
recognises exactly one, there.

**One dependency trap specific to this platform.** Community Cloud resolves
`requirements.txt` with **uv**, not pip, and uv will not fall back to a later
index for a package it already found on an earlier one — its defence against
dependency confusion. So the obvious way to get the CPU torch wheel,

```ini
--extra-index-url https://download.pytorch.org/whl/cpu
```

fails the *entire* install, because that URL also serves a `requests` listing:

```
Because there is no version of requests==2.32.3 and you require
requests==2.32.3, we can conclude that your requirements are unsatisfiable.
```

`requirements.txt` uses `--find-links https://download.pytorch.org/whl/cpu/torch/`
instead. `--find-links` declares a flat list of wheels rather than an index, so
it never claims a package name and everything else still resolves from PyPI.
Verified with `uv pip compile` against Linux for both Python 3.12 and 3.13:
123 packages, `torch==2.14.0+cpu`, and no `nvidia-*` or `triton` entries.

### Vercel will not work

Not a configuration problem — Vercel cannot run a Streamlit server. Its Python
runtime wraps a single WSGI/ASGI handler into a serverless function, and
Streamlit is a long-lived HTTP + WebSocket process that does not survive a
function freeze. The read-only filesystem also breaks the HuggingFace model
cache, and the 512 MB Hobby build limit is less than this build needs. Hosting
here would mean rewriting the app as a JSON API plus a separate frontend.

---

## Architecture

- [`deliverables/architecture.md`](deliverables/architecture.md) — layers,
  chunk schema, data flow, and the ADRs behind each non-obvious decision.
- [`deliverables/chunking_strategy.md`](deliverables/chunking_strategy.md) —
  why two producers, and why those sizes.
- [`PRD.md`](PRD.md) — requirements REQ-1…REQ-24, acceptance criteria
  AT-1…AT-12, and known limits.
- [`deliverables/implementation.md`](deliverables/implementation.md) — the
  build log, including the bugs found and fixed along the way.
- [`deliverables/sample_qa.md`](deliverables/sample_qa.md) — real captured
  answers covering AT-1…AT-9.

### Two decisions worth knowing before reading the code

**Citations are built in Python, never parsed from the model.** The prompt
tells the model not to emit URLs, and the citation is then attached from chunk
metadata. A model therefore *cannot* invent, alter or omit a source link
(architecture.md P1).

**Returns are removed at ingest, not forbidden in the prompt.** No return,
ranking or peer-comparison figure is ever written to the corpus, so none can
leak — not through the LLM, and not through the no-key fallback, which quotes
the corpus verbatim. A prompt instruction would be a request; this is a
guarantee.

### Corpus

130 chunks — **80 fact cards + 50 prose sections** across the five pages,
all 35 coverage cells (5 schemes × 7 target facts) populated.

Fact cards come from each page's `__NEXT_DATA__` payload
(`props.pageProps.mfServerSideData`); prose sections come from the rendered
visible text. Both are needed: **expense ratio and lock-in period exist only in
the JSON.** A text-only scrape of these pages cannot answer the two most-asked
questions.

Prose is chunked at 380 chars with 80 overlap and a 40-char minimum; fact cards
are emitted whole at 110–330 chars with no overlap, because they are already
one fact. Every chunk carries:

`chunk_id`, `source_url`, `source_name`, `amc`, `scheme_slug`, `scheme_name`,
`scheme_code`, `category`, `section`, `producer`, `extracted_from`, `as_of`,
`ingested_at`, `char_len`, `content_hash`

`data/chunks.txt` and `data/chunks.jsonl` are the human-readable audit trail
and are tracked in git.

### Retrieval

`TOP_K = 10` chunks, cosine similarity, gated twice:

- **`MIN_SIMILARITY = 0.54`** — calibrated, not guessed. Measured over 32
  in-domain and 20 off-topic queries (`scripts/calibrate_floor.py`):
  in-domain top-1 spans **0.660–0.928**; the loudest off-topic query reaches
  **0.421**. Those do not overlap, so any floor in `(0.421, 0.660]` is correct
  and 0.54 is the midpoint. The original provisional 0.18 admitted **14 of 20**
  off-topic questions.
- **Lexical grounding** (`MIN_SIMILARITY_LOWER = 0.30`) — a floor alone is not
  enough, because terse queries ("AUM ELSS", "riskometer") score *lower* than
  off-topic prose does. Retrieval keeps a hit if it clears the floor **or** is
  lexically grounded above 0.30.

`TOP_K` was raised from 5 to 10 to widen recall: several target facts have one
near-identical instance per scheme, so a scheme-qualified question and the
wrong scheme's card can sit close in rank. Verified not to cause cross-scheme
bleed by `scripts/check_context_dilution.py`.

---

## Known limits

1. **Single AMC, five Direct–Growth schemes.** No Regular-plan figures exist in
   this corpus and none must be inferred from them — the Direct and Regular
   expense ratios differ.

2. **Riskometer conflict, unresolved.** The rendered badge reads **"Very High
   Risk"**; the `__NEXT_DATA__` `nfo_risk` field reads **"Moderately High"**.
   The badge is treated as authoritative. This needs confirmation against HDFC
   AMC's official disclosure (PRD open question Q3). *If you rely on the
   riskometer answer, verify it.*

3. **Fund manager is not answered.** The JSON and the page prose name different
   fund managers, and the conflict could not be reconciled from public sources.
   The field is excluded rather than guessed.

4. **Two inception dates are stored, both labelled.** 01-Jan-2013 is the Direct
   Plan's; 10 Dec 1999 is the scheme's. They are kept separate and labelled
   rather than reconciled.

5. **A bare `"scheme code"` cannot be answered.** The query names no scheme, and
   the corpus holds five `scheme_identity` chunks with five different codes
   (119018 / 118955 / 119060 / 130503 / 118968). All five score 0.162–0.244,
   below the 0.30 rescue gate, so **no threshold admits the right one** — the
   top scorer wins by embedding noise. The user gets a non-answer plus a
   citation to an arbitrarily chosen scheme. Admitting a chunk would return
   119060 (ELSS) for a general question, trading a non-answer for a *confident
   error*, so the current behaviour is the safer one. The fix is a
   scope-clarification affordance ("which scheme?"), which is a product change,
   not a threshold — deliberately not built. The model does correctly decline to
   invent a figure.

   Note: the lexical classifier is **not** at fault. `"scheme code"` is a
   registered domain term and matches verbatim in the `scheme_identity` chunk,
   so `_lexical_grounding` identifies the right chunk and is then overruled by
   the score floor. An earlier version of this note claimed the rescue "never
   sees" the correct chunk and that the failure was "benign"; both were wrong
   and are corrected in `implementation.md` §16.4.

6. **AMC-level AUM is dropped.** The About prose repeats HDFC AMC's total AUM
   (₹9,86,237 Cr) on every one of the five pages. It is removed structurally so
   it cannot be mistaken for a scheme-level figure; scheme-level `aum` is
   stored instead.

7. **No performance data, by design.** Returns, rankings and peer comparisons
   are excluded from the corpus at **ingest** time, not merely forbidden in the
   prompt. So there is no figure to leak — not via the LLM, and not via the
   no-key fallback, which quotes the corpus verbatim. Two side effects: questions
   like "how has it done?" are refused rather than answered, and the word
   "return" still appears in answers, but only as part of a benchmark's name
   ("NIFTY 100 Total Return Index") or the statutory tax slab ("returns are taxed
   at 20%"). Neither is a performance claim.

8. **NAV is a snapshot.** It is stored as published on the `as_of` date and is
   stale the moment it is served. Every answer ends with
   `Last updated from sources: <date>` for this reason, and
   `python ingest.py --refresh` re-fetches the pages.

9. **Groww is client-rendered and can change.** A markup change breaks
   extraction. Ingestion fails loudly rather than answering from a thin corpus
   (R1), but this is the most likely thing to break.

10. **Sources are Groww's, not the AMC's.** For anything statutory — SID, KIM,
    addenda, monthly factsheet — use HDFC Mutual Fund or AMFI directly.

11. **English only**, no multilingual handling.

11. **No conversation memory.** Each question is answered independently, so
    follow-ups like "what about the ELSS one?" need to be spelled out. This is
    deliberate: carrying history across turns risks bleeding one scheme's
    figures into another's answer, which would break the single-citation
    guarantee.

12. **Free-tier rate limit.** Groq's free tier allows 200k tokens/day and a
    single answer costs ~1.6k, so roughly 120 questions/day. Past that the
    assistant falls back to quoting the source verbatim and says so on screen
    rather than failing silently.

13. **A cross-scheme answer gets one incomplete citation.** "What is the minimum
    SIP?" genuinely spans five schemes; the answer gives both values (₹500 for
    ELSS, ₹100 for the rest) but cites only the top-ranked page. One link is
    incomplete here by construction — the alternative, four links, would assert
    every page supports the answer. See `sample_qa.md` row 4.

14. **One answer is visibly truncated.** Asking how to download the SID ends
    mid-clause ("…is published by HDFC Mutual Fund at"). The `documents` chunk
    ends where the page's markup ends, and the 3-sentence cap then cuts the
    model's attempt to complete it. Factually safe, cosmetically broken, and
    **not fixed** — a larger window at that chunk boundary is the fix. See
    `sample_qa.md` row 9.

---

## Guardrails

Checked in a fixed order, cheapest and most decisive first. The first match
wins and the question never reaches retrieval, the LLM, or any log.

| # | Stage | Catches | Example |
|---|-------|---------|---------|
| 1 | PII | PAN, Aadhaar, folio/account numbers, OTP, e-mail, phone | *"my PAN is ABCDE1234F"* |
| 2 | Advice | "should I", "which is better", "recommend", "for me" | *"should I buy HDFC Large Cap?"* |
| 3 | Performance | returns, rankings, "best performing", NAV forecasts | *"which fund gives the best returns?"* |
| 4 | Out of scope | an HDFC fund we do not hold | *"expense ratio of HDFC Mid Cap?"* |
| 5 | Retrieval floor | no chunk clears similarity or lexical grounding | *"what is the GDP of India?"* |

Every refusal is polite, explains what the assistant will not do, and carries a
relevant **educational** link (SEBI, AMFI, HDFC AMC) — never a scheme figure.
Refusal copy is fixed in `guardrails.py`, so it is deterministic and costs no
tokens. Assertions in `tests/test_acceptance.py` cover each stage, including
that **no part of the input is echoed back** in a PII refusal.

---

## Layout

```
config.py        single source of truth: sources, paths, chunking, thresholds
guardrails.py    PII detection/scrubbing, advice & performance classifiers
ingest.py        the offline pipeline
rag.py           retrieval + generation + citations, and a CLI
app.py           Streamlit UI (no answer logic of its own)
tests/           AT-1..AT-12 acceptance suite
scripts/         verification, calibration, and the sample-Q&A capture
data/raw/        cached source HTML — the system of record
data/chroma/     vector store — chroma.sqlite3 is committed; hnsw/ is not
deliverables/    architecture, chunking, implementation log, sources, Q&A
```

`config.py` is shared by both processes. Ingestion and query never run in the
same process — they meet only through the on-disk index and that file.

## Licence & disclaimer

Source pages are Groww's. This is a facts-only informational assistant and
**not** a SEBI-registered investment adviser. See
[`deliverables/disclaimer.md`](deliverables/disclaimer.md).