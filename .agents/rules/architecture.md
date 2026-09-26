# Simba Intel Architecture Rules

This project is **Simba Intel**, an AI virtual assistant and desktop automation platform built with Django 6 and Python 3.12.

## Architectural Layers

```
Simba Intel Architecture:
┌────────────────────────────────────────────────────────┐
│ Presentation: Django Templates (Cyberpunk Themes)      │
│ Vanilla JS, CSS Custom Properties, Chart.js CDN        │
├────────────────────────────────────────────────────────┤
│ Routing & Views Layer:                                 │
│   - simba_web/urls.py (Root routes & health check)     │
│   - chat/views.py (Chat, Sessions, History, Media)     │
│   - chat/admin_views.py (Super Admin Operations)       │
├────────────────────────────────────────────────────────┤
│ Service Layer (chat/services/):                        │
│   - ai_router.py / model_registry.py / provider_mgr    │
│   - message_tree.py (Branching conversational graph)   │
│   - usage.py / cost_table.py (Rate-limits & tracking)  │
│   - conversation_memory.py (Fact & context extraction) │
│   - resend_backend.py (HTTPS transactional email)      │
│   - web_search/ (Tavily/SearXNG live search pipeline)  │
├────────────────────────────────────────────────────────┤
│ Local Desktop Automation Subsystem (chat/agent/):      │
│   - Controller, Planner, Executor, Fast Command Router │
│   - Real Windows tools: window, mouse, keys, files     │
│   - Client runners: simba_agent.py, simba_daemon.py    │
├────────────────────────────────────────────────────────┤
│ Data Layer (PostgreSQL via dj-database-url):           │
│   - chat/models.py (Tree schema, Profiles, Audit Logs) │
└────────────────────────────────────────────────────────┘
```

## Architectural Guidelines

1. **Keep Business Logic in `chat/services/`**:
   - Views (`chat/views.py` and `chat/admin_views.py`) must remain focused on HTTP request handling, permission checking, and response formatting.
   - Do NOT embed complex AI provider handling, message graph operations, or memory extraction directly into view functions.
   - Reuse existing services:
     - `chat.services.ai_router` for all AI streaming and completion.
     - `chat.services.message_tree` for message reading, branch switching, and turn appending.
     - `chat.services.usage` for token counting, rate-limiting, and `UsageEvent` recording.
     - `chat.services.model_registry` for model lookup, fallback chains, and capability inspection.

2. **The Branching Message Tree**:
   - Conversational history is modeled as a tree via `Message` (`parent` self-FK).
   - `ChatSession.active_leaf` points to the tip of the currently visible conversation branch.
   - **CRITICAL**: `ChatMessage` is a frozen legacy model preserved strictly for historical rollback. **Never** create or modify `ChatMessage` records. All writes must go to `Message` via `chat.services.message_tree.append_turn()`.

3. **Desktop Agent Isolation**:
   - Code inside `chat/agent/` and tools in `chat/agent/tools/` must remain decoupled from the web presentation layer.
   - Tools interact via standard `ExecutionResult` and `RiskLevel` abstractions defined in `chat/agent/tools/registry.py`.
   - Desktop automation must always adhere to the safety boundaries enforced in `RiskLevel` and require user confirmation for destructive actions.

4. **Independent RBAC System**:
   - Access control is governed by `chat.permissions.Role` and `has_role_at_least(user, required_role)`.
   - The 6-tier hierarchy (`OWNER` > `SUPER_ADMIN` > `ADMIN` > `MODERATOR` > `VERIFIED` > `USER`) operates independently of Django's default `is_staff` / `is_superuser` booleans.
   - Never replace `has_role_at_least()` with raw checks on `request.user.is_staff`.

5. **No Frontend Build Pipeline**:
   - The application does not use Webpack, Vite, or npm build steps.
   - All styling relies on semantic CSS tokens and theme variables (`[data-theme]`) defined in templates.
   - Scripts are plain Vanilla JavaScript. Do not introduce dependencies that require compilation or bundling unless explicitly requested.
