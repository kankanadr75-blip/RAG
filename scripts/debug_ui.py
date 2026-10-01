"""Phase 9 verification: the Streamlit app must import, render and answer.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/debug_ui.py

Streamlit's own API is hard to unit-test, so this drives the real widget tree
through ``streamlit.testing.v1.AppTest`` - the same code path the browser hits.
Anything that raises during render fails here rather than in front of a user.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

failures: list[str] = []

print("=" * 78)
print("PHASE 9 VERIFICATION - Streamlit UI")
print("=" * 78)

import re

try:
    from streamlit.testing.v1 import AppTest
except ImportError as exc:
    print(f"  streamlit.testing unavailable ({exc}); cannot drive the app.")
    sys.exit(1)

APP = ROOT / "app.py"


def run(**kwargs) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run(**kwargs)
    return at


def markdown_links(at: AppTest) -> list[str]:
    """Every URL rendered as a markdown link in the page body.

    Read out of the markdown *text* rather than element metadata: Streamlit's
    testing API exposes only ``value``/``proto`` on a Markdown element in 1.45,
    with no ``is_link``/``target`` accessor, so link assertions have to parse the
    rendered markdown. That is also the stronger check - it verifies what the
    user actually sees, not an internal field.
    """
    urls: list[str] = []
    for element in at.markdown:
        urls.extend(re.findall(r"\]\((https?://[^)]+)\)", element.value))
    return urls


def visible_text(at: AppTest) -> str:
    """Every string the user could actually see on the page.

    Streamlit element types expose their text under different attributes
    (``value`` for markdown/buttons, ``body`` for chat messages), and the set
    changes between versions - so probe rather than assume, or the test fails on
    a Streamlit upgrade instead of on a real defect.
    """
    parts: list[str] = []
    for element in list(at.markdown) + list(at.chat_message) + \
            list(at.warning) + list(at.info) + list(at.caption):
        for attr in ("value", "body", "text"):
            content = getattr(element, attr, None)
            if isinstance(content, str):
                parts.append(content)
                break
    return "\n".join(parts)


# --- 1. the app renders at all -----------------------------------------
print("\n-- app renders without error --")
at = run()
ok = not at.exception
print(f"  [{'OK' if ok else 'FAIL'}] initial render, "
      f"exception={list(at.exception) if at.exception else 'none'}")
if not ok:
    for e in at.exception:
        failures.append(f"initial render raised: {e}")
    raise SystemExit(1)

# --- 2. welcome line names it facts-only --------------------------------
print("\n-- REQ-22/23: welcome line + persistent disclaimer --")
titles = [t.value for t in at.title]
markdown = "\n".join(m.value for m in at.markdown)
warnings = "\n".join(w.value for w in at.warning)

ok = bool(titles)
print(f"  [{'OK' if ok else 'FAIL'}] title present: {titles}")
if not ok:
    failures.append("no st.title rendered")

combined = markdown.lower()
ok = "facts-only" in combined or "facts only" in combined
print(f"  [{'OK' if ok else 'FAIL'}] 'facts-only' stated in the welcome copy")
if not ok:
    failures.append("welcome line does not state facts-only")

ok = len(at.warning) >= 1
print(f"  [{'OK' if ok else 'FAIL'}] st.warning disclaimer rendered "
      f"({len(at.warning)} warning(s))")
if not ok:
    failures.append("no st.warning disclaimer rendered")

import config  # noqa: E402

ok = config.DISCLAIMER[:40] in warnings
print(f"  [{'OK' if ok else 'FAIL'}] warning carries config.DISCLAIMER")
if not ok:
    failures.append("disclaimer warning does not use config.DISCLAIMER")

# The brief's literal phrasing must be present too.
ok = "No investment advice" in warnings
print(f"  [{'OK' if ok else 'FAIL'}] 'No investment advice' visible")
if not ok:
    failures.append("'No investment advice' missing from the disclaimer")

# --- 3. three example questions, clickable ---------------------------
print("\n-- REQ-24: 3 example questions --")
buttons = [b.label for b in at.button]
print(f"  [{'OK' if len(buttons) >= 3 else 'FAIL'}] {len(buttons)} button(s)")
for label in buttons:
    print(f"       - {label}")
if len(buttons) < 3:
    failures.append(f"expected 3 example buttons, found {len(buttons)}")

EXPECTED_EXAMPLES = [
    "What is the expense ratio of HDFC ELSS Tax Saver?",
    "Is there a lock-in period on the HDFC ELSS Tax Saver Fund?",
    "What is the exit load and minimum SIP for HDFC Flexi Cap?",
]
for example in EXPECTED_EXAMPLES:
    ok = any(example in b for b in buttons)
    print(f"  [{'OK' if ok else 'FAIL'}] example offered: {example[:56]}")
    if not ok:
        failures.append(f"missing example question: {example!r}")

# --- 4. the in-scope scheme panel --------------------------------------
print("\n-- in-scope schemes panel --")
side_md = []
for sb in at.sidebar:
    side_md.extend(m.value for m in getattr(sb, "markdown", []))
    side_md.extend(c.value for c in getattr(sb, "caption", []))
side_text = "\n".join(side_md)
missing_schemes = []
for source in config.SOURCES:
    category = source["category"]
    if category.split(" (")[0].lower() not in side_text.lower():
        missing_schemes.append(category)
ok = not missing_schemes
print(f"  [{'OK' if ok else 'FAIL'}] all 5 categories listed "
      f"(missing: {missing_schemes or 'none'})")
if not ok:
    failures.append(f"scheme panel missing categories: {missing_schemes}")

# --- 5. clicking an example produces an answer + citation --------------
print("\n-- clicking an example answers, with one citation --")
for index, example in enumerate(EXPECTED_EXAMPLES):
    at = run()
    at.button[index].click().run()

    if at.exception:
        failures.append(f"{example!r} raised: {at.exception[0]}")
        print(f"  [FAIL] {example[:44]:<46} raised {at.exception[0]}")
        continue

    text = visible_text(at)
    groww_links = [u for u in markdown_links(at) if "groww.in" in u]

    has_link = bool(groww_links)
    ok = has_link
    print(f"  [{'OK' if ok else 'FAIL'}] {example[:44]:<46} "
          f"{len(groww_links)} groww link(s)")
    if not ok:
        failures.append(f"{example!r} rendered no Groww citation link")

    # EXACTLY ONE primary citation, per the DoD. The extra-page links live
    # inside the collapsed expander, so count only what is in the body.
    ok = len(groww_links) == 1
    print(f"       primary citations: {len(groww_links)} "
          f"({'OK' if ok else 'FAIL - must be exactly 1'})")
    if not ok:
        failures.append(f"{example!r} rendered {len(groww_links)} primary "
                        f"citations, expected exactly 1")

    # As-of line present.
    ok = "Last updated from sources:" in text
    print(f"       as-of line: {'OK' if ok else 'FAIL'}")
    if not ok:
        failures.append(f"{example!r} has no as-of line")

    # Transparency expander.
    expanders = [e.label for e in at.expander]
    ok = any("Sources used" in e for e in expanders)
    print(f"       'Sources used' expander: {'OK' if ok else 'FAIL'}")
    if not ok:
        failures.append(f"{example!r} missing the Sources used expander")

# --- 6. factual correctness through the UI ----------------------------
print("\n-- AT-1/AT-2 via the UI --")
NUMERIC_UI = [
    (0, "1.21", "expense ratio of HDFC ELSS"),
    (2, "1%", "exit load of HDFC Flexi Cap"),
]
for index, want, label in NUMERIC_UI:
    at = run()
    at.button[index].click().run()
    text = visible_text(at)
    ok = want in text
    print(f"  [{'OK' if ok else 'FAIL'}] {label:<40} contains {want!r}")
    if not ok:
        failures.append(f"UI answer for {label!r} lacks {want!r}")

# --- 7. PII typed into the box is never displayed --------------------
print("\n-- REQ-20: typed PII is never rendered back --")
at = run()
at.chat_input[0].set_value("my pan is ABCDE1234F, send my statement").run()
if at.exception:
    failures.append(f"PII path raised: {at.exception[0]}")
    print(f"  [FAIL] raised {at.exception[0]}")
else:
    text = visible_text(at)
    leaked = "ABCDE1234F" in text
    print(f"  [{'OK' if not leaked else 'FAIL'}] PAN not displayed anywhere")
    if leaked:
        failures.append("PAN echoed into the UI")

    ok = "PAN" in text or "personal data" in text.lower()
    print(f"  [{'OK' if ok else 'FAIL'}] refusal shown instead")
    if not ok:
        failures.append("PII refusal not rendered")

    groww = [u for u in markdown_links(at) if "groww.in" in u]
    ok = len(groww) == 0
    print(f"  [{'OK' if ok else 'FAIL'}] no scheme citation on a refusal "
          f"({len(groww)})")
    if not ok:
        failures.append("a PII refusal carried a scheme citation")

# --- 8. advice refusal renders an educational link --------------------
print("\n-- REQ-18: advice refusal with an educational link --")
at = run()
at.chat_input[0].set_value("Should I buy HDFC Large Cap?").run()
if at.exception:
    failures.append(f"advice path raised: {at.exception[0]}")
else:
    text = visible_text(at)
    edu = any(k in text for k in ("sebi.gov.in", "amfiindia.com", "hdfcfund.com"))
    print(f"  [{'OK' if edu else 'FAIL'}] educational link rendered")
    if not edu:
        failures.append("advice refusal rendered no educational link")

    ok = "can't tell you which scheme to choose" in text or \
         "only share published facts" in text
    print(f"  [{'OK' if ok else 'FAIL'}] refusal copy rendered")
    if not ok:
        failures.append("advice refusal copy missing")

    groww = [u for u in markdown_links(at) if "groww.in" in u]
    ok = len(groww) == 0
    print(f"  [{'OK' if ok else 'FAIL'}] no Groww scheme citation on a refusal")
    if not ok:
        failures.append("advice refusal cited a scheme page")

# --- 9. an out-of-scope scheme is refused -----------------------------
print("\n-- out-of-scope scheme is not answered --")
at = run()
at.chat_input[0].set_value("What is the expense ratio of HDFC Mid Cap Fund?").run()
if at.exception:
    failures.append(f"scope path raised: {at.exception[0]}")
else:
    text = visible_text(at)
    ok = "1.03" not in text and "1.21" not in text
    print(f"  [{'OK' if ok else 'FAIL'}] no other scheme's ratio leaked in")
    if not ok:
        failures.append("out-of-scope question returned a number")

    groww = [u for u in markdown_links(at) if "groww.in" in u]
    ok = len(groww) == 0
    print(f"  [{'OK' if ok else 'FAIL'}] no Groww citation ({len(groww)})")
    if not ok:
        failures.append("out-of-scope refusal cited a Groww scheme page")

# --- 10. cache_resource is used ---------------------------------------
print("\n-- engine is cached, not rebuilt per rerun --")
app_src = APP.read_text(encoding="utf-8")
ok = "@st.cache_resource" in app_src
print(f"  [{'OK' if ok else 'FAIL'}] @st.cache_resource present")
if not ok:
    failures.append("engine is not cached with @st.cache_resource")

ok = app_src.count("@st.cache_resource") == 1
print(f"  [{'OK' if ok else 'FAIL'}] exactly one cached resource")
if not ok:
    failures.append("unexpected number of @st.cache_resource decorators")

# --- 11. the UI holds no answer logic of its own ---------------------
print("\n-- UI delegates to rag.answer() (no duplicated logic) --")
ok = "engine.answer(" in app_src
print(f"  [{'OK' if ok else 'FAIL'}] calls rag.answer()")
if not ok:
    failures.append("app.py does not call engine.answer()")

for banned in ("retrieve(", "_truncate_sentences", "TOP_K", "SYSTEM_PROMPT"):
    present = banned in app_src
    print(f"  [{'OK' if not present else 'FAIL'}] does not re-implement "
          f"{banned}")
    if present:
        failures.append(f"app.py re-implements {banned}")

# detect_pii IS allowed: the UI needs it to decide whether to echo the user's
# own text back into the transcript. That is a rendering decision, not answer
# logic - the refusal copy itself still comes from rag.answer().
ok = "detect_pii(" in app_src
print(f"  [{'OK' if ok else 'WARN'}] uses detect_pii only to suppress echoing "
      f"the user's PII back into the transcript")

print("\n" + "=" * 78)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL PHASE 9 ASSERTIONS PASSED")
print("=" * 78)
