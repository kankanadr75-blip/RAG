"""Phase 3 verification: assert Extractor B against deliverables/implementation.md.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/debug_prose.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from ingest import (  # noqa: E402
    extract_prose,
    load_pages,
    split_section,
    CHUNK_HARD_LIMIT as MAX_SIZE,
)

PII_PATTERNS = [
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",   # e-mail
    r"\b\d{2}\s*[–-]\s*\d{8}\b",                          # phone e.g. 022 - 66316333
    r"\b\d{12}\b",                                        # aadhaar-like
    r"[A-Z]{5}[0-9]{4}[A-Z]",                             # PAN
]

BOILERPLATE = [
    "Download the App", "Trust & Safety", "Media & Press", "All rights reserved",
    "Sarjapur Main Road", "Anna Salai", "Prior to joining", "PGDM",
]

failures: list[str] = []
pages = load_pages()

print("\n" + "=" * 78)
print("PHASE 3 VERIFICATION - Extractor B (labelled prose sections)")
print("=" * 78)

all_chunks = []
for src in config.SOURCES:
    chunks = extract_prose(src, pages[src["slug"]])
    all_chunks += chunks
    sections = sorted({c.section for c in chunks})
    print(f"\n{src['slug']}")
    print(f"  {len(chunks)} prose chunks | sections: {', '.join(sections)}")

    # 0. all 10 sections resolved, including the 4 glossary definitions
    expected_sections = {
        "minimum_investments", "exit_load_stamp_duty_tax", "investment_objective",
        "fund_benchmark", "scheme_details", "riskometer",
        "expense_ratio_definition", "tax_definition",
        "exit_load_definition", "stamp_duty_definition",
    }
    missing = expected_sections - set(sections)
    if missing:
        failures.append(f"{src['slug']}: missing sections {sorted(missing)}")
    print(f"  [{'OK' if not missing else 'FAIL'}] all 10 sections resolved"
          + (f" (missing: {sorted(missing)})" if missing else ""))

    # 1. minimum_investments present for all 5
    mins = [c for c in chunks if c.section == "minimum_investments"]
    ok = bool(mins) and any("Min. for SIP" in c.text for c in mins)
    print(f"  [{'OK' if ok else 'FAIL'}] minimum_investments + 'Min. for SIP'")
    if not ok:
        failures.append(f"{src['slug']}: no minimum_investments section with 'Min. for SIP'")

    # 2. riskometer badge == 'Very High' (page renders it "Very High Risk") for all 5
    risk = [c for c in chunks if c.section == "riskometer"]
    ok = len(risk) == 1 and "Very High" in risk[0].text and "'Very High Risk'" in risk[0].text
    print(f"  [{'OK' if ok else 'FAIL'}] riskometer badge = Very High "
          f"({len(risk)} card(s))")
    if not ok:
        failures.append(f"{src['slug']}: riskometer {risk[0].text[:90] if risk else 'MISSING'}")

    # 3. every chunk <= MAX_SIZE
    over = [c for c in chunks if c.char_len > MAX_SIZE]
    print(f"  [{'OK' if not over else 'FAIL'}] all chunks <= {MAX_SIZE} chars "
          f"(max seen {max(c.char_len for c in chunks)})")
    if over:
        failures.append(f"{src['slug']}: {len(over)} chunk(s) over {MAX_SIZE} chars")

    # 4. no PII
    for c in chunks:
        for pat in PII_PATTERNS:
            if re.search(pat, c.text):
                failures.append(f"{src['slug']}/{c.section}: PII pattern {pat}")

    # 5. no boilerplate
    for c in chunks:
        for phrase in BOILERPLATE:
            if phrase.lower() in c.text.lower():
                failures.append(f"{src['slug']}/{c.section}: boilerplate {phrase!r}")

    # 6. must NOT contain the conflicted About-prose facts
    joined = " ".join(c.text for c in chunks)
    for bad in ("Total AUM", "9,86,23", "Rank (total assets)"):
        if bad in joined:
            failures.append(f"{src['slug']}: leaked AMC-level/wrong fact {bad!r}")

# --- global: total prose chunk count is sane ------------------------------
print("\n" + "-" * 78)
print(f"TOTAL prose chunks across 5 schemes: {len(all_chunks)}")
if not (40 <= len(all_chunks) <= 400):
    failures.append(f"implausible prose chunk count: {len(all_chunks)}")

# --- split_section unit checks -------------------------------------------
print("\nsplit_section unit checks:")
body = [f"Line {i} " + "x" * 30 for i in range(40)]
packs = split_section(body)
sizes = [sum(len(x) + 1 for x in p) for p in packs]
print(f"  40 lines -> {len(packs)} packs, sizes min={min(sizes)} max={max(sizes)}")
if max(sizes) > MAX_SIZE:
    failures.append(f"split_section exceeded {MAX_SIZE}: {max(sizes)}")

# overlap actually present
if len(packs) >= 2 and not (set(packs[0]) & set(packs[1])):
    failures.append("split_section produced no overlap between consecutive packs")

# normal lines are never split: every pack line must be an original whole line
whole = all(all(x in body for x in pack) for pack in packs)
print(f"  [{'OK' if whole else 'FAIL'}] no ordinary line was split mid-value")
if not whole:
    failures.append("split_section split an ordinary line")

# an over-long single line IS wrapped (not truncated) and stays within size
long_line = (
    "Exit Load for units in excess of 15% of the investment, 1% will be "
    "charged for redemption within 1 year from the date of investment, "
    "provided that the aggregate of all such redemptions in an assessment "
    "year does not exceed 15% of the units held at the start of that year. "
    "The load is levied at the time of redemption and the amount deducted "
    "from the redemption proceeds payable to the investor, and the units "
    "so redeemed shall be rounded down to the nearest whole unit."
)
wrapped = split_section([long_line])
wrapped_sizes = [sum(len(x) + 1 for x in p) for p in wrapped]
no_loss = "".join(x for p in wrapped for x in p).replace(" ", "") == long_line.replace(" ", "")
ok = len(wrapped) > 1 and max(wrapped_sizes) <= MAX_SIZE and no_loss
print(f"  [{'OK' if ok else 'FAIL'}] over-long line wrapped, not truncated "
      f"({len(wrapped)} pieces, max={max(wrapped_sizes)}, no content lost={no_loss})")
if not ok:
    failures.append("over-long line was truncated or exceeded the size limit")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 3 ASSERTIONS PASSED")
print("=" * 78)
