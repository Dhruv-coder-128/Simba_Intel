"""Auth-related signal receivers - kept separate from views.py since these
fire from Django/allauth's own login machinery, not from a request handler
in this app."""
from django.contrib.auth.signals import user_login_failed, user_logged_in
from django.dispatch import receiver

from chat.models import FailedLoginAttempt, SecurityEvent


def _client_ip(request):
    if not request:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request=None, **kwargs):
    FailedLoginAttempt.objects.create(
        email_attempted=(credentials.get('login') or credentials.get('email') or credentials.get('username') or '')[:254],
        ip_address=_client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT', '') if request else '')[:500],
    )


@receiver(user_logged_in)
def record_login_security_event(sender, user, request=None, **kwargs):
    # Deliberately "info" severity and not flagged as suspicious on its own -
    # this is a plain login record, not a fraud signal. It exists so the
    # admin security panel has a real login timeline per user rather than
    # nothing at all; multi-IP/geo anomaly detection would build on top of
    # this later but isn't implemented (no geo-IP lookup is wired in).
    SecurityEvent.objects.create(
        user=user,
        event_type="login",
        severity="info",
        ip_address=_client_ip(request),
        detail=f"Logged in from {_client_ip(request) or 'unknown IP'}",
    )
