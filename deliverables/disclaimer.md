# Disclaimer

Two forms are used. Both are defined once in `config.py`
(`DISCLAIMER_SHORT`, `DISCLAIMER`) so the UI, the CLI and the LLM system
prompt can never disagree about what the assistant promises.

---

## 1. Short form — rendered on the welcome screen and beside every answer

> **Facts-only. No investment advice.**

`config.DISCLAIMER_SHORT` · rendered by `app.py` as a persistent `st.warning`
above the input box.

This is the form required on the welcome screen. It is also appended to the
system prompt, so the model is told the same thing the user is shown.

---

## 2. Long form — rendered once at the top of the app, and in the system prompt

> Facts-only. No investment advice. Answers are sourced from public Groww
> scheme pages and may be incomplete - always verify with the official HDFC
> Mutual Fund SID / factsheet.

`config.DISCLAIMER` · rendered by `app.py` as a caption beneath the short form
and appended to `SYSTEM_PROMPT` in `rag.py`.

---

## Why both

The short form states the two promises that must never be broken — no advice,
no opinion. The long form adds the honest caveat that this assistant reads
**one distributor's** pages, not the AMC's statutory documents, so it can be
incomplete. Showing only the short form would overstate the coverage; showing
only the long form buries the actual limit.

---

## What the assistant will not do

These are enforced in code, not just promised in copy. See `guardrails.py` and
the pipeline order in `rag.py`.

| It will not | How that is enforced |
|---|---|
| Recommend a scheme, or say whether to buy/sell/hold/switch | `is_advice_request` refuses before retrieval |
| Quote, compute or rank returns | `is_performance_request` refuses; return figures are excluded **at ingest**, so none exist to leak |
| Answer about a fund outside the corpus | `is_out_of_scope_scheme` refuses; a lookalike fund cannot be answered from a neighbour's page |
| Accept or repeat PAN, Aadhaar, folio/account numbers, OTPs, e-mail or phone | `detect_pii` refuses at the first stage of the pipeline, before the question reaches retrieval, the LLM or any log |
| Invent a citation | Citations are built from chunk metadata in Python, never parsed from model prose |

## Scope of the facts

- One AMC: **HDFC Mutual Fund**.
- Five schemes, **Direct Growth** plan only. Regular-plan figures are not
  collected and must not be inferred from these.
- Facts are as published on the source pages on the `as_of` date stamped at the
  end of every answer.
- Source pages are Groww's, not the AMC's. For anything statutory — SID, KIM,
  addenda, monthly factsheet — use the official HDFC Mutual Fund or AMFI
  source.

## Standard regulatory note

> Mutual fund investments are subject to market risks. Read all scheme-related
> documents carefully. Investments in mutual funds are the investor's own
> responsibility. The asset class may decline in value as well as rise, and
> past performance is not a guide to future performance. This is a
> facts-only informational assistant and is **not** a SEBI-registered
> investment adviser; it does not provide investment advice or take into
> account any investor's personal circumstances.

**Not** an SEBI-registered investment adviser. This assistant publishes facts
retrieved from public pages. It does not assess suitability, and nothing it
outputs should be read as a recommendation to deal in any security.