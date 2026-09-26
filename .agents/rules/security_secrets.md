# Security & Secrets Management Rules

This rule defines mandatory security requirements and secrets handling policies for Simba Intel.

## Secrets & Credentials Protection

1. **Zero Exposure Policy**:
   - Never print, log, or commit `.env` files, API keys, database credentials, or secret tokens.
   - API keys include:
     - `DJANGO_SECRET_KEY`
     - `GROQ_API_KEY`
     - `MISTRAL_API_KEY`
     - `TAVILY_API_KEY`
     - `RESEND_API_KEY`
     - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
     - `OPENROUTER_API_KEY`
     - `DATABASE_URL` / `POSTGRES_PASSWORD`
   - All credentials must be read via `os.getenv()`. Never supply fallback API keys in source code.
   - Refuse running in production (`DEBUG=False`) with the default placeholder secret key.

2. **Password Recovery & Code Hashes**:
   - `RecoveryCode` objects store ONLY the bcrypt/argon2 `code_hash` produced by `make_password()`.
   - Raw recovery codes exist only in memory during generation and must never be written to logs or durable database tables.

3. **Desktop Agent Token Security**:
   - The desktop automation client connects using an agent token (`simba_at_<hex>`) stored in `UserProfile.agent_token`.
   - Validate agent tokens on all `/api/agent/*` endpoints.
   - Token regeneration immediately invalidates existing desktop sessions.

## Authorization & Access Control (RBAC)

1. **Simba RBAC Enforcement**:
   - Simba Intel enforces a strict 6-tier hierarchy:
     `OWNER` > `SUPER_ADMIN` > `ADMIN` > `MODERATOR` > `VERIFIED` > `USER`
   - Use `chat.permissions.has_role_at_least(user, role)` or `@require_role(role)` decorator.
   - Never rely on Django's `user.is_staff` or `user.is_superuser` for application-level RBAC; those fields exist solely for `django.contrib.admin`.

2. **Session & Ownership Validation**:
   - Always ensure queries against user-owned models filter by the authenticated user:
     ```python
     # Correct:
     session = get_object_or_404(ChatSession, id=session_id, user=request.user)
     # Incorrect (IDOR vulnerability):
     session = get_object_or_404(ChatSession, id=session_id)
     ```

## Input Validation & Injection Defenses

1. **SQL & Query Construction**:
   - Always use Django's ORM or parameterized cursor execution: `cursor.execute("SELECT ... WHERE id = %s", [item_id])`.
   - Never use f-strings or string concatenation to build SQL statements.

2. **File Uploads & Attachments**:
   - Validate file extensions, MIME types, and file sizes before saving attachments.
   - Store attachments through Django's `FileField` (`MessageAttachment.file`) with date-based subdirectories (`attachments/%Y/%m/%d/`).

3. **Desktop Agent Tool Safety**:
   - Filesystem tools in `chat/agent/tools/filesystem_tools.py` must sanitize paths using `_sanitize_path()` to block directory traversal outside allowed boundaries.
   - High-risk actions (`RiskLevel.HIGH`, `RiskLevel.CRITICAL`) require explicit user confirmation before execution.
