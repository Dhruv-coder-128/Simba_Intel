---
name: database-migrations
description: >-
  Procedures for safely modifying models, authoring database migrations, backfilling data,
  and maintaining PostgreSQL schema integrity in Simba Intel. Use when adding model fields,
  creating indexes, or evolving database schemas.
---

# Database Migrations Runbook

Follow these procedures to maintain schema consistency and avoid data loss in PostgreSQL.

## 1. Schema Change Design Rules

1. **Non-Destructive Additions**:
   - Never delete existing columns or drop tables unless explicitly instructed.
   - When adding fields to existing models (`UserProfile`, `ChatSession`, `Message`):
     - Supply an explicit `default` value, OR
     - Set `null=True, blank=True`.
2. **ForeignKey Best Practices**:
   - Always define explicit `on_delete` policies (`CASCADE`, `SET_NULL`, `PROTECT`).
   - Define meaningful `related_name` values to prevent reverse accessor collisions.
3. **Database Indexing**:
   - Add composite indexes for fields queried together (e.g. `[models.Index(fields=['user', '-created_at'])]`).

## 2. Generating & Inspecting Migrations

1. **Preview Migration Operations**:
   ```bash
   python manage.py makemigrations --dry-run
   ```
2. **Generate Migration**:
   ```bash
   python manage.py makemigrations chat --name add_feature_field
   ```
3. **Inspect Generated File**:
   - Review the generated file in `chat/migrations/`.
   - Ensure dependencies point to the latest migration (e.g. `0047_...`).
   - Verify there are no unintended `AlterField` or `RemoveField` operations.

## 3. Authoring Data Migrations

When migrating data between fields or models, write a data migration:

```python
from django.db import migrations

def forwards_func(apps, schema_editor):
    ChatSession = apps.get_model('chat', 'ChatSession')
    # Use apps.get_model, NOT direct import from chat.models
    for session in ChatSession.objects.filter(active_leaf__isnull=False):
        # Perform backfill
        pass

def backwards_func(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('chat', '0047_activityevent_conversationhighlight_savedprompt_tags_and_more'),
    ]
    operations = [
        migrations.RunPython(forwards_func, backwards_func),
    ]
```

## 4. Applying & Verifying Migrations

1. Apply migrations:
   ```bash
   python manage.py migrate
   ```
2. Run Django checks:
   ```bash
   python manage.py check
   ```
3. Run test suite:
   ```bash
   python manage.py test chat.tests
   ```
