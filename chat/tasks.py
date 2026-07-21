"""Celery tasks for the chat app - discovered automatically by simba_web/
celery.py's app.autodiscover_tasks() (any INSTALLED_APPS entry's tasks.py
is found this way; nothing needs to import or register this module
manually anywhere).

demo_ping_task is a deliberately minimal, standalone demonstration task
added to verify the Celery integration itself (broker connectivity, worker
startup, task routing/execution, retry policy) - it is NOT wired into any
view, URL, or existing feature, and changes no application behavior. Safe
to delete once Phase 6 is verified, or keep as a copy-paste starting point
for the next real background task.
"""
import logging
import time

from celery import shared_task

logger = logging.getLogger("simba_intel")

# Cache key the task writes to on success - read back by whatever verifies
# the task actually ran (see the Phase 6 report / manual verification
# steps), since no Celery result backend is configured (see config/
# settings/base.py's CELERY_BROKER_URL comment for why). Reuses the same
# shared Redis-backed cache from Phase 5 rather than introducing a second
# piece of infrastructure just to prove a task executed.
DEMO_PING_CACHE_KEY = "celery_demo_ping_last_run"


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 3},
)
def demo_ping_task(self):
    """Minimal round-trip: run on a worker, touch the shared cache, log,
    return a short value. `autoretry_for`/`retry_backoff`/`retry_kwargs`
    are a worked example of this project's retry policy for a task that
    might transiently fail (e.g. a future task doing an external HTTP
    call) - this particular task has nothing that can actually fail, so
    the policy is illustrative, not exercised in normal operation.
    """
    from django.core.cache import cache

    cache.set(DEMO_PING_CACHE_KEY, time.time(), timeout=3600)
    logger.info(
        "Celery demo_ping_task executed successfully (task_id=%s)",
        self.request.id,
    )
    return "pong"
