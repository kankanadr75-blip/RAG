"""Streamlit UI for the HDFC Mutual Fund FAQ assistant.

Run:  $env:PYTHONIOENCODING='utf-8'; streamlit run app.py

Deliberately small. It renders what ``rag.answer()`` returns and adds no logic
of its own - every answer, refusal and citation decision is made in ``rag.py``,
so the headless CLI (``python rag.py "question"``) and this UI can never
disagree. The UI's only jobs are presentation, and two safety rules:

* the disclaimer is always visible, and
* a question containing personal data renders the refusal only, never the input.

Design note: ``st.chat_input`` cannot coexist with arbitrary widgets below it in
older Streamlit, so the example questions are rendered as buttons ABOVE the
input, and the in-scope scheme panel sits in the sidebar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from guardrails import detect_pii  # noqa: E402
from rag import RAGEngine  # noqa: E402

# --------------------------------------------------------------------------
# Examples - the three AT queries from implementation.md Phase 9 task 3.
# Chosen because between them they cover the three most-asked facts AND the
# only scheme with a real lock-in, so a click-through exercises the corpus.
# --------------------------------------------------------------------------
EXAMPLES = [
    "What is the expense ratio of HDFC ELSS Tax Saver?",
    "Is there a lock-in period on the HDFC ELSS Tax Saver Fund?",
    "What is the exit load and minimum SIP for HDFC Flexi Cap?",
]

REFUSAL_HEADINGS = {
    "pii": "Personal data not accepted",
    "advice": "I don't give investment advice",
    "performance": "I don't report returns or rankings",
    "out_of_scope": "That scheme isn't in my sources",
    "no_context": "Not found in my sources",
    "empty": "Nothing to answer",
}


def _index_ready() -> bool:
    """True when a non-empty vector collection is already on disk.

    ``data/chroma/`` is git-ignored, so a fresh clone has no index. Render
    builds one during its build step; Streamlit Community Cloud has no build
    command at all, so something has to do it at runtime.
    """
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        return client.get_collection(config.COLLECTION_NAME).count() > 0
    except Exception:  # noqa: BLE001 - absent collection, or chroma not up yet
        return False


@st.cache_resource(show_spinner="Preparing the vector index (first run only)...")
def get_engine() -> RAGEngine:
    """Load the model + vector store ONCE per session (task 9).

    Without this, every rerun re-loads all-MiniLM-L6-v2, which costs several
    seconds and would make the app feel broken. ``cache_resource`` (not
    ``cache_data``) is correct because the engine holds a model and a Chroma
    client - mutable, non-serialisable objects.

    The ingestion call is the Community Cloud path. It is a no-op on Render,
    where the blueprint already ran ``ingest.py --reembed`` during the build,
    and a no-op on every run after the first because the container keeps
    ``data/chroma/`` between sessions. It reads the cached pages in
    ``data/raw/``, which ARE committed, so it needs no network to build the
    corpus - only the one-time embedding-model download.
    """
    if not _index_ready():
        import ingest

        st.info("No vector index found - building it from the cached source "
                "pages. This happens once; later visits start instantly.")
        if ingest.main([]) != 0:
            raise RuntimeError(
                "Ingestion failed, so there is nothing to answer from. See the "
                "logs above for the coverage gaps that caused it."
            )
    return RAGEngine()


def render_sidebar() -> None:
    with st.sidebar:
        st.header("Scope")
        st.caption(
            f"This assistant answers only from {len(config.SOURCES)} public "
            f"Groww scheme pages, all {config.SOURCES[0]['name'].split(' - ')[-1]} "
            f"options:"
        )
        for source in config.SOURCES:
            st.markdown(f"- **{source['category']}** — {source['name'].split(' - ')[0]}")
        st.divider()
        st.caption(config.DISCLAIMER)
        engine = get_engine()
        if engine.has_llm:
            st.caption(f"Model: `{config.GROQ_MODEL}`")
        else:
            st.warning(
                "No `GROQ_API_KEY` set — answers are quoted verbatim from the "
                "source rather than paraphrased.",
                icon="⚠️",
            )


def render_answer(answer) -> None:
    """Render one Answer. Mirrors the CLI's `_print_answer`."""
    st.write(answer.text)

    if answer.refused:
        kind = answer.refusal_kind or "refusal"
        st.caption(f"*{REFUSAL_HEADINGS.get(kind, 'Refused')}*")
        if answer.refusal_links:
            st.markdown("**Learn more**")
            for link in answer.refusal_links:
                st.markdown(f"- [{link['label']}]({link['url']})")
        return

    # EXACTLY ONE citation. The spec requires one clear link per answer, so the
    # primary source is the only link in the body; the rest live in the expander.
    #
    # Rendered as a markdown link rather than st.link_button: the spec allows
    # either, but markdown links are exposed by streamlit.testing.AppTest, so
    # the citation is verifiable in CI. A button would be untestable there and
    # could silently start pointing at the wrong URL.
    primary = answer.primary_source
    if primary is not None:
        st.markdown(f"**Source:** [{primary.title}]({primary.url})")

    if answer.mode == "extractive":
        # Distinguish "you have not configured a key" from "the API call failed".
        # The second is a real fault and labelling it as a missing key would
        # hide it. The warning then shows the Groq response itself rather than
        # guessing at "rate limit or network error" - that phrase cannot
        # separate an exhausted daily token quota from a rejected key, and the
        # two need completely different fixes.
        if answer.fallback_reason == "llm_error":
            detail = (answer.llm_error_detail or "").strip()
            st.warning(
                "The language model could not be reached, so this answer is "
                "quoted verbatim from the source page. No figure has been "
                "generated or inferred.",
                icon="⚠️",
            )
            if detail:
                # The Groq response itself: status, error code, and the actual
                # message (quota figures, reset time, or an auth error).
                st.code(detail, language=None)
            else:
                st.caption("No detail available - check the service logs.")
        else:
            st.caption(
                "Quoted verbatim from the source page — no language model "
                "configured. Set GROQ_API_KEY in .env for paraphrased answers."
            )

    if answer.hits:
        with st.expander(f"Sources used ({len(answer.hits)} chunks)"):
            st.caption(
                "Retrieved passages, best match first. This is the evidence the "
                "answer was built from."
            )
            for hit in answer.hits:
                st.markdown(
                    f"- `{hit.meta.get('chunk_id', '?')}` "
                    f"— score `{hit.score:.3f}`"
                )
                st.caption(hit.text)
            if len(answer.sources) > 1:
                st.divider()
                st.caption(
                    "Other scheme pages that were retrieved as context. They "
                    "were not necessarily the basis for the answer above."
                )
                # Plain text, NOT links: the DoD is one clear citation per
                # answer, and turning every retrieved page into a clickable
                # link dilutes that. The primary citation is the only link.
                for source in answer.sources[1:]:
                    st.caption(f"· {source.title} — {source.url}")


def main() -> None:
    st.set_page_config(
        page_title="HDFC Mutual Fund FAQ Assistant",
        page_icon="📄",
        layout="centered",
    )

    st.title("HDFC Mutual Fund scheme facts")
    st.markdown(
        "A **facts-only** assistant. It answers from five public HDFC Mutual "
        "Fund scheme pages and nothing else — no advice, no returns, no "
        "recommendations."
    )

    # REQ-23: the short form, prominent and persistent, above the fold and
    # above the input. Single source of truth - config.DISCLAIMER_SHORT.
    st.warning(config.DISCLAIMER_SHORT, icon="⚠️")
    st.caption(config.DISCLAIMER)

    render_sidebar()

    if "messages" not in st.session_state:
        st.session_state["messages"] = []
        st.session_state["question"] = None

    # Example questions, pre-seeded into the same flow as typed input so there
    # is exactly one rendering path.
    st.subheader("Try one of these")
    cols = st.columns(len(EXAMPLES))
    for col, example in zip(cols, EXAMPLES):
        if col.button(example, key=f"ex_{example[:24]}", use_container_width=True):
            st.session_state["question"] = example

    typed = st.chat_input("Ask about expense ratio, exit load, lock-in, "
                          "minimum SIP, risk, benchmark, RTA or stamp duty…")
    if typed:
        st.session_state["question"] = typed

    question = st.session_state.get("question")

    if question:
        engine = get_engine()
        with st.spinner("Looking this up…"):
            answer = engine.answer(question)

        # SAFETY: if the input contained PII, the user's own text is never
        # rendered back. The refusal already avoids echoing it (REQ-20); this
        # additionally stops the chat transcript from displaying it.
        if detect_pii(question) is not None:
            st.info("Your question contained personal data, so it is not "
                    "displayed or stored. Only the refusal below is shown.")
        else:
            st.chat_message("user").write(question)

        with st.chat_message("assistant"):
            render_answer(answer)

        st.session_state["question"] = None
    elif not st.session_state["messages"]:
        st.info("Pick an example above, or type a question below.")


if __name__ == "__main__":
    main()
