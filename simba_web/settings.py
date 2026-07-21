"""Backward-compatibility shim.

Every setting used to live directly in this file. It has been split into
the industry-standard config/settings/{base,dev,prod}.py structure (see
config/settings/base.py's docstring for the full rationale) - this module
now just re-exports config.settings.base, so it is byte-for-byte
behaviorally identical to what it contained before the split.

manage.py, simba_web/wsgi.py, and simba_web/asgi.py all still default
DJANGO_SETTINGS_MODULE to 'simba_web.settings' (this file), so every
existing deployment (Render, local dev, Docker) keeps working completely
unchanged. To start using the new explicit dev/prod modules instead, set
the DJANGO_SETTINGS_MODULE environment variable to config.settings.dev (or
config.settings.prod) - manage.py's os.environ.setdefault(...) call already
respects that override with zero code changes needed.
"""
from config.settings.base import *  # noqa: F401,F403
