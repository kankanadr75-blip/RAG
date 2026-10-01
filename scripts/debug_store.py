"""Phase 5 verification: embed + persist + idempotency.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/debug_store.py
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402

import config  # noqa: E402
from ingest import build_chunks, embed_and_store  # noqa: E402

failures: list[str] = []

print("=" * 78)
print("PHASE 5 VERIFICATION - embed + ChromaDB persist")
print("=" * 78)

chunks, _stats = build_chunks()
print(f"\n  corpus: {len(chunks)} chunks")

print("\n-- first store --")
embed_and_store(chunks)

client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
col = client.get_or_create_collection(
    config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
)
count_1 = col.count()
print(f"  collection count after first store: {count_1}")
ok = count_1 == len(chunks)
print(f"  [{'OK' if ok else 'FAIL'}] count == corpus size ({count_1} vs {len(chunks)})")
if not ok:
    failures.append(f"count {count_1} != {len(chunks)}")

print("\n-- embedding dimension --")
probe = col.get(limit=1, include=["embeddings", "documents", "metadatas"])
emb = probe["embeddings"][0]
dim = len(emb)
ok = dim == config.EMBED_DIM
print(f"  [{'OK' if ok else 'FAIL'}] stored vector dim = {dim} (want {config.EMBED_DIM})")
if not ok:
    failures.append(f"dim {dim} != {config.EMBED_DIM}")

print("\n-- metadata round-trip --")
meta = probe["metadatas"][0]
required = [
    "chunk_id", "source_url", "scheme_slug", "scheme_name", "section",
    "producer", "extracted_from", "as_of", "char_len", "content_hash",
]
missing = [f for f in required if f not in meta or meta[f] in (None, "")]
print(f"  [{'OK' if not missing else 'FAIL'}] metadata fields survive the round-trip"
      + (f" (missing {missing})" if missing else ""))
if missing:
    failures.append(f"metadata lost in Chroma: {missing}")

print(f"  chunk_id    = {meta['chunk_id']}")
print(f"  source_url  = {meta['source_url']}")

print("\n-- cosine similarity behaves (closer text scores higher) --")
res = col.query(
    query_texts=["expense ratio of HDFC ELSS Tax Saver Fund"],
    n_results=3,
    include=["documents", "metadatas", "distances"],
)
docs = res["documents"][0]
dists = res["distances"][0]
secs = [d["section"] for d in res["metadatas"][0]]
best_section = secs[0]
ok = best_section in ("expense_ratio", "expense_ratio_definition")
print(f"  top hit section = {best_section}  (distances {[round(d,3) for d in dists]})")
print(f"  [{'OK' if ok else 'WARN'}] 'expense ratio' retrieves the expense_ratio chunk first")
if not ok:
    print("       NOTE: raw Chroma text query uses its own embedder, NOT MiniLM.")
    print("       This probe only sanity-checks the store; real retrieval uses")
    print("       RAGEngine.retrieve() with the configured MiniLM vectors (Phase 7).")

print("\n-- idempotency: re-store must not duplicate --")
embed_and_store(chunks)
count_2 = col.count()
ok = count_2 == count_1
print(f"  [{'OK' if ok else 'FAIL'}] count unchanged after re-store "
      f"({count_1} -> {count_2})")
if not ok:
    failures.append(f"re-store changed count {count_1} -> {count_2}")

print("\n-- persistence on disk --")
ok = config.CHROMA_DIR.exists() and any(config.CHROMA_DIR.iterdir())
print(f"  [{'OK' if ok else 'FAIL'}] {config.CHROMA_DIR} exists and is non-empty")
if not ok:
    failures.append("chroma dir missing/empty")

print("\n-- fresh client sees the same data (survives restart) --")
del client, col
client2 = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
col2 = client2.get_or_create_collection(
    config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
)
ok = col2.count() == count_1
print(f"  [{'OK' if ok else 'FAIL'}] fresh client count = {col2.count()}")
if not ok:
    failures.append("data did not survive a new client")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 5 ASSERTIONS PASSED")
print("=" * 78)
