"""Explore the __NEXT_DATA__ JSON tree to find structured per-scheme facts."""

import json
import re
from collections import Counter
from pathlib import Path

RAW = Path("data/raw")


def load_nd(slug: str):
    html = (RAW / f"{slug}.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, flags=re.S)
    return json.loads(m.group(1))


nd = load_nd("hdfc-large-cap-fund-direct-growth")
print("top keys:", list(nd.keys()))
props = nd["props"]
print("props keys:", list(props.keys()))
pp = props["pageProps"]
print("pageProps keys:", list(pp.keys()))

# Walk the tree, report the shape (dict keys -> types) to depth 5
def shape(node, path="", depth=0, maxd=5):
    if depth > maxd:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            t = type(v).__name__
            extra = ""
            if isinstance(v, list):
                extra = f"[len={len(v)}]"
                if v and isinstance(v[0], dict):
                    extra += " keys=" + ",".join(list(v[0].keys())[:9])
            elif isinstance(v, dict):
                extra = " {" + ",".join(list(v.keys())[:9]) + "}"
            elif isinstance(v, str):
                extra = f" = {v[:60]!r}"
            else:
                extra = f" = {v}"
            print("  " * depth + f"{k}:{t}{extra}")
            if isinstance(v, dict):
                shape(v, path + "/" + k, depth + 1, maxd)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                shape(v[0], path + "/" + k + "[]", depth + 1, maxd)


shape(pp, maxd=3)

print("\n### analysis_subject value counts across all 5 pages")
subs = Counter()
for slug in [
    "hdfc-large-cap-fund-direct-growth",
    "hdfc-equity-fund-direct-growth",
    "hdfc-elss-tax-saver-fund-direct-plan-growth",
    "hdfc-small-cap-fund-direct-growth",
    "hdfc-balanced-advantage-fund-direct-growth",
]:
    blob = (RAW / f"{slug}.html").read_text(encoding="utf-8")
    for s, d in re.findall(r'"analysis_subject":"([^"]+)","analysis_desc":"([^"]+)"', blob):
        subs[s] += 1
for s, c in subs.most_common():
    print(f"  {s:<28} {c}")
