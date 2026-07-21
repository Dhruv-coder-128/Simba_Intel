"""One-time-use settings module for exporting legacy data out of the old
db.sqlite3 file during the PostgreSQL cutover.

simba_web/settings.py (the module the app actually runs on) no longer knows
how to connect to SQLite at all - by design, so nothing can ever silently
fall back to it again. That means `dumpdata` has nothing to point at for
reading the *old* file unless something bridges the gap. This is that
bridge, and only that: it inherits everything else from settings.py
(INSTALLED_APPS, AUTH_*, etc. all stay identical) and overrides only
DATABASES, back to the original SQLite file.

Usage (see the migration runbook / final report for the full sequence):
    python manage.py dumpdata --settings=simba_web.settings_sqlite_export \
        --natural-foreign --natural-primary \
        -e contenttypes -e auth.permission \
        -o legacy_data.json

Not imported anywhere, not referenced by manage.py's default
DJANGO_SETTINGS_MODULE, and safe to delete once the migration is complete
and verified - it has no purpose after that one export.
"""
from pathlib import Path

from .settings import *  # noqa: F401,F403 - inherit everything except DATABASES below

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
