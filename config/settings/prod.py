"""Production settings.

Opt in explicitly with:
    DJANGO_SETTINGS_MODULE=config.settings.prod

(manage.py / simba_web/wsgi.py / simba_web/asgi.py still default to
simba_web.settings - a backward-compatible shim that reproduces today's
"if not DEBUG" conditional exactly as it already behaved - so switching the
live/currently-deployed service over to this module is a deliberate,
separate step, not a side effect of this cleanup pass. Recommended for the
future Oracle Cloud + Nginx + Gunicorn target, and for Render once verified.)

Always hardened, regardless of what a stray/misconfigured DEBUG env var
says - unlike config/settings/base.py's own `if not DEBUG:` block (which
depends on reading the DEBUG env var correctly), everything below is
unconditional the moment this module is used. This closes a real latent gap
in the pre-split settings.py: previously, an environment that accidentally
left DEBUG=True set would silently run production traffic with every
security header off, with no independent safety net.
"""
from config.settings.base import *  # noqa: F401,F403

DEBUG = False

if SECRET_KEY == INSECURE_DEFAULT_SECRET_KEY:
    raise RuntimeError(
        "DJANGO_SECRET_KEY is not set. Refusing to run config.settings.prod "
        "with the publicly known default secret key."
    )

# HTTPS Settings - always on here, never conditional.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

# HSTS - starts at 1 hour rather than the usual 1-year recommendation, since
# a wrong HTTPS assumption under a year-long HSTS policy is very hard to
# walk back for anyone who visited while it was broken. Raise
# SECURE_HSTS_SECONDS once this has run cleanly in production for a while.
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '3600'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

CSRF_TRUSTED_ORIGINS = os.getenv(
    'CSRF_TRUSTED_ORIGINS', 'http://localhost:8000,https://simba-intel.onrender.com'
).split(',')
