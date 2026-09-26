# Database & Migrations Rules

This rule defines standards for PostgreSQL database interactions and migration management in Simba Intel.

## Database Configuration

1. **PostgreSQL as Primary Engine**:
   - Simba Intel uses PostgreSQL exclusively. Database configuration is parsed from `DATABASE_URL` via `dj-database-url`, or constructed from `POSTGRES_*` environment variables.
   - `CONN_MAX_AGE` is set to `0` by default to prevent connection holding across requests, avoiding `EMAXCONNSESSIONS` in pooled environments (such as Supabase, PgBouncer, or Render Postgres).
   - `db.sqlite3` and backup snapshots in the repository root are legacy archives. Do NOT configure or reintroduce SQLite fallbacks in `simba_web/settings.py`.

2. **The Conversational Message Tree**:
   - The primary conversational store is the `Message` model in `chat/models.py`.
   - **Never create or write to `ChatMessage`**: It is a legacy, read-only audit copy preserved from Phase 3.
   - All message writes must go through `chat.services.message_tree`:
     ```python
     from chat.services.message_tree import append_turn, regenerate_assistant_reply

     # Standard turn creation:
     user_msg, assistant_msg = append_turn(
         session=session,
         user_text="User question",
         assistant_text="AI reply",
         extra_data={"latency": 0.45, "model": "cyber-max"}
     )
     ```
   - Sibling branches and regeneration update `session.active_leaf` without mutating past nodes in-place.

## Migration Guidelines

1. **Non-Destructive Schema Evolution**:
   - Never drop tables or delete existing model columns without explicit confirmation from the user.
   - When adding fields to models with existing production data:
     - Provide an explicit default value, OR
     - Set `null=True, blank=True`.
   - Use meaningful migration names (e.g., `0048_add_custom_field_to_userprofile.py`).

2. **Migration Consistency & Verification**:
   - Check existing migrations in `chat/migrations/` before generating new ones.
   - Always verify new migrations with:
     ```bash
     python manage.py makemigrations --dry-run
     python manage.py check
     ```
   - Never edit past migrations that have already been merged or deployed.

3. **Data Backfills**:
   - If a schema change requires migrating existing data, write a separate data migration (using `RunPython`) with both `forwards` and `backwards` functions.
   - When running Django `dumpdata` or `loaddata` on Windows, prepend `PYTHONUTF8=1` to prevent charmap/CP1252 encoding corruption on unicode or emoji text.
