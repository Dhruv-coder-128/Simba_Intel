---
name: refactoring
description: >-
  Procedures for conducting safe, minimal refactoring in Simba Intel without breaking existing
  endpoints, templates, or message tree integrity. Use when restructuring code, extracting common
  utilities, optimizing queries, or removing dead code.
---

# Simba Intel Safe Refactoring Runbook

Follow these steps when refactoring code to ensure zero regressions and maintain backward compatibility.

## 1. Scope & Pre-Refactoring Safety

1. **Strictly Define the Target**:
   - Refactor only the specified module or function.
   - Do NOT perform opportunistic cleanup or reformatting on unrelated files.
2. **Find All Callers**:
   - Use grep to discover every reference to the function, class, or model field:
     - Check `chat/views.py`, `chat/admin_views.py`, `chat/services/`, and `templates/`.
3. **Verify Existing Test Coverage**:
   - Before modifying working logic, run the existing tests:
     ```bash
     python manage.py test chat.tests
     ```
   - If tests do not exist for the component being refactored, write characterization tests first to capture current behavior.

## 2. Refactoring Principles

1. **Preserve External Interfaces**:
   - Keep function signatures, parameter names, and return types identical.
   - If adding new optional parameters, provide backward-compatible defaults.
2. **Service Layer Consolidation**:
   - If extracting repeated logic from views, move it into the appropriate service:
     - AI logic -> `chat/services/ai_router.py`
     - Message handling -> `chat/services/message_tree.py`
     - Token/rate metrics -> `chat/services/usage.py`
3. **Deletion Over Addition**:
   - Remove unused private helpers or dead branches instead of wrapping them in extra conditional flags.
4. **Preserve Message Tree & DB Contracts**:
   - Never change the shape of `Message` or `ChatSession` without evaluating all downstream impacts on `build_display_messages()`.

## 3. Post-Refactoring Verification

1. Run Django system check:
   ```bash
   python manage.py check
   ```
2. Run full test suite:
   ```bash
   python manage.py test chat
   ```
3. Check for unintended diffs:
   - Review git status to ensure only intended files were modified.
