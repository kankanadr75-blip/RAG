"""Run the full Phase 0-4 verification suite in one go.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/verify_all.py
Exits non-zero if any phase fails.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASES = [
    ("Phase 0 - scaffolding & config", "scripts/debug_config.py"),
    ("Phase 2 - Extractor A (fact cards)", "scripts/debug_facts.py"),
    ("Phase 3 - Extractor B (prose)", "scripts/debug_prose.py"),
    ("Phase 4 - guardrails PII", "scripts/debug_guardrails.py"),
    ("Phase 5 - embed + store", "scripts/debug_store.py"),
    ("Phase 6 - online guardrails", "scripts/debug_online_guardrails.py"),
    ("Phase 7 - retrieval", "scripts/debug_retrieval.py"),
    ("Phase 7b - terse query stress", "scripts/stress_terse_queries.py"),
    ("Phase 8 - generation & citations", "scripts/debug_generation.py"),
    ("Phase 9 - Streamlit UI", "scripts/debug_ui.py"),
    ("Context dilution at TOP_K", "scripts/check_context_dilution.py"),
]

# Corpus-level audits performed directly on the dumps.
CORPUS_BANNED = {
    "return/ranking figure": r"annualised return|\b\d+Y\s+annualised\b|returns and rankings|"
                             r"fund returns|absolute returns|category average|Rank \(|"
                             r"compare similar funds",
    "e-mail address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phone number": r"\b\d{2}\s*[–—-]\s*\d{8}\b",
    "PAN": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    "aadhaar-like": r"\b\d{12}\b",
    "postal address": r"Anna Salai|Sarjapur|Backbay|Churchgate|Rayala Towers",
    "fund-manager name": r"Prashant Jain|Rahul Baijal|Dhruv Muchhal|"
                         r"Amar Kalkundrikar|Chirag Setalvad|Srinivas Rao Ravuri|"
                         r"Vinay Kulkarni",
    "AMC-level AUM": r"9,86,2|Total AUM",
}


def run(label: str, script: str) -> bool:
    print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
    proc = subprocess.run(
        [sys.executable, str(ROOT / script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(proc.stdout or "")
    if proc.returncode != 0:
        print(proc.stderr or "")
    return proc.returncode == 0


def audit_dumps() -> bool:
    print(f"\n{'=' * 78}\nCorpus audit - data/chunks.txt\n{'=' * 78}")
    ok = True
    path = ROOT / "data" / "chunks.txt"
    if not path.exists():
        print("  [FAIL] data/chunks.txt missing - run `python ingest.py --no-embed`")
        return False

    text = path.read_text(encoding="utf-8")
    for label, pattern in CORPUS_BANNED.items():
        hits = re.findall(pattern, text, flags=re.I)
        status = "OK" if not hits else "FAIL"
        if hits:
            ok = False
        print(f"  [{status}] no {label:<22} ({len(hits)} hit(s))")

    n_txt = len(re.findall(r"^\[\d{4}\] ", text, flags=re.M))
    jsonl = ROOT / "data" / "chunks.jsonl"
    n_jsonl = sum(1 for _ in jsonl.open(encoding="utf-8")) if jsonl.exists() else 0
    match = n_txt == n_jsonl and n_txt > 0
    if not match:
        ok = False
    print(f"  [{'OK' if match else 'FAIL'}] dump counts agree: "
          f"chunks.txt={n_txt} chunks.jsonl={n_jsonl}")
    return ok


def main() -> int:
    results: list[tuple[str, bool]] = []
    for label, script in PHASES:
        results.append((label, run(label, script)))
    results.append(("Corpus audit", audit_dumps()))

    print(f"\n{'=' * 78}\nSUMMARY - Phases 0 to 4\n{'=' * 78}")
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    failed = [l for l, p in results if not p]
    print(f"\n  {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
