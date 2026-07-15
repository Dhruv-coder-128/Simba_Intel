"""Turns a raw User-Agent header into short, human-readable browser/device/OS
labels shown on the Account Security page and stored on login records - e.g.
"Chrome 122" / "Desktop" / "Windows 10" instead of the full raw string.
Centralized here so SecurityEvent, UserProfile's last-login snapshot, and
UserSession all agree on the same labels.

parse_client_info() is guaranteed to never raise and never return an empty
or None value for any field - callers (chat/signals.py) insert its output
directly into NOT NULL database columns on every login, including from
mobile browsers and proxies that send minimal, missing, or malformed
User-Agent headers, and a parsing hiccup must never be able to turn into a
failed login.
"""
import logging

from user_agents import parse as parse_user_agent

logger = logging.getLogger(__name__)

UNKNOWN_BROWSER = "Unknown Browser"
UNKNOWN_DEVICE = "Unknown Device"
UNKNOWN_OS = "Unknown OS"


def parse_client_info(user_agent_string: str) -> tuple[str, str, str]:
    """Returns (browser, device, os) display strings for a raw UA header.
    Never raises and never returns a falsy value - any failure anywhere in
    parsing falls back to the Unknown_* constants above rather than
    propagating, since this only ever feeds display text, never a security
    decision worth blocking a login over."""
    if not user_agent_string:
        return UNKNOWN_BROWSER, UNKNOWN_DEVICE, UNKNOWN_OS

    try:
        return _parse(user_agent_string)
    except Exception:
        # A third-party parsing library choking on an unusual real-world UA
        # string (some mobile browsers and proxies send minimal or malformed
        # ones) is exactly the kind of thing that must never be allowed to
        # turn into a failed login - log it for visibility and move on.
        logger.exception("User-Agent parsing failed for: %r", user_agent_string[:200])
        return UNKNOWN_BROWSER, UNKNOWN_DEVICE, UNKNOWN_OS


def _parse(user_agent_string: str) -> tuple[str, str, str]:
    ua = parse_user_agent(user_agent_string)

    browser_family = getattr(ua.browser, "family", None) or ""
    browser_version = getattr(ua.browser, "version_string", None) or ""
    browser = f"{browser_family} {browser_version}".strip()
    if not browser or browser_family == "Other":
        browser = UNKNOWN_BROWSER

    os_family = getattr(ua.os, "family", None) or ""
    os_version = getattr(ua.os, "version_string", None) or ""
    os_name = f"{os_family} {os_version}".strip()
    if not os_name or os_family == "Other":
        os_name = UNKNOWN_OS

    device_family = getattr(ua.device, "family", None) or ""
    if ua.is_mobile:
        device = device_family if device_family and device_family != "Other" else "Mobile"
    elif ua.is_tablet:
        device = device_family if device_family and device_family != "Other" else "Tablet"
    elif ua.is_pc:
        device = "Desktop"
    else:
        device = device_family if device_family and device_family != "Other" else UNKNOWN_DEVICE

    return browser, device, os_name
