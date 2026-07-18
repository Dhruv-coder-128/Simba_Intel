"""Web Search pipeline orchestrator (PRESERVED, DORMANT ARCHITECTURE - see
this package's __init__.py for why this exists but isn't wired into v1.0).
Would be the single entry point a future view layer calls. Wires together
every other module in this package:

    query -> search_engine.search_web -> extraction.extract_pages_concurrently
          -> summarizer.stream_summary -> formatting.format_sources

Every failure mode short-circuits to a friendly, non-streaming outcome
(errors.py) instead of ever raising - see run_web_search's own docstring
for the exact contract callers depend on.
"""
import logging

from chat.services.web_search import errors
from chat.services.web_search.extraction import extract_pages_concurrently
from chat.services.web_search.formatting import format_sources
from chat.services.web_search.search_engine import WebSearchUnavailableError, search_web
from chat.services.web_search.summarizer import build_summary_messages, stream_summary

logger = logging.getLogger("simba_intel")


def run_web_search(model_id: str, query: str, on_usage=None):
    """Runs the full Web Search pipeline for `query` and returns one of:

      ("error", friendly_message: str, [])
          Either the search request itself failed/was blocked
          (WebSearchUnavailableError - see search_engine.py) or it
          completed but genuinely found nothing usable. friendly_message
          is safe to show the user as-is, and is worded differently for
          each of those two cases - never conflated into one generic "no
          results" message, since an exception is not proof the topic has
          no results (see WebSearchUnavailableError's own docstring).

      ("stream", token_generator, sources: list[dict])
          Success. token_generator is a lazy generator (chat_stream_with_
          failover) - no AI call happens until it's iterated, and a
          calling view's try/except around consuming a stream (identical
          to every other chat endpoint in this app) would handle a
          failure that surfaces mid-stream. sources is the exact list to
          store in the saved message's extra_data and to show the user as
          citations.

    Logs every stage (search request, result counts, extraction outcome,
    summarization input, final outcome) so a "why did this query fail"
    question is always answerable from the logs alone, without needing to
    reproduce it - see search_engine.py's and extraction.py's own logging
    for the search/extraction stages this function orchestrates.
    """
    logger.info("Web search pipeline: starting for query=%r (model_id=%s)", query, model_id)

    try:
        results = search_web(query)
    except WebSearchUnavailableError as e:
        # The real exception is already logged in full (ERROR, with
        # traceback) inside search_web itself - this is the pipeline-level
        # record of the OUTCOME that failure led to, not a re-hiding of it.
        logger.error(
            "Web search pipeline: search request failed for query=%r - %s - "
            "returning SEARCH_UNAVAILABLE (not NO_RESULTS - an exception is "
            "never treated as proof the topic has no results)", query, e,
        )
        return "error", errors.SEARCH_UNAVAILABLE_MESSAGE, []

    if not results:
        logger.info(
            "Web search pipeline: query=%r completed with zero results (no exception raised) "
            "- genuine no-results outcome", query,
        )
        return "error", errors.NO_RESULTS_MESSAGE, []

    pages = extract_pages_concurrently(results)
    extracted_urls = {p.url for p in pages}
    snippet_only = [r for r in results if r.url not in extracted_urls]
    logger.info(
        "Web search pipeline: %d/%d page(s) extracted, %d falling back to snippet-only for query=%r",
        len(pages), len(results), len(snippet_only), query,
    )

    has_any_content = bool(pages) or any(r.snippet for r in snippet_only)
    if not has_any_content:
        logger.info(
            "Web search pipeline: %d result(s) found but none yielded usable content for query=%r",
            len(results), query,
        )
        return "error", errors.NO_CONTENT_MESSAGE, []

    sources = format_sources(pages, snippet_only)
    summary_messages = build_summary_messages(query, pages, snippet_only)
    logger.info(
        "Web search pipeline: summarizing query=%r with %d source(s) (%d full-text, %d snippet-only), "
        "prompt length=%d chars, sources=%s",
        query, len(sources), len(pages), len(snippet_only),
        len(summary_messages[-1]["content"]), [s["url"] for s in sources],
    )
    token_gen = stream_summary(model_id, query, pages, snippet_only, on_usage=on_usage)
    return "stream", token_gen, sources
