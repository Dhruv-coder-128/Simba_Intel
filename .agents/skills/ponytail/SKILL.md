---
name: ponytail
description: >-
  Forces the simplest, most minimal, and pragmatic solution that solves the problem.
  Channels a senior engineer who eliminates code bloat, avoids unnecessary abstractions,
  reaches for existing code and standard library before new dependencies, and fixes root
  causes rather than symptoms. Use when the user requests minimal solutions, YAGNI, refactoring,
  or when addressing any coding or bug-fixing task.
---

# Ponytail — Pragmatic Senior Engineering Skill

Ponytail ensures that code changes remain minimal, robust, and free from over-engineering. Lazy means efficient and disciplined, not careless.

## The Ladder of Laziness

Stop at the first rung that holds:

1. **Does this need to exist at all? (YAGNI)**
   - Speculative feature or theoretical edge case? Do not build it. Explain why in one line.
2. **Is it already in this codebase? (Reuse)**
   - Check `chat/services/`, `chat/utils/`, and `chat/models.py`.
   - Never rewrite helper functions, tree traversals, or token estimators that already exist.
3. **Does the Python standard library do it?**
   - Use `pathlib`, `re`, `json`, `dataclasses`, `secrets`, `uuid`, `datetime` before importing third-party code.
4. **Does Django or the database already cover it?**
   - Use ORM constraints, validators, and built-in middleware before writing bespoke checks.
5. **Does an already-installed dependency solve it?**
   - Consult `requirements.txt`. Never add a new package for something an existing package (`requests`, `pydantic`, `pdfplumber`, `pillow`) can do.
6. **Can it be one line?**
   - If a standard comprehension or helper does it cleanly, keep it to one line.
7. **Only then: write the minimum code that works.**
   - Produce the shortest safe diff.

## Root-Cause Bug Fixing

- A bug report names a symptom.
- Before editing code, search for all callers of the function using ripgrep.
- Apply the fix at the shared root function rather than patching individual callers.
- A single guard in a shared service (e.g. `ai_router.py` or `message_tree.py`) is smaller, safer, and prevents future regressions.

## Intensity Modes

- **Lite**: Asks the ladder questions before writing code, but allows comfortable helper functions.
- **Full (Default)**: Strictly avoids any abstraction without multiple immediate callers. Enforces shortest safe diff.
- **Ultra**: Extreme minimalism. Zero new files unless syntactically required. Deletions strictly prioritized over additions.
