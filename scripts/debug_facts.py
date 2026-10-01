"""Phase 2 verification: assert Extractor A against the verified fact table.

Checks every value in deliverables/implementation.md §0.3. Run:
    $env:PYTHONIOENCODING='utf-8'; python scripts/debug_facts.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from ingest import extract_facts, load_pages  # noqa: E402

# slug -> expected values (implementation.md §0.3)
EXPECTED = {
    "hdfc-large-cap-fund-direct-growth": {
        "er": "1.03", "base": "0.84", "lock": None, "sip": "100",
        "exit": "1%", "bench": "NIFTY 100 Total Return Index",
    },
    "hdfc-equity-fund-direct-growth": {
        "er": "0.77", "base": "0.57", "lock": None, "sip": "100",
        "exit": "1%", "bench": "NIFTY 500 Total Return Index",
    },
    "hdfc-elss-tax-saver-fund-direct-plan-growth": {
        "er": "1.21", "base": "0.97", "lock": "3 year", "sip": "500",
        "exit": "Nil", "bench": "NIFTY 500 Total Return Index",
    },
    "hdfc-small-cap-fund-direct-growth": {
        "er": "0.78", "lock": None, "sip": "100",
        "exit": "1%", "bench": "BSE 250 SmallCap Total Return Index",
    },
    "hdfc-balanced-advantage-fund-direct-growth": {
        "er": "0.78", "lock": None, "sip": "100",
        "exit": "excess of 15%", "bench": "NIFTY 50 Hybrid Composite Debt 50:50 Index",
    },
}

BANNED = [
    # --- return / ranking / performance figures (PRD P3, risk R5) ---
    # NB: the bare word "annualised" is NOT banned. It legitimately appears in
    # "portfolio turnover ratio ... (annualised)", which is a disclosed
    # non-performance metric. Only *return* contexts are banned.
    r"annualised return",
    r"\d+Y annualised",
    r"returns and rankings",
    r"fund returns",
    r"absolute returns",
    r"category average",
    r"rank \(equity",
    # --- fund manager: JSON and page prose disagree, excluded (PRD §7.4) ---
    r"Prashant Jain", r"Rahul Baijal", r"Dhruv Muchhal", r"Amar Kalkundrikar",
    r"Chirag Setalvad", r"Srinivas Rao Ravuri", r"Vinay Kulkarni",
    # --- contact / PII ---
    r"@", r"022\s*[–-]\s*66316333",
]

failures: list[str] = []
pages = load_pages()

print("\n" + "=" * 78)
print("PHASE 2 VERIFICATION - Extractor A (__NEXT_DATA__ fact cards)")
print("=" * 78)

for src in config.SOURCES:
    slug = src["slug"]
    exp = EXPECTED[slug]
    chunks = extract_facts(src, pages[slug])
    by_section: dict[str, list[str]] = {}
    for c in chunks:
        by_section.setdefault(c.section, []).append(c.text)

    print(f"\n{slug}")
    print(f"  {len(chunks)} fact cards | sections: {', '.join(sorted(by_section))}")

    def one(section: str) -> str:
        return by_section.get(section, [""])[0]

    # expense ratio + base
    er_txt = one("expense_ratio")
    got = re.search(r"is ([\d.]+) %", er_txt)
    got = got.group(1) if got else None
    ok = got == exp["er"]
    print(f"  [{'OK' if ok else 'FAIL'}] expense_ratio  got={got!r} want={exp['er']!r}")
    if not ok:
        failures.append(f"{slug}: expense_ratio {got} != {exp['er']}")
    if "base" in exp:
        gotb = re.search(r"base expense ratio ([\d.]+) %", er_txt)
        gotb = gotb.group(1) if gotb else None
        ok = gotb == exp["base"]
        print(f"  [{'OK' if ok else 'FAIL'}] base_expense    got={gotb!r} want={exp['base']!r}")
        if not ok:
            failures.append(f"{slug}: base_expense {gotb} != {exp['base']}")

    # lock-in
    lock_txt = one("lock_in_period")
    if exp["lock"] is None:
        ok = "no lock-in period" in lock_txt
        detail = "explicit negative card present"
    else:
        ok = exp["lock"] in lock_txt
        detail = f"contains {exp['lock']!r}"
    print(f"  [{'OK' if ok else 'FAIL'}] lock_in          {detail}")
    if not ok:
        failures.append(f"{slug}: lock_in -> {lock_txt[:110]}")

    # min SIP
    sip_txt = one("sip_minimum")
    ok = re.search(rf"INR {re.escape(exp['sip'])}\b", sip_txt) is not None
    print(f"  [{'OK' if ok else 'FAIL'}] min_sip          want INR {exp['sip']} | {sip_txt[:70]}")
    if not ok:
        failures.append(f"{slug}: min_sip != {exp['sip']}")

    # exit load
    el_txt = one("exit_load")
    ok = exp["exit"].lower() in el_txt.lower()
    print(f"  [{'OK' if ok else 'FAIL'}] exit_load        want {exp['exit']!r}")
    if not ok:
        failures.append(f"{slug}: exit_load {el_txt[:110]}")

    # benchmark
    b_txt = one("benchmark")
    ok = exp["bench"].lower() in b_txt.lower()
    print(f"  [{'OK' if ok else 'FAIL'}] benchmark        want {exp['bench']!r}")
    if not ok:
        failures.append(f"{slug}: benchmark {b_txt[:110]}")

    # banned content
    alltext = " ".join(c.text for c in chunks)
    for pat in BANNED:
        if re.search(pat, alltext, flags=re.I):
            failures.append(f"{slug}: BANNED pattern {pat!r} present")
            print(f"  [FAIL] banned pattern present: {pat!r}")

    # every card names its scheme
    unnamed = [c.section for c in chunks if src["name"].split(" - ")[0].split()[1] not in c.text and c.section != "documents"]
    if unnamed:
        print(f"  [warn] cards not naming scheme: {unnamed}")

# global: exactly one scheme has a real lock-in
print("\n" + "-" * 78)
locky = []
for src in config.SOURCES:
    chunks = extract_facts(src, pages[src["slug"]])
    for c in chunks:
        if c.section == "lock_in_period" and "no lock-in" not in c.text:
            locky.append(src["slug"])
ok = locky == ["hdfc-elss-tax-saver-fund-direct-plan-growth"]
print(f"[{'OK' if ok else 'FAIL'}] exactly one scheme has a real lock-in: {locky}")
if not ok:
    failures.append(f"lock-in present on unexpected schemes: {locky}")

total = sum(len(extract_facts(s, pages[s["slug"]])) for s in config.SOURCES)
print(f"\nTOTAL fact cards across 5 schemes: {total}")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 2 ASSERTIONS PASSED")
print("=" * 78)
