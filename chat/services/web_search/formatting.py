"""Formats Web Search pipeline output into the plain-data shapes a view/
template layer would need (PRESERVED, DORMANT ARCHITECTURE - see this
package's __init__.py for why this exists but isn't wired into v1.0).

Kept separate from extraction.py/summarizer.py so a future change to how
sources are displayed (e.g. adding a favicon) never needs to touch the
extraction or AI-calling code at all.
"""
from typing import List, Optional


def format_sources(pages: List, snippet_only: Optional[List] = None) -> list:
    """Sources shown to the user, in citation order - full-content pages
    first, then snippet-only fallbacks (pages whose content couldn't be
    extracted but whose search snippet is still shown as a source). Every
    entry has exactly the 3 fields the spec requires - title, website
    (domain), and a clickable URL - and nothing else, since this would be
    stored verbatim as Message.extra_data and serialized into an HTTP
    response header for the live-streaming case."""
    sources = [{"title": p.title, "domain": p.domain, "url": p.url} for p in pages]
    if snippet_only:
        sources += [{"title": r.title, "domain": r.domain, "url": r.url} for r in snippet_only]
    return sources
