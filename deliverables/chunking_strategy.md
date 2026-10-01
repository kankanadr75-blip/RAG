# Chunking Strategy — HDFC MF FAQ RAG

> Written **after inspecting the 5 live pages** and **before** writing ingestion code,
> as required by the pipeline brief. Evidence for every choice is below.

---

## 1. What the data actually looks like

I fetched all 5 pages and profiled them (`scripts/inspect_data.py`,
`scripts/explore_json.py`, `scripts/dump_fields.py`).

| Property | Finding |
|---|---|
| Raw page size | 450 KB – 815 KB HTML per page |
| Visible text | 925 – 2,158 short lines (headings, values, holdings) |
| Hidden structured data | `__NEXT_DATA__` JSON, 230 KB – 347 KB per page |
| Structured fields per scheme | **97 keys**, flat, one object per page (`mfServerSideData`) |
| Fact density | Very high and very *atomic* — almost every fact is a `label: value` pair |
| Boilerplate | ~40 % of visible lines is nav chrome, footer, fund-manager bios, peer-fund comparison tables |

Two distinct fact sources exist, and **both are needed**:

**(a) `__NEXT_DATA__` JSON — precise values that are *not* in visible text.**
These are the answers to most of the target FAQ questions:

| Field | Example (HDFC ELSS Tax Saver) |
|---|---|
| `expense_ratio` | `1.21` |
| `base_expense_ratio` | `0.97` |
| `exit_load` | `Nil` |
| `lock_in` | `{'years': 3, 'months': 0, 'days': 0}` |
| `benchmark` / `benchmark_name` | `NIFTY 500 TRI` / `NIFTY 500 Total Return Index` |
| `min_sip_investment` | `500` |
| `nfo_risk` | `Moderately High Riskometer` |
| `nav`, `nav_date`, `aum` | `1416.896`, `30-Sep-2026`, `15991.7823` |
| `sid_url`, `amc_page_url`, `isin`, `rta_scheme_code` | document links / IDs |

Verified: `expense_ratio` = **1.03 / 0.77 / 1.21 / 0.78 / 0.78** and `lock_in` = **3 years
for ELSS only** (`None` for the other four). A naive text-only scraper **cannot** see these
— the rendered DOM only contains the word "Expense ratio" (its tooltip definition), never
the number. This is the single most important finding for the design.

**(b) Visible rendered text — the prose and human-facing labels.**
Contains the `Minimum investments` block (`Min. for SIP ₹100`), the `Exit load / stamp duty /
Tax implication` block, the risk badge (`Very High Risk`), the `About` + `Investment Objective`
paragraphs, the glossary definitions ("Exit load = a fee payable to…"), and the
`Scheme Information Document(SID)` / `Registrar & Transfer Agent: Cams` block.

---

## 2. Chosen strategy: **structure-first, hybrid, two producers**

A single fixed-size splitter over the raw page is the wrong tool here, for three measured
reasons:

1. **Splits labels from values.** "Exit load" and "Exit load of 1% if redeemed within 1 year"
   are adjacent lines; a 512-token window routine cuts between them, and the answer half
   becomes an orphan chunk that embeds as noise.
2. **Embeds the boilerplate.** ~40 % of visible lines are nav/footer/peer-comparison noise.
   Those tokens dilute the MiniLM vector and push real facts out of top-k.
3. **Misses the values that matter most.** The highest-value FAQ answers (expense ratio,
   lock-in) exist only in JSON and would never appear in a text scrape at all.

So ingestion runs **two producers that meet at one chunk schema**:

### Producer A — Fact cards (from `__NEXT_DATA__`)
One chunk per **atomic fact**. Each is rewritten into a *declarative, self-contained
sentence* that names the scheme explicitly, so the embedding carries the entity even when
the question does not ("What is the exit load?" → *"The exit load of HDFC Flexi Cap Fund
Direct Plan Growth is: Exit load of 1% if redeemed within 1 year."*).

Typical length **110 – 330 chars**, no overlap needed (each card is one indivisible fact).
Lock-in is normalised to a readable string (`3 years`, `None`) rather than dumped as a raw
Python dict repr.

### Producer B — Labelled prose sections (from rendered text)
Locate **named sections** (`Minimum investments`, `Exit load`, `Tax implication`,
`Investment Objective`, `About`, `Fund benchmark`, `Scheme Information Document(SID)`,
`Exit Load`, glossary terms) and emit each as `Section header + body`, so the header is
part of the embedded text and every chunk is interpretable standalone.

| Parameter | Value | Why |
|---|---|---|
| **Chunk size** | **380 chars** (~90 tokens) | The measured atomic fact + its label is 110–330 chars. 380 chars holds a full `label: value` pair **plus** its section header **plus** ~1 sentence of context, while staying under one MiniLM token window's worth of dilution. |
| **Chunk overlap** | **80 chars** (~20 tokens) | Enough to re-carry a section header and the start of the previous fact when a boundary lands mid-pair. Larger overlap wastes context here because 90 % of chunks are single-fact cards that must not be duplicated (duplicates crowd out *other* facts from top-k). |
| **Min chunk** | **40 chars** | Drops nav crumbs ("Stocks", "IPO", "See All") that would otherwise pollute results. |
| **Boundary** | Sentence / newline aware | Never cuts inside a `label: value` line. |

### Metadata kept per chunk
Every chunk carries enough to render a citation without a second lookup:

```
chunk_id        stable id, e.g. hdfc-elss-…__expense_ratio__0
source_url      the exact public page it came from  -> used for the citation link
source_name     "HDFC ELSS Tax Saver Fund - Direct Growth"
amc             "HDFC Mutual Fund"
scheme_slug     url slug
scheme_name     as published
scheme_code     Groww scheme code (119060 …)
category        ELSS / Large Cap / Flexi Cap / Small Cap / Balanced Advantage
section         "expense_ratio" | "minimum_investments" | "exit_load" | …
producer        "fact_card" | "prose_section"  (which of A/B made it)
extracted_from  "__NEXT_DATA__" | "visible_text"
as_of           source's own date string (e.g. "30-Sep-2026"), else ""
char_len        length of the embedded text
ingested_at     UTC ISO timestamp of the ingestion run
content_hash    sha1[:10] of chunk text, for dedupe / drift detection
```

`source_url` is stored **on every chunk**, which is what makes the "one citation in every
answer" requirement enforceable at answer time rather than by hope.

---

## 3. Resulting corpus shape (measured after running ingestion)

```
5 pages  ->  5 documents
          ->  ~165 chunks total
          ->  ~130 fact_card chunks  (Producer A, atomic label:value facts)
          ->  ~35  prose_section chunks (Producer B, labelled prose)
```

Verification steps performed on the written chunks (`data/chunks.txt`):
* every chunk contains at least one of the 7 target FAQ keywords, or is an identity fact;
* all 5 schemes have an `expense_ratio`, `exit_investment_minimum`/`sip_minimum`,
  `exit_load`, `benchmark`, `riskometer` and `lock_in_period` chunk;
* `lock_in_period` is non-null **only** for the ELSS scheme;
* no chunk contains a phone number, e-mail address or postal address from the page footer
  (PII / contact-data scrub — see `guardrails.scrub_pii`).

---

## 4. Deliberate exclusions (documented, not accidental)

| Excluded | Reason |
|---|---|
| Holdings tables, peer comparison, fund-manager bios | Not FAQ facts; ~40 % of page volume; hurts retrieval |
| NAV / AUM / returns **numbers** | Brief says **no performance claims** and don't compute/compare returns. NAV/AUM retained only as identity facts, and the app routes any "returns/performance" question to the official factsheet link instead of answering a number. |
| Registrar e-mail / phone / postal address | Contact data, not facts; removed to keep a no-PII corpus |
| `nfo_risk` ("Moderately High Riskometer") | **Conflicts** with the page's rendered risk badge ("Very High Risk"). The badge is what the page actually displays, so the badge wins; `nfo_risk` is kept as a secondary labelled field and the discrepancy is disclosed in README "Known limits". |
| "About" prose AUM figure (₹9,86,237 Cr) | Groww's `About` paragraph repeats **AMC-level** AUM on every scheme page. Scheme-level `aum` from JSON is used instead; the prose figure is dropped to avoid a wrong fact entering the corpus. |

---

## 5. Re-tuning guidance

* **Chunk size ↑ (500–600)** if evaluation shows multi-fact questions ("min SIP *and* exit
  load") miss context.
* **Overlap ↑ (120–150)** if you add long narrative documents (factsheets, SID PDFs) where
  a paragraph boundary can fall mid-argument. Not needed for these 5 short pages.
* **Producers A+B** generalise: if you later add HDFC factsheet PDFs, keep Producer A for
  the structured header block and add a page-aware Producer B rather than one global splitter.
