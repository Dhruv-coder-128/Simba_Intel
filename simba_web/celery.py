"""Celery application for Simba_INTEL.

Lives next to settings.py (simba_web/celery.py) - Celery's own documented
Django integration layout, unchanged:
https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html

Loaded once, at process startup, by simba_web/__init__.py's
`from .celery import app as celery_app` - that's what makes both
`@shared_task` (used in chat/tasks.py, or any future app's tasks.py,
without importing this module directly) and autodiscovery of every
installed app's tasks module work.

This app object is constructed the moment ANY Django process starts -
`manage.py runserver/check/test/migrate`, gunicorn's WSGI boot, and the
Celery worker's own boot (`celery -A simba_web worker`) all import
simba_web/__init__.py first. Constructing a Celery app and reading its
config from Django settings does NOT connect to the broker - only actually
sending or executing a task does. So this import is safe even when Redis/
the broker is completely unreachable (e.g. running `manage.py check`
without Docker up at all) - see chat/tasks.py's docstring for what happens
if a task is dispatched in that situation instead.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "simba_web.settings")

app = Celery("simba_web")

# namespace="CELERY" means every Celery-related setting in config/settings/
# base.py must be prefixed CELERY_ (CELERY_BROKER_URL, CELERY_TASK_
# SERIALIZER, etc.) - the standard Celery/Django convention, kept so it's
# unambiguous which settings are Django's and which are Celery's, with no
# risk of a name colliding with an unrelated Django setting.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Finds every INSTALLED_APPS entry's tasks.py automatically (chat/tasks.py
# today) - a future new app's tasks.py needs zero registration anywhere to
# be picked up, it's discovered the exact same way.
app.autodiscover_tasks()
