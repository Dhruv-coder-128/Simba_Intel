"""Exposes the handful of FeatureFlag values that affect shared, base-level
templates (the Google SSO button and signup link, both rendered by
allauth's own views rather than a chat/views.py view this app controls
directly) - other flags (ai_chat, vision, image_generation, analytics) are
enforced server-side in their own views and passed into those views' own
context instead, not injected globally here.
"""
from chat.models import FeatureFlag


def feature_flags(request):
    return {
        'google_login_enabled': FeatureFlag.is_enabled('google_login', default=True),
        'registration_enabled': FeatureFlag.is_enabled('registration', default=True),
    }
