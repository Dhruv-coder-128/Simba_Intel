# Ponytail Principles — Pragmatic Senior Engineering

This project enforces Ponytail principles to eliminate over-engineering, code bloat, and premature abstractions.

## Core Philosophy: The Ladder of Laziness

Before writing any new code, stop at the first rung that holds:

1. **Does this need to exist at all? (YAGNI)**
   - Question speculative requirements. If it doesn't solve an immediate user requirement or bug, do not write it. Say so in one line.
2. **Is it already in this codebase? (Reuse)**
   - Look before you write. Re-implementing a utility, helper, model query, or service that already exists in `chat/services/`, `chat/utils/`, or `chat/agent/tools/` is prohibited.
3. **Does the Python standard library do it?**
   - Prefer `pathlib`, `re`, `json`, `dataclasses`, `typing`, `secrets`, `uuid`, `datetime` over custom code or third-party packages.
4. **Does a native platform or Django feature cover it?**
   - Prefer Django ORM constraints, built-in validators, Django middleware, HTML native inputs (`<input type="date">`, `<input type="color">`), and CSS over bespoke JavaScript or manual database checks.
5. **Does an already-installed dependency solve it?**
   - Check `requirements.txt` first. Never introduce a new package when an installed library (`pydantic`, `pdfplumber`, `psutil`, `httpx`, `requests`, `pillow`) or standard library module can do the job.
6. **Can it be one line?**
   - If a Python comprehension, built-in function, or existing helper does it cleanly, keep it to one line.
7. **Only then: write the minimum safe code that works.**
   - Produce the smallest working diff that solves the user's problem without collateral damage.

## Problem Solving & Root Causes

- **Fix root causes, not symptoms:**
  - A bug report describes a symptom. Grep for all callers of the affected function before editing.
  - One guard inside a shared function/service (e.g., inside `ai_router.py` or `message_tree.py`) is a smaller and safer diff than patching individual callers across `views.py`.
- **Trace before touching:**
  - Read the task and all relevant code paths end-to-end first. The smallest change in the wrong place is not lazy—it is a second bug.
- **No speculative improvements:**
  - Do not clean up unrelated code, reformat untouched files, or refactor nearby functions while working on a specific task.

## Rules of Construction

- **No unrequested abstractions:**
  - No interface or base class with only one implementation.
  - No factory pattern for a single object.
  - No configuration dictionary for a value that never changes.
- **Deletion over addition:**
  - Removing dead code or redundant branches is always preferred over adding more conditional logic.
- **Boring over clever:**
  - Write straightforward, readable Python that any engineer can debug at 3 AM.
- **Fewest files possible:**
  - Keep related logic cohesive. Do not create new modules or files unless there is an architectural necessity.
