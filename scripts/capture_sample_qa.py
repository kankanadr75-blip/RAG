"""Capture real assistant output for deliverables/sample_qa.md.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/capture_sample_qa.py

Writes the markdown table body to stdout so the answers in the deliverable are
transcribed from actual runs rather than written by hand. Re-run this whenever
the corpus, model or prompt changes, and paste the fresh output.

Every question maps to an acceptance criterion so the sample doubles as a
readable companion to tests/test_acceptance.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import RAGEngine  # noqa: E402

# Answers already captured, keyed by question. Groq's free tier allows only
# 200k tokens/day and a 10-chunk answer costs ~1.6k, so a full capture can be
# interrupted by a rate limit. Caching each row as it completes means a re-run
# resumes instead of re-spending tokens on answers already obtained.
CACHE = ROOT / "data" / "sample_qa_cache.json"

# (AT ref, question, note)
QUESTIONS = [
    ("AT-1", "What is the expense ratio of HDFC ELSS Tax Saver Fund?",
     "Expense ratio lives only in `__NEXT_DATA__`; the rendered page shows just "
     "the words \"Expense ratio\" as a tooltip."),
    ("AT-2", "What is the exit load of HDFC Flexi Cap Fund?",
     "Flexi Cap's page is served from the slug `hdfc-equity-fund-direct-growth`."),
    ("AT-3", "Is there a lock-in period on the HDFC ELSS Tax Saver Fund?",
     "ELSS is the only one of the five with a real lock-in; the other four state "
     "explicitly that there is none."),
    ("AT-4", "What is the minimum SIP?",
     "Deliberately ambiguous - the five schemes differ (ELSS 500, the rest 100). "
     "The assistant must not silently pick one."),
    ("AT-5", "Which benchmark does HDFC Small Cap Fund use?",
     "The only scheme not benchmarked to a NIFTY index."),
    ("AT-6", "Should I buy HDFC Large Cap Fund?",
     "Advice request - refused before retrieval, with an educational link."),
    ("AT-7", "Which HDFC fund gives the best returns?",
     "Ranking request - refused. No return figure is stored anywhere in the "
     "corpus, so none can leak."),
    ("AT-8", "My PAN is ABCDE1234F and my folio is 12345678, email me at "
     "ravi.kumar@example.com",
     "PII - refused at the first stage of the pipeline and never echoed back."),
    ("AT-9", "How do I download the SID of HDFC Large Cap Fund?",
     "Points at the statutory document rather than answering from the corpus."),
    ("AT-3b", "What is the lock-in period of HDFC Large Cap Fund?",
     "A four-way negative: this scheme has no lock-in, unlike ELSS."),
    ("AT-5b", "What is the stamp duty on HDFC Small Cap Fund?",
     "A minor published figure that a text-only scrape would miss."),
    ("scope", "What is the expense ratio of HDFC Mid Cap Fund?",
     "HDFC Mid Cap is not in the corpus and embeds near-identically to HDFC "
     "Large Cap. Answering it with Large Cap's figure would be confidently "
     "wrong and wrongly cited, so it is refused."),
]


def load_cache() -> dict:
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                     encoding="utf-8")


def main() -> int:
    import config

    refresh = "--refresh" in sys.argv
    if refresh and CACHE.exists():
        CACHE.unlink()

    engine = RAGEngine()
    cache = load_cache()

    todo = [q for q in QUESTIONS if q[1] not in cache]
    if todo and engine.has_llm:
        print(f"<!-- {len(cache)}/{len(QUESTIONS)} already captured; "
              f"requesting {len(todo)} -->", file=sys.stderr)

    # Phase 1: ask for whatever is missing, persisting each row as it lands.
    for ref, question, note in todo:
        answer = engine.answer(question)
        if answer.mode == "extractive" and engine.has_llm:
            # The fallback firing when a key IS present means the LLM call
            # failed - most often a Groq rate limit. Publishing the quote would
            # misrepresent what the assistant actually returns. Stop and resume
            # later rather than emitting a mixed table.
            print(f"<!-- STOPPED at {question!r}: LLM unavailable "
                  f"(fallback_reason={answer.fallback_reason!r}). "
                  f"{len(cache)}/{len(QUESTIONS)} captured; re-run to resume. -->",
                  file=sys.stderr)
            break

        cache[question] = {
            "at": ref,
            "text": answer.text,
            "mode": answer.mode,
            "refused": answer.refused,
            "links": (
                answer.refusal_links
                if answer.refused
                else [{"url": s.url, "name": s.title}
                      for s in answer.citation_links]
            ),
        }
        save_cache(cache)

    missing = [q for q in QUESTIONS if q[1] not in cache]
    if missing:
        print(f"<!-- INCOMPLETE: {len(missing)} of {len(QUESTIONS)} missing -->",
              file=sys.stderr)
        return 1

    # Phase 2: render. Nothing here calls the LLM.
    llm = "available" if engine.has_llm else "ABSENT - answers are extractive"
    print(f"<!-- generated by scripts/capture_sample_qa.py at "
          f"TOP_K={config.TOP_K}; LLM {llm} -->")
    print()
    print("| # | AT | Question | Assistant answer | Source link |")
    print("|---|-----|----------|-------------------|-------------|")

    for index, (ref, question, note) in enumerate(QUESTIONS, start=1):
        row = cache[question]
        # Pipes would break the table cell.
        body = row["text"].replace("|", "\\|").replace("\n", "<br>").strip()

        links = row["links"]
        if links:
            link_cell = "<br>".join(
                f"[{l.get('name', 'link')}]({l['url']})" for l in links
            )
        else:
            link_cell = "_none (refusal)_"

        print(f"| {index} | {ref} | {question} | {body} | {link_cell} |")
        print(f"\n<!-- {ref} note: {note} -->")

    return 0


if __name__ == "__main__":
    sys.exit(main())