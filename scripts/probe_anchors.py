"""Probe: locate exact anchor positions in the rendered visible text."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup  # noqa: E402
import config  # noqa: E402

ANCHORS = [
    "Minimum investments", "Understand terms", "Exit load", "Exit Load",
    "Exit load, stamp duty and tax", "Tax implication", "Stamp duty on investment",
    "Investment Objective", "Fund benchmark", "Scheme Information Document(SID)",
    "Custodian", "Registrar & Transfer Agent", "Expense ratio", "About",
    "Fund management", "Returns and rankings", "Annualised returns",
    "Absolute returns", "Tax", "Stamp duty", "View details",
]

src = config.SOURCES[0]
html = (config.RAW_DIR / f"{src['slug']}.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "lxml")
for t in soup(["script", "style", "noscript"]):
    t.decompose()
lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if len(ln.strip()) > 1]

print(f"{src['slug']}: {len(lines)} visible lines\n")
for a in ANCHORS:
    hits = [i for i, ln in enumerate(lines) if ln == a or ln.startswith(a)]
    print(f"{a!r:<40} -> {hits[:8]}")
    for i in hits[:2]:
        lo, hi = max(0, i), min(len(lines), i + 9)
        print("      ctx:", " | ".join(lines[lo:hi])[:230])

print("\n\n### risk badge line indices")
for i, ln in enumerate(lines):
    if re.fullmatch(r"(Very High|High|Moderately High|Moderate|Low)\s*Risk", ln):
        print(f"  idx={i}: {ln!r}  prev={lines[i-1][:50]!r}")

print("\n### long paragraphs (candidate prose, len>120)")
for i, ln in enumerate(lines):
    if len(ln) > 120:
        print(f"  idx={i}: {ln[:190]}")
