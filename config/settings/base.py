"""
Base Django settings for the Simba_INTEL project - every setting that is
IDENTICAL regardless of environment (dev vs prod) lives here. Environment-
specific behavior lives in config/settings/dev.py and config/settings/prod.py,
which both do `from config.settings.base import *` and then override only
what genuinely differs.

This is the industry-standard config/settings/{base,dev,prod}.py split.
`simba_web/settings.py` (the module every existing entrypoint - manage.py,
simba_web/wsgi.py, simba_web/asgi.py - still points at by default) is now a
thin backward-compatibility shim that imports everything from this file, so
nothing that already worked breaks: it is byte-for-byte behaviorally
identical to what simba_web/settings.py used to contain directly.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/topics/settings/
For the full list of settings and their values, see
https://docs.djangoproject.com/en/6.0/ref/settings/
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'. This file
# lives two directories below the project root (config/settings/base.py),
# one deeper than the old simba_web/settings.py - hence three .parent calls
# here where the old file only needed two.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, ".env"))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
INSECURE_DEFAULT_SECRET_KEY = 'django-insecure-0dxud_bzn1-j5*+avl*c7ossn*qcsin#*36(l#y04xzyv$nur8'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', INSECURE_DEFAULT_SECRET_KEY)

# SECURITY WARNING: don't run with debug turned on in production!
# Defaults to False (not True) so a DEBUG env var that's missing entirely -
# a misconfigured deploy, not just "someone forgot .env locally" - fails
# safe (verbose 500 pages off) instead of failing open. Both .env and
# .env.example already set DEBUG explicitly, so local development is
# unaffected either way; this only changes behavior for an environment that
# never set it at all. config/settings/dev.py and config/settings/prod.py
# both override this explicitly anyway, so this default only matters if
# something imports config.settings.base directly (unsupported) or the
# simba_web.settings compatibility shim is used with no DEBUG env var set.
DEBUG = os.getenv('DEBUG', 'False') == 'True'

if not DEBUG and SECRET_KEY == INSECURE_DEFAULT_SECRET_KEY:
    raise RuntimeError(
        "DJANGO_SECRET_KEY is not set. Refusing to run with the publicly "
        "known default secret key while DEBUG=False."
    )

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,simba-intel.onrender.com').split(',')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'chat',
]

SITE_ID = int(os.getenv('SITE_ID', '1'))

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Needs request.user (set by AuthenticationMiddleware above) to let
    # superusers through during an active kill switch.
    'chat.middleware.MaintenanceModeMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'simba_web.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # toward templates folder
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'chat.context_processors.feature_flags',
                'chat.context_processors.rbac',
            ],
        },
    },
]

WSGI_APPLICATION = 'simba_web.wsgi.application'


# Database - PostgreSQL only. SQLite was the original default (still
# reachable in git history) but is dropped entirely here: it doesn't support
# concurrent writers across processes, which the admin console's audit log +
# usage tracking + regular chat traffic all hit simultaneously under any
# real multi-worker deployment, and a deployed filesystem is typically
# ephemeral anyway (SQLite's on-disk file would just vanish on every
# redeploy).
#
# DATABASE_URL is the primary path - this is what every hosted Postgres
# (Supabase, Render, Neon, Heroku, ElephantSQL) hands you directly, one env
# var, no assembly required. conn_max_age=600 and conn_health_checks=True
# are Django's own connection-reuse mechanism (a real, if modest, form of
# "pooling" - a WSGI worker keeps its connection open across requests for up
# to 10 minutes instead of reconnecting every time, with a health check
# before reuse so a dropped connection doesn't surface as a request-time
# error). For a heavier pooling need under real concurrent load, put
# PgBouncer/Supavisor in front (Supabase's connection pooler offers this
# already - enabling it just changes the connection string DATABASE_URL
# points at, no code change needed here).
#
# ssl_require=True whenever DATABASE_URL is used: nobody sets this env var
# to point at a plaintext local socket - it's always a remote managed
# instance, which is exactly the case that needs SSL enforced.
#
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases
import dj_database_url

DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=True,
        )
    }
else:
    # No DATABASE_URL: local development. Still genuinely PostgreSQL, never
    # SQLite - point these at a local `createdb simba_intel` (see README /
    # .env.example). Defaults match Postgres's own out-of-the-box local
    # conventions (superuser "postgres", localhost:5432) purely for
    # first-run convenience; they are not production credentials and are
    # never used once DATABASE_URL is set.
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB', 'simba_intel'),
            'USER': os.getenv('POSTGRES_USER', 'postgres'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'postgres'),
            'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': 600,
            'CONN_HEALTH_CHECKS': True,
        }
    }


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]

STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Security Settings
if not DEBUG:
    # HTTPS Settings
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_CONTENT_TYPE_NOSNIFF = True

    # HSTS - starts at 1 hour rather than the usual 1-year recommendation,
    # specifically because it's new here: a wrong HTTPS assumption under a
    # year-long HSTS policy is very hard to walk back for anyone who visited
    # while it was broken. Raise SECURE_HSTS_SECONDS once this has run
    # cleanly in production for a while.
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False

    # CSRF Trusted Origins
    CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', 'http://localhost:8000,https://simba-intel.onrender.com').split(',')

# Email Configuration
# SMTP is not usable from every host (e.g. Render's outbound network cannot
# reach smtp.gmail.com - OSError: [Errno 101] Network is unreachable, a
# routing/firewall restriction, not a timeout or credentials problem), so no
# amount of SMTP tuning could fix it there. Email now goes out through
# Resend's HTTPS API instead (see chat/services/resend_backend.py), which
# travels over the same outbound path this app already uses for Groq/
# Mistral/Tavily. EMAIL_BACKEND stays env-overridable (e.g. to the console
# backend for local debugging without a real API key), but defaults straight
# to the Resend backend since that's the only backend this app actually
# ships against now.
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'chat.services.resend_backend.ResendEmailBackend')
# The only credential this needs. Read securely from the environment, never
# hardcoded; chat/services/resend_backend.py fails gracefully (logs a
# warning, sends nothing, never raises) if this is blank rather than
# crashing whatever request triggered the send.
RESEND_API_KEY = os.getenv('RESEND_API_KEY', '')
# onboarding@resend.dev is Resend's own sandbox sender - it works without a
# verified sending domain, purely so a fresh checkout has a working default
# rather than a silently-broken one. Replace with a real address on a
# domain verified in the Resend dashboard once ready.
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'onboarding@resend.dev')
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Allauth Config
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Account Settings
# "mandatory" blocks LOGIN ITSELF for unverified users (allauth redirects them
# to a holding page instead of ever completing authentication) - that's a
# stricter product than this app implements. The in-app gate (chat/services/
# verification.py) is built for "optional": users can log in and chat, but
# image generation/Vision/Settings stay locked until they verify. For
# production, set this to "optional" (not "mandatory") once EMAIL_BACKEND
# above is pointed at real SMTP - otherwise verification emails are only
# printed to the console and no one can ever complete the flow.
ACCOUNT_EMAIL_VERIFICATION = os.getenv('ACCOUNT_EMAIL_VERIFICATION', 'none')
# Confirms on the GET request the emailed link itself points at, rather than
# requiring an extra "click here to confirm" button-press on the landing
# page first - a genuinely valid link should just work in one click, not two.
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
# Where a signed-in user lands right after that GET confirms them - a
# dedicated success page rather than dropping them straight back on chat
# home with no acknowledgement that anything just happened.
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = '/accounts/email-verified/'
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
LOGIN_REDIRECT_URL = "/"

# RBAC (chat/permissions.py): which account chat/migrations/0022_add_role_
# field_and_promote_owner.py promotes to Role.OWNER. Read only by that
# migration and the promote_owner management command - never by a view, so
# there's nothing here for a view to accidentally hardcode. Leave unset to
# fall back to promoting whichever existing Django superuser has the
# earliest date_joined (the common case: the one account created via
# createsuperuser before this migration ever ran).
OWNER_EMAIL = os.getenv('OWNER_EMAIL', '')
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
ACCOUNT_ADAPTER = 'chat.adapters.SimbaAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'chat.adapters.SimbaSocialAccountAdapter'
ACCOUNT_FORMS = {
    'login': 'chat.forms.SimbaLoginForm',
    'signup': 'chat.forms.SimbaSignupForm',
    'reset_password': 'chat.forms.SimbaResetPasswordForm',
    'change_password': 'chat.forms.SimbaChangePasswordForm',
    'add_email': 'chat.forms.SimbaAddEmailForm',
}

# Social Account Settings for Google Login

# Auto Signup and Smooth Flow
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_AUTO_SIGNUP = True
# EMAIL_AUTHENTICATION_AUTO_CONNECT alone does nothing without
# EMAIL_AUTHENTICATION also being true somewhere - it only controls whether a
# successful email-authenticated login also *connects* the social account,
# not whether email-authentication is attempted at all. Without the
# per-provider EMAIL_AUTHENTICATION below, a Google login matching an
# existing local account's email was being bounced to the signup form
# instead of logging into (and connecting to) that existing account - and
# that signup would then fail outright on the unique-email constraint,
# leaving the user unable to sign in with Google at all. Scoped to the
# "google" provider specifically (not the global SOCIALACCOUNT_EMAIL_
# AUTHENTICATION) because this trust decision is provider-specific: Google
# verifies email ownership via OAuth, so a verified Google email is safe to
# treat as proof of that account - an untrusted/self-hosted provider would
# not get the same benefit of the doubt.
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# Explicit (not left to allauth's defaults) so the requested scope and PKCE
# are guaranteed regardless of allauth version upgrades. The actual Client
# ID/Secret still live in a SocialApp row (Django admin) tied to SITE_ID
# above, not here - this block only controls *how* the OAuth handshake runs.
# Behind a TLS-terminating reverse proxy (Render, or a future Nginx in front
# on Oracle Cloud): SECURE_PROXY_SSL_HEADER (set above, only when DEBUG=
# False) is what makes Django build the callback URL as https:// instead of
# http:// - without it, Google's "redirect_uri mismatch" error is the usual
# symptom, not a Google-side misconfiguration.
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "OAUTH_PKCE_ENABLED": True,
        "EMAIL_AUTHENTICATION": True,
    }
}

# Login rate-limiting / temporary lockout. allauth applies these itself
# (view-level, via Django's cache framework - no custom lockout code needed
# here) - restated explicitly rather than left as an invisible default so
# it's visible and tunable: 5 failed login attempts per identifier (email)
# within 5 minutes triggers a temporary throttle, on top of a flat 10/minute
# cap per source IP regardless of which account is being targeted.
ACCOUNT_RATE_LIMITS = {
    "login_failed": "10/m/ip,5/300s/key",
}

# Logging - chat/utils/logger.py's own AI-request logging is separate and
# untouched by this.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        # Feeds the admin console's Live Monitor "Live Log Stream" panel -
        # see chat/log_buffer.py's docstring for what this is and isn't
        # (in-memory, per-process, not a durable audit trail).
        'ring_buffer': {
            'class': 'chat.log_buffer.RingBufferHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'ring_buffer'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'ring_buffer'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'ring_buffer'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

# Error tracking (optional) - only activates if both SENTRY_DSN is set and
# sentry-sdk is installed, so it's a no-op for anyone who hasn't opted in
# rather than a hard new dependency.
SENTRY_DSN = os.getenv('SENTRY_DSN')
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.0')),
            send_default_pii=False,
        )
    except ImportError:
        pass
