# Django & Python Standards for Simba Intel

This rule outlines development standards for Python 3.12 and Django 6.0 in the Simba Intel codebase.

## Python Standards

1. **Python 3.12 Idioms**:
   - Use standard library type hints (`list[str]`, `dict[str, Any]`, `Optional[T]` or `T | None`).
   - Use `pathlib.Path` for path operations instead of `os.path`.
   - Prefer standard library modules (`secrets`, `uuid`, `re`, `datetime`, `dataclasses`) over third-party alternatives.
2. **Clean Imports**:
   - Order imports logically:
     1. Standard library (`os`, `sys`, `time`, `logging`, `typing`)
     2. Django core (`django.shortcuts`, `django.http`, `django.db`)
     3. Third-party packages (`groq`, `mistralai`, `pydantic`)
     4. Simba internal modules (`chat.models`, `chat.services`, `chat.utils`)
3. **Logging & Error Recording**:
   - Use named logger: `logger = logging.getLogger("simba_intel")`.
   - Use `ErrorLog.record(category, message, detail)` from `chat.models` for application and provider error tracking.
   - Do NOT log raw API keys, passwords, recovery codes, or sensitive user tokens.

## Django 6 Conventions

1. **Sync vs Async Views**:
   - Views in Simba Intel are predominantly **synchronous**.
   - Streaming AI completions use Python generators wrapped in Django's `StreamingHttpResponse`.
   - Do NOT convert views to `async def` without explicit architectural need, as it can cause database connection leaks or thread-safety issues with psycopg3.
2. **Database Querying & ORM Efficiency**:
   - Prevent N+1 queries by using `select_related()` for single-valued relationships (e.g., `user`, `session`, `parent`) and `prefetch_related()` for multi-valued relationships (e.g., `attachments`, `children`).
   - Use `.only()` or `.values()` / `.values_list()` when fetching large datasets (e.g., in analytics or exports) to avoid loading heavy `TextField` content unnecessarily.
   - For existence checks, prefer `.exists()` over `len(queryset)` or `bool(queryset.first())`.
   - Use `models.F()` expressions for atomic counter updates (e.g., `ErrorLog.objects.filter(...).update(count=models.F('count') + 1)`).
3. **Model & Helper Usage**:
   - Use established model helper methods:
     - `UserProfile.get_or_create_for(request.user)` to access or initialize a user profile with appropriate cached defaults.
     - `FeatureFlag.is_enabled(key, default=True)` for cached feature-flag checks.
     - `chat.services.message_tree.walk_active_chain(session)` to fetch active session history.
4. **Form & Input Validation**:
   - Validate client input server-side. Do not trust client-supplied session IDs, message IDs, or user IDs without checking ownership (`user=request.user`).
   - Return clean `JsonResponse({"status": "error", "error": "..."})` with proper HTTP status codes (400, 403, 404, 429, 503).
