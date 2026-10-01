"""Phase 4 verification: PII detection + corpus scrubbing.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/debug_guardrails.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guardrails import PIIHit, detect_pii, scrub_pii  # noqa: E402

# (label, text, expected kind or None)
PII_CASES = [
    ("PAN", "My PAN is ABCDE1234F, please help", "pan"),
    ("Aadhaar", "aadhaar number 2345 6789 0123", "aadhaar"),
    ("e-mail", "mail me at ravi.kumar@example.com", "email"),
    ("mobile", "call me on +91 98765 43210", "phone"),
    ("OTP", "my otp is 482913", "otp"),
    ("account digits", "account 1234567890123", "account_number"),
    ("clean question", "What is the expense ratio of HDFC ELSS?", None),
    ("clean question 2", "Is there a lock-in period?", None),
    ("empty", "", None),
]

failures: list[str] = []

print("=" * 78)
print("PHASE 4 VERIFICATION - guardrails (PII)")
print("=" * 78)

print("\n-- detect_pii --")
for label, text, want in PII_CASES:
    hit = detect_pii(text)
    got = hit.kind if hit else None
    ok = got == want
    print(f"  [{'OK' if ok else 'FAIL'}] {label:<16} got={got!r:<18} want={want!r}")
    if not ok:
        failures.append(f"detect_pii({label}) -> {got}, want {want}")

print("\n-- PIIHit must never carry the raw value --")
for label, text, _ in PII_CASES:
    if detect_pii(text):
        hit = detect_pii(text)
        leaked = text.split()[2] if len(text.split()) > 2 else ""
        if leaked and leaked in str(hit):
            failures.append(f"PIIHit leaked the raw value for {label}")
        break
ok = not any("leaked" in f for f in failures)
print(f"  [{'OK' if ok else 'FAIL'}] PIIHit(kind, count) carries no raw substring")
print(f"         repr(PIIHit) = {PIIHit('pan', 1)!r}")

print("\n-- scrub_pii on corpus-style contact data --")
SCRUB_CASES = [
    ("e-mail", "Registrar CAMS, email hdfc@camsonline.com, phone 022 - 66316333",
     ["hdfc@camsonline.com", "022 - 66316333"]),
    ("PAN", "PAN ABCDE1234F on file", ["ABCDE1234F"]),
    ("aadhaar", "aadhaar 2345 6789 0123", ["2345 6789 0123"]),
    ("big AUM", "Total AUM is 9,86,236.84 Cr", ["9,86,236.84"]),
]
for label, text, must_go in SCRUB_CASES:
    out = scrub_pii(text)
    gone = all(m not in out for m in must_go)
    ok = gone and "[redacted]" in out
    print(f"  [{'OK' if ok else 'FAIL'}] {label:<10} -> {out[:78]!r}")
    if not ok:
        failures.append(f"scrub_pii({label}) left PII behind: {out!r}")

ok = scrub_pii("nothing sensitive here") == "nothing sensitive here"
print(f"  [{'OK' if ok else 'FAIL'}] clean text passes through unchanged")
if not ok:
    failures.append("scrub_pii altered clean text")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 4 GUARDRAIL ASSERTIONS PASSED")
print("=" * 78)
