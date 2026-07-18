"""Web Search mode - PRESERVED, DORMANT ARCHITECTURE (not wired into the app
in Version 1.0; the "Search the Web" option, its ask_ai routing, and its
frontend UI were all deliberately removed from v1.0 as not production-ready
- see the removal report in project history for the full rationale).

Kept here intact, importable, and independently testable so the feature can
be reintroduced in a future version - most likely with a different search
provider than DuckDuckGo, given DuckDuckGo's html-scraping endpoint proved
prone to soft anti-bot blocking in production testing (see search_engine.py's
WebSearchUnavailableError docstring for the full incident). Nothing in this
package is imported by chat/views.py or any other active code path - it is
reachable only if a future version explicitly wires it back in.

Pipeline modules, kept separate on purpose:

    search_engine.py  - DuckDuckGo search (via the `ddgs` package) + quality
                         filtering/dedup
    extraction.py     - per-page fetch + trafilatura content extraction,
                         concurrent across pages, each with its own timeout
    summarizer.py     - builds the AI prompt from extracted content and
                         streams a summary via the existing multi-provider
                         chat pipeline (chat/services/ai_router.py)
    formatting.py     - shapes sources into the plain dicts the view/
                         template layer would store and display
    cache.py          - short-lived cache for search results and per-page
                         extractions, so the same query/URL isn't re-fetched
                         needlessly
    errors.py         - user-facing friendly message constants
    pipeline.py        - orchestrates all of the above; run_web_search() is
                         the single entry point a future view layer would call

Reintroducing this feature requires, at minimum: `pip install ddgs
trafilatura` (removed from requirements.txt when the feature was pulled from
v1.0), re-adding a sticky per-conversation flag (a ChatSession field, removed
via migration 0040), and re-wiring pipeline.run_web_search() into ask_ai plus
its "+" menu / streaming UI in chat.html.
"""
from chat.services.web_search.pipeline import run_web_search

__all__ = ["run_web_search"]
