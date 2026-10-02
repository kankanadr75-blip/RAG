"""Show exactly what each candidate model answered, and why a figure "missed".

Run:  $env:PYTHONIOENCODING='utf-8'; python scripts/inspect_model_answers.py

compare_models.py reported 3/5 for both gpt-oss models. Before treating that as
a correctness failure, rule out the boring explanation: a NARROW NO-BREAK SPACE
(U+202F) sitting inside the number, e.g. "1.21 %" vs "1.21%", which would fail a
substring check while the answer is in fact right.

Prints the raw text with U+202F made visible, plus which stage dropped the
figure if it did.
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

CASES = [
    ("What is the expense ratio of HDFC ELSS Tax Saver Fund?", "1.21"),
    ("What is the exit load of HDFC Flexi Cap Fund?", "1%"),
    ("What is the lock-in period of HDFC ELSS Tax Saver Fund?", "3 year"),
    ("What is the stamp duty on HDFC Small Cap Fund?", "0.005"),
    ("Which benchmark does HDFC Small Cap Fund use?", "BSE 250"),
]

MODELS = [m for m in sys.argv[1:]] or ["openai/gpt-oss-20b",
                                       "openai/gpt-oss-120b"]


def visible(text: str) -> str:
    """Make invisible characters obvious."""
    return (text
            .replace("\u202f", "<NBSP>")
            .replace("\u00a0", "<NBSP-160>")
            .replace("\u2009", "<THIN>")
            .replace("\n", " "))


def main() -> int:
    engine = RAGEngine()
    if not engine.has_llm:
        print("No GROQ_API_KEY.")
        return 1

    contexts = {}
    for question, _ in CASES:
        contexts[question] = _build_context(
            engine.retrieve(question, skip_guardrails=True)
        )

    for model in MODELS:
        print("=" * 70)
        print(model)
        print("=" * 70)
        for question, want in CASES:
            try:
                resp = engine.groq_client.chat.completions.create(
                    model=model, temperature=0, max_tokens=1024,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": (
                            f"{contexts[question]}\n\nQuestion: {question}\n\n"
                            "Answer in at most 3 sentences, using only the "
                            "context above."
                        )},
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  FAILED {type(exc).__name__}: {exc}")
                continue

            msg = resp.choices[0].message
            raw = getattr(msg, "content", None) or ""
            reasoning = (getattr(msg, "reasoning", None)
                         or getattr(msg, "reasoning_content", None) or "")
            stripped = _strip_disallowed(raw)
            final = _truncate_sentences(stripped)

            stage = "ok"
            if want.lower() not in final.lower():
                if want.lower() in raw.lower():
                    stage = "LOST IN _strip_disallowed / _truncate_sentences"
                else:
                    stage = "MODEL NEVER STATED IT"

            shown = visible(final)
            print(f"\n  Q: {question}")
            print(f"     want: {want!r}   -> {stage}")
            print(f"     final: {shown[:210]}")
            if reasoning:
                r_shown = visible(reasoning)
                print(f"     reasoning({len(reasoning)}): {r_shown[:100]}")
            if "\u202f" in raw:
                print(f"     !! {raw.count(chr(0x202f))} narrow no-break space(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
