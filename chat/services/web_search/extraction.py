"""Content extraction step of the Web Search pipeline (PRESERVED, DORMANT
ARCHITECTURE - see this package's __init__.py for why this exists but isn't
wired into v1.0).

Fetches each search result's URL with an explicit, strict timeout, then
pulls out just the readable, main-article text via trafilatura - ads,
navigation, headers, footers, cookie banners, sidebars, and comments are
all stripped away automatically by trafilatura's own boilerplate-removal
(that's its whole purpose; no extra cleanup code is needed on top of it).

Every failure mode (timeout, connection error, non-HTML response,
trafilatura finding nothing) is caught here and treated as "skip this
page" - never raised - so one bad page never takes down the whole search.
Fetches happen concurrently across pages (extract_pages_concurrently), not
one after another, so 5 slow pages cost roughly one timeout's worth of
wall-clock time instead of five.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

import httpx
import trafilatura

from chat.services.web_search.cache import get_cached_page, set_cached_page

logger = logging.getLogger("simba_intel")

PAGE_TIMEOUT_SECONDS = 8.0
MAX_CONCURRENT_EXTRACTIONS = 5
# Per page, before it's handed to the summarizer - keeps the AI prompt
# bounded regardless of how long the source article actually is.
MAX_CONTENT_CHARS = 6000

# Identifies this as a bot fetching for a search feature (courteous, and
# some sites' WAFs reject requests with no User-Agent at all outright) -
# never executes any JavaScript from the page and never trusts its HTML,
# both handled by using trafilatura's own parser (lxml-based, not a browser
# engine) rather than anything that would render/execute page content.
USER_AGENT = "Mozilla/5.0 (compatible; SimbaIntelBot/1.0; +https://simba-intel.onrender.com)"


@dataclass
class ExtractedPage:
    url: str
    title: str
    domain: str
    text: str


def _fetch_html(url: str, timeout: float) -> Optional[str]:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url)
    except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPError) as e:
        logger.info("Web search: could not fetch %s (%s)", url, e)
        return None

    if response.status_code >= 400:
        logger.info("Web search: %s returned status %s - skipped", url, response.status_code)
        return None
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        logger.info("Web search: %s is not HTML (content-type=%s) - skipped", url, content_type)
        return None
    return response.text


def extract_page(result, timeout: float = PAGE_TIMEOUT_SECONDS) -> Optional[ExtractedPage]:
    """`result` is a search_engine.SearchResult. Returns an ExtractedPage on
    success, or None if the page couldn't be fetched, wasn't HTML, or had
    nothing trafilatura could extract - callers must treat None as "skip
    this source", never as an error to propagate. Wrapped in one broad
    try/except (in addition to the narrower ones inside _fetch_html) so
    literally nothing about a single bad page can ever crash the request -
    "gracefully skip that page" from the spec, taken literally."""
    logger.info("Web search: processing URL %s (domain=%s)", result.url, result.domain)
    try:
        cached = get_cached_page(result.url)
        if cached is not None:
            logger.info("Web search: %s served from cache (%d chars)", result.url, len(cached.text))
            return cached

        html = _fetch_html(result.url, timeout)
        if not html:
            # _fetch_html already logged the specific reason (timeout,
            # status code, non-HTML content-type).
            return None

        text = trafilatura.extract(
            html, url=result.url, include_comments=False, include_tables=False,
            favor_precision=True, output_format="txt",
        )
        if not text or not text.strip():
            logger.info("Web search: trafilatura found nothing extractable at %s - skipped", result.url)
            return None

        page = ExtractedPage(
            url=result.url, title=result.title, domain=result.domain,
            text=text.strip()[:MAX_CONTENT_CHARS],
        )
        logger.info(
            "Web search: extracted %d char(s) from %s (title=%r)", len(page.text), result.url, page.title,
        )
        set_cached_page(result.url, page)
        return page
    except Exception as e:
        # Never hidden: full exception type + message + traceback, at ERROR
        # level - an unexpected extraction failure (as opposed to the
        # expected/narrower cases above, which already log their own
        # specific reason) must be loud, not silently downgraded to "skip".
        logger.error(
            "Web search: extraction FAILED unexpectedly for %s - %s: %s",
            getattr(result, "url", "?"), type(e).__name__, e, exc_info=True,
        )
        return None


def extract_pages_concurrently(
    results: List, timeout: float = PAGE_TIMEOUT_SECONDS, max_workers: int = MAX_CONCURRENT_EXTRACTIONS,
) -> List[ExtractedPage]:
    """Extracts every result concurrently (bounded by max_workers) instead
    of sequentially - fetching 5 pages one after another at up to `timeout`
    seconds each could otherwise take up to 5x as long as the slowest
    single page. Returns only the pages that succeeded, in the same
    relative order as `results` (submission order, not completion order) -
    order matters since the summarizer numbers citations from it."""
    if not results:
        logger.info("Web search: no search results to extract from")
        return []

    logger.info(
        "Web search: extracting %d page(s) concurrently (max_workers=%d, timeout=%.1fs each)",
        len(results), min(max_workers, len(results)), timeout,
    )
    with ThreadPoolExecutor(max_workers=min(max_workers, len(results))) as pool:
        futures = [pool.submit(extract_page, r, timeout) for r in results]
        pages = [f.result() for f in futures]
    successful = [p for p in pages if p is not None]
    logger.info(
        "Web search: extraction complete - %d of %d page(s) succeeded (%s)",
        len(successful), len(results), [p.url for p in successful],
    )
    return successful
