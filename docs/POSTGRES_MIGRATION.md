# SQLite → PostgreSQL migration runbook

One-time runbook for moving an existing deployment's data (local dev DB, or
a legacy Render instance still on SQLite) onto PostgreSQL. If you're setting
up a brand-new environment with no existing data, skip straight to
`python manage.py migrate` in the README — none of this applies to you.

## Why this exists

`simba_web/settings.py` no longer knows how to connect to SQLite at all —
`DATABASES` is PostgreSQL-only, sourced from `DATABASE_URL` or the
`POSTGRES_*` env vars, with no fallback. That's deliberate (SQLite doesn't
support concurrent writers across processes, and Render's filesystem is
ephemeral anyway). But it means the normal `dumpdata`/`loaddata` commands
have nothing to point at for reading the *old* `db.sqlite3` file, since they
run through the app's regular settings. `simba_web/settings_sqlite_export.py`
bridges that one gap: it inherits everything from `settings.py` except
`DATABASES`, which it points back at the original SQLite file. It has no
other purpose and is safe to delete once this migration is complete and
verified.

## 1. Snapshot row counts (before)

```bash
python manage.py db_row_counts --settings=simba_web.settings_sqlite_export
```

Save this output — it's what you diff the post-migration counts against.

## 2. Export the SQLite data

```bash
PYTHONUTF8=1 python manage.py dumpdata \
    --settings=simba_web.settings_sqlite_export \
    --natural-foreign --natural-primary \
    -e contenttypes -e auth.permission -e admin.logentry \
    -o legacy_data.json
```

Notes:

- `PYTHONUTF8=1` is required on Windows. Without it, Django opens the output
  file using the OS default codepage (cp1252/"charmap") instead of UTF-8, and
  `dumpdata` fails partway through with `'charmap' codec can't encode
  character ...` the moment it hits any real chat message containing a
  character outside that codepage (smart quotes, em/en-dashes, emoji,
  non-English text — anything). The command exits 1 and leaves a truncated,
  unusable file behind if you forget this flag. Not needed on Linux/macOS.
- `--natural-foreign --natural-primary` avoids hardcoding auto-incrementing
  PKs, so records don't collide with whatever a freshly-migrated Postgres
  database assigns on its own.
- `-e contenttypes -e auth.permission -e admin.logentry` excludes tables
  Django/the admin repopulate automatically on `migrate` — loading them from
  the old export would fight with the new DB's own IDs for those rows.

## 3. Point the app at PostgreSQL and run migrations

Set `DATABASE_URL` (or the `POSTGRES_*` vars) to the **new**, empty
PostgreSQL database, then:

```bash
python manage.py migrate
```

This creates every table from scratch on Postgres using the existing,
unmodified migration history (`chat/migrations/0001_initial` through
`0016_...`) — nothing about the migrations themselves changed for this move.

## 4. Load the data

```bash
PYTHONUTF8=1 python manage.py loaddata legacy_data.json
```

## 5. Verify (after)

```bash
python manage.py db_row_counts
```

Compare against the step-1 snapshot. The three excluded models aside, every
count should match exactly — this is what was verified during this
migration (739 total SQLite rows → 614 exported objects, exactly accounting
for the 125 rows in the three excluded models: 24 contenttypes + 96
auth.permission + 5 admin.logentry).

## 6. Spot-check the app itself

Row counts catch missing data, not broken relationships. After loading,
actually exercise: login (including Google OAuth), password reset OTP flow,
opening an existing chat session and confirming message history/branches
render correctly, the admin console user list and audit log, and the
analytics dashboard's provider/cost breakdown.

## 7. Clean up

Once verified, both `legacy_data.json` and `simba_web/settings_sqlite_export.py`
have no further purpose. `db.sqlite3` itself is safe to remove from the
working directory (it is already gitignored) — nothing in the app can read
it anymore.
