"""DuckDuckGo search step of the Web Search pipeline (PRESERVED, DORMANT
ARCHITECTURE - see this package's __init__.py for why this exists but isn't
wired into v1.0).

Uses the `ddgs` package - the actively-maintained successor to the
now-deprecated `duckduckgo_search` package (same `DDGS` class and API;
`duckduckgo_search` itself emits a runtime warning pointing here, and
empirically returned zero results in testing against the old package,
confirming the rename matters in practice, not just in name). Never
Google - DuckDuckGo only, per this feature's own requirement.

Neither `ddgs` nor `trafilatura` (extraction.py's dependency) are in
requirements.txt in v1.0 - both were removed when this feature was pulled
from the release. `pip install ddgs trafilatura` before reintroducing it.
"""
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from ddgs import DDGS

from chat.services.web_search.cache import get_cached_search_results, set_cached_search_results

logger = logging.getLogger("simba_intel")

MAX_RESULTS = 5
# Pulled from DDGS before quality filtering narrows it down to MAX_RESULTS -
# a wider raw pool means dropping spam/duplicates still leaves enough good
# candidates left over.
RAW_FETCH_COUNT = 12

# Domains/suffixes whose content is reliably high quality - "prefer official
# websites, documentation, government websites, Wikipedia, trusted blogs,
# trusted news" from the spec. This is a sort-order boost, not an allowlist:
# nothing outside this set is excluded, it's just ranked after these.
TRUSTED_DOMAIN_SUFFIXES = (
    ".gov", ".edu", "wikipedia.org", "python.org", "djangoproject.com",
    "developer.mozilla.org", "docs.python.org", "readthedocs.io",
    "stackoverflow.com", "github.com", "reuters.com", "apnews.com",
    "bbc.com", "bbc.co.uk",
)

# Non-HTML/binary extensions trafilatura can't meaningfully extract from -
# filtered out before ever attempting a fetch, not discovered after wasting
# one.
SKIP_URL_EXTENSIONS = (
    ".pdf", ".zip", ".exe", ".dmg", ".mp4", ".mp3", ".jpg", ".jpeg",
    ".png", ".gif", ".webp", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


class WebSearchUnavailableError(Exception):
    """Raised when the DuckDuckGo search REQUEST itself failed - network
    error, timeout, or ddgs's own DDGSException. Deliberately distinct from
    "the search ran and genuinely found zero results": confirmed by direct
    HTTP inspection during a real production incident that DuckDuckGo's
    html endpoint can soft-block automated traffic by returning its own
    homepage (HTTP 202, no result markup) instead of an error - the ddgs
    library parses that "successfully" and raises DDGSException("No
    results found."), identical to what it would raise for a genuinely
    obscure query with zero real results. Since the two cases are
    indistinguishable at that level, any exception from the search call is
    treated as "the search failed/was blocked", never as proof the topic
    has no results - see pipeline.py's use of this exception type.

    This soft-blocking behavior (observed for the query "current news on
    donald trump", which obviously has many real results) is a major reason
    this feature was pulled from v1.0 rather than shipped as-is - a future
    reintroduction should evaluate a provider with an official API rather
    than an HTML-scraping endpoint."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    domain: str


def _domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def is_usable_url(url: str) -> bool:
    """Rejects anything that isn't a plain http(s) page worth fetching -
    the security requirement ("never trust webpage HTML", "prevent XSS")
    starts here: a non-http(s) scheme (javascript:, data:, file:, etc.)
    is refused outright rather than ever being handed to a browser as a
    "clickable URL" in the sources list."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    return not parsed.path.lower().endswith(SKIP_URL_EXTENSIONS)


def _is_trusted(domain: str) -> bool:
    return any(domain == s.lstrip(".") or domain.endswith(s) for s in TRUSTED_DOMAIN_SUFFIXES)


def _dedupe_and_filter(raw_results) -> list:
    """Drops broken/invalid/unusable URLs, collapses duplicates (the same
    URL, or more than 2 results from the same domain - a domain
    occasionally legitimately has 2 distinct relevant pages, e.g. two
    different Wikipedia articles), and sorts trusted domains first with a
    stable sort (so within each tier, DuckDuckGo's own relevance ranking is
    preserved)."""
    seen_urls = set()
    domain_counts = {}
    filtered = []
    for r in raw_results:
        url = (r.get("href") or "").strip()
        title = (r.get("title") or "").strip()
        snippet = (r.get("body") or "").strip()
        if not url or not title or not is_usable_url(url) or url in seen_urls:
            continue
        domain = _domain_of(url)
        if not domain or domain_counts.get(domain, 0) >= 2:
            continue
        seen_urls.add(url)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        filtered.append(SearchResult(title=title, url=url, snippet=snippet, domain=domain))

    filtered.sort(key=lambda r: 0 if _is_trusted(r.domain) else 1)
    return filtered


def search_web(query: str, max_results: int = MAX_RESULTS) -> list:
    """Returns up to `max_results` SearchResult objects for `query`.

    Raises WebSearchUnavailableError if the DuckDuckGo request itself
    failed (see that class's docstring for exactly why this is NOT folded
    into "return an empty list") - callers must not treat that the same as
    a clean, successful search that happened to find nothing. Only a
    genuine empty/blank `query` short-circuits to an empty list without
    ever calling DuckDuckGo at all.

    Uses a short-lived cache (cache.py) keyed by the normalized query text,
    so repeating the same search shortly after reuses the prior result set
    instead of re-hitting DuckDuckGo."""
    query = (query or "").strip()
    if not query:
        logger.info("Web search: empty query - skipping DuckDuckGo call entirely")
        return []

    cached = get_cached_search_results(query)
    if cached is not None:
        logger.info(
            "Web search: query=%r served from cache (%d cached result(s))", query, len(cached),
        )
        return cached[:max_results]

    logger.info(
        "Web search: requesting DuckDuckGo for query=%r (backend=duckduckgo, "
        "raw_fetch_count=%d, safesearch=moderate)", query, RAW_FETCH_COUNT,
    )
    try:
        # backend="duckduckgo" (never the default "auto") is not optional:
        # ddgs's "auto" backend transparently falls through to scraping
        # Google, Yahoo, and Brave as well - confirmed by watching its own
        # request log during testing - which directly violates this
        # feature's own requirement to use DuckDuckGo only.
        raw_results = DDGS().text(
            query, max_results=RAW_FETCH_COUNT, safesearch="moderate", backend="duckduckgo",
        )
    except Exception as e:
        # Never hidden: the real exception type, message, and traceback are
        # logged at ERROR level - this must be loud and diagnosable, not a
        # silently-swallowed warning that gets reported to the user as a
        # generic "no results" (that conflation was the root cause of a
        # real production bug - a soft anti-bot block on DuckDuckGo's side
        # was indistinguishable from "genuinely zero results" once reduced
        # to a bare warning + empty list).
        logger.error(
            "Web search: DuckDuckGo REQUEST FAILED for query=%r - %s: %s",
            query, type(e).__name__, e, exc_info=True,
        )
        raise WebSearchUnavailableError(f"{type(e).__name__}: {e}") from e

    raw_results = raw_results or []
    logger.info("Web search: DuckDuckGo returned %d raw result(s) for query=%r", len(raw_results), query)
    for i, r in enumerate(raw_results):
        logger.info(
            "Web search: raw result #%d - title=%r href=%r", i, r.get("title"), r.get("href"),
        )

    results = _dedupe_and_filter(raw_results)
    logger.info(
        "Web search: %d of %d raw result(s) survived filtering/dedup for query=%r - urls=%s",
        len(results), len(raw_results), query, [r.url for r in results],
    )
    # Cache the wider filtered pool, not just the slice eventually returned,
    # so a differently-sized max_results request for the same query still
    # benefits from this same cached search.
    set_cached_search_results(query, results)
    return results[:max_results]
