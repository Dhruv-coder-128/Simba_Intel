# Simba Intel — Antigravity Agent Guidelines

Welcome to **Simba Intel**, an AI-powered virtual assistant, image generation studio, and desktop automation platform built with Django 6 and Python 3.12.

This document serves as the **primary project-level instruction file** for all Antigravity agents working in this repository.

---

## 1. Ten Non-Negotiable Directives

Every agent operating in this codebase must strictly adhere to these 10 directives:

1. **Understand before modifying**: Read and trace existing code end-to-end before proposing or making changes.
2. **Follow existing architecture**: Respect established boundaries between presentation (`templates/`), services (`chat/services/`), automation (`chat/agent/`), and data models (`chat/models.py`).
3. **Reuse existing code**: Check `chat/services/`, `chat/utils/`, and `chat/agent/tools/` before creating new utilities, helpers, or queries.
4. **Keep changes minimal**: Make the smallest safe diff that solves the user's problem. Never introduce speculative abstractions.
5. **Avoid unnecessary dependencies**: Never add packages to `requirements.txt` if the Python standard library, Django, or existing dependencies can accomplish the task.
6. **Protect existing functionality**: Do not break existing features, endpoints, or UI behaviors. Ensure backward compatibility.
7. **Run relevant verification**: Validate every change with Django system checks and targeted automated tests. Never claim something works without verification.
8. **Explain architectural decisions**: Clearly document the rationale behind non-obvious design choices in task summaries.
9. **Never expose or commit secrets**: Strictly protect API keys, database credentials, recovery code hashes, and environment variables.
10. **Never modify unrelated files**: Focus only on the requested task. Do not perform opportunistic refactoring, formatting, or cleanup in untouched areas.

---

## 2. Priority Hierarchy

When resolving conflicts or deciding how to proceed, follow this strict priority order:

1. **User's current request**
2. **Project safety and integrity**
3. **Project-specific AGENTS.md and `.agents/rules/`**
4. **Relevant project skills (`.agents/skills/`)**
5. **Ponytail principles (pragmatic minimalism)**
6. **Generic framework / general best practices**

*Never let a generic skill or general guideline override an explicit project architectural decision.*

---

## 3. Ponytail Principles — The Ladder of Laziness

Simba Intel integrates the official **Ponytail** engineering philosophy: *the best code is the code you never wrote*. Before writing any code, stop at the first rung that holds:

1. **Does this need to exist at all? (YAGNI)**: If the requirement is speculative, skip it.
2. **Is it already in this codebase? (Reuse)**: Reuse existing helpers, services, or patterns.
3. **Does the Python standard library do it?**: Use `pathlib`, `re`, `json`, `dataclasses`, `secrets`, `uuid`, etc.
4. **Does a native platform or Django feature cover it?**: Use native HTML elements, CSS variables, or Django ORM constraints.
5. **Does an already-installed dependency solve it?**: Leverage packages already in `requirements.txt`.
6. **Can it be one line?**: Prefer a clean one-line comprehension or helper.
7. **Only then: write the minimum code that works.**

**Bug Fixing Rule**: Always fix the root cause, not the symptom. Grep for all callers of a function before modifying it, and apply guards at the shared root level.

---

## 4. Project Architecture Overview

```
Simba Intel Architecture Blueprint:
┌─────────────────────────────────────────────────────────────────┐
│ Web Presentation Layer                                          │
│   templates/ (Cyberpunk aesthetic, [data-theme], CSS tokens)    │
│   Vanilla JavaScript, no npm/webpack/vite build pipeline        │
├─────────────────────────────────────────────────────────────────┤
│ Views & Routing Layer                                           │
│   simba_web/urls.py (Root routes, /health/ endpoint)            │
│   chat/views.py (Chat sessions, streaming, uploads, settings)   │
│   chat/admin_views.py (Super Admin Console, Live Monitors)      │
├─────────────────────────────────────────────────────────────────┤
│ Service Layer (chat/services/)                                  │
│   ai_router.py (Request dispatch, safety injection, cooldowns)  │
│   model_registry.py (MODEL_REGISTRY, fallback chains, config)   │
│   provider_manager.py (Provider factory & caching)              │
│   message_tree.py (Branching conversational graph & leaves)     │
│   usage.py & cost_table.py (Rate-limiting & cost estimation)    │
│   conversation_memory.py (Cross-chat facts & summaries)         │
│   resend_backend.py (HTTPS transactional email delivery)        │
│   web_search/ (Tavily/SearXNG live search pipeline)             │
├─────────────────────────────────────────────────────────────────┤
│ Local Desktop Automation Subsystem (chat/agent/)                │
│   Controller, Planner, Executor, FastCommandRouter, Daemon      │
│   Tools: Window, mouse, keyboard, filesystem, system power      │
│   Client runners: simba_agent.py, simba_daemon.py               │
├─────────────────────────────────────────────────────────────────┤
│ Security & RBAC Layer                                           │
│   chat/permissions.py (6-tier hierarchy: OWNER to USER)         │
│   chat/middleware.py (DatabaseResilience, MaintenanceMode)      │
├─────────────────────────────────────────────────────────────────┤
│ Database Layer (PostgreSQL)                                     │
│   chat/models.py (Message tree, UserProfile, Audit & Error logs)│
└─────────────────────────────────────────────────────────────────┘
```

### Critical Architectural Invariants

- **Message Tree vs. ChatMessage**:
  - `ChatMessage` is a **frozen legacy table**. NEVER write to `ChatMessage`.
  - All conversational turns must be written to `Message` via `chat.services.message_tree.append_turn()`.
  - `ChatSession.active_leaf` must always track the active tip of the conversation.
- **Database Engine**:
  - PostgreSQL only via `dj-database-url`. `CONN_MAX_AGE=0` for connection pool friendliness.
  - Do NOT reintroduce SQLite fallbacks in production.
- **AI Providers**:
  - Providers subclass `BaseProvider` (`chat/providers/base.py`).
  - Models are registered in `MODEL_REGISTRY` with fallbacks in `FALLBACK_CHAINS`.
  - All AI requests must route through `chat.services.ai_router` (never call providers directly from views).
- **Email Delivery**:
  - Render blocks outbound SMTP ports. All transactional emails route through Resend's HTTPS API (`chat.services.resend_backend.ResendEmailBackend`).

---

## 5. Development Behavior — 8-Step Workflow

When executing any task, follow this exact progression:

1. **STEP 1 — Understand the request**: Clarify intent and identify constraints.
2. **STEP 2 — Inspect relevant existing files**: Read code, imports, and caller hierarchies.
3. **STEP 3 — Identify reusable functionality**: Check `chat/services/`, `chat/utils/`, and `chat/models.py`.
4. **STEP 4 — Identify the smallest safe implementation**: Plan the shortest safe diff.
5. **STEP 5 — Implement only the required changes**: Do not touch unrelated files or code.
6. **STEP 6 — Review changes for regressions**: Check for broken imports, IDOR risks, or broken branch pointers.
7. **STEP 7 — Run appropriate tests and checks**:
   - `python manage.py check`
   - `python manage.py makemigrations --dry-run` (if models changed)
   - `python manage.py test chat.tests.<SpecificTest>`
8. **STEP 8 — Report clearly**: State what changed, why it changed, files modified, verification performed, and any remaining concerns.

---

## 6. Skill Loading Behavior

Antigravity uses progressive disclosure for skills to preserve context window capacity:

- **Do not load all skills at once**: Only activate skills directly relevant to the current task.
- **Read the full `SKILL.md`**: When a skill is relevant, view its complete instructions using `view_file`.
- **Project rules supersede skills**: If a generic skill's instruction conflicts with Simba Intel's project rules, the project rules in `.agents/rules/` take precedence.
- **External safety**: Never execute unknown code or scripts from external repositories without prior review.

---

## 7. Rules & Skills Directory Map

### Project Rules (`.agents/rules/`)

| Rule File | Scope & Purpose |
| :--- | :--- |
| [ponytail_principles.md](file:///.agents/rules/ponytail_principles.md) | The Ladder of Laziness, root-cause bug fixing, YAGNI, minimalist diffs |
| [architecture.md](file:///.agents/rules/architecture.md) | Multi-tier architecture, message tree invariants, service layer rules |
| [django_python.md](file:///.agents/rules/django_python.md) | Python 3.12 & Django 6 standards, query optimization, sync streaming |
| [ai_providers.md](file:///.agents/rules/ai_providers.md) | `BaseProvider`, `MODEL_REGISTRY`, fallbacks, cooldowns, token usage |
| [database_migrations.md](file:///.agents/rules/database_migrations.md) | PostgreSQL configuration, non-destructive migrations, message tree writes |
| [security_secrets.md](file:///.agents/rules/security_secrets.md) | Zero secrets exposure, RBAC hierarchy, agent token security, IDOR protection |
| [testing_verification.md](file:///.agents/rules/testing_verification.md) | Verification ladder, Django test execution, mock requirements |
| [frontend_templates.md](file:///.agents/rules/frontend_templates.md) | Cyberpunk theme tokens, vanilla JS, DOM updates, no build step |
| [api_development.md](file:///.agents/rules/api_development.md) | Standard JSON response payloads, streaming SSE, desktop agent polling APIs |
| [deployment_environment.md](file:///.agents/rules/deployment_environment.md) | Render container settings, Gunicorn thread config, connection pooling |

### Project Skills (`.agents/skills/`)

| Skill | Activation Trigger & Purpose |
| :--- | :--- |
| [ponytail](file:///.agents/skills/ponytail/SKILL.md) | Minimalist senior developer mindset, YAGNI enforcement, shortest safe diff |
| [debugging](file:///.agents/skills/debugging/SKILL.md) | Diagnosing ErrorLog entries, AI streaming errors, 429 cooldowns, DB pool issues |
| [code-review](file:///.agents/skills/code-review/SKILL.md) | Systematic review checklist for architecture, security, minimalism, and tests |
| [testing](file:///.agents/skills/testing/SKILL.md) | Running Django tests, authoring unit tests, mocking external AI providers |
| [security-audit](file:///.agents/skills/security-audit/SKILL.md) | Auditing secrets leaks, verifying RBAC enforcement, agent tokens, and IDOR |
| [refactoring](file:///.agents/skills/refactoring/SKILL.md) | Minimal safe refactoring without breaking public APIs, endpoints, or UI |
| [django-python](file:///.agents/skills/django-python/SKILL.md) | Writing Django views, management commands, middleware, and optimized queries |
| [ai-provider-integration](file:///.agents/skills/ai-provider-integration/SKILL.md) | Integrating new models/providers, updating registry, fallbacks, and cost table |
| [database-migrations](file:///.agents/skills/database-migrations/SKILL.md) | Creating safe schema migrations, data backfills, indexes, and constraints |
| [frontend-ui](file:///.agents/skills/frontend-ui/SKILL.md) | Developing Cyberpunk templates, theme tokens, command palette, and UI components |
