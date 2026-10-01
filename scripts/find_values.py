"""Locate the *values* for expense ratio / lock-in / riskometer inside raw HTML."""

import re
from pathlib import Path

html = Path("data/raw/hdfc-large-cap-fund-direct-growth.html").read_text(encoding="utf-8")

print("### expense_ratio-ish keys")
for m in re.finditer(r'[^"]*[Ee]xpense[_ ]?[Rr]atio[^"]*"', html):
    print(repr(m.group(0))[:160])

print("\n### windows around every 'Expense ratio' (raw, script data)")
seen = set()
for m in re.finditer(r"Expense ratio", html):
    w = re.sub(r"\s+", " ", html[max(0, m.start() - 60) : m.start() + 260])
    if w[:80] in seen:
        continue
    seen.add(w[:80])
    print("->", w[:320])

print("\n### riskometer")
for m in re.finditer(r"[Rr]iskometer", html):
    print(repr(re.sub(r"\s+", " ", html[max(0, m.start() - 150) : m.start() + 300]))[:460])

elss = Path("data/raw/hdfc-elss-tax-saver-fund-direct-plan-growth.html").read_text(encoding="utf-8")
print("\n### ELSS lock-in windows")
for m in re.finditer(r"[Ll]ock-?[Ii]n", elss):
    print(repr(re.sub(r"\s+", " ", elss[max(0, m.start() - 200) : m.start() + 300]))[:520])
