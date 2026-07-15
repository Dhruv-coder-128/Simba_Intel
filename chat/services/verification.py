"""Email-verification gating.

Deliberately a no-op whenever ACCOUNT_EMAIL_VERIFICATION is "none" -
flipping enforcement on for every existing account the moment this code
ships (regardless of whether real SMTP is even configured) would lock
everyone, including the project owner, out of image gen/vision/settings.
Enforcement only activates once the owner opts in via that env-driven
setting *and* has a working email backend behind it.

Note: allauth's "mandatory" mode blocks LOGIN itself for unverified users
(they never reach the app at all) - that's a different, stricter product
than what's being built here ("let them chat, gate the premium features").
"optional" is the setting that matches this feature: allauth still sends
confirmation emails and tracks EmailAddress.verified, but doesn't block
login, so users land in the app and see the in-app verification gate.
Both "optional" and "mandatory" are treated as "verification is active"
here since either one means EmailAddress.verified is actually meaningful.
"""
from django.conf import settings
from allauth.account.models import EmailAddress


def verification_required() -> bool:
    return getattr(settings, "ACCOUNT_EMAIL_VERIFICATION", "none") in ("mandatory", "optional")


def is_email_verified(user) -> bool:
    if not verification_required():
        return True
    if not user.is_authenticated:
        return False
    return EmailAddress.objects.filter(user=user, verified=True).exists()
