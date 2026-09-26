---
name: code-review
description: >-
  Comprehensive code review checklist for Simba Intel. Use before finalizing any code change,
  pull request, or feature implementation to verify architectural compliance, Ponytail principles,
  security rules, message tree integrity, and test coverage.
---

# Simba Intel Code Review Checklist

Review all proposed code changes against this checklist before considering a task complete.

## 1. Ponytail Minimalism & YAGNI

- [ ] **Necessity**: Does this change directly solve the requested task without adding speculative features?
- [ ] **Code Reuse**: Did the change reuse existing services (`ai_router`, `message_tree`, `usage`, `model_registry`) instead of reinventing them?
- [ ] **Standard Library**: Are standard Python modules (`pathlib`, `json`, `re`, `secrets`, `uuid`) used instead of new packages?
- [ ] **Minimal Diff**: Is this the smallest safe implementation that solves the problem?
- [ ] **No Unrequested Abstractions**: Are there single-use classes, unnecessary interfaces, or premature configurations?

## 2. Architectural Integrity

- [ ] **Service Layer Separation**: Does business logic live in `chat/services/` rather than view functions?
- [ ] **Message Tree Preservation**:
  - Are all conversational writes made to `Message` via `chat.services.message_tree.append_turn()`?
  - Is `ChatMessage` completely untouched?
  - Is `ChatSession.active_leaf` properly updated?
- [ ] **RBAC Enforcement**:
  - Are permissions checked using `chat.permissions.has_role_at_least(user, role)`?
  - Are Django's `is_staff` and `is_superuser` NOT used for application-level authorization?
- [ ] **Provider Decoupling**:
  - Do new AI models or capabilities integrate through `BaseProvider` and `MODEL_REGISTRY`?
  - Are raw provider names mapped through `PROVIDER_DISPLAY_NAMES` before UI rendering?

## 3. Security & Secrets

- [ ] **No Hardcoded Secrets**: Are API keys, passwords, or tokens strictly read from `os.getenv()`?
- [ ] **IDOR Protection**: Are all database queries for user resources explicitly scoped by `user=request.user`?
- [ ] **SQL Injection Defense**: Are queries parameterized with the Django ORM or `cursor.execute(sql, params)`?
- [ ] **XSS Defense**: Are rendered template variables properly escaped, and are markdown bodies sanitized with `DOMPurify`?

## 4. Verification & Testing

- [ ] **Targeted Tests**: Are there unit tests verifying the new behavior?
- [ ] **Mocked External APIs**: Are external HTTP calls (Groq, Mistral, Tavily, Resend) mocked in test cases?
- [ ] **Clean System Check**: Does `python manage.py check` pass without warnings or errors?
- [ ] **Automated Test Run**: Did `python manage.py test <target>` pass cleanly?
