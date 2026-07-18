"""User-facing, friendly error/status messages for the Web Search pipeline
(PRESERVED, DORMANT ARCHITECTURE - see this package's __init__.py).

Kept as plain string constants in one place so wording stays consistent and
is never duplicated inline across the pipeline/view layers - "users should
never see raw errors" applies to this feature exactly as it does to the
rest of the app.
"""

NO_RESULTS_MESSAGE = (
    "I couldn't find any web results for that. Try rephrasing your question "
    "or being more specific."
)

NO_CONTENT_MESSAGE = (
    "I found some results, but couldn't read any of those pages right now. "
    "Please try again in a moment."
)

# Distinct from NO_RESULTS_MESSAGE on purpose: this is shown when the search
# REQUEST itself failed or was blocked (see search_engine.WebSearchUnavailableError)
# - DuckDuckGo's html endpoint returning a soft anti-bot block page is
# indistinguishable, at the ddgs library level, from a genuine "found
# nothing" page, so an exception from the search call is never treated as
# proof the topic has no results (that would be misleading - "try
# rephrasing" implies the query was the problem, when the search may not
# have run at all).
SEARCH_UNAVAILABLE_MESSAGE = (
    "I'm having trouble reaching the web search service right now. "
    "Please try again in a moment."
)
