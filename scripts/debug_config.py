"""Phase 0 verification: config, secrets handling, gitignore.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/debug_config.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

failures: list[str] = []

print("=" * 78)
print("PHASE 0 VERIFICATION - scaffolding & config")
print("=" * 78)

# --- config values match the documented pipeline --------------------------
EXPECTED = {
    "SOURCES": 5,
    "CHUNK_SIZE": 380,
    "CHUNK_OVERLAP": 80,
    "MIN_CHUNK_CHARS": 40,
    "MIN_LINE_CHARS": 2,
    "EMBED_DIM": 384,
    "TOP_K": 10,
}
for name, want in EXPECTED.items():
    got = getattr(config, name)
    got = len(got) if name == "SOURCES" else got
    ok = got == want
    print(f"  [{'OK' if ok else 'FAIL'}] {name:<16} = {got!r} (want {want!r})")
    if not ok:
        failures.append(f"{name} = {got!r}, want {want!r}")

ok = config.EMBED_MODEL == "sentence-transformers/all-MiniLM-L6-v2"
print(f"  [{'OK' if ok else 'FAIL'}] EMBED_MODEL       = {config.EMBED_MODEL}")
if not ok:
    failures.append("unexpected EMBED_MODEL")

ok = bool(config.COLLECTION_NAME)
print(f"  [{'OK' if ok else 'FAIL'}] COLLECTION_NAME   = {config.COLLECTION_NAME}")
if not ok:
    failures.append("COLLECTION_NAME empty")

ok = len(config.SOURCE_BY_SLUG) == 5
print(f"  [{'OK' if ok else 'FAIL'}] SOURCE_BY_SLUG indexed by slug ({len(config.SOURCE_BY_SLUG)})")
if not ok:
    failures.append("SOURCE_BY_SLUG incomplete")

ok = bool(config.DISCLAIMER) and "no investment advice" in config.DISCLAIMER.lower()
print(f"  [{'OK' if ok else 'FAIL'}] DISCLAIMER states 'no investment advice'")
if not ok:
    failures.append("DISCLAIMER missing the facts-only wording")

ok = len(config.REFUSAL_PATTERNS) >= 10 and len(config.EDUCATIONAL_LINKS) >= 3
print(f"  [{'OK' if ok else 'FAIL'}] guardrail assets: "
      f"{len(config.REFUSAL_PATTERNS)} patterns, "
      f"{len(config.EDUCATIONAL_LINKS)} edu links")
if not ok:
    failures.append("guardrail assets incomplete")

# --- every source URL is an https groww.in page ---------------------------
for src in config.SOURCES:
    if not src["url"].startswith("https://groww.in/mutual-funds/"):
        failures.append(f"non-Groww source URL: {src['url']}")
    for key in ("slug", "name", "category", "url"):
        if key not in src:
            failures.append(f"source missing {key!r}")
ok = not any("non-Groww" in f or "source missing" in f for f in failures)
print(f"  [{'OK' if ok else 'FAIL'}] all 5 sources are public groww.in pages with full metadata")

# --- files exist -----------------------------------------------------------
ok = 0.42 < config.MIN_SIMILARITY <= 0.66
print(f"  [{'OK' if ok else 'FAIL'}] MIN_SIMILARITY     = {config.MIN_SIMILARITY} "
      f"(calibrated; must sit in the measured gap (0.42, 0.66])")
if not ok:
    failures.append(
        f"MIN_SIMILARITY={config.MIN_SIMILARITY} outside the calibrated gap; "
        f"re-run scripts/calibrate_floor.py"
    )

for rel in ("requirements.txt", ".gitignore", ".env.example", "ingest.py",
            "guardrails.py", "rag.py", "app.py"):
    exists = (ROOT / rel).exists()
    print(f"  [{'OK' if exists else 'FAIL'}] {rel} exists")
    if not exists:
        failures.append(f"missing {rel}")

# --- secrets: .env must be ignored, .env.example tracked ------------------
def ignored(path: str) -> bool:
    proc = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=ROOT, capture_output=True, text=True,
    )
    return proc.returncode == 0

ok = ignored(".env")
print(f"  [{'OK' if ok else 'FAIL'}] .env is git-ignored")
if not ok:
    failures.append(".env is NOT git-ignored")

ok = not ignored(".env.example")
print(f"  [{'OK' if ok else 'FAIL'}] .env.example is tracked (not ignored)")
if not ok:
    failures.append(".env.example should be tracked")

ok = ignored("data/chroma")
print(f"  [{'OK' if ok else 'FAIL'}] data/chroma is git-ignored (regenerable)")
if not ok:
    failures.append("data/chroma should be ignored")

for keep in ("data/raw", "data/chunks.txt"):
    ok = not ignored(keep)
    print(f"  [{'OK' if ok else 'FAIL'}] {keep} is tracked (audit trail)")
    if not ok:
        failures.append(f"{keep} must stay tracked")

# --- no secret material committed -----------------------------------------
env = ROOT / ".env"
if env.exists():
    leaked = [
        ln for ln in env.read_text(encoding="utf-8").splitlines()
        if ln.startswith("GROQ_API_KEY=") and ln.split("=", 1)[1].strip()
    ]
    print(f"  [OK] .env holds no live key value "
          f"(GROQ_API_KEY set locally: {'yes' if leaked else 'no'})")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 0 ASSERTIONS PASSED")
print("=" * 78)
