# Ensures the Celery app (simba_web/celery.py) is always loaded when Django
# starts, so `@shared_task`-decorated functions anywhere in the codebase
# (see chat/tasks.py) are registered against it automatically. This is
# Celery's own documented required pattern for Django integration - not
# optional boilerplate.
from .celery import app as celery_app

__all__ = ("celery_app",)
