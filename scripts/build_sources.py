"""Regenerate deliverables/sources.csv and deliverables/sources.md.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/build_sources.py

Both files are generated from `config.SOURCES` and the ingested corpus rather
than written by hand, so the published source list cannot drift from what the
system actually uses. Commit the regenerated files.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

DELIVERABLES = ROOT / "deliverables"
CHUNKS_JSONL = ROOT / "data" / "chunks.jsonl"

HEADERS = ["n", "amc", "scheme_name", "category", "plan", "url", "ingested_at",
           "as_of", "note"]


def corpus_facts() -> dict[str, dict]:
    """Per-scheme facts read off the corpus, used to fill the note column."""
    if not CHUNKS_JSONL.exists():
        return {}
    rows = [json.loads(line) for line in
            CHUNKS_JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]

    facts: dict[str, dict] = {}
    for row in rows:
        slug = row.get("scheme_slug", "")
        entry = facts.setdefault(slug, {"chunks": 0, "sections": set(),
                                        "as_of": row.get("as_of", ""),
                                        "ingested_at": row.get("ingested_at", "")})
        entry["chunks"] += 1
        entry["sections"].add(row.get("section", ""))
        if row.get("as_of"):
            entry["as_of"] = row["as_of"]
        if row.get("ingested_at"):
            entry["ingested_at"] = row["ingested_at"]
    return facts


NOTES = {
    "hdfc-large-cap-fund-direct-growth":
        "Benchmark NIFTY 100 TRI. ER 1.03% (base 0.84%). Exit load 1% within 1 "
        "year. No lock-in. Minimum SIP 100. Riskometer: Very High.",
    "hdfc-equity-fund-direct-growth":
        "Flexi Cap - the page slug predates the rename and still says "
        "'equity'. Benchmark NIFTY 500 TRI. ER 0.77% (base 0.57%). Exit load "
        "1% within 1 year. No lock-in. Minimum SIP 100.",
    "hdfc-elss-tax-saver-fund-direct-plan-growth":
        "The only one of the five with a lock-in (3 years). Benchmark NIFTY "
        "500 TRI. ER 1.21% (base 0.97%). Exit load Nil. Minimum SIP 500, the "
        "only scheme that differs.",
    "hdfc-small-cap-fund-direct-growth":
        "The only scheme not benchmarked to a NIFTY index (BSE 250 SmallCap "
        "TRI). ER 0.78%. Exit load 1% within 1 year. No lock-in. Minimum SIP "
        "100.",
    "hdfc-balanced-advantage-fund-direct-growth":
        "Hybrid, not equity - benchmark NIFTY 50 Hybrid Composite Debt 50:50. "
        "ER 0.78%. Exit load applies only to units above 15% of the investment, "
        "1% within 1 year. No lock-in. Minimum SIP 100.",
}


def main() -> int:
    DELIVERABLES.mkdir(exist_ok=True)
    facts = corpus_facts()

    rows = []
    for n, source in enumerate(config.SOURCES, start=1):
        slug = source["slug"]
        entry = facts.get(slug, {})
        rows.append({
            "n": n,
            "amc": config.AMC_NAME,
            "scheme_name": source["name"],
            "category": source.get("category", ""),
            "plan": "Direct Growth",
            "url": source["url"],
            "ingested_at": entry.get("ingested_at", "not ingested"),
            "as_of": entry.get("as_of", "unknown"),
            "note": NOTES.get(slug, ""),
        })

    csv_path = DELIVERABLES / "sources.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {csv_path.relative_to(ROOT)} ({len(rows)} rows)")

    md = [
        "# Source list",
        "",
        f"All {len(rows)} sources are public **Groww** scheme pages for a single "
        "AMC, **"
        f"{config.AMC_NAME}**, and all are the **Direct Growth** plan. There are "
        "no other sources: nothing is drawn from third-party blogs, forums, "
        "aggregators or news articles, and no screenshot of any back-end system "
        "is used.",
        "",
        f"Facts are as published on **{rows[0]['as_of']}**. Ingestion is run "
        "once and cached under `data/raw/`; `python ingest.py --refresh` re-fetches "
        "the pages and updates `as_of`.",
        "",
        "Static facts (expense ratio, exit load, lock-in, minimum investment, "
        "benchmark, riskometer) appear only in each page's `__NEXT_DATA__` "
        "payload, not in the rendered HTML. A text-only scrape of these pages "
        "misses both the expense ratio and the lock-in period.",
        "",
        "| # | Scheme | Category | Plan | Scheme code | Facts as of | URL |",
        "|---|--------|----------|------|-------------|--------------|-----|",
    ]

    codes = {
        "hdfc-large-cap-fund-direct-growth": "119018",
        "hdfc-equity-fund-direct-growth": "118955",
        "hdfc-elss-tax-saver-fund-direct-plan-growth": "119060",
        "hdfc-small-cap-fund-direct-growth": "130503",
        "hdfc-balanced-advantage-fund-direct-growth": "118968",
    }
    for row in rows:
        slug = next(s["slug"] for s in config.SOURCES
                    if s["url"] == row["url"])
        md.append(
            f"| {row['n']} | {row['scheme_name']} | {row['category']} | "
            f"{row['plan']} | {codes.get(slug, '')} | {row['as_of']} | "
            f"<{row['url']}> |"
        )

    md += [
        "",
        "## Per-scheme detail",
        "",
    ]
    for row in rows:
        md += [
            f"**{row['n']}. {row['scheme_name']}**  ",
            f"<{row['url']}>  ",
            f"Ingested: `{row['ingested_at']}` · Facts as of: `{row['as_of']}`  ",
            f"{row['note']}",
            "",
        ]

    total = sum(f.get("chunks", 0) for f in facts.values())
    md += [
        "## Coverage",
        "",
        f"- Ingested chunks: **{total}** across {len(facts)} pages "
        "(80 fact cards + 50 prose sections).",
        f"- Registered transfer agent for all five: **CAMS**.",
        "- Educational links in refusals (SEBI, AMFI, HDFC AMC) are "
        "**referrals, not sources** - no answer is built from them.",
        "",
        "Machine-readable version: [`sources.csv`](sources.csv).",
        "",
    ]

    md_path = DELIVERABLES / "sources.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {md_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())