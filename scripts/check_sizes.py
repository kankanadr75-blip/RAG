"""Check chunk-size outliers: which chunks exceed config.CHUNK_SIZE and why."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

rows = [
    json.loads(line)
    for line in Path("data/chunks.jsonl").open(encoding="utf-8")
]

over = [r for r in rows if r["char_len"] > config.CHUNK_SIZE]
print(f"CHUNK_SIZE = {config.CHUNK_SIZE}, hard limit = {config.CHUNK_SIZE + 40}")
print(f"chunks over CHUNK_SIZE: {len(over)} of {len(rows)}")
print(f"chunks over hard limit: {sum(1 for r in rows if r['char_len'] > config.CHUNK_SIZE + 40)}")
print()

for r in sorted(over, key=lambda x: -x["char_len"]):
    print(f"--- {r['char_len']} chars | {r['producer']} | {r['section']} | {r['scheme_slug'][:34]}")
    print(f"    {r['text'][:150]}")
    print()

print("\nby producer:")
from collections import Counter  # noqa: E402

print("  over CHUNK_SIZE:", Counter(r["producer"] for r in over))
print("  over hard limit:", Counter(r["producer"] for r in rows if r["char_len"] > config.CHUNK_SIZE + 40))
