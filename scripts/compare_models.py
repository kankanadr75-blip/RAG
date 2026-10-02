"""Compare candidate Groq models on this project's actual prompts.

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/compare_models.py

Choosing a model on vibes is how a project ends up with a "verified" default
that silently burns the daily token quota or breaks a string assertion. This
runs the real SYSTEM_PROMPT over the real retrieved context and reports what
actually differs:

  ok      - answer contains the verified figure (implementation.md 0.3)
  U+202F  - model emits NARROW NO-BREAK SPACE instead of a normal space.
            Invisible in most viewers, but it makes "HDFC ELSS" fail an exact
            substring test and it renders oddly. gpt-oss models do this.
  bold    - model emits markdown, which _strip_disallowed has to remove.
  sent    - total sentences across all answers (budget is 3 each)
  tok     - completion tokens, which is what the 200k/day free tier spends.
            Reasoning models bill their scratchpad here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import (  # noqa: E402
    SYSTEM_PROMPT,
    RAGEngine,
    _build_context,
    _strip_disallowed,
    _truncate_sentences,
)

MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
]

# (question, substring the verified answer must contain)
CASES = [
    ("What is the expense ratio of HDFC ELSS Tax Saver Fund?", "1.21"),
    ("What is the exit load of HDFC Flexi Cap Fund?", "1%"),
    ("What is the lock-in period of HDFC ELSS Tax Saver Fund?", "3 year"),
    ("What is the stamp duty on HDFC Small Cap Fund?", "0.005"),
    ("Which benchmark does HDFC Small Cap Fund use?", "BSE 250"),
]


def sentences(text: str) -> int:
    return len([p for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()])


def main() -> int:
    engine = RAGEngine()
    if not engine.has_llm:
        print("No GROQ_API_KEY - nothing to compare.")
        return 1

    # Retrieved once per question so every model sees an identical context.
    contexts = []
    for question, _ in CASES:
        hits = engine.retrieve(question, skip_guardrails=True)
        contexts.append(_build_context(hits))

    header = ("model", "figures", "U+202F", "bold", "sents/15", "compl.tok")
    print(f"{header[0]:<24}{header[1]:<9}{header[2]:<8}{header[3]:<7}"
          f"{header[4]:<10}{header[5]}")
    print("-" * 62)

    for model in MODELS:
        correct = narrow = bold = 0
        sents = tokens = 0
        for (question, want), context in zip(CASES, contexts):
            try:
                resp = engine.groq_client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=1024,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": (
                            f"{context}\n\nQuestion: {question}\n\n"
                            "Answer in at most 3 sentences, using only the "
                            "context above."
                        )},
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                print(f"{model:<24}FAILED {type(exc).__name__}: {exc}")
                break

            message = resp.choices[0].message
            raw = getattr(message, "content", None) or ""
            tokens += resp.usage.completion_tokens

            final = _truncate_sentences(_strip_disallowed(raw))
            if want.lower() in final.lower():
                correct += 1
            if "\u202f" in raw:
                narrow += 1
            if "**" in raw:
                bold += 1
            sents += sentences(final)
        else:
            n = len(CASES)
            print(f"{model:<24}{f'{correct}/{n}':<9}{f'{narrow}/{n}':<8}"
                  f"{f'{bold}/{n}':<7}{f'{sents}/{n * 3}':<10}{tokens}")

    print()
    print("U+202F = narrow no-break space; breaks exact substring tests.")
    print("compl.tok is the real cost: reasoning models bill their scratchpad")
    print("against the same 200k/day free-tier budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())