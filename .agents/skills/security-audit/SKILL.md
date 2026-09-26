---
name: security-audit
description: >-
  Procedures for auditing application security, preventing secrets leakage, validating RBAC
  rules, checking for IDOR vulnerabilities, and securing desktop agent interfaces.
  Use when conducting security reviews, auditing new endpoints, or verifying access control.
---

# Simba Intel Security Audit Runbook

Follow this checklist to audit code for security vulnerabilities and secrets exposure.

## 1. Secrets Leakage Audit

1. **Verify No Hardcoded Credentials**:
   - Grep for secret keywords in newly added or modified files:
     - `GROQ_API_KEY`, `MISTRAL_API_KEY`, `TAVILY_API_KEY`, `RESEND_API_KEY`, `OPENROUTER_API_KEY`
     - `SECRET_KEY`, `PASSWORD`, `token_hex`
   - Confirm that all secrets are read strictly from `os.getenv()`.
2. **Environment File Audit**:
   - Ensure `.env` is never added to git staging (`git status`).
   - Check `.gitignore` contains `.env` and `*.sqlite3`.

## 2. Access Control & RBAC Verification

1. **Role Gating on Admin Endpoints**:
   - Check that all views in `chat/admin_views.py` require at least `Role.ADMIN` or `Role.SUPER_ADMIN`:
     ```python
     from chat.permissions import has_role_at_least, Role
     if not has_role_at_least(request.user, Role.ADMIN):
         return HttpResponseForbidden("Admin access required")
     ```
2. **IDOR (Ownership) Verification**:
   - Verify every query for user resources includes the owner constraint:
     ```python
     # Audit Target:
     ChatSession.objects.filter(id=session_id, user=request.user)
     Message.objects.filter(id=message_id, session__user=request.user)
     Folder.objects.filter(id=folder_id, user=request.user)
     SavedPrompt.objects.filter(id=prompt_id, user=request.user)
     ```
   - Never allow updating or deleting an entity based solely on primary key without checking `user`.

## 3. Desktop Agent Token & Tool Safety

1. **Agent Token Enforcement**:
   - Ensure `/api/agent/*` endpoints validate `UserProfile.agent_token`.
   - Reject unauthenticated requests with `401 Unauthorized`.
2. **Path Traversal Defenses**:
   - Inspect `chat/agent/tools/filesystem_tools.py`:
   - Verify all file paths pass through `_sanitize_path()` to prevent `../` directory escapes.
3. **Risk Level Gating**:
   - Verify destructive tools (file deletion, power actions, task killing) are classified as `RiskLevel.HIGH` or `RiskLevel.CRITICAL`.

## 4. File Attachment Security

1. **Upload Size & Extension Checks**:
   - Verify that file upload endpoints restrict allowable MIME types and maximum file size (e.g. 10MB limit).
   - Ensure uploaded files are stored outside the public document root and served via controlled views.
