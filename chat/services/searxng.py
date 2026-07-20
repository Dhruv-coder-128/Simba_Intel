"""SearXNG-backed search - the primary web/image search engine (see
chat/views.py's _get_web_search_results and _rewrite_images_in_stream).
Self-hosted, so it needs SEARXNG_URL configured (a running SearXNG
instance's base URL, e.g. "https://searxng.example.com"); if it isn't set,
every function here returns an empty result rather than raising, so a
deployment without SearXNG configured degrades to "no search results" /
"no image" instead of crashing - callers must treat an empty result as
"nothing real was found," never substitute a placeholder.
"""
import hashlib
import logging

import requests
from django.core.cache import cache

from chat.utils.env import get_env_var

logger = logging.getLogger("simba_intel")

_CACHE_PREFIX = "searxng"
_CACHE_TTL_SECONDS = 3600


def _cache_key(category: str, query: str) -> str:
    # A raw query can contain spaces/unicode/arbitrary length, none of which
    # are safe (or bounded) memcached key characters - hash it instead of
    # interpolating it directly, same reasoning as any other cache key here.
    digest = hashlib.sha1(query.strip().lower().encode("utf-8")).hexdigest()
    return f"{_CACHE_PREFIX}:{category}:{digest}"
# Fast timeout per the product requirement ("Fast timeout") - a slow/dead
# SearXNG instance must never stall page/response generation.
_REQUEST_TIMEOUT_SECONDS = 4.0


def _base_url() -> str:
    return get_env_var("SEARXNG_URL", "").rstrip("/")


def _search(query: str, category: str, cache_key: str) -> list:
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    base = _base_url()
    if not base or not query.strip():
        return []

    try:
        response = requests.get(
            f"{base}/search",
            params={
                "q": query,
                "format": "json",
                "categories": category,
                # SafeSearch enabled per the product requirement - 2 = strict.
                "safesearch": 2,
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SimbaIntelBot/1.0)"},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except Exception as e:
        logger.warning("SearXNG %s search failed (query=%r): %s", category, query, e)
        return []

    cache.set(cache_key, results, timeout=_CACHE_TTL_SECONDS)
    return results


def searxng_web_search(query: str, count: int = 5) -> list:
    """General web search - shape-compatible with the old Tavily results
    list (each item has 'title'/'content'/'url'), so it's a drop-in
    replacement wherever that shape is consumed."""
    key = _cache_key("general", query)
    results = _search(query, "general", key)
    return [
        {"title": r.get("title", ""), "content": r.get("content") or "", "url": r.get("url", "")}
        for r in results[:count]
    ]


def searxng_image_search(query: str) -> str:
    """One real image URL that actually matches `query`, or "" if SearXNG
    isn't configured or nothing was found - "" means the caller must not
    show an image at all, never fall back to a placeholder/random one."""
    key = _cache_key("images", query)
    results = _search(query, "images", key)
    for r in results:
        url = r.get("img_src") or r.get("url") or ""
        if url:
            return url
    return ""
