# Source list

All 5 sources are public **Groww** scheme pages for a single AMC, **HDFC Mutual Fund**, and all are the **Direct Growth** plan. There are no other sources: nothing is drawn from third-party blogs, forums, aggregators or news articles, and no screenshot of any back-end system is used.

Facts are as published on **30-Sep-2026**. Ingestion is run once and cached under `data/raw/`; `python ingest.py --refresh` re-fetches the pages and updates `as_of`.

Static facts (expense ratio, exit load, lock-in, minimum investment, benchmark, riskometer) appear only in each page's `__NEXT_DATA__` payload, not in the rendered HTML. A text-only scrape of these pages misses both the expense ratio and the lock-in period.

| # | Scheme | Category | Plan | Scheme code | Facts as of | URL |
|---|--------|----------|------|-------------|--------------|-----|
| 1 | HDFC Large Cap Fund - Direct Growth | Large Cap | Direct Growth | 119018 | 30-Sep-2026 | <https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth> |
| 2 | HDFC Flexi Cap Fund - Direct Growth | Flexi Cap | Direct Growth | 118955 | 30-Sep-2026 | <https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth> |
| 3 | HDFC ELSS Tax Saver Fund - Direct Growth | ELSS | Direct Growth | 119060 | 30-Sep-2026 | <https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth> |
| 4 | HDFC Small Cap Fund - Direct Growth | Small Cap | Direct Growth | 130503 | 30-Sep-2026 | <https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth> |
| 5 | HDFC Balanced Advantage Fund - Direct Growth | Balanced Advantage (Hybrid) | Direct Growth | 118968 | 30-Sep-2026 | <https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth> |

## Per-scheme detail

**1. HDFC Large Cap Fund - Direct Growth**  
<https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth>  
Ingested: `2026-10-01T17:36:58+00:00` · Facts as of: `30-Sep-2026`  
Benchmark NIFTY 100 TRI. ER 1.03% (base 0.84%). Exit load 1% within 1 year. No lock-in. Minimum SIP 100. Riskometer: Very High.

**2. HDFC Flexi Cap Fund - Direct Growth**  
<https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth>  
Ingested: `2026-10-01T17:36:59+00:00` · Facts as of: `30-Sep-2026`  
Flexi Cap - the page slug predates the rename and still says 'equity'. Benchmark NIFTY 500 TRI. ER 0.77% (base 0.57%). Exit load 1% within 1 year. No lock-in. Minimum SIP 100.

**3. HDFC ELSS Tax Saver Fund - Direct Growth**  
<https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth>  
Ingested: `2026-10-01T17:36:59+00:00` · Facts as of: `30-Sep-2026`  
The only one of the five with a lock-in (3 years). Benchmark NIFTY 500 TRI. ER 1.21% (base 0.97%). Exit load Nil. Minimum SIP 500, the only scheme that differs.

**4. HDFC Small Cap Fund - Direct Growth**  
<https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth>  
Ingested: `2026-10-01T17:36:59+00:00` · Facts as of: `30-Sep-2026`  
The only scheme not benchmarked to a NIFTY index (BSE 250 SmallCap TRI). ER 0.78%. Exit load 1% within 1 year. No lock-in. Minimum SIP 100.

**5. HDFC Balanced Advantage Fund - Direct Growth**  
<https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth>  
Ingested: `2026-10-01T17:36:59+00:00` · Facts as of: `30-Sep-2026`  
Hybrid, not equity - benchmark NIFTY 50 Hybrid Composite Debt 50:50. ER 0.78%. Exit load applies only to units above 15% of the investment, 1% within 1 year. No lock-in. Minimum SIP 100.

## Coverage

- Ingested chunks: **130** across 5 pages (80 fact cards + 50 prose sections).
- Registered transfer agent for all five: **CAMS**.
- Educational links in refusals (SEBI, AMFI, HDFC AMC) are **referrals, not sources** - no answer is built from them.

Machine-readable version: [`sources.csv`](sources.csv).
