from django.http import HttpResponse
from django.template.loader import render_to_string

from chat.models import FeatureFlag

# Health checks, static assets, and the admin console itself must always be
# reachable - the console is precisely what a superuser needs to turn
# maintenance mode back off.
MAINTENANCE_EXEMPT_PREFIXES = ('/admin-console/', '/static/', '/health/', '/accounts/login/', '/accounts/logout/')


class MaintenanceModeMiddleware:
    """The "emergency kill switch" - toggled from the admin console (a
    FeatureFlag row, not a settings/env change), so it can be flipped
    without a redeploy. Superusers always pass through, so a locked-out
    site can still be unlocked."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_blocked(request):
            html = render_to_string('maintenance.html')
            return HttpResponse(html, status=503)
        return self.get_response(request)

    def _is_blocked(self, request):
        if getattr(request, 'user', None) and request.user.is_authenticated and request.user.is_superuser:
            return False
        if request.path.startswith(MAINTENANCE_EXEMPT_PREFIXES):
            return False
        return FeatureFlag.is_enabled('maintenance_mode', default=False)
