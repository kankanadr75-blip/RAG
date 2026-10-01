# PRD — Mutual Fund FAQ Assistant (Facts-Only RAG Chatbot)

**Milestone:** RAG Chatbot — Data Ingestion + Data Retrieval
**Version:** v1.0
**Status:** Approved for build
**Owner:** Kankana Dhar
**Last updated:** 01 Oct 2026

---

## 1. Problem Statement

Retail investors and support/content teams repeatedly ask the same factual questions about
mutual fund schemes — *what is the expense ratio, what is the exit load, what is the minimum
SIP, is there a lock-in, what is the benchmark/riskometer, how do I download a statement?*

Today these answers are scattered across five different kinds of place: a scheme's factsheet
PDF, a 200-page Scheme Information Document, an AMC fee/charges page, an AMFI circular, and a
broker app's help centre. The cost of that fragmentation is paid in two ways:

1. **For the retail user** — the answer exists, but finding it takes several minutes and the
   user cannot be sure whether the number they found is current, applies to *their* plan
   (Direct vs Regular), or is stale.
2. **For support/content teams** — the same question gets answered by hand dozens of times a
   day, each time re-reading the same source pages, with a real risk of quoting a figure from
   the wrong plan or an outdated document.

Meanwhile the questions that dominate search are *factual*, not advisory. What people
actually need is a fast, trustworthy, **sourced** fact — not a recommendation.

The gap: **there is no single assistant that answers mutual fund scheme facts from official
public sources and shows you exactly where the fact came from.**

### 1.1 The failure mode we are explicitly designing against

An LLM asked "what is the exit load of HDFC Flexi Cap?" will confidently produce a plausible
number from pretraining memory. That number may be real, but it may be from the **Regular
plan**, may predate a fee change, or may be invented. In a financial context a confidently
wrong fee is worse than no answer, because the user has no way to tell. Therefore this
product's core requirement is not fluency — it is **provenance and refusal**.

---

## 2. Milestone Brief

Build a small, working **Retrieval-Augmented Generation (RAG) chatbot** that answers
**factual** questions about mutual fund schemes using **only** collected public pages, and
that shows **one clear source link in every answer**.

This milestone covers the **full RAG lifecycle**, both stages:

```
INGESTION (runs once, persisted)
  Load  ->  Chunk  ->  Embed  ->  Store in Vector DB (on disk)

QUERY (runs per question)
  Question  ->  Embed  ->  Retrieve top-k chunks  ->  LLM  ->  Answer + citation
```

Deliverable is an end-to-end **RAG chatbot**.

---

## 3. Who This Helps

| User | Need | Pain today |
|---|---|---|
| **Retail investors** comparing HDFC schemes | A fast, trustworthy answer to one factual question (fee, lock-in, minimum, benchmark) before they read the factsheet | Facts are spread across a factsheet PDF, an SID, and an app; hard to confirm a number is current and plan-specific |
| **Support / content teams** answering repetitive MF questions | A consistent, cited answer to the top ~10 recurring questions | Each reply is manual re-reading of source pages; risk of quoting the wrong plan or a stale figure |

**Explicitly not a user:** someone asking whether to buy or sell. That is out of scope
(§8) and the assistant must refuse it politely.

---

## 4. Goals & Non-Goals

### 4.1 Goals

| # | Goal | Measurable |
|---|---|---|
| G1 | Answer the 7 target fact types for 5 schemes from public sources only | 7/7 fact types answered for 5/5 schemes |
| G2 | Every answer carries exactly one working source link | 100 % of factual answers |
| G3 | Ingestion runs **once**; vector DB persisted to disk | Restart does not re-embed |
| G4 | Refuse opinionated / portfolio questions with a polite facts-only message + educational link | 100 % refusal on the advice test set |
| G5 | Zero PII accepted or stored | No PAN/Aadhaar/account/OTP/email/phone stored or echoed |
| G6 | Answers ≤ 3 sentences, plus a "Last updated from sources:" line | Enforced in prompt + validated in tests |

### 4.2 Non-Goals

* No returns, performance, ranking or comparison computation of any kind.
* No buy/sell/hold/timing advice, no portfolio allocation, no personalised suitability.
* No login, no user accounts, no portfolio data, no transaction history.
* No multi-AMC coverage — **one AMC (HDFC)** in this milestone.
* No live NAV streaming; facts are as-published at ingest time with an explicit as-of date.
* No app-store back-end scraping; **public web pages only**.

---

## 5. Scope — AMC + Schemes

**AMC: HDFC Mutual Fund.** All 5 schemes are **Direct – Growth** plans, so every figure is
unambiguous and no Regular-plan confusion is possible.

| # | Scheme | Category | Groww slug |
|---|---|---|---|
| 1 | HDFC Large Cap Fund – Direct Growth | Large Cap | `hdfc-large-cap-fund-direct-growth` |
| 2 | HDFC Flexi Cap Fund – Direct Growth | Flexi Cap | `hdfc-equity-fund-direct-growth` |
| 3 | HDFC ELSS Tax Saver Fund – Direct Growth | ELSS (Tax Saver) | `hdfc-elss-tax-saver-fund-direct-plan-growth` |
| 4 | HDFC Small Cap Fund – Direct Growth | Small Cap | `hdfc-small-cap-fund-direct-growth` |
| 5 | HDFC Balanced Advantage Fund – Direct Growth | Balanced Advantage (Hybrid) | `hdfc-balanced-advantage-fund-direct-growth` |

Category spread is deliberate: it forces the retriever to disambiguate on **category**, not
just fund name, and it includes one **hybrid** (to test non-equity handling) and one **ELSS**
(to test a lock-in fact that exists on only 1 of 5 pages).

---

## 6. Source List (the 5 public pages used)

| # | URL | Supplies |
|---|---|---|
| S1 | `https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth` | Large Cap facts |
| S2 | `https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth` | Flexi Cap facts |
| S3 | `https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth` | ELSS facts incl. 3-yr lock-in |
| S4 | `https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth` | Small Cap facts |
| S5 | `https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth` | Balanced Advantage facts |

Machine-readable list also delivered as `deliverables/sources.csv` and `sources.md`.

### 6.1 Target question types (the 7 facts the assistant must answer)

1. **Expense ratio** (and base expense ratio)
2. **Exit load**
3. **Minimum SIP** / minimum lump-sum / minimum additional investment
4. **Lock-in period** (ELSS — 3 years)
5. **Riskometer** level
6. **Benchmark** index
7. **How to download documents / statements** (SID, RTA/CAMS, AMC site)

Plus supported identity facts: objective, scheme type, NAV + as-of date, AUM, ISIN,
scheme code, launch date, portfolio turnover, registrar.

---

## 7. Evidence — Verified Data Findings (measured, not assumed)

The 5 pages were fetched and profiled **before** this PRD was finalised
(`scripts/inspect_data.py`, `scripts/explore_json.py`, `scripts/dump_fields.py`).
These measurements drive the requirements below.

### 7.1 Corpus shape

| Metric | Measured value |
|---|---|
| Raw HTML per page | 450 KB – 815 KB |
| Visible text per page | 925 – 2,158 short lines |
| `__NEXT_DATA__` JSON per page | 230 KB – 347 KB, **97 flat keys** per scheme |
| Boilerplate share of visible text | **~40 %** (nav, footer, fund-manager bios, peer tables) |

### 7.2 Critical finding that shapes the whole design

> **The values for expense ratio and lock-in do not exist in the page's visible text.**

The rendered DOM contains only the *word* "Expense ratio" (as a tooltip definition).
The **number** lives only in the embedded `__NEXT_DATA__` JSON as
`expense_ratio`, `base_expense_ratio`, `lock_in`, `min_sip_investment`, `benchmark`,
`nfo_risk`, etc.

**Implication (REQ-2):** a text-only scraper would silently fail the two most-asked
questions. Ingestion must parse **both** the structured JSON *and* the rendered prose.
This is recorded in `deliverables/chunking_strategy.md`.

### 7.3 Verified fact snapshot (as published 30-Sep-2026)

| Scheme | Expense ratio | Base ER | Exit load | Lock-in | Min SIP | Benchmark |
|---|---|---|---|---|---|---|
| Large Cap | **1.03 %** | 0.84 % | 1 % if redeemed within 1 year | none | ₹100 | NIFTY 100 Total Return Index |
| Flexi Cap | **0.77 %** | 0.57 % | 1 % if redeemed within 1 year | none | ₹100 | NIFTY 500 Total Return Index |
| ELSS Tax Saver | **1.21 %** | 0.97 % | **Nil** | **3 years** | ₹500 | NIFTY 500 Total Return Index |
| Small Cap | **0.78 %** | — | 1 % if redeemed within 1 year | none | ₹100 | BSE 250 SmallCap Total Return Index |
| Balanced Advantage | **0.78 %** | — | 1 % on units **in excess of 15 %** of investment, if redeemed within 1 year | none | ₹100 | NIFTY 50 Hybrid Composite Debt 50:50 Index |

`lock_in` is non-null **only** for the ELSS scheme — confirming the test case for
"answer a fact that exists on exactly one page."

### 7.4 Data-quality conflicts found (must be disclosed, not silently resolved)

| Conflict | Detail | Resolution |
|---|---|---|
| **Riskometer** | Rendered badge says **"Very High Risk"**; JSON `nfo_risk` says **"Moderately High Riskometer"** (3 of 5) / "Moderately High" (2 of 5) | The **rendered badge** is what the page displays, so it is authoritative for the answer; `nfo_risk` kept as a secondary labelled field; conflict disclosed in README "Known limits" |
| **Fund manager** | JSON `fund_manager` (e.g. Large Cap = "Prashant Jain") disagrees with the page's own "About" prose (Large Cap = "Rahul Baijal") | Manager name is **excluded from answered facts** (not a target fact type) until reconciled against the official SID/factsheet |
| **AUM** | The "About" prose repeats the **AMC-level** AUM (₹9,86,237 Cr) on *every* scheme page | Prose AUM dropped; scheme-level JSON `aum` used instead |
| **Inception date** | JSON `launch_date` = 01-Jan-2013 (Direct-plan re-labelling) vs prose "made available to investors on 10 Dec 1999" (scheme inception) | Both stored, each labelled distinctly; prose framing used for "inception" |
| **Performance figures** | Pages publish 1Y/3Y/5Y/10Y returns and peer rankings | **Excluded from corpus.** No returns are answered or computed (see §8) |

These conflicts are the reason the product must show a citation for every answer: a user can
check the number against the page themselves.

---

## 8. Functional Requirements

### 8.1 Ingestion stage (runs once, persisted)

| ID | Requirement |
|---|---|
| **REQ-1** | Load each of the 5 public pages; cache raw HTML to disk so re-runs don't re-hit the network |
| **REQ-2** | Extract facts from **two** sources per page: embedded `__NEXT_DATA__` JSON **and** rendered visible text (§7.2) |
| **REQ-3** | Convert each atomic fact into a **self-contained declarative sentence** naming the scheme, so it embeds correctly even when the question omits the fund name |
| **REQ-4** | Chunk labelled prose sections at **380 chars / 80 char overlap**, sentence-boundary aware, min 40 chars |
| **REQ-5** | Attach metadata to every chunk incl. **`source_url`**, scheme identity, category, section, producer, as-of date, content hash |
| **REQ-6** | Embed all chunks with **`sentence-transformers/all-MiniLM-L6-v2`** (384-dim, local, no API key) |
| **REQ-7** | Store in **ChromaDB persisted to disk**; re-running the app must **not** re-embed |
| **REQ-8** | Dump every chunk to a human-readable **`data/chunks.txt`** for inspection |
| **REQ-9** | Scrub PII/contact data (e-mail, phone, postal address) from all chunk text |
| **REQ-10** | Print an ingestion report: pages, chunks per producer, per-scheme coverage of the 7 target facts |

### 8.2 Retrieval + answer stage

| ID | Requirement |
|---|---|
| **REQ-11** | Embed the user question with the **same** MiniLM model |
| **REQ-12** | Retrieve **top 5** chunks; apply a similarity floor so "nothing relevant" is a valid outcome |
| **REQ-13** | If nothing clears the floor, say so honestly and point to the official source — never fill the gap from model memory |
| **REQ-14** | Generate the answer with **Groq** (`llama-3.3-70b-versatile`), API key from `.env`, never committed |
| **REQ-15** | **Every** answer includes exactly one clear, clickable source link taken from chunk metadata |
| **REQ-16** | Answers are **≤ 3 sentences** and end with a **`Last updated from sources: <date>`** line |
| **REQ-17** | Answers are **facts only** — the LLM is instructed to state only what the retrieved chunks support |

### 8.3 Guardrails

| ID | Requirement |
|---|---|
| **REQ-18** | **Refuse advice/opinion questions** ("Should I buy…", "best fund…", "which is better", "for me", "allocate…") with a polite facts-only message **plus** a relevant educational link (SEBI / AMFI / HDFC AMC FAQ) |
| **REQ-19** | **No performance claims** — never compute, compare or state returns. Route performance/returns questions to the official factsheet/SID link instead |
| **REQ-20** | **No PII** — detect and refuse PAN, Aadhaar, account numbers, OTPs, e-mails, phone numbers in user input; never log or persist them |
| **REQ-21** | Guardrails run **before** retrieval (cheap regex) **and** the refusal is enforced in the system prompt |

### 8.4 UI (tiny, per brief)

| ID | Requirement |
|---|---|
| **REQ-22** | Welcome line + **3 example questions** |
| **REQ-23** | Persistent note: **"Facts-only. No investment advice."** |
| **REQ-24** | Render each answer with its citation link and the last-updated line |
| **REQ-25** | Show which schemes are in scope |

---

## 9. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | Local embedding model — **no API key** for the embed stage |
| NFR-2 | **No secrets in Git**: `.env` git-ignored, `.env.example` committed |
| NFR-3 | Ingestion is idempotent and restartable; vector DB survives restart |
| NFR-4 | Deterministic chunk ids so re-ingestion is diffable |
| NFR-5 | Graceful degradation: if `GROQ_API_KEY` is absent, the app must still run and answer from retrieved chunks (extractive mode) rather than crash |
| NFR-6 | Runs on CPU, Windows-friendly, no GPU required |
| NFR-7 | Clean separation: `ingest.py` (offline) vs `rag.py` (online) vs `app.py` (UI) |

---

## 10. Architecture

```
                    ┌──────────────── ONE-TIME, OFFLINE ────────────────┐
  5 public URLs ──▶ │ Load        fetch + cache raw HTML (data/raw)    │
                    │ Extract     __NEXT_DATA__ JSON + visible text    │
                    │ Chunk       fact cards + labelled sections       │
                    │             380 chars / 80 overlap               │
                    │ Scrub       strip PII / drop performance figures  │
                    │ Embed       all-MiniLM-L6-v2  → 384-d vectors    │
                    │ Store       ChromaDB  →  data/chroma (persisted)  │
                    │ Dump        data/chunks.txt  (+ chunks.jsonl)     │
                    └──────────────────────────────────────────────────┘
                                              │
                    ┌───────── PER QUESTION, ONLINE ──────────────────┐
 user question ──▶ │ Pre-check PII → refuse advice → classify topic   │
                    │ Embed       same MiniLM model                    │
                    │ Retrieve    top 5 chunks + similarity floor      │
                    │ Generate    Groq llama-3.3-70b (facts only,      │
                    │             ≤3 sentences, 1 citation)           │
                    │ Render      answer + source link + last-updated  │
                    └──────────────────────────────────────────────────┘
```

### 10.1 Component map

| Component | File | Responsibility |
|---|---|---|
| Config | `config.py` | Sources, paths, chunk params, model ids, refusal patterns, disclaimer |
| Ingestion | `ingest.py` | Load → Chunk → Embed → Store (+ report, dumps) |
| Query engine | `rag.py` | Embed → Retrieve → Generate → Cite |
| Guardrails | `guardrails.py` | PII detection, advice refusal, performance deflection |
| UI | `app.py` | Streamlit chat, examples, disclaimer, citations |
| Strategy | `deliverables/chunking_strategy.md` | The required pre-code chunking proposal |

### 10.2 Technology decisions

| Concern | Choice | Rationale |
|---|---|---|
| Embedding | `sentence-transformers/all-MiniLM-L6-v2` | Required; local, no key, 384-dim, fast on CPU |
| Vector DB | ChromaDB, persisted | Required; embedded, zero-server, survives restart |
| LLM | Groq `llama-3.3-70b-versatile` | Required; fast, cheap, strong instruction-following for the refusal rules |
| UI | Streamlit | Tiny UI in hours; supports chat + clickable links natively |
| Extraction | BeautifulSoup + `__NEXT_DATA__` JSON | See §7.2 — JSON is mandatory, text alone fails |

---

## 11. Success Criteria / Acceptance Tests

| # | Test | Pass condition |
|---|---|---|
| AT-1 | "What is the expense ratio of HDFC ELSS Tax Saver?" | Answers **1.21 %**, with the S3 link |
| AT-2 | "What is the exit load of HDFC Flexi Cap?" | Answers **1 % within 1 year**, with the S2 link |
| AT-3 | "Is there a lock-in on HDFC ELSS?" | Answers **3 years**, with the S3 link |
| AT-4 | "What is the minimum SIP?" (ambiguous, no fund named) | Answers per-scheme or asks which scheme; does **not** invent one |
| AT-5 | "What is the benchmark of HDFC Small Cap?" | Answers **BSE 250 SmallCap Total Return Index**, S4 link |
| AT-6 | "Should I buy HDFC Large Cap?" | **Refuses** politely + educational link, no recommendation |
| AT-7 | "Which fund gives the best returns?" | **Refuses / deflects** to official factsheet, states no return figure |
| AT-8 | "My PAN is ABCDE1234F, download my statement" | **Refuses PII**, does not echo the PAN |
| AT-9 | "How do I download the SID?" | Points to HDFC AMC / SID, cites a source |
| AT-10 | Restart the app | No re-embedding; answers still work |
| AT-11 | Every factual answer | ≤ 3 sentences + 1 link + "Last updated from sources:" line |
| AT-12 | Inspect `data/chunks.txt` | Lock-in fact present for ELSS only; no PII; no return figures |

---

## 12. Deliverables

| # | Deliverable | Status |
|---|---|---|
| D1 | **Working prototype** — Streamlit RAG chatbot (app) | ☐ |
| D2 | **Source list** (CSV + MD) of the 5 URLs used | ☐ |
| D3 | **README** — setup steps, scope (AMC + schemes), known limits | ☐ |
| D4 | **Sample Q&A** — 5–10 queries with the assistant's answers + links | ☐ |
| D5 | **Disclaimer snippet** used in the UI (facts-only, no advice) | ☐ |
| D6 | **Chunking strategy** — inspected data, rationale, size/overlap/metadata | ☐ |
| D7 | Inspectable chunk dump (`data/chunks.txt`) | ☐ |
| D8 | **PRD.md** (this document) | ☑ |
| D9 | ≤3-min demo video (only if hosting isn't possible) | ☐ |

---

## 13. Risks & Mitigations

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | **Page structure changes** → scraper silently returns nothing | High | Assert 5 pages × ≥7 target facts at ingest; **fail loudly** on coverage drop. Never answer from a thin corpus |
| R2 | **Facts go stale** after ingest | High | Persist `as_of` + `ingested_at`; surface "Last updated from sources"; document `python ingest.py --refresh` to re-run |
| R3 | **Hallucinated number** from LLM memory | High | Facts-only system prompt + "if not in context, say so"; NFR-5 extractive fallback; citation on every answer so the user can verify |
| R4 | **Advice leakage** ("you should buy…") | High | REQ-18 regex pre-filter **plus** prompt-level prohibition **plus** refusal test set (AT-6/AT-7) |
| R5 | **Performance claims** slipping through | Medium | Corpus excludes return figures; REQ-19 deflects such questions to the official factsheet |
| R6 | **PII entered by user** | Medium | REQ-20 detect + refuse + never log; corpus contact data scrubbed at ingest |
| R7 | **Source conflicts** (§7.4) | Medium | Authoritative-source rule, documented in README Known Limits, disclosed rather than hidden |
| R8 | **Scope creep** to more AMCs / live NAV | Medium | §4.2 non-goals; 1 AMC × 5 schemes is this milestone's boundary |
| R9 | **No Groq key available** | Low | NFR-5 extractive mode keeps the prototype demoable |
| R10 | **MiniLM weak on long numeric strings** | Low | Fact cards restate values as declarative sentences, improving numeric matching |

---

## 14. Open Questions

| # | Question | Proposed default |
|---|---|---|
| Q1 | Groww vs AMC's own site as the citation of record? | Groww (the collected source); add AMC/SID as the "verify officially" link in the UI |
| Q2 | Include Regular-plan figures alongside Direct? | No — one plan per scheme keeps facts unambiguous this milestone |
| Q3 | Which riskometer value is authoritative? | Rendered badge ("Very High Risk"); conflict disclosed. **Confirm against HDFC's official riskometer disclosure** |
| Q4 | Multilingual (Hinglish/Hindi) questions? | Out of scope; English only, noted in Known Limits |
| Q5 | Answer in chat only, or also expose a REST endpoint? | Chat only this milestone |

---

## 15. Appendix — Source Facts Reference (for reviewers)

- Structured fields read per scheme: `scheme_code`, `scheme_name`, `amc`, `fund_house`,
  `category`, `sub_category`, `benchmark`, `benchmark_name`, `expense_ratio`,
  `base_expense_ratio`, `exit_load`, `lock_in`, `additional_details`, `min_sip_investment`,
  `max_sip_investment`, `min_investment_amount`, `min_withdrawal`, `sip_multiplier`,
  `purchase_multiplier`, `mini_additional_investment`, `nfo_risk`, `nav`, `nav_date`, `aum`,
  `portfolio_turnover`, `launch_date`, `allotment_date`, `isin`, `rta_scheme_code`,
  `registrar_agent`, `stamp_duty`, `groww_rating`, `description`, `sid_url`, `amc_page_url`,
  `sip_allowed`, `lumpsum_allowed`.
- Scheme codes verified: Large Cap `119018`, Flexi Cap `118955`, ELSS `119060`,
  Small Cap `130503`, Balanced Advantage `118968`.
- Registrar & Transfer Agent for all 5: **CAMS**.
- Source `as_of` date at ingest: **30-Sep-2026**.
