"""Corpus statistics for the built Phase 0-4 corpus."""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest import COVERAGE_MAP  # noqa: E402

rows = [
    json.loads(line)
    for line in (Path("data/chunks.jsonl")).open(encoding="utf-8")
]

print(f"TOTAL CHUNKS: {len(rows)}\n")

print("--- by producer ---")
for k, v in Counter(r["producer"] for r in rows).most_common():
    print(f"  {k:<16}{v:>4}")

print("\n--- by section ---")
for k, v in Counter(r["section"] for r in rows).most_common():
    print(f"  {k:<28}{v:>4}")

print("\n--- by scheme ---")
for k, v in Counter(r["category"] for r in rows).most_common():
    print(f"  {k:<28}{v:>4}")

lens = [r["char_len"] for r in rows]
print("\n--- chunk size ---")
print(f"  min={min(lens)}  max={max(lens)}  mean={sum(lens) // len(lens)}")

print("\n--- metadata integrity ---")
required = [
    "chunk_id", "source_url", "source_name", "amc", "scheme_slug",
    "scheme_name", "scheme_code", "category", "section", "producer",
    "extracted_from", "as_of", "ingested_at", "char_len", "content_hash",
]
missing = [f for f in required if any(f not in r for r in rows)]
print(f"  all {len(required)} metadata fields present on every chunk: {not missing}")
if missing:
    print(f"  missing: {missing}")
print(f"  distinct source_urls: {len({r['source_url'] for r in rows})}")
print(f"  every chunk carries a source_url: {all(r.get('source_url') for r in rows)}")
print(f"  unique chunk_ids: {len({r['chunk_id'] for r in rows})} == {len(rows)}")

print("\n--- the 7 target facts, per scheme ---")
for scheme in dict.fromkeys(r["scheme_slug"] for r in rows):
    secs = {r["section"] for r in rows if r["scheme_slug"] == scheme}
    marks = []
    for fact, allowed in COVERAGE_MAP.items():
        marks.append(f"{fact}={'Y' if secs & allowed else 'N'}")
    print(f"  {scheme[:44]:<46}{' '.join(marks)}")
