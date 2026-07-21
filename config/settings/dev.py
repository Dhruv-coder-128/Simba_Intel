"""Local development settings.

Opt in explicitly with:
    DJANGO_SETTINGS_MODULE=config.settings.dev

(manage.py / simba_web/wsgi.py / simba_web/asgi.py still default to
simba_web.settings - a backward-compatible shim - so nothing breaks if you
don't set this; this module is available for anyone who wants to start
using the new config/settings/{base,dev,prod}.py structure explicitly.)

Always non-hardened (DEBUG on, no HSTS/SSL-redirect/secure-cookies) so
local http://localhost:8000 keeps working without HTTPS - regardless of
what config/settings/base.py's own env-derived DEBUG happened to compute,
these lines are the last word since they run after `from .base import *`.

Still points at the same PostgreSQL database as everything else (see
config/settings/base.py's DATABASES block) - Supabase/local Postgres, never
SQLite. Nothing here changes what database is used.
"""
from config.settings.base import *  # noqa: F401,F403

DEBUG = True

# Never hardened locally - these mirror config/settings/prod.py's block,
# forced the other way, so this module's behavior never depends on env-var
# timing (see this file's own docstring).
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
