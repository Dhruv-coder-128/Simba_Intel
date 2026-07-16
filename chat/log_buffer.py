"""In-memory ring buffer of recent log records, feeding the admin
console's Live Monitor "Live Log Stream" panel.

Deliberately NOT a database table: this is meant to be cheap, zero-schema,
and instantaneous to both write to (every log call in the whole process)
and read from (polled every few seconds). The tradeoff, stated plainly: it
resets on every worker restart/deploy and is per-process (Render/gunicorn
workers don't share memory), so on a multi-worker deployment this shows
"recent logs from whichever worker happened to serve this admin request",
not a merged global stream. That's an accepted limitation for a live
debugging aid, not a permanent audit trail - AdminAuditLog and ErrorLog
(chat/models.py) are the durable records for anything that needs to survive
a restart or be queried after the fact.

Registered as a handler in two places (both share this same module-level
deque, since Python caches imported modules): simba_web/settings.py's
LOGGING dict (for Django's own root/request logging) and chat/utils/logger.
py's SimbaLogger (for the AI-request logs, which manage their own handler
and don't propagate to the root logger)."""
import logging
from collections import deque

_BUFFER_MAXLEN = 500
_buffer = deque(maxlen=_BUFFER_MAXLEN)


class RingBufferHandler(logging.Handler):
    def emit(self, record):
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        _buffer.append({
            'time': record.created,
            'level': record.levelname,
            'logger': record.name,
            'message': message,
        })


def get_recent_logs(limit: int = 100, since: float = None) -> list:
    """Most-recent-first. `since` (a record's `time` float) lets the poller
    ask for only what it hasn't already seen, instead of re-fetching the
    whole buffer every 5 seconds."""
    entries = list(_buffer)
    if since is not None:
        entries = [e for e in entries if e['time'] > since]
    return list(reversed(entries[-limit:]))
