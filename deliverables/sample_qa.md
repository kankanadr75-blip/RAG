# Sample Q&A

Real captured output. Every answer below was produced by the running system and
transcribed from it by `scripts/capture_sample_qa.py` — none is hand-written.

Regenerate with:

```powershell
python scripts/capture_sample_qa.py > deliverables/sample_qa.md
```

The script **refuses to emit a table** if any row fell back to extractive mode
while an API key was configured, so a rate-limited or broken run cannot be
mistaken for a representative one. Each row is cached to
`data/sample_qa_cache.json` as it completes, so an interrupted capture resumes
instead of re-spending tokens.

Captured at `TOP_K = 10` with Groq `qwen/qwen3.8-27b` live, facts as published
**30-Sep-2026**.

---

## Answers

| # | AT | Question | Assistant answer | Source link |
|---|-----|----------|-------------------|-------------|
| 1 | AT-1 | What is the expense ratio of HDFC ELSS Tax Saver Fund? | The expense ratio of HDFC ELSS Tax Saver Fund Direct Plan Growth is 1.21%, with a base expense ratio of 0.97%. This annual percentage is charged to the fund for management and administration.<br><br>Last updated from sources: 30-Sep-2026 | [HDFC ELSS Tax Saver Fund - Direct Growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-growth) |
| 2 | AT-2 | What is the exit load of HDFC Flexi Cap Fund? | The exit load for HDFC Flexi Cap Direct Plan Growth is 1% if units are redeemed within 1 year. This fee is payable to the fund house for redeeming units before the specified period from the date of investment.<br><br>Last updated from sources: 30-Sep-2026 | [HDFC Flexi Cap Fund - Direct Growth](https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth) |
| 3 | AT-3 | Is there a lock-in period on the HDFC ELSS Tax Saver Fund? | Yes, the HDFC ELSS Tax Saver Fund Direct Plan Growth has a lock-in period of 3 years. Units cannot be redeemed before this lock-in period ends.<br><br>Last updated from sources: 30-Sep-2026 | [HDFC ELSS Tax Saver Fund - Direct Growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth) |
| 4 | AT-4 | What is the minimum SIP? | The minimum SIP amount is ₹100 for the HDFC Large Cap, Flexi Cap, Small Cap, and Balanced Advantage Funds. For the HDFC ELSS Tax Saver Fund, the minimum SIP is ₹500, with instalments required to be in multiples of ₹500.<br><br>Last updated from sources: 30-Sep-2026 | [HDFC Large Cap Fund - Direct Growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth) |
| 5 | AT-5 | Which benchmark does HDFC Small Cap Fund use? | The fund benchmark of HDFC Small Cap Fund Direct Growth is the BSE 250 SmallCap Total Return Index, listed as BSE 250 SmallCap TRI.<br><br>Last updated from sources: 30-Sep-2026 | [HDFC Small Cap Fund - Direct Growth](https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth) |
| 6 | AT-6 | Should I buy HDFC Large Cap Fund? | I only share published facts about HDFC Mutual Fund schemes, so I can't tell you which scheme to choose or what to do with your money - that depends on your goals, time horizon and risk tolerance, which only you and a SEBI-registered investment adviser can assess. Here's where you can learn the concepts yourself. | [SEBI](https://www.sebi.gov.in/) |
| 7 | AT-7 | Which HDFC fund gives the best returns? | I don't provide, calculate or compare returns or rankings - that information is published directly by the fund house, and I'd rather point you at the source than risk stating a stale or misleading figure. Please check the official monthly factsheet and SID for the scheme, which carry the SEBI-mandated performance disclosures. | [SEBI](https://www.sebi.gov.in/) |
| 8 | AT-8 | My PAN is ABCDE1234F and my folio is 12345678, email me at ravi.kumar@example.com | This assistant only answers questions about publicly published HDFC Mutual Fund scheme facts, and it does not accept or store a PAN number. Please remove it from your question - you never need to share personal or login details here to look up a scheme fact. | [HDFC Mutual Fund FAQs](https://www.hdfcfund.com/faqs) |
| 9 | AT-9 | How do I download the SID of HDFC Large Cap Fund? | The Scheme Information Document (SID) for HDFC Large Cap Fund Direct Growth is published by HDFC Mutual Fund at<br><br>Last updated from sources: 30-Sep-2026 | [HDFC Large Cap Fund - Direct Growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth) |
| 10 | AT-3b | What is the lock-in period of HDFC Large Cap Fund? | HDFC Large Cap Fund Direct Growth has no lock-in period. Units can be redeemed at any time after purchase.<br><br>Last updated from sources: 30-Sep-2026 | [HDFC Large Cap Fund - Direct Growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth) |
| 11 | AT-5b | What is the stamp duty on HDFC Small Cap Fund? | The stamp duty on investment in HDFC Small Cap Fund Direct Growth is 0.005%, effective from July 1st, 2020. This tax is payable on the purchase of units.<br><br>Last updated from sources: 30-Sep-2026 | [HDFC Small Cap Fund - Direct Growth](https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth) |
| 12 | scope | What is the expense ratio of HDFC Mid Cap Fund? | I couldn't find that in the sources I hold, which cover five HDFC Mutual Fund Direct Growth scheme pages only - so I won't guess. For the authoritative answer, check the official monthly factsheet and Scheme Information Document for the scheme, which are published by the fund house. | [HDFC Mutual Fund FAQs](https://www.hdfcfund.com/faqs) |

---

## Notes

### 1 — AT-1: the field that only exists in JSON
The expense ratio appears **nowhere in the rendered HTML**. The page shows only
the words "Expense ratio" as a tooltip label; the value is in the page's
`__NEXT_DATA__` payload. A text-only scrape of these pages cannot answer this —
arguably the most-asked question about a mutual fund. The base ratio (0.97%)
comes from the same card.

### 2 — AT-2: the slug is misleading
Flexi Cap's page is served from `hdfc-equity-fund-direct-growth` — the slug
predates the category rename. Worth knowing before writing any code that infers a
category from a URL.

### 3 & 10 — AT-3: only one of the five has a lock-in
ELSS is the only one with a real 3-year lock-in. The other four state explicitly
that there is none (row 10), and those negatives are stored in the corpus on
purpose: "does this scheme have a lock-in?" must be answerable with *no* for the
four, not merely silent.

### 4 — AT-4: an ambiguous question, handled rather than guessed
Unqualified, the five schemes disagree: ELSS is ₹500, the rest ₹100. The answer
gives **both** groups in two sentences instead of silently picking one — which is
the outcome AT-4 requires.

Two honest caveats:
- The single citation is Large Cap's page, the top-ranked hit. For a genuinely
  cross-scheme answer one link is incomplete by construction. The alternative —
  four links — would assert all four pages support it, which is worse.
- This depends on the retrieved set happening to contain all five `sip_minimum`
  cards. It does at `TOP_K = 10`; at `TOP_K = 5` it would not. A more robust
  answer to an unqualified cross-scheme question would ask which scheme is meant
  rather than enumerate.

### 6 & 7 — AT-6/AT-7: refusals, with a link instead of a number
Both are fixed copy from `guardrails.py`, so they are deterministic and cost no
tokens. Row 7 matters most: **no return figure exists anywhere in the corpus**,
so there is nothing for the model to leak even if the guard were bypassed. The
refusal points at the factsheet rather than quoting a number.

### 8 — AT-8: PII never reaches the model or the screen
Refused at the **first** stage of the pipeline, before retrieval, before the LLM,
before any log. Note that nothing from the input — PAN, folio number or e-mail —
appears in the answer, and the Streamlit UI additionally suppresses the user's own
text from the transcript. `test_at8` asserts this against the serialised answer,
not just the visible string.

### 9 — AT-9: the one visibly weak answer
This answer **dangles**: "…is published by HDFC Mutual Fund at" — the sentence is
truncated mid-clause. The cause is upstream, in the corpus: the `documents` chunk
ends where the page's markup ends, and the sentence limit then cuts the model's
attempt to complete it.

It is factually safe — it names the right document and the right publisher, and
cites the right page — but it reads as broken. Fixing it means either a larger
window at the `documents` chunk boundary or a "say plainly what is not stated"
answer, and it is **not** fixed. Recorded rather than hidden.

### 12 — scope: the lookalike refusal
`HDFC Mid Cap` is not in the corpus and embeds **near-identically** to HDFC Large
Cap — the wrong chunk scores 0.88. Without the scope guard the assistant would
answer with Large Cap's 1.03% and cite the Large Cap page: confidently wrong,
correctly formatted, wrongly cited. It refuses instead.

---

## Acceptance criteria covered

| Criterion | Rows |
|---|---|
| AT-1 expense ratio | 1 |
| AT-2 exit load | 2 |
| AT-3 lock-in | 3, 10 |
| AT-4 minimum SIP | 4 |
| AT-5 benchmark | 5, 11 |
| AT-6 advice refusal | 6 |
| AT-7 performance refusal | 7 |
| AT-8 PII | 8 |
| AT-9 statutory document | 9 |
| Out-of-scope scheme (not in the AT table) | 12 |

AT-10 (corpus coverage), AT-11 (answer policy) and AT-12 (no PII, no performance
figures in the corpus) are properties of the corpus and of every answer, so they
are asserted across the suite in `tests/test_acceptance.py` rather than
demonstrated by a single example.