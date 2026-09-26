---
name: debugging
description: >-
  Systematic debugging workflows for Simba Intel. Use when diagnosing runtime errors,
  exceptions, AI provider failures, streaming dropouts, rate-limiting loops, database connection
  exhaustion, message tree corruption, or desktop agent communication issues.
---

# Simba Intel Debugging Runbook

Follow this systematic workflow when diagnosing and resolving issues in Simba Intel.

## 1. Inspecting Application Errors

1. **Check `ErrorLog` Database Records**:
   - Provider errors and uncaught exceptions are recorded in `chat.models.ErrorLog`.
   - Inspect unresolved errors via Django shell:
     ```python
     python manage.py shell -c "from chat.models import ErrorLog; [print(e.category, e.message[:100], e.count) for e in ErrorLog.objects.filter(resolved=False)[:10]]"
     ```
2. **Review Ring Buffer Logs**:
   - `chat.log_buffer.RingBufferHandler` stores recent in-memory log entries.
   - Accessible via Admin Console Live Monitor (`/admin-console/live/logs/`).

## 2. Diagnosing AI Provider Failures

1. **Check Rate Limits & 429 Cooldowns**:
   - Upstream rate limits place providers in temporary cache cooldowns (`provider_cooldown:<provider>`).
   - Inspect cooldown status via Django shell:
     ```python
     python manage.py shell -c "from chat.services.ai_router import is_provider_cooling_down; print('Groq cooldown:', is_provider_cooling_down('groq'), 'Mistral cooldown:', is_provider_cooling_down('mistral'))"
     ```
2. **Verify API Credentials**:
   - Confirm environment variables are populated:
     `GROQ_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, `TAVILY_API_KEY`.
3. **Trace Fallback Chain Execution**:
   - Check `get_fallback_chain(model_id)` in `chat/services/model_registry.py`.
   - Verify if fallback provider threw a secondary error.

## 3. Diagnosing Message Tree & Branching Issues

1. **Verify `active_leaf` Consistency**:
   - A session's active branch is determined by `ChatSession.active_leaf`.
   - Check if a session has orphaned or disconnected messages:
     ```python
     python manage.py shell -c "from chat.models import ChatSession; s = ChatSession.objects.get(id=<SESSION_ID>); print('Active leaf:', s.active_leaf_id, 'Total messages:', s.thread.count())"
     ```
2. **Verify Sibling Counts**:
   - Inspect `chat.services.message_tree.build_display_messages(session)` to confirm sibling indices (`current_index` / `sibling_count`) match database rows.

## 4. Diagnosing Database Connection Issues

1. **PostgreSQL Pool Exhaustion**:
   - If seeing `OperationalError: connection limit exceeded` or `EMAXCONNSESSIONS`:
     - Ensure `CONN_MAX_AGE=0` in `.env` or settings.
     - Verify `DatabaseResilienceMiddleware` is returning 503 instead of crashing.
2. **Probe Health Check**:
   - Run: `curl http://localhost:8000/health/`
   - Should return `{"status": "ok", "db": "connected"}`.

## 5. Verification After Fixes

1. Run Django system check:
   `python manage.py check`
2. Run targeted regression test:
   `python manage.py test chat.tests`
