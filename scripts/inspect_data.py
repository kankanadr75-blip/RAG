"""Probe script: inspect raw HTML from the 5 Groww HDFC pages.

Purpose: before writing any chunking code, understand what text actually lives
in each page so the chunking strategy can be chosen against real evidence.
Run:  python scripts/inspect_data.py
"""

import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import SOURCES, RAW_DIR, USER_AGENT  # noqa: E402

KEYWORDS = [
    "Expense ratio",
    "Exit load",
    "Lock-in",
    "Minimum investments",
    "Min. for SIP",
    "Fund benchmark",
    "Very High Risk",
    "Riskometer",
    "Investment Objective",
    "AUM",
    "Stamp duty",
    "Tax implication",
    "SID",
]


def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=45)
    r.raise_for_status()
    return r.text


def visible_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    raw = soup.get_text("\n")
    return [ln.strip() for ln in raw.split("\n") if len(ln.strip()) > 1]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for src in SOURCES:
        slug = src["slug"]
        cache = RAW_DIR / f"{slug}.html"
        if cache.exists():
            html = cache.read_text(encoding="utf-8")
            note = "cached"
        else:
            html = fetch(src["url"])
            cache.write_text(html, encoding="utf-8")
            note = "fetched"

        lines = visible_lines(html)
        print("=" * 78)
        print(f"{src['name']}  [{note}]  html={len(html)}B  visible_lines={len(lines)}")

        joined = "\n".join(lines)
        for kw in KEYWORDS:
            hits = len(re.findall(re.escape(kw), joined, flags=re.I))
            raw_hits = len(re.findall(re.escape(kw), html, flags=re.I))
            print(f"   {kw:<22} visible={hits:<4} raw_html={raw_hits}")

        # Show the window around 'Expense ratio' to learn if a value sits next to it.
        m = re.search(r"Expense ratio", html, flags=re.I)
        if m:
            snippet = re.sub(r"\s+", " ", html[m.start() - 150 : m.start() + 400])
            print("   [expense-ratio raw window]", snippet[:520])


if __name__ == "__main__":
    main()
