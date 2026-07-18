"""Lightweight caching for the Web Search pipeline (PRESERVED, DORMANT
ARCHITECTURE - see this package's __init__.py for why this exists but isn't
wired into v1.0).

Keeps a short-lived result cache so the exact same query searched again
within a few minutes reuses prior search results instead of re-hitting
DuckDuckGo, and reuses prior page extractions instead of re-fetching/
re-parsing the same URL. Both use Django's own cache framework (the same
mechanism chat/models.py's FeatureFlag.is_enabled already relies on for its
own short-TTL cache), so this needs no new infrastructure and transparently
gets stronger (cross-process/cross-worker) the moment a shared backend like
Redis is configured via CACHES, with zero code change here.
"""
import hashlib

from django.core.cache import cache

SEARCH_RESULTS_TTL_SECONDS = 600  # 10 minutes
# A page's actual content changes far less often than DuckDuckGo's ranking
# does, so extractions can be cached longer than search result lists.
PAGE_EXTRACTION_TTL_SECONDS = 1800  # 30 minutes

_SEARCH_PREFIX = "web_search:results"
_PAGE_PREFIX = "web_search:page"


def _normalize_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def _search_key(query: str) -> str:
    digest = hashlib.sha256(_normalize_query(query).encode("utf-8")).hexdigest()
    return f"{_SEARCH_PREFIX}:{digest}"


def _page_key(url: str) -> str:
    digest = hashlib.sha256((url or "").encode("utf-8")).hexdigest()
    return f"{_PAGE_PREFIX}:{digest}"


def get_cached_search_results(query: str):
    """None means "not cached" (a real cache miss) - callers must not
    confuse this with an empty list, which means "cached, and the search
    genuinely found nothing" (also a valid, cacheable outcome)."""
    return cache.get(_search_key(query))


def set_cached_search_results(query: str, results: list) -> None:
    cache.set(_search_key(query), results, timeout=SEARCH_RESULTS_TTL_SECONDS)


def get_cached_page(url: str):
    return cache.get(_page_key(url))


def set_cached_page(url: str, extracted_page) -> None:
    cache.set(_page_key(url), extracted_page, timeout=PAGE_EXTRACTION_TTL_SECONDS)
