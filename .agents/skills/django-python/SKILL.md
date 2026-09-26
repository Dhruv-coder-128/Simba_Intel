---
name: django-python
description: >-
  Specialized procedures for Python 3.12 and Django 6.0 development in Simba Intel.
  Use when creating or updating Django views, optimizing ORM queries, authoring management
  commands, registering context processors, or writing middleware.
---

# Django & Python 3.12 Development Runbook

Follow these patterns when implementing Django and Python features in Simba Intel.

## 1. View & Endpoint Patterns

1. **Synchronous View with JSON Response**:
   ```python
   from django.http import JsonResponse
   from django.contrib.auth.decorators import login_required
   from django.views.decorators.http import require_POST
   from django.shortcuts import get_object_or_404
   from chat.models import ChatSession

   @login_required
   @require_POST
   def example_api_view(request):
       session_id = request.POST.get("session_id")
       session = get_object_or_404(ChatSession, id=session_id, user=request.user)
       # Perform operation
       return JsonResponse({"status": "ok", "title": session.title})
   ```

2. **Streaming View with Generator**:
   ```python
   from django.http import StreamingHttpResponse
   from django.contrib.auth.decorators import login_required

   @login_required
   def stream_view(request):
       def event_generator():
           for chunk in ["data: chunk1\n\n", "data: chunk2\n\n"]:
               yield chunk
       return StreamingHttpResponse(event_generator(), content_type="text/event-stream")
   ```

## 2. ORM Query Optimization

1. **Eliminating N+1 Queries**:
   ```python
   # For ForeignKeys and OneToOne:
   sessions = ChatSession.objects.filter(user=request.user).select_related('active_leaf', 'user')

   # For ManyToMany or reverse ForeignKeys:
   messages = Message.objects.filter(session=session).prefetch_related('attachments', 'children')
   ```

2. **Atomic Counter Increments**:
   ```python
   from django.db.models import F
   from chat.models import SavedPrompt
   SavedPrompt.objects.filter(id=prompt_id).update(use_count=F('use_count') + 1)
   ```

## 3. Management Commands

1. **Structure in `chat/management/commands/`**:
   ```python
   from django.core.management.base import BaseCommand

   class Command(BaseCommand):
       help = "Descriptive help string"

       def add_arguments(self, parser):
           parser.add_argument("--dry-run", action="store_true", help="Simulate execution")

       def handle(self, *args, **options):
           self.stdout.write(self.style.SUCCESS("Executed successfully"))
   ```

## 4. Verification Checklist

- [ ] Run `python manage.py check` to verify imports and model definitions.
- [ ] Verify query count with `assertNumQueries` in test cases where performance is critical.
