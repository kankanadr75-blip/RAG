"""Dump every scalar field of mfServerSideData for each of the 5 schemes."""

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

INTERESTING = [
    "scheme_code", "scheme_name", "amc", "fund_house", "sub_category", "category",
    "benchmark", "benchmark_name", "exit_load", "nfo_risk", "min_investment_amount",
    "launch_date", "fund_manager", "description", "aum", "nav", "expense_ratio",
    "lock_in", "riskometer", "status", "isin", "rta_scheme_code", "groww_rating",
    "tax", "stamp_duty", "sip_multiplier", "facility", "plan_type",
]

for slug in SLUGS:
    html = (RAW / f"{slug}.html").read_text(encoding="utf-8")
    nd = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, flags=re.S).group(1))
    d = nd["props"]["pageProps"]["mfServerSideData"]
    print("=" * 78)
    print(f"{slug}   ({len(d)} keys)")
    print("-" * 78)
    for k in INTERESTING:
        if k in d:
            v = d[k]
            print(f"  {k:<24} = {str(v)[:150]!r}")
    missing = [k for k in INTERESTING if k not in d]
    if missing:
        print("  [absent]", ", ".join(missing))
    # show all keys not in INTERESTING for discovery
    other = [k for k in d if k not in INTERESTING and not isinstance(d[k], (dict, list))]
    print("  [other scalars]", ", ".join(other[:45]))
