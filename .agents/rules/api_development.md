# API Development Rules

This rule outlines standards for designing, implementing, and maintaining HTTP and streaming APIs in Simba Intel.

## API Conventions

1. **Uniform Response Structure**:
   - JSON endpoints must return standardized JSON payloads:
     ```python
     # Success payload:
     return JsonResponse({"status": "ok", "data": ...})

     # Error payload:
     return JsonResponse({
         "status": "error",
         "error": "Human-readable explanation of error"
     }, status=400)
     ```

2. **HTTP Status Code Standards**:
   - `200 OK`: Operation succeeded.
   - `400 Bad Request`: Invalid or malformed JSON, missing required fields.
   - `401 Unauthorized`: Anonymous request on an authenticated endpoint.
   - `403 Forbidden`: Authenticated user lacks required RBAC role or email verification.
   - `404 Not Found`: Entity does not exist or belongs to another user (protect against IDOR).
   - `429 Too Many Requests`: User exceeded sliding-window rate limit (30 req/min) or daily quota.
   - `503 Service Unavailable`: Temporary upstream provider exhaustion or database pool busy.

3. **Request Body Parsing**:
   - Parse JSON request bodies safely:
     ```python
     import json
     try:
         data = json.loads(request.body.decode('utf-8'))
     except (json.JSONDecodeError, UnicodeDecodeError):
         return JsonResponse({"status": "error", "error": "Invalid JSON body"}, status=400)
     ```

## Streaming Endpoints

1. **Streaming Protocol**:
   - Streaming completions (`views.ask_ai`) return a Django `StreamingHttpResponse`.
   - Streaming generators should yield string fragments as they arrive from the provider.
   - When using SSE (Server-Sent Events), prefix data frames with `data: ` and separate events with double newlines `\n\n`.
2. **Post-Streaming Metadata**:
   - Because HTTP headers and initial status codes cannot be modified once the response stream begins, subsequent metadata (such as newly created message IDs) must be fetched by the client via dedicated follow-up endpoints (e.g., `/session/<id>/active-leaf/`).

## Desktop Agent API Contracts (`/api/agent/*`)

1. **Authentication**:
   - Requests to `/api/agent/*` authenticate using the bearer token in `UserProfile.agent_token`.
   - Clients must pass `X-Simba-Agent-Token: <token>` or `Authorization: Bearer <token>`.
2. **Polling & Heartbeats**:
   - Desktop agent polls for queued tasks via `POST /api/agent/poll/`.
   - The daemon sends periodic heartbeats via `POST /api/agent/heartbeat/` to update `UserProfile.agent_last_seen`.
   - Task completion results stream to `POST /api/agent/result/` with exact task execution status (`COMPLETED`, `FAILED`, or `CANCELLED`). Zero fake completed states are permitted.
