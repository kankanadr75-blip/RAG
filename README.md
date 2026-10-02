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
measurement (`scripts/compare_models.py`, same prompt over the same context):

| model | figures stated | invisible chars | completion tokens |
|---|---|---|---|
| **`qwen/qwen3.8-27b`** | **5/5** | **none** | **53** |
| `openai/gpt-oss-20b` | 3/5 | U+202F in 4/5 | 548 |
| `openai/gpt-oss-120b` | 3/5 | U+202F in 3/5 | 540 |

The gpt-oss misses are **not wrong facts** — both models emit U+202F narrow
no-break space instead of a normal space, so `BSE 250` arrives as
`BSE<NBSP>250<NBSP>SmallCap`. The answer is correct but the text no longer
contains the string, which breaks substring assertions and renders with odd
gaps. They also cost ~10x the completion tokens, because a reasoning model's
scratchpad is billed to the same output budget. Answer text is normalised either
way, so swapping the model cannot corrupt output.

Groq's daily limit is **per model**, so exhausting `qwen` does not block
`gpt-oss`. Override in `.env` if your account serves a different subset —
`config.py` records the verified list.

### Build the index (once)

```powershell
python ingest.py              # fetch → extract → chunk → embed → store
python ingest.py --refresh    # re-fetch the pages and update the as-of date
python ingest.py --no-embed   # fast audit path, skips the model entirely
python ingest.py --reembed    # drop and rebuild the vector store
```

The first run downloads `all-MiniLM-L6-v2` (~90 MB) and takes a few minutes on
CPU. Pages are cached in `data/raw/`, so later runs are offline.

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

5. **`"scheme code"` retrieves the wrong field.** Asking for a scheme code
   returns the `investment_objective` chunk (0.316) rather than
   `scheme_identity` (0.244), which sits below the 0.30 rescue gate. The answer
   is still a true fact about the scheme, just not the requested field. Not
   tuned around deliberately — the alternatives either admit off-topic queries
   or require hand-written routing.

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
data/chroma/     vector store (git-ignored, rebuilt by ingest.py)
deliverables/    architecture, chunking, implementation log, sources, Q&A
```

`config.py` is shared by both processes. Ingestion and query never run in the
same process — they meet only through the on-disk index and that file.

## Licence & disclaimer

Source pages are Groww's. This is a facts-only informational assistant and
**not** a SEBI-registered investment adviser. See
[`deliverables/disclaimer.md`](deliverables/disclaimer.md).