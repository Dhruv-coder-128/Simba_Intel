"""Browser navigation and web search tools for SIMBA_INTEL Agent.
Executes real local browser actions on the user's Windows operating system.
"""
import logging
import os
import subprocess
import urllib.parse
import webbrowser
from typing import Dict, Optional

from .registry import ExecutionResult, Tool, ToolParameter, global_tool_registry

logger = logging.getLogger("simba_intel.agent.browser")

POPULAR_SITES: Dict[str, str] = {
    "facebook": "https://www.facebook.com",
    "fb": "https://www.facebook.com",
    "youtube": "https://www.youtube.com",
    "yt": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "reddit": "https://reddit.com",
    "instagram": "https://www.instagram.com",
    "insta": "https://www.instagram.com",
    "gmail": "https://mail.google.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "wikipedia": "https://www.wikipedia.org",
    "amazon": "https://www.amazon.com",
    "twitch": "https://www.twitch.tv",
    "whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://openai.com",
    "claude": "https://claude.ai",
    "discord": "https://discord.com",
    "pinterest": "https://www.pinterest.com",
    "tiktok": "https://www.tiktok.com",
    "yahoo": "https://www.yahoo.com",
    "bing": "https://www.bing.com",
    "duckduckgo": "https://duckduckgo.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "quora": "https://www.quora.com",
    "medium": "https://medium.com",
    "apple": "https://www.apple.com",
    "microsoft": "https://www.microsoft.com",
}

SEARCH_ENGINES: Dict[str, str] = {
    "facebook": "https://www.facebook.com/search/top/?q={query}",
    "fb": "https://www.facebook.com/search/top/?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "yt": "https://www.youtube.com/results?search_query={query}",
    "google": "https://www.google.com/search?q={query}",
    "chrome": "https://www.google.com/search?q={query}",
    "google chrome": "https://www.google.com/search?q={query}",
    "browser": "https://www.google.com/search?q={query}",
    "default browser": "https://www.google.com/search?q={query}",
    "web": "https://www.google.com/search?q={query}",
    "github": "https://github.com/search?q={query}",
    "reddit": "https://www.reddit.com/search/?q={query}",
    "instagram": "https://www.instagram.com/explore/tags/{query}/",
    "insta": "https://www.instagram.com/explore/tags/{query}/",
    "twitter": "https://x.com/search?q={query}",
    "x": "https://x.com/search?q={query}",
    "wikipedia": "https://en.wikipedia.org/wiki/Special:Search?search={query}",
    "wiki": "https://en.wikipedia.org/wiki/Special:Search?search={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/?q={query}",
    "ddg": "https://duckduckgo.com/?q={query}",
    "amazon": "https://www.amazon.com/s?k={query}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={query}",
    "spotify": "https://open.spotify.com/search/{query}",
    "stackoverflow": "https://stackoverflow.com/search?q={query}",
    "stack overflow": "https://stackoverflow.com/search?q={query}",
    "quora": "https://www.quora.com/search?q={query}",
    "medium": "https://medium.com/search?q={query}",
    "yahoo": "https://search.yahoo.com/search?p={query}",
    "twitch": "https://www.twitch.tv/search?term={query}",
    "pinterest": "https://www.pinterest.com/search/pins/?q={query}",
    "tiktok": "https://www.tiktok.com/search?q={query}",
}

ENGINE_DISPLAY_NAMES: Dict[str, str] = {
    "facebook": "Facebook",
    "fb": "Facebook",
    "youtube": "YouTube",
    "yt": "YouTube",
    "google": "Google",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "browser": "Default Browser",
    "default browser": "Default Browser",
    "web": "Google",
    "github": "GitHub",
    "reddit": "Reddit",
    "instagram": "Instagram",
    "insta": "Instagram",
    "gmail": "Gmail",
    "wikipedia": "Wikipedia",
    "wiki": "Wikipedia",
    "duckduckgo": "DuckDuckGo",
    "ddg": "DuckDuckGo",
    "bing": "Bing",
    "twitter": "Twitter",
    "x": "X",
    "amazon": "Amazon",
    "linkedin": "LinkedIn",
    "spotify": "Spotify",
    "netflix": "Netflix",
    "stackoverflow": "Stack Overflow",
    "stack overflow": "Stack Overflow",
    "quora": "Quora",
    "medium": "Medium",
    "yahoo": "Yahoo",
    "twitch": "Twitch",
    "pinterest": "Pinterest",
    "tiktok": "TikTok",
}


def resolve_site_url(target: str) -> str:
    """Resolves a raw site name or domain to a complete HTTPS URL."""
    cleaned = target.strip().lower()
    if cleaned in POPULAR_SITES:
        return POPULAR_SITES[cleaned]
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return target.strip()
    if "." in cleaned:
        return f"https://{cleaned}"
    return f"https://www.{cleaned}.com"


def _launch_browser_url(url: str) -> bool:
    """Invokes the default browser on Windows to open a URL."""
    # 1. Direct Windows ShellExecute via os.startfile
    if hasattr(os, "startfile"):
        try:
            os.startfile(url)
            return True
        except Exception as e:
            logger.warning("os.startfile failed for %s: %s", url, e)

    # 2. Python standard webbrowser
    try:
        if webbrowser.open(url, new=2):
            return True
    except Exception as e:
        logger.warning("webbrowser.open failed for %s: %s", url, e)

    # 3. Windows command fallback
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", url],
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return True
    except Exception as e:
        logger.warning("cmd /c start failed for %s: %s", url, e)

    return False


def open_url(url: str) -> ExecutionResult:
    """Opens a website URL in the user's default web browser."""
    clean_url = url.strip()
    if not clean_url:
        return ExecutionResult(success=False, error="URL cannot be empty", action_type="browser")

    # If it's a popular site key or domain without scheme, resolve it
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        clean_url = resolve_site_url(clean_url)

    parsed = urllib.parse.urlparse(clean_url)
    if not parsed.netloc:
        return ExecutionResult(success=False, error=f"Invalid URL structure: {url}", action_type="browser")

    domain = parsed.netloc.lower().replace("www.", "")
    site_key = domain.split(".")[0]
    display_name = ENGINE_DISPLAY_NAMES.get(site_key, site_key.capitalize())

    try:
        opened = _launch_browser_url(clean_url)
        if not opened:
            return ExecutionResult(
                success=False,
                error="SIMBA can't execute this action because the local executor is unavailable.",
                details={"url": clean_url},
                action_type="browser",
            )

        return ExecutionResult(
            success=True,
            tool="open_url",
            action="open_url",
            target=display_name,
            output=f"Done — {display_name} is open.",
            details={
                "url": clean_url,
                "domain": parsed.netloc,
                "site_name": display_name,
                "verification": {"verified": True},
            },
            action_type="browser",
        )
    except Exception as e:
        logger.exception("Failed to open browser for %s: %s", clean_url, e)
        return ExecutionResult(
            success=False,
            tool="open_url",
            action="open_url",
            target=display_name if 'display_name' in locals() else url,
            error=f"Failed to open browser: {str(e)}",
            details={"url": clean_url, "verification": {"verified": False}},
            action_type="browser",
        )


def browser_search(query: str, engine: str = "google") -> ExecutionResult:
    """Searches a query on the specified search engine / platform using default browser."""
    clean_query = query.strip()
    if not clean_query:
        return ExecutionResult(success=False, error="Search query cannot be empty", action_type="browser_search")

    engine_key = engine.lower().strip()
    template = SEARCH_ENGINES.get(engine_key, SEARCH_ENGINES["google"])
    encoded_query = urllib.parse.quote_plus(clean_query)
    target_url = template.format(query=encoded_query)

    engine_name = ENGINE_DISPLAY_NAMES.get(engine_key, engine_key.capitalize())

    try:
        opened = _launch_browser_url(target_url)
        if not opened:
            return ExecutionResult(
                success=False,
                tool="browser_search",
                action="browser_search",
                target=engine_name,
                error="SIMBA can't execute this action because the local executor is unavailable.",
                details={"query": clean_query, "engine": engine_key, "verification": {"verified": False}},
                action_type="browser_search",
            )

        return ExecutionResult(
            success=True,
            tool="browser_search",
            action="browser_search",
            target=engine_name,
            output=f"Searched '{clean_query}' on {engine_name}.",
            details={
                "query": clean_query,
                "engine": engine_key,
                "url": target_url,
                "verification": {"verified": True},
            },
            action_type="browser_search",
        )
    except Exception as e:
        logger.exception("Failed to search '%s' on %s: %s", clean_query, engine, e)
        return ExecutionResult(
            success=False,
            tool="browser_search",
            action="browser_search",
            target=engine_name,
            error=f"Failed to execute search: {str(e)}",
            details={"query": clean_query, "engine": engine_key, "verification": {"verified": False}},
            action_type="browser_search",
        )


def search_web_cloud(query: str, engine: str = "google") -> ExecutionResult:
    """Performs a web search in the cloud and returns structured results."""
    clean_query = query.strip()
    if not clean_query:
        return ExecutionResult(success=False, error="Search query cannot be empty", action_type="search", execution_target="cloud")
    try:
        from chat.views import _get_web_search_results
        results = _get_web_search_results(clean_query)
        if results:
            summary_lines = []
            for i, r in enumerate(results[:5], 1):
                title = r.get("title", "No title")
                url = r.get("url", "")
                snippet = r.get("content", "")
                summary_lines.append(f"{i}. [{title}]({url})\n   {snippet}")
            output = f"Web search results for '{clean_query}':\n\n" + "\n\n".join(summary_lines)
            return ExecutionResult(
                success=True,
                tool="search_web",
                action="search_web",
                target="Web",
                output=output,
                details={"query": clean_query, "results": results[:5], "verification": {"verified": True}},
                action_type="search",
                execution_target="cloud",
            )
        else:
            return ExecutionResult(
                success=True,
                tool="search_web",
                action="search_web",
                target="Web",
                output=f"Searched for '{clean_query}', but no relevant live results were returned.",
                details={"query": clean_query, "results": [], "verification": {"verified": True}},
                action_type="search",
                execution_target="cloud",
            )
    except Exception as e:
        logger.warning("search_web_cloud failed: %s", e)
        return ExecutionResult(
            success=False,
            tool="search_web",
            action="search_web",
            target="Web",
            error=f"Cloud web search encountered an error: {str(e)}",
            details={"query": clean_query, "verification": {"verified": False}},
            action_type="search",
            execution_target="cloud",
        )


# Register tools
global_tool_registry.register(
    Tool(
        name="open_url",
        display_name="Open Website",
        icon="fa-globe",
        category="web",
        example_prompt="Open https://github.com in browser",
        description="Opens a website URL in the user's default browser on their local PC.",
        parameters=[
            ToolParameter(name="url", type="string", description="The full URL, website name, or domain to open (e.g. 'facebook', 'https://github.com').", required=True),
        ],
        func=open_url,
        action_type="browser",
        execution_target="desktop",
    )
)

global_tool_registry.register(
    Tool(
        name="browser_search",
        display_name="Search on Site",
        icon="fa-compass",
        category="web",
        example_prompt="Search YouTube for Python tutorials",
        description="Searches for a topic on a platform/engine (YouTube, Facebook, Google, GitHub, Reddit, Instagram, Wikipedia, Bing, DuckDuckGo) in the local browser.",
        parameters=[
            ToolParameter(name="query", type="string", description="The search query text (e.g. 'Roblox', 'dhruv', 'Python tutorials').", required=True),
            ToolParameter(
                name="engine",
                type="string",
                description="The search engine or website to search on.",
                required=False,
                default="google",
                enum=["google", "youtube", "facebook", "github", "bing", "duckduckgo", "reddit", "instagram", "wikipedia", "twitter", "x", "amazon", "linkedin", "spotify"],
            ),
        ],
        func=browser_search,
        action_type="browser_search",
        execution_target="desktop",
    )
)

global_tool_registry.register(
    Tool(
        name="search_web",
        display_name="Web Search",
        icon="fa-search",
        category="web",
        example_prompt="Search the web for latest AI news",
        description="Searches the web for information in the cloud and retrieves synthesized results.",
        parameters=[
            ToolParameter(name="query", type="string", description="The search query text.", required=True),
            ToolParameter(name="engine", type="string", description="Target engine or website.", required=False, default="google"),
        ],
        func=search_web_cloud,
        action_type="search",
        execution_target="cloud",
    )
)

