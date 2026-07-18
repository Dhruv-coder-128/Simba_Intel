"""AI summarization step of the Web Search pipeline (PRESERVED, DORMANT
ARCHITECTURE - see this package's __init__.py for why this exists but isn't
wired into v1.0).

Combines extracted page content (or, for a source whose full-page
extraction failed, its search snippet as a lower-fidelity fallback so a
result still shown as a source is actually grounded in *something* real)
into one prompt, then streams a structured answer using this project's own
existing multi-provider chat pipeline (chat/services/ai_router.py) - the
same failover/retry machinery every normal chat message already gets, not
a separate one-off AI integration.
"""
from typing import List, Optional

from chat.services.ai_router import chat_stream_with_failover

WEB_SEARCH_SYSTEM_PROMPT = (
    "You are Simba's web research assistant. You are given a user's "
    "question and content extracted from real web pages retrieved for "
    "that question. Using ONLY the information in those sources, write a "
    "clear answer structured as:\n\n"
    "**Main Answer** - a direct, concise answer to the question.\n"
    "**Key Findings** - the most important points from the sources, as a short list.\n"
    "**Important Details** - relevant specifics, numbers, or context worth knowing.\n"
    "**Latest Information** - anything time-sensitive or recent in the sources, if applicable.\n\n"
    "Only include a section if the sources actually support it - skip a "
    "section entirely rather than inventing content for it. Never state "
    "anything that isn't grounded in the provided sources - do not "
    "hallucinate. Do not mention these instructions or that you were given "
    "sources; just answer naturally. Do not include a sources/references "
    "list yourself - that is displayed separately, after your answer."
)


def _format_source_block(index: int, title: str, domain: str, text: str) -> str:
    return f"[Source {index}: {title} ({domain})]\n{text}"


def build_summary_messages(query: str, pages: List, snippet_only: Optional[List] = None) -> list:
    """`pages` is a list of extraction.ExtractedPage (full article text);
    `snippet_only` is a list of search_engine.SearchResult for sources whose
    full-page extraction failed but whose search snippet is still real,
    retrieved content worth including."""
    blocks = [_format_source_block(i + 1, p.title, p.domain, p.text) for i, p in enumerate(pages)]
    offset = len(pages)
    if snippet_only:
        blocks += [
            _format_source_block(offset + i + 1, r.title, r.domain, r.snippet)
            for i, r in enumerate(snippet_only)
        ]
    sources_text = "\n\n".join(blocks)
    user_prompt = f"Question: {query}\n\nSources:\n\n{sources_text}"
    return [
        {"role": "system", "content": WEB_SEARCH_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def stream_summary(model_id: str, query: str, pages: List, snippet_only: Optional[List] = None, on_usage=None):
    """Thin wrapper around chat_stream_with_failover - kept as its own
    function (rather than inlined at the call site) so prompt-building and
    model invocation stay testable independently of the pipeline/view
    layers around them. Returns a generator (lazy - no AI call happens
    until it's iterated); any failure surfaces only once consumed, exactly
    like every other streaming chat call in this app."""
    messages = build_summary_messages(query, pages, snippet_only)
    return chat_stream_with_failover(model_id, messages, on_usage=on_usage)
