import logging
from zoneinfo import ZoneInfoNotFoundError

from django.db import connection, close_old_connections
from django.db.utils import OperationalError, InterfaceError
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone as tz

from chat.models import FeatureFlag, Role
from chat.permissions import has_role_at_least

db_logger = logging.getLogger("simba_intel.db")


class DatabaseResilienceMiddleware:
    """Catches operational database connectivity failures (such as Supabase connection
    pool exhaustion or transient network interruptions) at the HTTP request boundary.
    Logs the exception cleanly, disposes of stale connection handles, and returns
    structured JSON for API endpoints or a SIMBA-branded retry screen for HTML views,
    preventing ugly raw 500 error pages without exposing credentials or internal hostnames."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except (OperationalError, InterfaceError) as db_err:
            db_logger.error(
                "Database connectivity exception on [%s %s]: %s",
                request.method, request.path, db_err,
                exc_info=True
            )
            # Unconditionally dispose of stale or broken connections
            try:
                connection.close()
                close_old_connections()
            except Exception:
                pass

            # Detect API / JSON request
            is_api = (
                request.path.startswith(('/api/', '/ask_ai/', '/system_stats/', '/folders/', '/session/')) or
                request.headers.get('Accept', '').find('application/json') != -1 or
                request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            )

            if is_api:
                return JsonResponse({
                    "status": "error",
                    "error": "Database service is temporarily busy. Please retry in a moment.",
                    "code": "DB_CONNECTION_LIMIT"
                }, status=503)

            try:
                html = render_to_string('db_error.html', {'path': request.path})
                return HttpResponse(html, status=503)
            except Exception:
                return HttpResponse(
                    "<!DOCTYPE html><html><head><title>SIMBA_INTEL - Service Busy</title>"
                    "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
                    "<style>body{background:#0b0c10;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}"
                    ".c{text-align:center;max-width:440px;padding:32px;background:rgba(20,24,33,0.9);border:1px solid rgba(0,229,255,0.25);border-radius:12px;box-shadow:0 0 40px rgba(0,0,0,0.8);}"
                    "h1{color:#00e5ff;font-size:20px;letter-spacing:1px;margin-bottom:12px;}"
                    "p{color:rgba(255,255,255,0.7);font-size:14px;line-height:1.6;margin-bottom:20px;}"
                    "button{background:#00e5ff;color:#0b0c10;border:none;padding:10px 22px;border-radius:6px;font-weight:700;cursor:pointer;}"
                    "</style></head><body><div class='c'>"
                    "<h1>SIMBA INTEL &mdash; SERVICE BUSY</h1>"
                    "<p>The database connection pool is currently at maximum capacity. Standing by to reconnect...</p>"
                    "<button onclick='location.reload()'>RETRY CONNECTION</button>"
                    "</div></body></html>",
                    status=503
                )


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
