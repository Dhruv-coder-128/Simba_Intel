"""Custom allauth adapters - the documented extension points for gating
signup/social-login behind this app's FeatureFlag system (admin console ->
Feature Flags), so an admin can flip "registration" or "google_login" off
at runtime without a redeploy. Nothing here changes normal login/signup
behavior when the relevant flag is enabled (the default), so existing auth
flows are unaffected unless a flag is deliberately turned off.
"""
from django.contrib import messages
from django.shortcuts import redirect

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from chat.models import FeatureFlag


class SimbaAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return FeatureFlag.is_enabled('registration', default=True)


class SimbaSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # Gates EVERY Google login attempt, not just new signups (is_open_
        # for_signup only covers account creation) - an existing user who
        # already has Google connected is blocked too while this is off,
        # matching "disable Google Login" as a full kill switch rather than
        # just closing off new connections.
        if sociallogin.account.provider == 'google' and not FeatureFlag.is_enabled('google_login', default=True):
            messages.error(request, "Google sign-in is temporarily disabled. Please use email/password instead.")
            raise ImmediateHttpResponse(redirect('account_login'))
        super().pre_social_login(request, sociallogin)
