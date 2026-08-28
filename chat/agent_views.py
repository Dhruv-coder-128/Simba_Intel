"""API Endpoints for Cloud ↔ Local SIMBA Desktop Agent Connection.
Handles authentication, long-poll command streaming, truthful execution result ingestion,
and frontend connection status indicators.
"""
import json
import logging
import time
from typing import Optional, Tuple

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

    commands = default_agent_hub.poll_commands(user_id=user.id, agent_id=agent_id, timeout=timeout)
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
    """Frontend web endpoint: Returns connection status and agent token for current user."""
    profile = getattr(request.user, "profile", None)
    agent_token = profile.get_or_create_agent_token() if profile else ""
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
