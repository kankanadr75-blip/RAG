"""Extract the numeric values behind expense_ratio / lock-in / riskometer."""

import json
import re
from pathlib import Path

RAW = Path("data/raw")
SLUGS = [
    "hdfc-large-cap-fund-direct-growth",
    "hdfc-equity-fund-direct-growth",
    "hdfc-elss-tax-saver-fund-direct-plan-growth",
    "hdfc-small-cap-fund-direct-growth",
    "hdfc-balanced-advantage-fund-direct-growth",
]

for slug in SLUGS:
    html = (RAW / f"{slug}.html").read_text(encoding="utf-8")
    print("=" * 70)
    print(slug)

    # expense_ratio / base_expense_ratio -> number that follows
    vals = re.findall(r'"(?:base_)?expense_ratio"\s*:\s*([0-9.]+|null)', html)
    uniq = sorted({v for v in vals if v not in ("null",)})
    print("  expense_ratio candidates:", uniq[:12])

    # riskometer text
    rk = set(re.findall(r'"(?:riskometer|risk_level|riskometer_level)"\s*:\s*"([^"]{0,40})"', html))
    print("  risk keys:", rk)

    # lock-in
    lk = set(re.findall(r'"[^"]*lock[^"]*"\s*:\s*"?([^",}]{0,60})', html, flags=re.I))
    print("  lock keys:", list(lk)[:6])

    # Any long prose that mentions lock-in (ELSS FAQ-ish copy)
    if "elss" in slug:
        for m in re.finditer(r"[Ll]ock-?[Ii]n period", html):
            w = re.sub(r"\\+", " ", re.sub(r"\s+", " ", html[max(0, m.start() - 260) : m.start() + 260]))
            print("  LOCKIN PROSE:", w[:480])
            break

    # __NEXT_DATA__ presence
    nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, flags=re.S)
    print("  __NEXT_DATA__:", "yes" if nd else "no", len(nd.group(1)) if nd else 0)
