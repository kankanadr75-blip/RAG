# Implementation Guide — Mutual Fund FAQ Assistant (RAG Chatbot)

**Derived from:** `PRD.md` v1.0 + `deliverables/architecture.md` v1.0
**Purpose:** Phase-by-phase work orders to implement the RAG chatbot with an AI coding
agent (Cursor / Claude Code / OpenCode), one phase at a time.
**Version:** v1.0 · **Last updated:** 01 Oct 2026

---

## How to use this document

**Each phase is a self-contained, independently verifiable increment.** Do them in order.
Do not start Phase N+1 until Phase N's *Definition of Done* is met — every later phase
assumes the earlier phase's artifacts exist and are correct.

| Rule | Why |
|---|---|
| Run the **Verification** block at the end of every phase | Cheap, catches drift immediately |
| Do **not** let the agent guess values | The verified fact table in §0.3 already has every answer — supply it |
| One phase per agent request | Keeps each diff reviewable |
| Never commit `.env` | NFR-2 |

Each phase gives you: **Objective → Inputs/Outputs → Files → Tasks → Verification →
Definition of Done → pasteable agent prompt.**

---

## 0. Pre-flight context (read before Phase 0)

### 0.1 Reading order for the agent

```
PRD.md                        → what must be built (requirements)
deliverables/architecture.md  → how it is structured (design)
deliverables/chunking_strategy.md → chunk parameters + rationale
deliverables/implementation.md (this file) → in what order
config.py                     → already exists; single source of truth
```

### 0.2 The five critical findings (already verified — do not re-derive)

1. **`__NEXT_DATA__` is mandatory.** Each page embeds a `script#__NEXT_DATA__` tag whose
   exact path is **`props.pageProps.mfServerSideData`** — a flat dict of **97 keys** per scheme.
   **Expense ratio and lock-in exist ONLY here** — the rendered DOM contains just the word
   "Expense ratio" (a tooltip). A text-only scraper fails the two most-asked questions.
2. **Rendered text is still needed** for prose: `Minimum investments`, `Exit load`,
   `Tax implication`, `Investment Objective`, `About`, `Fund benchmark`,
   `Scheme Information Document(SID)`, `Registrar & Transfer Agent`, glossary definitions.
3. **~40 % of visible lines are boilerplate** (nav, footer, holdings, peer tables,
   manager bios) — must be excluded.
4. **The riskometer conflicts**: the rendered badge says **"Very High Risk"**; JSON
   `nfo_risk` says **"Moderately High Riskometer"** (3 schemes) / **"Moderately High"** (2).
   → **Use the rendered badge.** Document the conflict. Do not silently pick one.
5. **Return/performance figures must never enter the corpus** (PRD P3 / R5).

### 0.3 Verified fact table — sanity-check every extractor against this

Source `as_of` = **30-Sep-2026**. All figures are **Direct – Growth**.

| Scheme | slug | scheme_code | `expense_ratio` | `base_expense_ratio` | `exit_load` | `lock_in` | `min_sip_investment` | `benchmark_name` |
|---|---|---|---|---|---|---|---|---|
| Large Cap | `hdfc-large-cap-fund-direct-growth` | 119018 | **1.03** | 0.84 | Exit load of 1% if redeemed within 1 year | none | 100 | NIFTY 100 Total Return Index |
| Flexi Cap | `hdfc-equity-fund-direct-growth` | 118955 | **0.77** | 0.57 | Exit load of 1% if redeemed within 1 year | none | 100 | NIFTY 500 Total Return Index |
| ELSS | `hdfc-elss-tax-saver-fund-direct-plan-growth` | 119060 | **1.21** | 0.97 | **Nil** | **3 years** | 500 | NIFTY 500 Total Return Index |
| Small Cap | `hdfc-small-cap-fund-direct-growth` | 130503 | **0.78** | — | Exit load of 1% if redeemed within 1 year | none | 100 | BSE 250 SmallCap Total Return Index |
| Balanced Advantage | `hdfc-balanced-advantage-fund-direct-growth` | 118968 | **0.78** | — | Exit Load for units in excess of 15% of the investment, 1% will be charged for redemption within 1 year | none | 100 | NIFTY 50 Hybrid Composite Debt 50:50 Index |

Other verified values: `nfo_risk` = `Moderately High Riskometer` / `Moderately High`;
`stamp_duty` = `0.005% (from July 1st, 2020)`; `portfolio_turnover` = 18 / 29 / 32 / — / —;
`aum` = 39933.3663 / 113606.46602051 / 15991.7823 / 41890.8613 / 107295.7919;
`nav_date` = `30-Sep-2026`; `registrar_agent` = `CAMS` for all 5;
`sid_url` = `https://www.hdfcfund.com`; `amc_page_url` = `https://groww.in/mutual-funds/amc/hdfc-mutual-funds`;
`additional_details` for ELSS = `{'lock_in_yrs': 3, ...}`;
`nfo_risk`-independent rendered badge = **`Very High Risk`** on all 5.
`groww_rating` = 4 / 5 / 5 / 3 / 5.

### 0.4 Environment gotchas (will otherwise waste a cycle each)

| Gotcha | Fix |
|---|---|
| **Windows console is cp1252** → printing `₹` raises `UnicodeEncodeError` | Run every Python command with `$env:PYTHONIOENCODING='utf-8'` |
| **`Invoke-WebRequest` fails** — PowerShell is NonInteractive | Use `python -c` / `requests`, never PowerShell web cmdlets |
| **Streamlit is already installed**; so are `chromadb`, `sentence-transformers`, `torch` (CPU), `flask`, `beautifulsoup4`, `lxml`, `python-dotenv` | Do **not** reinstall; just pin in `requirements.txt` |
| `MIN_SIMILARITY = 0.18` is a **starting** value | Phase 7 must tune it against real hits and document the chosen value |
| Pydantic/v2 API differences in `chromadb 1.5.x` | Use `collection.upsert(ids=, documents=, embeddings=, metadatas=)` and `collection.query(query_embeddings=, n_results=, include=)` |
| First `SentenceTransformer(...)` call downloads ~90 MB | Needs network on first run only |

---

## Phase 0 — Scaffolding, dependencies, secrets

**Objective:** Repo skeleton, dependency manifest, secret handling, config validated.
**Refs:** PRD §9 (NFR-2, NFR-6, NFR-7); Arch §2 L0, §6.
**Depends on:** nothing.

### Files

| File | Action |
|---|---|
| `requirements.txt` | create |
| `.gitignore` | create |
| `.env.example` | create |
| `.env` | create (git-ignored) |
| `config.py` | **exists — review only, do not rewrite** |

### Tasks

1. **Keep `config.py` as-is.** It already defines `SOURCES`, `RAW_DIR`, `CHROMA_DIR`,
   `CHUNKS_TXT`, `DOCS_JSONL`, `CHUNK_SIZE=380`, `CHUNK_OVERLAP=80`,
   `MIN_CHUNK_CHARS=40`, `EMBED_MODEL`, `EMBED_DIM=384`, `COLLECTION_NAME`, `TOP_K=5`,
   `MIN_SIMILARITY=0.18`, `GROQ_MODEL`, `DISCLAIMER`, `REFUSAL_PATTERNS`,
   `EDUCATIONAL_LINKS`, `USER_AGENT`. Only **add** keys if a later phase needs them.
2. Create `requirements.txt` pinning what's installed:
   `chromadb`, `sentence-transformers`, `torch`, `streamlit`, `groq`, `requests`,
   `beautifulsoup4`, `lxml`, `python-dotenv`, plus `pytest` for Phase 10.
3. Create `.gitignore` containing **`.env`**, `__pycache__/`, `.venv/`, `*.pyc`,
   `data/chroma/`.
   **Must NOT ignore** `data/raw/` and `data/chunks.txt` — they are the audit trail.
4. Create `.env.example` with `GROQ_API_KEY=` and `GROQ_MODEL=llama-3.3-70b-versatile`.
5. Create `.env` locally (ask the user for the real key; **never** write a key into any
   tracked file, and never echo it in output).

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python -c "import config; print(len(config.SOURCES), config.CHUNK_SIZE, config.CHUNK_OVERLAP, config.TOP_K, config.MIN_SIMILARITY, config.EMBED_DIM)"
git check-ignore .env; git status --short
```

**Expected:** `5 380 80 5 0.18 384` · `.env` ignored · no `.env` in `git status`.

### Definition of Done
- [ ] `requirements.txt`, `.gitignore`, `.env.example`, `.env` exist
- [ ] `config.py` imports and prints the expected 6 values
- [ ] `git check-ignore .env` returns a match

> **Agent prompt — Phase 0**
> Create `requirements.txt`, `.gitignore`, `.env.example` for this RAG project. Packages
> already installed: chromadb, sentence-transformers, torch (CPU), streamlit, requests,
> beautifulsoup4, lxml, python-dotenv — pin them, do not reinstall. Add `groq` and `pytest`.
> `.gitignore` MUST include `.env`, `__pycache__/`, `.venv/`, `*.pyc`, `data/chroma/` and
> MUST NOT include `data/raw/` or `data/chunks.txt`. `.env.example` contains
> `GROQ_API_KEY=` and `GROQ_MODEL=llama-3.3-70b-versatile`. Do not create a real `.env`
> with a key; do not modify `config.py`. Then verify
> `python -c "import config; print(len(config.SOURCES), config.CHUNK_SIZE, config.CHUNK_OVERLAP, config.TOP_K, config.MIN_SIMILARITY, config.EMBED_DIM)"`
> prints `5 380 80 5 0.18 384`.

---

## Phase 1 — Loader (Load stage)

**Objective:** Fetch the 5 public pages once and cache raw HTML to disk.
**Refs:** PRD REQ-1; Arch §3.1, A-none; mitigates R2.
**Depends on:** Phase 0.

### Files
| File | Action |
|---|---|
| `ingest.py` | create — **loader section only** for now |
| `data/raw/*.html` | produced (5 files, 450–815 KB each) |

### Tasks

1. Add to `ingest.py`:
   - `load_pages(force_refresh: bool = False) -> dict[str, str]`
   - For each `config.SOURCES`: if `data/raw/<slug>.html` exists and not `force_refresh`,
     read from disk; else `requests.get(url, headers={"User-Agent": config.USER_AGENT},
     timeout=45)`, `raise_for_status()`, then write UTF-8.
2. Print a one-line-per-page summary: slug, `cached`/`fetched`, byte length.
3. If a fetch fails, **raise** with the slug and status — do not skip silently (R1).
4. Add a `if __name__ == "__main__":` that runs `load_pages()` and prints counts.
5. CLI flag `--refresh` wired to `force_refresh`.

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python ingest.py                      # first run: 5 fetched
python ingest.py                      # second run: 5 cached, no network
(Get-ChildItem data/raw/*.html).Count  # 5
```

**Expected:** second run reports all 5 `cached`; file count = 5.

### Definition of Done
- [ ] 5 HTML files in `data/raw/`, each > 400 KB
- [ ] Re-run makes no network calls
- [ ] `--refresh` re-fetches
- [ ] A failed fetch raises, never skips

> **Agent prompt — Phase 1**
> Add a loader to `ingest.py`. Implement `load_pages(force_refresh=False) -> dict[str,str]`
> that iterates `config.SOURCES`, reads `data/raw/<slug>.html` from disk when present and
> not refreshing, else GETs `src["url"]` with `config.USER_AGENT` and `timeout=45`, calls
> `raise_for_status()`, and writes UTF-8. Print `slug | cached|fetched | bytes`. Raise on
> fetch failure including the slug — never skip silently. Wire a `--refresh` argparse flag.
> Do not write any extraction or chunking code yet.

---

## Phase 2 — Extractor A: structured facts from `__NEXT_DATA__`

**Objective:** Turn the embedded JSON into one self-contained declarative sentence per fact.
**Refs:** PRD REQ-2, REQ-3; Arch §3.2 Extractor A, §3.3 producer A; finding §0.2.1.
**Depends on:** Phase 1.

### Files
| File | Action |
|---|---|
| `ingest.py` | add `Chunk` dataclass + `extract_facts()` |
| `scripts/debug_facts.py` | create — throwaway inspector |

### Tasks

1. Define a single `Chunk` dataclass used by **both** extractors (schema in Arch §3.4).
   Start with: `chunk_id, text, source_url, source_name, amc, scheme_slug, scheme_name,
   scheme_code, category, section, producer, extracted_from, as_of, ingested_at, char_len,
   content_hash`.
2. `extract_facts(slug, html) -> list[Chunk]`:
   - `re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)` → `json.loads`
   - navigate `props.pageProps.mfServerSideData`
   - **fail loudly** if that path is missing (R1) — the page shape changed
3. Build fact cards from a **whitelist** of keys (never a blind loop over all 97):
   `expense_ratio`, `base_expense_ratio`, `exit_load`, `lock_in`, `benchmark`,
   `benchmark_name`, `min_sip_investment`, `min_investment_amount`, `min_withdrawal`,
   `sip_multiplier`, `purchase_multiplier`, `mini_additional_investment`, `nfo_risk`,
   `description`, `category`, `sub_category`, `nav`, `nav_date`, `aum`,
   `portfolio_turnover`, `launch_date`, `allotment_date`, `isin`, `rta_scheme_code`,
   `registrar_agent`, `stamp_duty`, `groww_rating`, `sid_url`, `amc_page_url`,
   `plan_type`, `scheme_type`, `sip_allowed`, `lumpsum_allowed`, `additional_details`.
4. **Normalise before phrasing** (REQ-3):
   - `lock_in` arrives as the **string** `"{'years': 3, 'months': 0, 'days': 0}"` —
     `ast.literal_eval` it, then render `"3 years"` / `"None"`.
   - `additional_details` is likewise a stringified dict → parse for `lock_in_yrs`.
   - `min_sip_investment` = `'500'` → `"₹500"`.
   - `expense_ratio` = `'1.21'` → `"1.21 %"`.
   - Empty/`'None'`/`0` values → **skip the card entirely**.
5. Each card is a **declarative sentence naming the scheme**, e.g.
   `"The expense ratio of HDFC ELSS Tax Saver Fund Direct Plan Growth is 1.21 % (base expense ratio 0.97 %)."`
   and `"The lock-in period of HDFC ELSS Tax Saver Fund Direct Plan Growth is 3 years."`
6. **Exclusions** (P3 / R5 / §7.4): never emit `fund_manager` (unreconciled conflict);
   never emit any return/ranking/peer field; never emit the AMC-level AUM from About prose.
7. `extracted_from="__NEXT_DATA__"`, `producer="fact_card"`, `as_of = nav_date or ""`.

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/debug_facts.py
```

The debug script must assert, per §0.3:
- expense ratios are exactly **1.03 / 0.77 / 1.21 / 0.78 / 0.78**
- `lock_in` is **3 years for ELSS only**, absent for the other 4
- `min_sip_investment` = 100/100/**500**/100/100
- benchmarks match §0.3
- `exit_load` == **"Nil"** for ELSS
- **zero** cards contain "1Y", "3Y annualised", "annualised returns", or a fund-manager name

### Definition of Done
- [ ] `Chunk` dataclass defined once, used by both extractors later
- [ ] All assertions in `scripts/debug_facts.py` pass
- [ ] Every card is a full sentence naming its scheme
- [ ] No card contains PII, a return figure, or a manager name
- [ ] Missing `mfServerSideData` raises a clear error

> **Agent prompt — Phase 2**
> In `ingest.py`, define a `Chunk` dataclass with fields: chunk_id, text, source_url,
> source_name, amc, scheme_slug, scheme_name, scheme_code, category, section, producer,
> extracted_from, as_of, ingested_at, char_len, content_hash. Implement
> `extract_facts(slug, html) -> list[Chunk]` that parses
> `<script id="__NEXT_DATA__">` → `props.pageProps.mfServerSideData` and raises a clear
> error if that path is missing. Build fact cards ONLY from this whitelist: expense_ratio,
> base_expense_ratio, exit_load, lock_in, benchmark, benchmark_name, min_sip_investment,
> min_investment_amount, min_withdrawal, sip_multiplier, purchase_multiplier,
> mini_additional_investment, nfo_risk, description, category, sub_category, nav, nav_date,
> aum, portfolio_turnover, launch_date, allotment_date, isin, rta_scheme_code,
> registrar_agent, stamp_duty, groww_rating, sid_url, amc_page_url, plan_type, scheme_type,
> sip_allowed, lumpsum_allowed, additional_details. Normalise first: `lock_in` and
> `additional_details` are STRINGIFIED python dicts — use ast.literal_eval then render
> "3 years" / "None"; rupees as "₹500"; ratios as "1.21 %"; skip empty/'None' values.
> Each card must be a declarative sentence that names the scheme, e.g. "The expense ratio of
> HDFC ELSS Tax Saver Fund Direct Plan Growth is 1.21 % (base expense ratio 0.97 %).".
> Set producer="fact_card", extracted_from="__NEXT_DATA__", as_of=nav_date. NEVER emit
> fund_manager, any return/ranking/peer number, or contact details. Then create
> scripts/debug_facts.py asserting: expense ratios 1.03/0.77/1.21/0.78/0.78; lock-in 3 years
> for ELSS ONLY; min SIP 100/100/500/100/100; exit_load "Nil" for ELSS; benchmarks per table;
> and zero cards containing "annualised", "1Y", "3Y", or a fund-manager name.

---

## Phase 3 — Extractor B: labelled prose sections

**Objective:** Extract the human-facing prose sections from rendered text.
**Refs:** PRD REQ-2, REQ-4; Arch §3.2 Extractor B, §3.3 producer B.
**Depends on:** Phase 2.

### Files
| File | Action |
|---|---|
| `ingest.py` | add `extract_prose()` + `split_section()` |
| `scripts/debug_prose.py` | create |

### Tasks

1. `extract_prose(slug, html) -> list[Chunk]`:
   - `BeautifulSoup(html, "lxml")`; **`decompose()`** `script`, `style`, `noscript`
     (critical — otherwise the `__NEXT_DATA__` blob becomes "text")
   - `soup.get_text("\n")`, drop lines `< MIN_CHUNK_CHARS`, collapse blank runs
2. Locate these **named anchors** and capture the text that follows, each emitted as
   `"{Section header}\n{body}"` so the header is inside the embedded text:
   `Minimum investments`, `Exit load`, `Exit Load`, `Tax implication`,
   `Investment Objective`, `About`, `Fund benchmark`, `Scheme Information Document(SID)`,
   `Registrar & Transfer Agent`, `Stamp duty`, and the glossary definitions for
   `Expense ratio`, `Exit load`, `Stamp duty`, `Tax`.
3. **`split_section(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)`** (REQ-4):
   - split at newline / sentence boundaries first, greedily pack up to **380 chars**
   - slide by **80 chars** on overflow
   - drop chunks `< 40 chars`
   - **never cut inside a `label: value` line**
4. **Exclusions**: nav chrome, footer, holdings tables, peer-comparison tables,
   fund-manager bios. Add a nav/footer deny-list of known strings
   (`Stocks`, `IPO`, `See All`, `Download the App`, `GROWW`, `Pricing`, `Media & Press`,
   `Careers`, `Trust & Safety`, `Investor Relations`, `© 2016-`, `Version:` …).
5. **Rendered risk badge**: regex `^\s*(Very High|High|Moderately High|Moderate|Low)\s*Risk\s*$`
   over the text → emit one `riskometer` card per scheme. **This is the authoritative
   riskometer value** (finding §0.2.4).
6. `producer="prose_section"`, `extracted_from="visible_text"`.

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/debug_prose.py
```

Must assert:
- a `minimum_investments` section exists for **all 5** schemes and mentions `Min. for SIP`
- a `riskometer` card exists for all 5 and says **"Very High Risk"**
- every prose chunk is **≤ 380 chars** (`char_len` max)
- `chunks.txt`-style overlap actually occurs (not required, but chunk count sane)
- **zero** chunks contain `₹` inside nav, no `@` e-mail, no `022 –` phone, no postal address
- ELSS page still yields a lock-in-related string (it appears in prose too)

### Definition of Done
- [ ] All 10 named anchors resolved
- [ ] Every prose chunk ≤ 380 chars, none < 40 chars
- [ ] `riskometer` = "Very High Risk" for all 5
- [ ] No nav/footer/holdings/peer/bio text
- [ ] No e-mail, phone, or postal address in any chunk

> **Agent prompt — Phase 3**
> In `ingest.py`, implement `extract_prose(slug, html) -> list[Chunk]` using
> BeautifulSoup+lxml. FIRST decompose script/style/noscript (otherwise __NEXT_DATA__ leaks
> in as text), then get_text("\n"), drop lines under 40 chars, collapse blank runs. Capture
> these labelled anchors, emitting each as "Header\nbody" so the header is part of the text:
> Minimum investments, Exit load, Exit Load, Tax implication, Investment Objective, About,
> Fund benchmark, Scheme Information Document(SID), Registrar & Transfer Agent, Stamp duty,
> plus glossary definitions for Expense ratio, Exit load, Stamp duty, Tax. Implement
> `split_section(text, size=380, overlap=80)`: split on newlines/sentence boundaries,
> greedily pack to 380 chars, slide 80 on overflow, drop <40, never cut inside a
> "label: value" line. Exclude nav/footer/holdings/peer-comparison/fund-manager-bio text
> via a deny-list (Stocks, IPO, See All, Download the App, GROWW, Pricing, Media & Press,
> Careers, Trust & Safety, Investor Relations, © 2016-, Version:). Additionally regex
> `^\s*(Very High|High|Moderately High|Moderate|Low)\s*Risk\s*$` over the rendered text and
> emit ONE authoritative `riskometer` card per scheme (expected "Very High Risk" on all 5).
> Set producer="prose_section", extracted_from="visible_text". Create
> scripts/debug_prose.py asserting all 5 schemes have a minimum_investments section, all 5
> have riskometer == "Very High Risk", every chunk char_len <= 380, and no chunk contains an
> e-mail, "022 –" phone, or postal address.

---

## Phase 4 — Chunk assembly, scrub, dumps, coverage report

**Objective:** Merge both extractors, scrub PII, write inspectable dumps, assert coverage.
**Refs:** PRD REQ-5, REQ-8, REQ-9, REQ-10; Arch §3.3, §3.4, §3.6; mitigates R1, R6.
**Depends on:** Phase 3.

### Files
| File | Action |
|---|---|
| `guardrails.py` | create — **only `scrub_pii()` + `detect_pii()`** |
| `ingest.py` | add `build_chunks()`, `write_dumps()`, `coverage_report()`, `run_ingest()` (no embedding yet) |

### Tasks

1. `guardrails.py`:
   - `detect_pii(text) -> PIIHit | None` with regexes for PAN
     (`[A-Z]{5}[0-9]{4}[A-Z]`), Aadhaar (`\b\d{4}\s?\d{4}\s?\d{4}\b`), account-like digit runs
     (≥9 digits), OTP (4–6 digit codes near "otp"), email, phone (`\+?\d[\d\s-]{8,}`).
   - `scrub_pii(text) -> str` replaces matches with `[redacted]`.
   - **Never** include the matched value in the returned object that could be logged.
2. `build_chunks(force_refresh=False) -> list[Chunk]`:
   - `load_pages()` → for each page, `extract_facts()` + `extract_prose()`
   - `text = scrub_pii(chunk.text)`
   - **drop** any chunk matching a performance pattern
     (`annualised`, `1Y annualised`, `returns and rankings`, `category average`,
      `rank (equity`, `absolute returns`)
   - `chunk_id = f"{slug}__{section}__{i:03d}"` (deterministic — NFR-4)
   - `char_len = len(text)`; `content_hash = sha1(text)[:10]`
   - `ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")`
3. `write_dumps(chunks)`:
   - `data/chunks.txt` — a header block (source list, counts, params) then **every chunk**
     delimited with its `chunk_id`, section, producer, char_len and `source_url`
   - `data/chunks.jsonl` — one JSON object per line
4. `coverage_report(chunks) -> dict` — a scheme × target-fact matrix for the 7 fact types:
   `expense_ratio`, `exit_load`, `minimum_investment`/`sip_minimum`, `lock_in_period`,
   `riskometer`, `benchmark`, `documents`. **Assert** all 35 cells are populated and
   `lock_in_period` is non-null **only** for ELSS. **Raise** on a gap (R1).

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python ingest.py
Get-Content data/chunks.txt -TotalCount 60
python -c "import json;print(sum(1 for _ in open('data/chunks.jsonl',encoding='utf-8')))"
Select-String -Path data/chunks.txt -Pattern "annualised|@|022 –|Rank \("   # expect no matches
```

**Expected:** ~150–200 chunks; coverage matrix complete; the `Select-String` returns
**nothing**.

### Definition of Done
- [ ] `data/chunks.txt` + `data/chunks.jsonl` written and human-readable
- [ ] Coverage matrix 5 schemes × 7 facts all populated
- [ ] `lock_in_period` present **only** for ELSS
- [ ] Zero return figures, zero PII/contact strings in the corpus
- [ ] No ingest yet touches the vector DB

> **Agent prompt — Phase 4**
> Create `guardrails.py` with `detect_pii(text)->PIIHit|None` (PAN [A-Z]{5}[0-9]{4}[A-Z],
> Aadhaar 12-digit spaced, account-like >=9 digit runs, OTP near the word "otp", email,
> phone) and `scrub_pii(text)->str` replacing matches with "[redacted]". Never store or
> return the raw matched value in anything that could be logged. In `ingest.py` add
> `build_chunks(force_refresh=False)` that loads pages, runs BOTH extract_facts and
> extract_prose, applies scrub_pii, then DROPS any chunk matching annualised / 1Y annualised
> / returns and rankings / category average / rank (equity / absolute returns. Set
> chunk_id = f"{slug}__{section}__{i:03d}", char_len, content_hash = sha1(text)[:10],
> ingested_at = UTC ISO. Add `write_dumps(chunks)` producing data/chunks.txt (header block
> + every chunk with chunk_id, section, producer, char_len, source_url) and data/chunks.jsonl.
> Add `coverage_report(chunks)` building a scheme x fact matrix for expense_ratio, exit_load,
> minimum_investment, lock_in_period, riskometer, benchmark, documents; RAISE if any of the
> 35 cells is empty or if lock_in_period is non-null for any scheme other than ELSS. Wire
> run_ingest() to do load->extract->scrub->dump->report but do NOT embed yet.

---

## Phase 5 — Embed + Store (ChromaDB)

**Objective:** Embed chunks with MiniLM and persist to ChromaDB. **Run once.**
**Refs:** PRD REQ-6, REQ-7; Arch §3.5; NFR-1, NFR-3, NFR-4.
**Depends on:** Phase 4.

### Files
| File | Action |
|---|---|
| `ingest.py` | add `embed_and_store()`; wire into `run_ingest()` |

### Tasks

1. Lazy singleton for `SentenceTransformer(config.EMBED_MODEL)` — loading is slow, and
   Phase 7+ must reuse the identical model instance/config.
2. `embed_and_store(chunks)`:
   ```python
   vectors = model.encode([c.text for c in chunks],
                          normalize_embeddings=True, show_progress_bar=True)
   client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
   col = client.get_or_create_collection(config.COLLECTION_NAME,
                                         metadata={"hnsw:space": "cosine"})
   col.upsert(ids=[c.chunk_id for c in chunks],
              documents=[c.text for c in chunks],
              embeddings=[v.tolist() for v in vectors],
              metadatas=[c.to_metadata() for c in chunks])
   ```
3. Print: chunk count, embedding dim (**must be 384**), collection count after upsert.
4. Idempotency: running twice must leave `col.count()` unchanged (`upsert`, not `add`).
5. Keep `__main__` as `argparse` with `--refresh` and `--reembed`.

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python ingest.py                       # embeds, prints dim 384
python ingest.py                       # again -> count identical (idempotent)
python -c "import chromadb;c=chromadb.PersistentClient(path='data/chroma').get_or_create_collection('hdfc_mf_faqs');print(c.count());print(c.peek()['metadatas'][0])"
```

**Expected:** dim **384**; identical count on re-run; first metadata dict contains
`source_url`, `scheme_slug`, `section`.

### Definition of Done
- [x] dim == 384
- [x] `data/chroma/` on disk; re-run is idempotent
- [x] Metadata round-trips from Chroma
- [x] Embed stage needs **no** API key

> **Status: BUILT & VERIFIED.** `ingest.py::_model()` (lazy singleton),
> `drop_collection()`, `embed_and_store()`; `--reembed` wired. Verified by
> `scripts/debug_store.py` (9 assertions: dim 384, count == 130, metadata
> round-trip, idempotent re-store, on-disk persistence, survives a fresh client).
> Full suite `python scripts/verify_all.py` → **6/6 PASS**.
> Extra beyond spec: `drop_collection()` exists because `upsert` keys on
> `chunk_id`, so after a model/chunking change stale vectors would survive and
> silently corrupt retrieval — hence `--reembed`.

> **Agent prompt — Phase 5**
> In `ingest.py` add `embed_and_store(chunks)`. Use a module-level lazy singleton for
> `SentenceTransformer(config.EMBED_MODEL)`. Encode with
> `normalize_embeddings=True`, then
> `chromadb.PersistentClient(path=str(config.CHROMA_DIR)).get_or_create_collection(config.COLLECTION_NAME, metadata={"hnsw:space":"cosine"})`
> and call `collection.upsert(ids=, documents=, embeddings=, metadatas=)` using each chunk's
> deterministic chunk_id (NOT add — must be idempotent) and its metadata dict. Print chunk
> count, embedding dimension (must be 384), and collection count after upsert. Extend the
> __main__ argparse with --refresh and --reembed. Do not write any query code yet.

---

## Phase 6 — Guardrails (online)

**Objective:** Classify and refuse advice / performance / PII **before** retrieval.
**Refs:** PRD REQ-18, REQ-19, REQ-20, REQ-21; Arch §4.1, §5; mitigates R4, R5, R6.
**Depends on:** Phase 4 (needs `scrub_pii`); independent of Phase 5.

### Files
| File | Action |
|---|---|
| `guardrails.py` | add `is_advice_request()`, `is_performance_request()`, refusal copy builders |

### Tasks

1. `is_advice_request(text) -> bool` — compile `config.REFUSAL_PATTERNS` as one
   case-insensitive regex; add extra patterns for "which is better", "worth it",
   "should i buy/sell/exit/switch", "for me", "my portfolio", "allocate", "plan my".
2. `is_performance_request(text) -> bool` — "returns", "how much will it grow/give",
   "best performing", "top performing", "outperform", "% gain", "cagr", "since inception
   return", "compare returns".
3. Refusal copy builders returning `(message, links)`:
   - `advice_refusal()` — polite, states the facts-only boundary, **one** relevant
     educational link from `config.EDUCATIONAL_LINKS` (SEBI / AMFI / HDFC AMC FAQ)
   - `performance_refusal()` — states the assistant does not provide or compare returns;
     points to the **official factsheet/SID**
   - `pii_refusal()` — states personal data is not accepted; **must not echo the value**
4. Keep each refusal **≤ 3 sentences** (REQ-16 applies to refusals too).

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python -c "from guardrails import *; [print(repr(q), is_advice_request(q)) for q in ['Should I buy HDFC Large Cap?','best mutual fund for me','which fund should I choose','is it a good scheme','what is the expense ratio of HDFC ELSS']]"
```

**Expected:** first four `True`; the expense-ratio question **`False`**.

### Definition of Done
- [x] All 4 advice phrasings `True`, factual question `False`
- [x] `is_performance_request("best performing fund")` → `True`
- [x] `pii_refusal()` output contains **no** substring of the input
- [x] Every refusal ≤ 3 sentences and carries an educational link

> **Status: BUILT & VERIFIED.** `is_advice_request()`, `is_performance_request()`,
> `advice_refusal()`, `performance_refusal()`, `pii_refusal()`, plus a
> `refusal_for()` router that PII-checks first. Verified by
> `scripts/debug_online_guardrails.py` — 11 advice phrasings `True`, 20 factual
> questions `False` on both classifiers, 10 performance phrasings `True`, 4
> no-echo PII cases, all 3 refusals 2 sentences with a well-formed link, and
> PII-precedence-over-advice routing. Full suite **8/8 PASS**.
>
> Two corrections to the plan, both caught by the factual-question assertions:
> 1. A bare `\bportfolio\b` advice pattern refused *"what is the portfolio
>    turnover ratio of X?"* — a disclosed SEBI metric we do answer. Narrowed to
>    the personalised senses (`my/our/your portfolio`, rebalance, allocation,
>    diversification).
> 2. Added `_ALLOW_EXCEPTIONS` so riskometer/risk-rating questions are never
>    refused, and kept 20 factual phrasings as regression cases.

> **Agent prompt — Phase 6**
> Extend `guardrails.py` (keep detect_pii/scrub_pii). Add `is_advice_request(text)->bool`
> compiling config.REFUSAL_PATTERNS case-insensitively plus patterns for "which is better",
> "worth it", "should i buy/sell/exit/switch", "for me", "my portfolio", "allocate",
> "plan my". Add `is_performance_request(text)->bool` for "returns", "how much will it
> grow", "best performing", "outperform", "% gain", "cagr", "compare returns". Add
> `advice_refusal()`, `performance_refusal()`, `pii_refusal()` each returning
> (message, links) where message is at most 3 sentences: advice_refusal politely states the
> facts-only boundary and includes ONE relevant educational link from
> config.EDUCATIONAL_LINKS (SEBI/AMFI/HDFC AMC FAQ); performance_refusal states the
> assistant does not provide or compare returns and points to the official factsheet/SID;
> pii_refusal states personal data is not accepted and MUST NOT echo any part of the input.
> Verify that "Should I buy HDFC Large Cap?", "best mutual fund for me", "which fund should
> I choose", "is it a good scheme" all return True while "what is the expense ratio of HDFC
> ELSS" returns False.

---

## Phase 7 — Retrieval

**Objective:** Embed the question, fetch top-5 chunks, apply the similarity floor.
**Refs:** PRD REQ-11, REQ-12, REQ-13; Arch §4.2; mitigates R3.
**Depends on:** Phase 5.

### Files
| File | Action |
|---|---|
| `rag.py` | create — `SourceRef`, `Hit`, `RAGEngine.__init__`, `retrieve()` |

### Tasks

1. `RAGEngine.__init__`:
   - `SentenceTransformer(config.EMBED_MODEL)` — **must be the same model as ingestion**
   - `chromadb.PersistentClient(path=config.CHROMA_DIR).get_or_create_collection(config.COLLECTION_NAME, metadata={"hnsw:space":"cosine"})`
   - `self.groq_client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None`
   - **Never** raise at construction if the key is missing (NFR-5)
2. `retrieve(question, top_k=config.TOP_K) -> list[Hit]`:
   - encode with `normalize_embeddings=True`
   - `col.query(query_embeddings=[q], n_results=top_k, include=["documents","metadatas","distances"])`
   - **convert distance → similarity** correctly for the configured space
   - filter `similarity >= config.MIN_SIMILARITY`
   - build `Hit(text, score, meta)` with `source_url`, `scheme_slug`, `section`, `as_of`
3. **Empty result is valid** — return `[]`; never pad with the top hit regardless of score.
4. Log the top scores so Phase 8 can tune `MIN_SIMILARITY` empirically.

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python -c "from rag import RAGEngine; e=RAGEngine(); [print(round(h.score,3), h.meta['scheme_slug'], h.meta['section']) for q in ['expense ratio of HDFC ELSS Tax Saver','lock-in period ELSS','minimum SIP HDFC Large Cap','which crypto should I buy'] for h in e.retrieve(q)]"
```

**Expected:** the first three return relevant hits with the correct scheme; the crypto
question returns **zero** hits above the floor.

### Definition of Done
- [x] Same model instance/config as ingestion
- [x] Top-5 with similarity ≥ **`MIN_SIMILARITY`** (calibrated to 0.54, see below)
- [x] Off-topic question → `[]`
- [x] Constructing `RAGEngine()` with no API key does **not** raise
- [x] **Observed score range recorded** — in-domain top-1 **0.628–0.928**,
      off-topic best-nearest **0.000–0.421**. Floor **0.54**. To be carried into
      the README's Known Limits (Phase 11).

> **Status: BUILT & VERIFIED.** `rag.py` with `Hit`, `SourceRef`,
> `RetrievalResult`, `RAGEngine`, `_distance_to_similarity`. Verified by
> `scripts/debug_retrieval.py` (7/7 relevant queries hit the correct
> scheme+section; 8 off-topic queries return `[]`; cosine conversion exact at
> d=0/0.5/1.0 and clamped to [0,1]; every hit carries `source_url`/`section`/
> `scheme_slug`; `sources()` de-duplicates 5 hits to 3 citations; `ask()` routes
> all 4 refusal cases correctly). Full suite **8/8 PASS**.

> **IMPORTANT — the provisional `MIN_SIMILARITY = 0.18` was wrong and is now
> calibrated to 0.54.** 0.18 was a placeholder that was never validated against
> negatives. Running `scripts/calibrate_floor.py` over 32 in-domain and 20
> off-topic queries showed MiniLM cosine similarity between short *unrelated
> English sentences* sits around 0.2–0.3, so 0.18 admitted **14 of 20**
> off-topic queries — weather, Tokyo's population, biryani recipes — as if they
> were relevant. The two clusters do not overlap (gap 0.239 wide), so any floor
> in (0.421, 0.660] is correct; 0.54 is the midpoint.
> Re-run `python scripts/calibrate_floor.py` after any corpus or model change.
> The hardcoded `0.18` in task 2 above and in Phase 7's DoD is superseded.

> **Agent prompt — Phase 7**
> Create `rag.py`. Define dataclasses `SourceRef(title,url,scheme_slug,section,score,as_of)`
> and `Hit(text,score,meta)`. `RAGEngine.__init__` loads
> `SentenceTransformer(config.EMBED_MODEL)` — the SAME model used at ingestion — plus
> `chromadb.PersistentClient(path=str(config.CHROMA_DIR)).get_or_create_collection(config.COLLECTION_NAME, metadata={"hnsw:space":"cosine"})`,
> and creates a Groq client ONLY if config.GROQ_API_KEY is non-empty (never raise when it
> is absent). Implement `retrieve(question, top_k=config.TOP_K) -> list[Hit]`: encode with
> normalize_embeddings=True, query with include=["documents","metadatas","distances"],
> convert distance to similarity correctly for the configured space, drop anything below
> config.MIN_SIMILARITY, and return [] when nothing qualifies — never pad with a low-scoring
> hit. Print top scores. Verify: "expense ratio of HDFC ELSS Tax Saver", "lock-in period
> ELSS" and "minimum SIP HDFC Large Cap" return correct-scheme hits, while "which crypto
> should I buy" returns zero hits. Report the observed score range so MIN_SIMILARITY can be
> tuned.

---

## Phase 8 — Generation, citations, refusal routing

**Objective:** Produce the ≤3-sentence answer with exactly one citation; wire refusals.
**Refs:** PRD REQ-14..17, REQ-21; Arch §4.3; mitigates R3, R4.
**Depends on:** Phases 6 and 7.

### Files
| File | Action |
|---|---|
| `rag.py` | add `Answer` dataclass, prompt builders, `answer()` |

### Tasks

1. `Answer(text, sources, refused, refusal_kind, as_of, chunks_used)`.
2. `answer(question) -> Answer` — strict order:
   1. `detect_pii` → `pii_refusal()` → return (**never echo input**)
   2. `is_advice_request` → `advice_refusal()` + edu link
   3. `is_performance_request` → `performance_refusal()` + factsheet link
   4. `retrieve()`; if `[]` → honest "not in the collected sources" + official link,
      `refusal_kind="no_context"`
   5. else generate
3. **System prompt contract** (REQ-17, REQ-21) — state all six rules: only the provided
   context; facts only, no advice; if unsupported say so and don't use prior knowledge;
   **≤ 3 sentences**; exactly one source URL; never output or request personal data.
4. **Context assembly**: `[1] scheme — category — section\n{text}\nURL: {source_url}`
   so the model can cite from structure.
5. **Citation from metadata (P1)**: build `sources` from `hit.meta["source_url"]` in
   Python. **Never** parse a URL out of the model's prose. Dedupe to one primary link.
6. **Append the as-of line** outside the LLM text: `Last updated from sources: {as_of}`
   (`nav_date` → `30-Sep-2026`).
7. **Extractive fallback (NFR-5)**: if `self.groq_client is None` or the call raises
   (after one retry), answer **from the top chunk verbatim** with its citation, and say
   the answer is quoted directly from the source.
8. Enforce ≤3 sentences on the final text; truncate defensively with an ellipsis.
9. Optional `python rag.py "<question>"` CLI for headless eval/demo.

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python rag.py "What is the expense ratio of HDFC ELSS Tax Saver?"
python rag.py "What is the exit load of HDFC Flexi Cap?"
python rag.py "Should I buy HDFC Large Cap?"
python rag.py "My PAN is ABCDE1234F, send my statement"
python rag.py "Which fund gives the best returns?"
```

**Expected:** ELSS → **1.21 %**; Flexi Cap → **1 % within 1 year**; advice → refusal + edu
link; PAN → refusal **without** `ABCDE1234F` anywhere in the output; returns → deflection,
no return figure.

### Definition of Done
- [ ] AT-1, AT-2 answers numerically correct with a citation
- [ ] AT-6, AT-7, AT-8 refusals correct; PAN never echoed
- [ ] Every answer ends with `Last updated from sources:`
- [ ] No API key → still answers via extractive fallback
- [ ] Answers ≤ 3 sentences

> **Agent prompt — Phase 8**
> Extend `rag.py`. Add `Answer(text, sources, refused, refusal_kind, as_of, chunks_used)`.
> Implement `answer(question) -> Answer` in this exact order: (1) guardrails.detect_pii →
> pii_refusal(), returning without echoing any part of the input; (2) is_advice_request →
> advice_refusal() with an educational link; (3) is_performance_request →
> performance_refusal() pointing at the official factsheet; (4) retrieve(); if empty return
> an honest "not in the collected sources" answer with refusal_kind="no_context" and an
> official link; (5) otherwise generate. The system prompt must state: answer ONLY from the
> provided context chunks; facts only, no advice or recommendation; if not fully supported,
> say so and do NOT use prior knowledge; maximum 3 sentences; include exactly one source
> URL; never output or request personal data. Assemble context as
> "[n] scheme - category - section\ntext\nURL: source_url". CRITICAL: build the citation
> SourceRef list from hit metadata in Python — never parse a URL out of the model's prose,
> because the model must not be able to invent a citation. Append
> "Last updated from sources: {as_of}" outside the LLM output. If no Groq key or the call
> fails after one retry, fall back to quoting the top chunk verbatim with its citation.
> Defensively enforce the 3-sentence cap. Add a `python rag.py "question"` CLI.

---

## Phase 9 — Streamlit UI

**Objective:** The tiny UI from the brief.
**Refs:** PRD REQ-22..25; Arch §4.4.
**Depends on:** Phase 8.

### Files
| File | Action |
|---|---|
| `app.py` | create |
| `requirements.txt` | ensure `streamlit` listed |

### Tasks

1. `st.set_page_config(page_title=…, layout="centered")`.
2. `st.title` welcome line naming the assistant as **facts-only**.
3. **Three example questions** as clickable buttons — use the three AT queries:
   - "What is the expense ratio of HDFC ELSS Tax Saver?"
   - "Is there a lock-in period on the HDFC ELSS Tax Saver Fund?"
   - "What is the exit load and minimum SIP for HDFC Flexi Cap?"
4. Render `config.DISCLAIMER` **prominently and persistently**:
   `st.warning("Facts-only. No investment advice.")` (REQ-23).
5. `st.chat_input`; render each answer with `st.markdown`, then the citation via
   `st.link_button` / markdown link (**one clear link**), then the as-of line.
6. Show the **in-scope schemes** panel (the 5 names + categories from `config.SOURCES`).
7. Show which chunks were used behind an `st.expander("Sources used")` — transparency
   (PRD "Clarity & transparency").
8. Never render PII: if the user typed PII, show the refusal only.
9. Cache the `RAGEngine` with `@st.cache_resource` so the model loads once.

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
streamlit run app.py
```

Click through all 3 examples; confirm citation links open the correct Groww URLs; confirm
the advice refusal renders its educational link.

### Definition of Done
- [ ] Welcome line + 3 working example questions
- [ ] Disclaimer visible without scrolling
- [ ] Every factual answer shows exactly one working source link
- [ ] `Last updated from sources:` line present
- [ ] Engine loaded once (`@st.cache_resource`)

> **Agent prompt — Phase 9**
> Create `app.py` (Streamlit). Centered layout; title states it is a facts-only assistant;
> show config.DISCLAIMER via st.warning("Facts-only. No investment advice.") permanently;
> three clickable example questions: "What is the expense ratio of HDFC ELSS Tax Saver?",
> "Is there a lock-in period on the HDFC ELSS Tax Saver Fund?", "What is the exit load and
> minimum SIP for HDFC Flexi Cap?". Use st.chat_input. For each answer render the text, then
> EXACTLY ONE clickable citation link from Answer.sources, then the "Last updated from
> sources:" line. Add an st.expander("Sources used") listing chunk ids/sections/scores, and
> a panel listing the 5 in-scope schemes from config.SOURCES. Build the RAGEngine with
> @st.cache_resource so the embedding model loads once. If the question contained PII, show
> only the refusal and never echo the input.

---

## Phase 10 — Acceptance tests

**Objective:** Automated proof of AT-1 … AT-12.
**Refs:** PRD §11; Arch §11.
**Depends on:** Phase 9.

### Files
| File | Action |
|---|---|
| `tests/test_acceptance.py` | create |

### Tasks

1. `pytest` suite, **offline** where possible: build/require the corpus once in a session
   fixture (`scope="session"`).
2. Implement AT-1..AT-12 as tests:

| Test | Assertion |
|---|---|
| AT-1 | ELSS expense ratio answer contains `1.21` and the ELSS URL |
| AT-2 | Flexi Cap exit load contains `1` and `1 year` and the Flexi URL |
| AT-3 | ELSS lock-in contains `3 year` and the ELSS URL |
| AT-4 | "What is the minimum SIP?" → per-scheme values **or** a clarifying question; must not invent one scheme |
| AT-5 | Small Cap benchmark contains `BSE 250 SmallCap` and the Small Cap URL |
| AT-6 | "Should I buy HDFC Large Cap?" → `refused`, `refusal_kind="advice"`, a link, no recommendation verb |
| AT-7 | "best returns" → `refused`, `refusal_kind="performance"`, **no** return figure |
| AT-8 | PAN input → `refused`, and the PAN string is absent from `answer.text` |
| AT-9 | "How do I download the SID?" → mentions SID / HDFC AMC and cites a source |
| AT-10 | corpus coverage: all 5 schemes × 7 facts present; `lock_in_period` only for ELSS |
| AT-11 | every factual answer ≤ 3 sentences and ends with `Last updated from sources:` |
| AT-12 | `data/chunks.txt` contains no PAN/e-mail/phone and no return figures |
3. AT-1/2/3/5 need an API key — mark them `@pytest.mark.skipif(not config.GROQ_API_KEY, ...)`
   so the suite passes offline via the extractive fallback. **Do not silently skip in the
   final report** — record which ran.
4. `tests/__init__.py` if needed.

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m pytest tests/ -v
```

### Definition of Done
- [ ] All 12 tests present
- [ ] Suite green offline; key-dependent tests skip cleanly and are reported
- [ ] AT-8 asserts the PAN never appears in output

> **Agent prompt — Phase 10**
> Create `tests/test_acceptance.py` implementing AT-1..AT-12 from PRD §11 as pytest tests.
> Use a session-scoped fixture for the RAGEngine. Assertions: AT-1 ELSS expense ratio
> answer contains "1.21" and the ELSS source URL; AT-2 Flexi Cap exit load contains "1" and
> "1 year"; AT-3 ELSS lock-in contains "3 year"; AT-4 "What is the minimum SIP?" returns
> per-scheme values or asks for clarification and never invents a single scheme; AT-5 Small
> Cap benchmark contains "BSE 250 SmallCap"; AT-6 "Should I buy HDFC Large Cap?" has
> refused=True and refusal_kind="advice" with a link and no recommendation verb; AT-7 a
> best-returns question has refused=True and refusal_kind="performance" with no return
> figure; AT-8 a PAN input is refused AND the PAN string is absent from answer.text; AT-9
> "How do I download the SID?" mentions SID/HDFC AMC with a citation; AT-10 all 5 schemes
> x 7 target facts are present in the corpus and lock_in_period exists ONLY for ELSS; AT-11
> every factual answer is at most 3 sentences and ends with "Last updated from sources:";
> AT-12 data/chunks.txt contains no PAN, e-mail, phone, or return figures. Mark the
> API-key-dependent tests with skipif when config.GROQ_API_KEY is empty so the suite passes
> offline.

---

## Phase 11 — Deliverables documentation

**Objective:** Complete D2–D7 so the submission is reviewable without running anything.
**Refs:** PRD §12.
**Depends on:** Phase 10.

### Files
| File | Action |
|---|---|
| `deliverables/sources.csv` | create |
| `deliverables/sources.md` | create |
| `deliverables/sample_qa.md` | create (5–10 Q&A, real captured output) |
| `deliverables/disclaimer.md` | create |
| `README.md` | create |
| `.gitignore` | final check |

### Tasks

1. **`sources.csv`** — headers `n,amc,scheme_name,category,plan,url,ingested_at,as_of,note`.
   5 rows. **`sources.md`** — same as a table plus a one-line note that these are the only
   sources and all are public Groww scheme pages.
2. **`sample_qa.md`** — **paste real captured output** from `python rag.py "…"`, 8–10 rows:
   cover AT-1, AT-2, AT-3, AT-4, AT-5, AT-6, AT-7, AT-9. Columns:
   `# | Question | Assistant answer | Source link | Notes`. Include at least one refusal.
3. **`disclaimer.md`** — the exact UI string from `config.DISCLAIMER` plus the short form
   actually rendered (`Facts-only. No investment advice.`).
4. **`README.md`** — must contain:
   - **What it is** + the one-line pipeline diagram
   - **Scope:** AMC HDFC + the 5 schemes (table) + "facts only, no advice"
   - **Setup:** venv, `pip install -r requirements.txt`, copy `.env.example` → `.env`,
     add `GROQ_API_KEY`, `python ingest.py`, `streamlit run app.py`, `python rag.py "…"`
   - **Architecture:** pointer to `architecture.md` + `chunking_strategy.md`
   - **Chunking:** 380 / 80 / min 40, two producers, metadata list
   - **Known limits (mandatory):**
     1. Single AMC, 5 Direct–Growth schemes; no Regular-plan figures
     2. **Riskometer conflict** — rendered badge "Very High Risk" vs JSON
        `nfo_risk` "Moderately High"; badge used, needs confirmation against HDFC's
        official disclosure (PRD Q3)
     3. **Fund manager excluded** — JSON and page prose disagree; not answered
     4. **Inception dates** — 01-Jan-2013 (plan) vs 10 Dec 1999 (scheme); both stored, labelled
     5. **AUM** — the page's About prose repeats AMC-level AUM; scheme-level JSON value used
     6. **No performance data at all** — by design (PRD P3/R5)
     7. Facts are as-published at ingest; `as_of` shown; re-run `python ingest.py --refresh`
     8. **Scraper fragility** — Groww is client-rendered; a markup change breaks extraction,
        and ingest fails loudly rather than answering from a thin corpus (R1)
     9. English only; no multilingual handling
     10. Sources are Groww, not HDFC's own site — for statutory documents use the AMC/SID
   - **The chosen `MIN_SIMILARITY`** from Phase 7 and why
   - **Guardrails** summary + refusal test set
5. Final `.gitignore` check: `.env` and `data/chroma/` ignored; `data/raw/` and
   `data/chunks.txt` **tracked**.
6. Optional: record a ≤3-min demo video **only if** hosting isn't possible (D9).

### Verification

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m pytest tests/ -q
git status --short          # .env and data/chroma/ MUST NOT appear
Select-String -Path README.md -Pattern "Known limits"
```

### Definition of Done
- [ ] D2–D7 all present
- [ ] `sample_qa.md` contains **real** captured answers, not invented ones
- [ ] README documents all 10 known limits
- [ ] `git status` shows no `.env` and no `data/chroma/`

> **Agent prompt — Phase 11**
> Create deliverables/sources.csv (headers n,amc,scheme_name,category,plan,url,ingested_at,
> as_of,note with the 5 Groww URLs) and deliverables/sources.md. Create
> deliverables/sample_qa.md by ACTUALLY RUNNING `python rag.py "<question>"` for 8-10
> questions covering AT-1..AT-7 and AT-9, and pasting the real captured output verbatim in
> a table (columns: #, Question, Assistant answer, Source link, Notes) — include at least one
> advice refusal and one performance deflection; never invent answers. Create
> deliverables/disclaimer.md containing the exact config.DISCLAIMER string and the short
> form "Facts-only. No investment advice.". Write README.md with: what it is + pipeline
> diagram; scope (HDFC AMC, the 5 Direct-Growth schemes); setup steps (venv, pip install,
> .env, GROQ_API_KEY, python ingest.py, streamlit run app.py, python rag.py "q");
> architecture and chunking pointers; the 380/80/40 parameters; a MANDATORY "Known limits"
> section listing all 10 documented limits (single AMC/5 Direct schemes; the riskometer
> conflict Very High Risk vs Moderately High; fund manager excluded due to source
> disagreement; the two inception dates; AMC-level vs scheme-level AUM; no performance data
> by design; staleness + --refresh; Groww client-rendered scraper fragility; English only;
> sources are Groww not HDFC's own site); the chosen MIN_SIMILARITY and its rationale; and a
> guardrails summary. Finally confirm `git status --short` lists neither `.env` nor
> `data/chroma/`, while `data/raw/` and `data/chunks.txt` remain tracked.

---

## 12. Phase Dependency Graph

```
Phase 0  Scaffolding ──┬──────────────────────────────────────────────┐
                       │                                              │
Phase 1  Load ──────────┤                                              │
                       ▼                                              │
Phase 2  Extractor A ───┤  (finds __NEXT_DATA__ — the critical path)  │
                       ▼                                              │
Phase 3  Extractor B ───┤                                              │
                       ▼                                              │
Phase 4  Chunk + scrub ─┤                                              │
                       ├──────────────┐                               │
                       ▼              ▼                               │
Phase 5  Embed+Store    Phase 6 Guardrails                            │
                       │              │                               │
                       └──────┬───────┘                               │
                              ▼                                       │
                       Phase 7  Retrieve ──────────────────────────────┤
                              │                                       │
                              ▼                                       │
                       Phase 8  Generate + Cite                       │
                              │                                       │
                              ▼                                       │
                       Phase 9  Streamlit UI ─────────────────────────┤
                              │                                       │
                              ▼                                       │
                       Phase 10  Acceptance tests ────────────────────┤
                              │                                       │
                              ▼                                       ▼
                       Phase 11  Deliverables docs ───────────────────┘
```

**Critical path:** `2 → 3 → 4 → 5 → 7 → 8 → 9 → 10 → 11`.
Phase 6 can run in parallel with Phase 5.

---

## 13. Risk Register for the Build (agent-facing)

| # | Risk | Symptom you'll see | Do this |
|---|---|---|---|
| B1 | `__NEXT_DATA__` path wrong | `KeyError: 'mfServerSideData'` | Re-run `scripts/explore_json.py` to re-derive the path; **never** fall back to guessing |
| B2 | `script` tags not decomposed | Prose chunks full of JS | Must `decompose()` before `get_text()` |
| B3 | `lock_in` compared as a string | ELSS lock-in missing | It's a **stringified dict** — `ast.literal_eval` first |
| B4 | Return figures leak into the corpus | "annualised" in `chunks.txt` | Tighten the exclusion regex in `build_chunks` |
| B5 | Console `UnicodeEncodeError` on `₹` | Traceback on print | `$env:PYTHONIOENCODING='utf-8'` |
| B6 | Different embedder at query time | All scores ~0, garbage retrieval | Must use `config.EMBED_MODEL` on both sides |
| B7 | `add()` instead of `upsert()` | Chunk count doubles each ingest | Use `upsert` with deterministic ids |
| B8 | Model invents a citation | URL not matching any source | Attach citations from metadata only |
| B9 | PAN echoed in the refusal | Test AT-8 fails | Refusal must never interpolate the input |
| B10 | Floor too high → nothing retrieved | Empty answers on valid questions | Tune from Phase 7 observed scores; document the final value |
| B11 | Missing API key crashes the app | App won't start | NFR-5 extractive fallback — never raise in `__init__` |
| B12 | `chroma` distance treated as similarity | Ranking inverted | Verify direction with one known query |

---

## 14. Definition of Done — Milestone Complete

- [ ] Phases 0–11 each met their own Definition of Done
- [ ] `python -m pytest tests/ -v` green (with key-dependent tests honestly reported)
- [ ] `streamlit run app.py` serves the UI: welcome line, 3 examples, disclaimer
- [ ] AT-1 … AT-12 all pass or are explicitly documented as skipped-for-key
- [ ] Every factual answer: ≤3 sentences, 1 citation, `Last updated from sources:`
- [ ] Every advice/performance/PII question: polite refusal + relevant link, no advice
- [ ] `git status` shows no `.env`, no `data/chroma/`
- [ ] D1–D9 all delivered (D1 prototype, D2 sources, D3 README, D4 sample Q&A,
      D5 disclaimer, D6 chunking strategy, D7 chunk dump, D8 PRD, D9 demo video if unhosted)

---

## 15. Build log — corrections made while executing Phases 0–5

The corpus is built and verified: **130 chunks** (80 `fact_card` + 50 `prose_section`)
from 5 pages, all 35 coverage cells populated, 0 PII, 0 performance figures,
index persisted at `data/chroma/` with 384-dim vectors.

Executing the phases surfaced eight places where the plan as written was either
wrong or self-contradictory. Each correction below is now in the **code**, and
this section records why so a reviewer is not confused by a spec/code mismatch.

### 15.1 Corrections to the written plan

| # | Plan said | Built instead | Why |
|---|---|---|---|
| 1 | Phase 4 task 4: "assert all 35 cells populated **and** `lock_in_period` non-null **only** for ELSS" | `lock_in_period` cards exist for **all 5**; 4 state an explicit negative, only ELSS states a duration | The plan was self-contradictory. Emitting only ELSS means answering "is there a lock-in on HDFC Large Cap?" with "not in sources" when the true answer is **no**. An explicit negative *is* the fact. `coverage_report()` now asserts all 5 present **and** exactly one real duration. |
| 2 | Ban `annualised` as a performance term | Ban only return *contexts*: `annualised return`, `\d+Y annualised`, `returns and rankings`, … | Portfolio turnover ratio is a disclosed **non-performance** metric that legitimately reads "(annualised, as published)". A blanket ban silently deleted a real disclosed fact. |
| 3 | Phase 3 anchor list includes the `About` block | `About` **excluded** from prose extraction | The About prose carries the two facts we already know are wrong: it repeats AMC-level AUM ₹9,86,237 Cr on every scheme page, and names a fund manager that contradicts the JSON field. Ingesting it wholesale would re-inject both known conflicts. Every fact it uniquely holds (objective, launch date, NAV, AUM, risk, min SIP, exit load) is already covered from the reliable JSON path. |
| 4 | One `documents` fact card per scheme | Three: `documents`, `documents_statements`, `documents_amc_page` | Combined they ran to **527 chars**, past the 420 ceiling. Worse, three distinct facts in one embedding blurs all three — a query about statements would retrieve a blob dominated by the SID URL. |
| 5 | `MIN_CHUNK_CHARS = 40` applied while splitting source lines | New `config.MIN_LINE_CHARS = 2`; the 40-char floor applies at **chunk** level only | Applying 40 chars to *lines* discarded exactly the anchors the prose extractor needs — `Min. for SIP` (12) and the badge `Very High Risk` (14). This silently produced **0 prose chunks** before it was caught. |
| 6 | `split_section` keeps an over-long single line whole | `_hard_wrap()` wraps it on a sentence, then a word boundary, then a hard cut | Keeping a 527-char line whole breaks the size ceiling. Truncating would lose the fact (exit-load clauses are long). Wrapping loses nothing — asserted by a no-content-loss test. |
| 7 | Overlap carry takes trailing lines until the budget is met | Carry is **capped** so carried text + incoming line still fits `size` | Without the cap, carrying one 271-char wrapped sentence rebuilt a 470-char chunk — silently violating the limit while still "applying overlap". |
| 8 | `nfo_risk` in the Phase 2 whitelist | **Excluded** from the corpus; surfaced in `coverage_report()["conflicts"]` instead | The rendered badge says `Very High`, the JSON says `Moderately High`. Emitting both puts two contradictory numbers in a facts-only corpus. Same precedent as `fund_manager`. The conflict stays *visible* to a reviewer without being *retrievable*. |

### 15.2 Bugs found and fixed during verification

| Symptom | Root cause | Fix |
|---|---|---|
| `AttributeError: 'NoneType' has no attribute 'group'` on the risk badge | `re.fullmatch()` returns `None` for non-matching lines; `map()` yielded `None`s straight into `.group(1)` | Filter out `None` in the generator |
| 0 prose chunks | #5 and: deny-list wrongly contained content labels (`min. for sip`) **and** the stop-anchors (`understand terms`), so `_window()` searched a filtered list and found no boundary | Locate anchors/stops in the **raw** lines, apply the deny-list to the collected body afterwards |
| `expense_ratio_definition` missing | Glossary lookup returned the *first* `Expense ratio` occurrence — a stat tile whose value is `1.03%` — and the 18-char result was dropped as under-minimum | `_definition_after()` scans all occurrences and takes the first following line that *looks like a sentence* (long + sentence-terminated) |
| `stamp_duty_definition` missing | Its definition is 69 chars, below the 80-char threshold used for the above | Sentence-shape test replaces a length cutoff; a threshold alone is brittle |
| 13-digit account number classified as `phone` | The permissive phone regex matched before `account_number` | Reorder: unbroken 9–18 digit run = account number, digit groups broken by separators = phone |
| `+91 98765 43210` classified as `None` | Tightened phone regex demanded a separator after *every* digit | With `account_number` checked first, phone can be permissive again |
| Scheme-level AUM redacted from 5 chunks | A money/AUM scrub pattern added to `_CONTACT_PATTERNS` was destroying the **legitimate** scheme-level AUM (`39,933.37 crore`) | Removed it. AMC-level AUM is removed *structurally* by the prose deny-list, which is the correct mechanism. **Redaction is for PII only.** |
| One prose chunk at 391 chars | Section header is prepended *after* packing, so 380 + header > 380 | `budget = CHUNK_HARD_LIMIT - len(anchor) - 1`, reserving room before packing |

### 15.3 Reusable verification entry point

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/verify_all.py     # runs every phase suite + a corpus audit; exits non-zero on failure
```

Suites: `debug_config.py` (Phase 0), `debug_facts.py` (2), `debug_prose.py` (3),
`debug_guardrails.py` (4), `debug_store.py` (5), `debug_online_guardrails.py` (6),
`debug_retrieval.py` (7), `stress_terse_queries.py` (7b), plus a direct audit of
`data/chunks.txt` for the 8 banned-content classes. Current result: **9/9 PASS**.

Supporting scripts: `scripts/probe_anchors.py` (finds anchor line indices when
page markup changes), `scripts/corpus_stats.py`, `scripts/check_sizes.py`,
`scripts/calibrate_floor.py` (re-derives `MIN_SIMILARITY` from measured score
distributions — re-run after any corpus or model change).

---

## 16. Build log — corrections made while executing Phases 6–7

### 16.1 `MIN_SIMILARITY = 0.18` was never validated, and was wrong

The spec set the floor at `0.18` as a placeholder. Running
`scripts/calibrate_floor.py` over 32 in-domain and 20 off-topic queries:

| Population | min | max |
|---|---|---|
| in-domain top-1 similarity | 0.660 | 0.928 |
| off-topic best-nearest | 0.000 | 0.421 |

The clusters do not overlap, so any floor in `(0.421, 0.660]` is correct;
**0.54** is the midpoint. The original 0.18 admitted **14 of 20** off-topic
queries — weather, Tokyo's population, biryani recipes — because MiniLM cosine
similarity between two short *unrelated English sentences* sits around 0.2–0.3.

### 16.2 A single similarity floor still was not enough

Stress-testing with the phrasing real users type (`"AUM ELSS"`, `"riskometer"`,
`"RTA"`) exposed an **overlap** the calibration set had hidden: terse queries
score *lower* than off-topic ones, because a 1–3 word query has little context to
embed against. `"AUM ELSS"` → 0.380 is a legitimate question; `"how to file
income tax"` → 0.421 is noise. The two populations straddle each other, so no
single threshold separates them.

Rather than trade one failure for the other, retrieval now uses a **second,
independent signal** — lexical grounding:

```
accept if  similarity >= MIN_SIMILARITY (0.54)          confident path
accept if  similarity >= MIN_SIMILARITY_LOWER (0.30)
          and the question's own domain vocabulary occurs verbatim
                                                       terse-query path
otherwise reject
```

A terse question contains the literal terms (`aum`, `rta`, `lock in`); an
off-topic question contains none. Result: all 20 terse queries answered, 10 of
them via the rescue path, with off-topic leakage still at 0/8.

`min_similarity` passed explicitly is a **hard ceiling** — it disables the
rescue, because the caller is asserting "only things at least this similar".
Without that, a 0.99 floor leaked through the lexical path.

### 16.3 Bugs in the lexical gate itself

| Symptom | Root cause | Fix |
|---|---|---|
| `"lock in period"` returned nothing | Corpus writes `lock-in`; the term is `lock in`. Substring matching never connected them | `_normalise()` maps `-`, `_`, `/` to spaces; all matching is word-boundary based |
| `"scheme code"` returned `investment_objective` | Generic terms `scheme`, `code`, `fund` occur in almost every chunk, so they "ground" a match against anything | Dropped every bare generic term; multi-word terms only |
| `ter` matched `after`, `water` | Substring, not word-boundary | `(?<!\w)…(?!\w)` on every term |

The third bug had a sharp edge: `lock in period` was the one query that *most*
needed the rescue, and the per-candidate filter — which compared the raw
substring against non-normalised chunk text — silently failed on exactly that
case.

### 16.4 Known limitation, deliberately not tuned around

`"scheme code"` retrieves `investment_objective` rather than `scheme_identity`.
The correct chunk scores 0.244, below `MIN_SIMILARITY_LOWER` (0.30), so the
rescue falls back to the next candidate. Lowering the rescue floor to 0.24 would
admit this one query while widening the gate for *every* query, and the failure is
benign — the returned chunk is still a true, on-topic fact about the scheme,
just not the specific field asked for. Carried into the README Known Limits.

### 15.4 Invariant worth keeping

`python ingest.py --no-embed` is a **fast, network-free, no-API-key** way to
audit the corpus. It re-extracts from `data/raw/`, applies exclusions and
scrubbing, writes both dumps, and fails loudly if any of the 35 coverage cells
is empty — so a page-markup change that silently thins the corpus surfaces as a
non-zero exit rather than a plausible-looking short answer at query time.

---

## 17. Build log - Phases 8-11 (generation, UI, acceptance, deliverables)

### 17.1 `TOP_K` 5 → 10, and what had to be re-verified

Raising the context to 10 chunks widens recall: several target facts have one
near-identical instance per scheme, so a scheme-qualified question and the wrong
scheme's card can sit close in rank. The risk was **context dilution** — with all
five schemes' `expense_ratio` cards in one window (1.21 / 1.03 / 0.77 / 0.78 /
0.78), reading the wrong card is a live hazard. `scripts/check_context_dilution.py`
now asserts that each of the five resolves to its own figure *and* cites its own
page, and that no advice language appears. Suite: 12/12, then 13/13.

The similarity floor was **not** re-derived, and that is a deliberate result
rather than an omission: top-1 similarity does not depend on how many candidates
are returned, so `TOP_K` cannot move the calibrated gap. `scripts/calibrate_floor.py`
was re-run to confirm — identical separation (in-domain min 0.660, off-topic max
0.421).

### 17.2 Bug: the extractive fallback was mislabelling a fault as a configuration state

While capturing the sample Q&A, every answer came back prefixed *"Quoted directly
from the source page, since no language model is configured."* The key **was**
configured. Groq's free tier allows 200k tokens/day, a full verification run
consumes most of it, and the 429 was being absorbed silently by the fallback.

This is the worst kind of bug for this project: it degrades to something that
still *looks* correct. NFR-5 behaved exactly as designed — the answers were
verbatim quotes of true facts — but "no language model configured" is a benign
explanation for what was actually a rate limit, and a reviewer would have
believed it.

Fixed by distinguishing the two cases in `Answer.fallback_reason`
(`"no_key"` vs `"llm_error"`), with the UI rendering an explicit warning for the
second. `scripts/capture_sample_qa.py` now **refuses to publish** a table if any
row fell back to extractive while a key was present, so a rate-limited run can
never be mistaken for a representative one.

### 17.3 Bug: four citations where the spec requires one

`_sources_from_hits` emitted a citation for *every* retrieved hit. At `TOP_K=5`
that was mostly harmless; at `TOP_K=10` a single answer cited **all four
applicable scheme pages**. That asserts every page supports the answer, which is
false — for "exit load of HDFC Flexi Cap" only Flexi Cap's page states it — and
it dilutes the one citation the whole design exists to guarantee.

The UI had already anticipated this and rendered extras as plain text, so the
*rendered* rule was intact and the data model was the thing that was wrong. Made
explicit: `Answer.citation` and `Answer.citation_links` (never more than one) are
now the only citation surface, and `tests/test_acceptance.py` asserts
`len(citation_links) == 1` plus that the cited page is the right scheme.

### 17.4 Two acceptance tests were wrong, not the corpus

AT-12 failed on first run. Both causes were the tests, not the data:

- `\b\d{9,18}\b` (account-number heuristic) matched `content_hash=2169311853` —
  this tool's own hash in the dump header. The scan now reads chunk **text**
  fields, which is exactly what can reach the LLM.
- `\breturns?\b` matched *"NIFTY 100 **Total Return** Index"* (the benchmark's
  actual name, and a required fact for AT-5), the statutory tax slab (*"returns
  are taxed at 20%"*), and the dump's own "EXCLUSIONS BY DESIGN" header.

Rewritten to assert the guarantee that actually matters — no return **figure** and
no ranking claim — plus positive assertions that the two legitimate uses are
still present, so the tightened test can never be mistaken for a silent gap.

### 17.5 Groq's daily quota is a real operational constraint

200k tokens/day on the free tier; a 10-chunk answer costs ~1.6k, so roughly 120
questions/day. A full `verify_all.py` run plus the pytest suite consumes a large
share of it. Two consequences worth recording:

- `scripts/capture_sample_qa.py` persists each row to `data/sample_qa_cache.json`
  as it completes, so a capture interrupted by a 429 **resumes** rather than
  re-spending tokens on answers already obtained.
- Verification and day-to-day use compete for one budget. Carried into the README
  Known Limits.

### 17.6 Generated deliverables, not hand-written

`deliverables/sources.csv` and `sources.md` are produced by
`scripts/build_sources.py` from `config.SOURCES` plus the ingested corpus, and
`deliverables/sample_qa.md` is transcribed from `scripts/capture_sample_qa.py`.
A published source list that can drift from what the system actually uses is a
defect, so both are regenerated rather than written.

`config.AMC_NAME`, `AMC_SHORT` and `SUPPORTED_PLAN` were added as single points of
truth, and `DISCLAIMER_SHORT` now holds the exact phrase required on the welcome
screen (`Facts-only. No investment advice.`), with `app.py` rendering the long
form beneath it as a caption. Both live in `config.py` so the UI, the CLI and the
system prompt cannot disagree.
