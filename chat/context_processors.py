"""Exposes the handful of FeatureFlag/RBAC values that affect shared,
base-level templates (the Google SSO button and signup link, both rendered
by allauth's own views rather than a chat/views.py view this app controls
directly; the profile-menu's Admin Console link, shared across every page
that includes it) - other flags (ai_chat, vision, image_generation,
analytics) are enforced server-side in their own views and passed into
those views' own context instead, not injected globally here.
"""
from chat.models import FeatureFlag
from chat.permissions import can_access_admin_console


def feature_flags(request):
    return {
        'google_login_enabled': FeatureFlag.is_enabled('google_login', default=True),
        'registration_enabled': FeatureFlag.is_enabled('registration', default=True),
    }


def rbac(request):
    # Purely a display decision (show/hide the Admin Console link) - never
    # the actual enforcement, which is require_role(Role.ADMIN) on every
    # admin-console view itself. Cheap even on every request: has_role_at_
    # least reads request.user.profile, already loaded via select_related
    # wherever it matters, and falls back safely for anonymous users.
    return {
        'can_access_admin_console': can_access_admin_console(request.user),
    }


def user_timezone(request):
    """Exposes the same IANA timezone name TimezoneMiddleware activated for
    this request, so any template's inline JS (Intl.DateTimeFormat /
    toLocaleString calls that can't go through Django's `date` filter) can
    format in the identical timezone instead of silently falling back to the
    browser's own local time."""
    user = getattr(request, 'user', None)
    tzname = 'UTC'
    if user and user.is_authenticated:
        profile = getattr(user, 'profile', None)
        tzname = getattr(profile, 'timezone', None) or 'UTC'
    return {'user_timezone': tzname}
