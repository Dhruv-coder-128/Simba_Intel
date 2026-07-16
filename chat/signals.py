"""Auth-related signal receivers - kept separate from views.py since these
fire from Django/allauth's own login machinery, not from a request handler
in this app.

Every receiver below that isn't itself the security-critical action (i.e.
everything except the actual auth decision Django/allauth already made) is
wrapped in a broad try/except: a login, signup, or email confirmation must
never fail because a tracking/audit write did - see _guarded() and its
docstring."""
import functools
import logging
from datetime import timedelta

from django.contrib.auth.signals import user_login_failed, user_logged_in
from django.dispatch import receiver
from django.utils import timezone

from allauth.account.signals import email_confirmed
from allauth.socialaccount.signals import social_account_added, social_account_updated

from chat.models import FailedLoginAttempt, Role, SecurityEvent, UserProfile, UserSession
from chat.utils.device import UNKNOWN_BROWSER, UNKNOWN_DEVICE, UNKNOWN_OS, parse_client_info
from chat.utils.request_info import client_ip, raw_user_agent

logger = logging.getLogger(__name__)


def _guarded(label):
    """Decorator: runs the wrapped signal receiver inside a try/except that
    swallows and logs ANY exception rather than letting it propagate. Signal
    receivers registered on Django/allauth's own auth signals run
    synchronously, in-line, as part of the login/signup/confirm request - an
    unhandled exception here doesn't just fail silently, it fails the
    surrounding login/signup/confirmation itself. Security/device tracking
    is a nice-to-have layered on top of auth, not a precondition for it, so
    a failure here must degrade to "this login isn't tracked this time",
    never to "this login failed"."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:
                logger.exception("%s failed (non-fatal, auth flow continues)", label)
        return wrapper
    return decorator


@receiver(user_login_failed)
@_guarded("record_failed_login")
def record_failed_login(sender, credentials, request=None, **kwargs):
    FailedLoginAttempt.objects.create(
        email_attempted=(credentials.get('login') or credentials.get('email') or credentials.get('username') or '')[:254],
        ip_address=client_ip(request),
        user_agent=raw_user_agent(request),
    )


@receiver(user_logged_in)
@_guarded("record_login_security_event")
def record_login_security_event(sender, user, request=None, **kwargs):
    ip = client_ip(request)
    raw_ua = raw_user_agent(request)
    # parse_client_info() itself never raises and never returns a falsy
    # value, but the `or` fallbacks below are a second line of defense -
    # this exact spot (the values going into a NOT NULL insert) is where a
    # None slipping through anywhere upstream would otherwise become a
    # database IntegrityError instead of just a generic label.
    browser, device, os_name = parse_client_info(raw_ua)
    browser = browser or UNKNOWN_BROWSER
    device = device or UNKNOWN_DEVICE
    os_name = os_name or UNKNOWN_OS

    # Deliberately "info" severity and not flagged as suspicious on its own -
    # this is a plain login record, not a fraud signal. It exists so the
    # admin security panel (and the user-facing Account Security page) has a
    # real login timeline per user rather than nothing at all; multi-IP/geo
    # anomaly detection would build on top of this later but isn't
    # implemented (no geo-IP lookup is wired in - "location" always reads
    # "Unknown Location" until one is).
    SecurityEvent.objects.create(
        user=user,
        event_type="login",
        severity="info",
        ip_address=ip,
        user_agent=raw_ua,
        browser=browser,
        device=device,
        os=os_name,
        detail=f"Logged in from {ip or 'Unknown IP'}",
    )

    # Snapshot on UserProfile so "last login was X from Y" doesn't need a
    # query against the SecurityEvent log every time it's displayed.
    profile = UserProfile.get_or_create_for(user)
    profile.last_login_ip = ip
    profile.last_login_browser = browser
    profile.last_login_device = device
    profile.last_login_os = os_name
    profile.save(update_fields=['last_login_ip', 'last_login_browser', 'last_login_device', 'last_login_os'])

    # One UserSession row per Django session_key - powers the Account
    # Security page's device list and logout-this-device/logout-all.
    # Django's login() rotates/creates the session key before firing this
    # signal (session-fixation protection), so it's normally already
    # populated here - guarded with getattr/None-check anyway rather than
    # assumed, since a missing session key should just skip this row, not
    # blow up the login.
    session_key = getattr(getattr(request, 'session', None), 'session_key', None)
    if session_key:
        UserSession.objects.update_or_create(
            session_key=session_key,
            defaults={
                'user': user,
                'ip_address': ip,
                'user_agent': raw_ua,
                'browser': browser,
                'device': device,
                'os': os_name,
            },
        )


@receiver(email_confirmed)
@_guarded("record_email_verified")
def record_email_verified(sender, request, email_address, **kwargs):
    profile = UserProfile.get_or_create_for(email_address.user)
    profile.email_verified_at = timezone.now()
    update_fields = ['email_verified_at']
    # Auto-promotion, one tier only (User -> Verified) - never touches an
    # account that's already Moderator or above, so confirming email can
    # never demote an admin/moderator back down to a plain "verified" role.
    if profile.role == Role.USER:
        profile.role = Role.VERIFIED
        update_fields.append('role')
    profile.save(update_fields=update_fields)


@receiver(social_account_added)
@receiver(social_account_updated)
@_guarded("record_google_link")
def record_google_link(sender, request, sociallogin, **kwargs):
    """Imports the provider's profile picture and, only for a genuinely new
    signup (not an existing user connecting Google from account settings),
    records that the account originated from Google. A freshly-created
    account's date_joined is within moments of "now" at this point in the
    request; an existing user connecting Google later has an old
    date_joined, so this never overwrites an established account's original
    registration_source."""
    account = sociallogin.account
    if account.provider != 'google':
        return

    user = sociallogin.user
    profile = UserProfile.get_or_create_for(user)

    avatar_url = account.get_avatar_url()
    if avatar_url:
        profile.avatar_url = avatar_url

    is_fresh_signup = (timezone.now() - user.date_joined) < timedelta(minutes=1)
    if is_fresh_signup:
        profile.registration_source = 'google'

    profile.save()
