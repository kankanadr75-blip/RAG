"""Check SIP bounds, the visible risk badge, and statement/download mentions."""

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

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
    nd = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, flags=re.S).group(1))
    d = nd["props"]["pageProps"]["mfServerSideData"]
    print("=" * 70)
    print(slug)
    for k in [
        "min_sip_investment", "max_sip_investment", "min_withdrawal",
        "sip_multiplier", "purchase_multiplier", "mini_additional_investment",
        "nav_date", "portfolio_turnover", "base_expense_ratio",
        "sid_url", "amc_page_url", "additional_details", "dividend",
        "doc_required", "sip_allowed", "lumpsum_allowed",
    ]:
        print(f"   {k:<26} = {str(d.get(k))[:120]!r}")

    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    txt = re.sub(r"\n{2,}", "\n", soup.get_text("\n"))
    print("   -- risk badge candidates --")
    for m in re.finditer(r"^\s*(Very High|High|Moderately High|Moderate|Low)\s*Risk\s*$", txt, flags=re.M):
        print("      badge:", repr(m.group(0)))
    print("   -- 'About' prose --")
    i = txt.find("About")
    if i > 0:
        print("     ", re.sub(r"\s+", " ", txt[i : i + 700]))
