from zoneinfo import ZoneInfoNotFoundError

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone as tz

from chat.models import FeatureFlag, Role
from chat.permissions import has_role_at_least

# Health checks, static assets, and the admin console itself must always be
# reachable - the console is precisely what an Admin+ needs to turn
# maintenance mode back off.
MAINTENANCE_EXEMPT_PREFIXES = ('/admin-console/', '/static/', '/health/', '/accounts/login/', '/accounts/logout/')


class MaintenanceModeMiddleware:
    """The "emergency kill switch" - toggled from the admin console (a
    FeatureFlag row, not a settings/env change), so it can be flipped
    without a redeploy. Role >= Admin always passes through (matching admin
    console access - anyone who can reach Feature Flags to turn maintenance
    mode back off must not be locked out by it themselves), so a locked-out
    site can still be unlocked."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_blocked(request):
            html = render_to_string('maintenance.html')
            return HttpResponse(html, status=503)
        return self.get_response(request)

    def _is_blocked(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and has_role_at_least(user, Role.ADMIN):
            return False
        if request.path.startswith(MAINTENANCE_EXEMPT_PREFIXES):
            return False
        return FeatureFlag.is_enabled('maintenance_mode', default=False)


class TimezoneMiddleware:
    """The one place every timestamp in the app gets its timezone from.
    Activates the signed-in user's UserProfile.timezone for the duration of
    the request, so every `{{ x|date:... }}` template render and every
    timezone.localtime()/localdate() call downstream (chat grouping,
    analytics day/week boundaries, admin console) automatically agrees -
    no per-view or per-template changes needed. Falls back to
    settings.TIME_ZONE (UTC) for anonymous users or an invalid/unrecognized
    IANA name rather than raising."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        tzname = None
        if user and user.is_authenticated:
            profile = getattr(user, 'profile', None)
            tzname = getattr(profile, 'timezone', None) if profile else None
        if tzname:
            try:
                tz.activate(tzname)
            except ZoneInfoNotFoundError:
                tz.deactivate()
        else:
            tz.deactivate()
        try:
            return self.get_response(request)
        finally:
            tz.deactivate()
