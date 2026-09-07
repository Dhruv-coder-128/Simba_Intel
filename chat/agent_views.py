"""API Endpoints for Cloud ↔ Local SIMBA Desktop Agent Connection.
Handles authentication, long-poll command streaming, truthful execution result ingestion,
and frontend connection status indicators.
"""
import json
import logging
import time
from typing import Optional, Tuple, Any

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET, require_http_methods

from .agent.agent_hub import default_agent_hub
from .utils.request_info import client_ip

logger = logging.getLogger("simba_intel.agent.api")
User = get_user_model()


def _authenticate_agent_request(request: HttpRequest) -> Tuple[Optional[Any], Optional[str]]:
    """Helper that extracts and validates Bearer token from headers or JSON payload."""
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()

    payload_data = {}
    if not token and request.body:
        try:
            payload_data = json.loads(request.body.decode("utf-8"))
            token = payload_data.get("token") or payload_data.get("agent_token") or ""
        except Exception:
            pass

    if not token:
        token = request.headers.get("X-Simba-Agent-Token", "")

    user = default_agent_hub.authenticate_agent_token(token)
    return user, token


@csrf_exempt
@require_POST
def agent_connect_view(request: HttpRequest) -> JsonResponse:
    """Handshake endpoint: Authenticates the local Desktop Agent and marks it ONLINE."""
    user, token = _authenticate_agent_request(request)
    if not user:
        return JsonResponse({"error": "Authentication failed: Invalid or missing Desktop Agent token."}, status=401)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}

    agent_id = data.get("agent_id")
    hostname = data.get("hostname")
    platform_str = data.get("platform")
    agent_version = data.get("agent_version", "1.0.0")
    ip = client_ip(request)

    conn = default_agent_hub.register_agent(
        user=user,
        agent_id=agent_id,
        hostname=hostname,
        platform_str=platform_str,
        agent_version=agent_version,
        ip_address=ip,
    )

    return JsonResponse({
        "status": "ok",
        "message": f"Desktop Agent connected for user '{user.username}'.",
        "user_id": user.id,
        "username": user.username,
        "agent_id": conn.agent_id,
        "connection_id": conn.connection_id,
        "server_time": time.time(),
    })


@csrf_exempt
@require_POST
def agent_poll_view(request: HttpRequest) -> JsonResponse:
    """Long-polling endpoint: Desktop Agent waits for structured automation commands."""
    user, _ = _authenticate_agent_request(request)
    if not user:
        return JsonResponse({"error": "Authentication failed."}, status=401)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}

    agent_id = data.get("agent_id", "")
    timeout = min(float(data.get("timeout", 25.0)), 30.0)

    # Release PostgreSQL connection back to the pool BEFORE the 25-30s in-memory wait.
    # Holding a database connection while waiting in Python memory exhausts pool limits.
    from django.db import connection
    try:
        connection.close()
    except Exception:
        pass

    try:
        commands = default_agent_hub.poll_commands(user_id=user.id, agent_id=agent_id, timeout=timeout)
    finally:
        try:
            connection.close()
        except Exception:
            pass

    return JsonResponse({
        "status": "ok",
        "commands": commands,
        "server_time": time.time(),
    })


@csrf_exempt
@require_POST
def agent_result_view(request: HttpRequest) -> JsonResponse:
    """Ingestion endpoint: Receives verified execution results from the Desktop Agent."""
    user, _ = _authenticate_agent_request(request)
    if not user:
        return JsonResponse({"error": "Authentication failed."}, status=401)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception as e:
        return JsonResponse({"error": f"Invalid JSON payload: {str(e)}"}, status=400)

    command_id = data.get("command_id")
    if not command_id:
        return JsonResponse({"error": "Missing 'command_id' field."}, status=400)

    accepted = default_agent_hub.submit_result(user_id=user.id, command_id=command_id, result_dict=data)
    return JsonResponse({
        "status": "ok",
        "accepted": accepted,
        "command_id": command_id,
    })


@csrf_exempt
@require_POST
def agent_heartbeat_view(request: HttpRequest) -> JsonResponse:
    """Keepalive ping endpoint for the Desktop Agent."""
    user, _ = _authenticate_agent_request(request)
    if not user:
        return JsonResponse({"error": "Authentication failed."}, status=401)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}

    agent_id = data.get("agent_id")
    default_agent_hub.heartbeat(user_id=user.id, agent_id=agent_id)
    return JsonResponse({"status": "ok", "server_time": time.time()})


@csrf_exempt
@require_POST
def agent_disconnect_view(request: HttpRequest) -> JsonResponse:
    """Graceful disconnect notification when the Desktop Agent process terminates."""
    user, _ = _authenticate_agent_request(request)
    if not user:
        return JsonResponse({"error": "Authentication failed."}, status=401)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}

    agent_id = data.get("agent_id")
    default_agent_hub.disconnect_agent(user_id=user.id, agent_id=agent_id)
    return JsonResponse({"status": "ok", "message": "Desktop Agent marked offline."})


@login_required
@require_GET
def agent_status_view(request: HttpRequest) -> JsonResponse:
    """Frontend web endpoint: Returns connection status, agent token, and screen awareness status."""
    profile = getattr(request.user, "profile", None)
    agent_token = profile.get_or_create_agent_token() if profile else ""
    screen_awareness_enabled = profile.screen_awareness_enabled if profile else True
    info = default_agent_hub.get_user_agent_info(request.user.id)

    return JsonResponse({
        "connected": info.get("is_online", False),
        "status": info.get("status", "OFFLINE").lower(),
        "device": {
            "hostname": info.get("hostname", profile.agent_device_name if profile else "Not Connected"),
            "platform": info.get("platform", profile.agent_platform if profile else "Windows"),
            "seconds_since_last_seen": info.get("seconds_since_last_seen"),
            "connected_at": info.get("connected_at"),
        },
        "agent_token": agent_token,
        "screen_awareness_enabled": screen_awareness_enabled,
    })


@login_required
@require_POST
def agent_regenerate_token_view(request: HttpRequest) -> JsonResponse:
    """Frontend web endpoint: Generates a new desktop agent token and invalidates old sessions."""
    profile = getattr(request.user, "profile", None)
    if not profile:
        return JsonResponse({"error": "Profile not found."}, status=400)

    new_token = profile.regenerate_agent_token()
    default_agent_hub.disconnect_agent(request.user.id)
    return JsonResponse({
        "status": "ok",
        "agent_token": new_token,
        "message": "New Desktop Agent token generated. Previous sessions invalidated.",
    })


@login_required
@require_POST
def agent_screen_awareness_toggle_view(request: HttpRequest) -> JsonResponse:
    """Frontend web endpoint: Toggles user's screen awareness permission."""
    profile = getattr(request.user, "profile", None)
    if not profile:
        return JsonResponse({"error": "Profile not found."}, status=400)

    profile.screen_awareness_enabled = not profile.screen_awareness_enabled
    profile.save(update_fields=["screen_awareness_enabled"])

    status_str = "ENABLED" if profile.screen_awareness_enabled else "DISABLED"
    return JsonResponse({
        "status": "ok",
        "screen_awareness_enabled": profile.screen_awareness_enabled,
        "message": f"Screen access {status_str}.",
    })


@login_required
@require_POST
def agent_task_cancel_view(request: HttpRequest) -> JsonResponse:
    """Safely stops and cancels any active or in-flight agent task for current user."""
    from chat.agent.task_manager import default_task_manager
    task_id = request.POST.get("task_id")
    if not task_id and request.body:
        try:
            body = json.loads(request.body.decode("utf-8"))
            task_id = body.get("task_id")
        except Exception:
            pass
    cancelled = default_task_manager.cancel_task(task_id=task_id, user_id=request.user.id)
    return JsonResponse({"status": "ok", "cancelled": cancelled, "message": "Agent task cancelled."})


@login_required
@require_GET
def agent_task_history_view(request: HttpRequest) -> JsonResponse:
    """Returns dedicated task execution history for the current user with search and status filtering."""
    from chat.agent.task_manager import default_task_manager
    search = request.GET.get("search", "")
    status_filter = request.GET.get("status", "")
    try:
        limit = min(int(request.GET.get("limit", 30)), 100)
    except Exception:
        limit = 30

    history = default_task_manager.get_user_task_history(
        request.user.id,
        limit=limit,
        search=search,
        status_filter=status_filter,
    )
    return JsonResponse({"status": "ok", "tasks": history})


@login_required
@require_GET
def agent_tools_list_view(request: HttpRequest) -> JsonResponse:
    """Returns dynamic registry tools metadata for Action Discovery."""
    from chat.agent.tools.registry import global_tool_registry
    info = default_agent_hub.get_user_agent_info(request.user.id)
    desktop_online = info.get("is_online", False)
    tools = global_tool_registry.list_ui_tools(desktop_online=desktop_online)
    return JsonResponse({
        "status": "ok",
        "tools": tools,
        "desktop_online": desktop_online,
    })


@login_required
@require_POST
def agent_task_confirm_view(request: HttpRequest) -> JsonResponse:
    """Allows user to approve or cancel a waiting sensitive task/tool action."""
    from chat.agent.task_manager import default_task_manager
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}

    task_id = data.get("task_id") or request.POST.get("task_id")
    action = data.get("action") or request.POST.get("action") or "allow"

    if not task_id:
        return JsonResponse({"error": "Missing task_id."}, status=400)

    task = default_task_manager.get_task(task_id)
    if not task:
        return JsonResponse({"error": "Task not found."}, status=404)

    if task.user_id != request.user.id:
        return JsonResponse({"error": "Unauthorized."}, status=403)

    if action == "allow":
        default_task_manager.approve_task(task_id)
        return JsonResponse({"status": "ok", "approved": True, "message": "Task approved for execution."})
    else:
        default_task_manager.cancel_task(task_id=task_id, user_id=request.user.id)
        return JsonResponse({"status": "ok", "cancelled": True, "message": "Action cancelled by user."})



