"""SIMBA Desktop Agent Hub.
Manages secure authentication, state tracking, heartbeat keepalive, and bidirectional
command dispatch/response queues between the Cloud/Render Django server and the user's
local Windows Desktop Agent client.
"""
import logging
import queue
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from django.contrib.auth import get_user_model
from django.utils import timezone

from .tools.registry import ExecutionResult

logger = logging.getLogger("simba_intel.agent.hub")
User = get_user_model()

HEARTBEAT_TIMEOUT_SECONDS = 35.0  # Agent considered offline if no heartbeat/poll in 35s


@dataclass
class DesktopAgentConnection:
    """Represents an active or recently-seen Desktop Agent connection."""
    user_id: int
    agent_id: str
    connection_id: str
    status: str = "ONLINE"  # ONLINE, OFFLINE, CONNECTING, RECONNECTING
    platform: str = "Windows"
    hostname: str = "Unknown Host"
    agent_version: str = "1.0.0"
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    ip_address: Optional[str] = None

    def is_alive(self) -> bool:
        return self.status == "ONLINE" and (time.time() - self.last_seen < HEARTBEAT_TIMEOUT_SECONDS)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "connection_id": self.connection_id,
            "status": "ONLINE" if self.is_alive() else "OFFLINE",
            "platform": self.platform,
            "hostname": self.hostname,
            "agent_version": self.agent_version,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "seconds_since_last_seen": round(time.time() - self.last_seen, 1),
            "is_online": self.is_alive(),
        }


@dataclass
class PendingCommand:
    """Tracks the lifecycle of a command sent to the local Desktop Agent."""
    command_id: str
    user_id: int
    tool: str
    arguments: Dict[str, Any]
    status: str = "QUEUED"  # QUEUED, SENT, EXECUTING, VERIFYING, SUCCESS, FAILED
    created_at: float = field(default_factory=time.time)
    timeout: float = 30.0
    result: Optional[ExecutionResult] = None
    event: threading.Event = field(default_factory=threading.Event)

    def to_wire_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "tool": self.tool,
            "arguments": self.arguments,
            "timeout": self.timeout,
            "timestamp": self.created_at,
        }


class DesktopAgentHub:
    """Central manager for connected Windows Desktop Agents."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DesktopAgentHub, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.lock = threading.RLock()
        self.active_agents: Dict[int, DesktopAgentConnection] = {}  # user_id -> connection
        self.command_queues: Dict[int, queue.Queue] = {}  # user_id -> Queue[PendingCommand]
        self.pending_commands: Dict[str, PendingCommand] = {}  # command_id -> PendingCommand
        self.executed_command_ids: set = set()  # idempotency cache

    def authenticate_agent_token(self, token: str) -> Optional[Any]:
        """Validates agent Bearer token against UserProfile and returns User if valid."""
        clean_token = (token or "").strip()
        if clean_token.lower().startswith("bearer "):
            clean_token = clean_token[7:].strip()
        if not clean_token:
            return None

        try:
            from chat.models import UserProfile
            profile = UserProfile.objects.select_related("user").filter(agent_token=clean_token).first()
            if profile and profile.user and profile.user.is_active:
                return profile.user
        except Exception as e:
            logger.error("Error authenticating agent token: %s", e)
        return None

    def register_agent(
        self,
        user: Any,
        agent_id: Optional[str] = None,
        hostname: Optional[str] = None,
        platform_str: Optional[str] = None,
        agent_version: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> DesktopAgentConnection:
        """Registers an authenticated Desktop Agent connection for a user."""
        with self.lock:
            aid = agent_id or str(uuid.uuid4())
            cid = f"conn_{secrets.token_hex(8)}"
            now = time.time()

            conn = DesktopAgentConnection(
                user_id=user.id,
                agent_id=aid,
                connection_id=cid,
                status="ONLINE",
                platform=platform_str or "Windows",
                hostname=hostname or "Windows PC",
                agent_version=agent_version or "1.0.0",
                connected_at=now,
                last_seen=now,
                ip_address=ip_address,
            )
            self.active_agents[user.id] = conn
            if user.id not in self.command_queues:
                self.command_queues[user.id] = queue.Queue()

            # Update DB profile metadata asynchronously / opportunistically
            try:
                profile = getattr(user, "profile", None)
                if profile:
                    profile.agent_device_name = conn.hostname
                    profile.agent_platform = conn.platform
                    profile.agent_last_seen = timezone.now()
                    profile.save(update_fields=["agent_device_name", "agent_platform", "agent_last_seen"])
            except Exception as e:
                logger.debug("Failed updating UserProfile agent metadata: %s", e)

            logger.info("Agent connected: user_id=%s agent_id=%s host='%s' platform='%s'", user.id, aid, conn.hostname, conn.platform)
            return conn

    def disconnect_agent(self, user_id: int, agent_id: Optional[str] = None) -> None:
        """Marks agent as offline when disconnected."""
        with self.lock:
            if user_id in self.active_agents:
                conn = self.active_agents[user_id]
                if agent_id is None or conn.agent_id == agent_id:
                    conn.status = "OFFLINE"
                    logger.info("Agent disconnected: user_id=%s agent_id=%s", user_id, conn.agent_id)

    def heartbeat(self, user_id: int, agent_id: Optional[str] = None) -> bool:
        """Updates agent last_seen timestamp."""
        with self.lock:
            if user_id in self.active_agents:
                conn = self.active_agents[user_id]
                if agent_id is None or conn.agent_id == agent_id:
                    conn.last_seen = time.time()
                    conn.status = "ONLINE"
                    return True
        return False

    def is_user_agent_online(self, user_id: int) -> bool:
        """Checks if the user has an active, authenticated Desktop Agent connected."""
        with self.lock:
            if user_id in self.active_agents:
                return self.active_agents[user_id].is_alive()
        return False

    def get_user_agent_info(self, user_id: int) -> Dict[str, Any]:
        """Returns the current connection metadata for the user's Desktop Agent."""
        with self.lock:
            if user_id in self.active_agents:
                return self.active_agents[user_id].to_dict()
        return {
            "status": "OFFLINE",
            "is_online": False,
            "platform": "Unknown",
            "hostname": "Not Connected",
            "last_seen": None,
        }

    def poll_commands(self, user_id: int, agent_id: str, timeout: float = 25.0) -> List[Dict[str, Any]]:
        """Long-polling endpoint for Desktop Agent to retrieve queued commands."""
        # 1. Update heartbeat
        self.heartbeat(user_id, agent_id)

        # 2. Get user's command queue
        with self.lock:
            if user_id not in self.command_queues:
                self.command_queues[user_id] = queue.Queue()
            q = self.command_queues[user_id]

        commands = []
        try:
            # Block up to timeout waiting for command
            cmd = q.get(block=True, timeout=timeout)
            if cmd:
                with self.lock:
                    cmd.status = "SENT"
                commands.append(cmd.to_wire_dict())

                # Drain any additional queued commands without blocking
                while not q.empty():
                    extra = q.get_nowait()
                    with self.lock:
                        extra.status = "SENT"
                    commands.append(extra.to_wire_dict())
        except queue.Empty:
            pass

        return commands

    def submit_result(self, user_id: int, command_id: str, result_dict: Dict[str, Any]) -> bool:
        """Called when Desktop Agent completes a command and returns verified result."""
        with self.lock:
            self.heartbeat(user_id)
            if command_id not in self.pending_commands:
                logger.warning("Received result for unknown/expired command_id: %s", command_id)
                return False

            cmd = self.pending_commands[command_id]
            if cmd.user_id != user_id:
                logger.error("Security violation: user_id %s tried submitting result for command owned by %s", user_id, cmd.user_id)
                return False

            success = bool(result_dict.get("success", False))
            tool = result_dict.get("tool", cmd.tool)
            action = result_dict.get("action", tool)
            target = result_dict.get("target")
            output = result_dict.get("output") or result_dict.get("message") or ""
            error = result_dict.get("error")
            details = result_dict.get("details") or {}
            is_sensitive = bool(result_dict.get("is_sensitive", False))
            requires_confirmation = bool(result_dict.get("requires_confirmation", False))
            confirmation_prompt = result_dict.get("confirmation_prompt")

            cmd.result = ExecutionResult(
                success=success,
                tool=tool,
                action=action,
                target=target,
                output=output,
                error=error,
                details=details,
                is_sensitive=is_sensitive,
                requires_confirmation=requires_confirmation,
                confirmation_prompt=confirmation_prompt,
            )
            cmd.status = "SUCCESS" if success else "FAILED"
            self.executed_command_ids.add(command_id)
            cmd.event.set()
            logger.info("Command %s finished: success=%s output='%s' error='%s'", command_id, success, output, error)
            return True

    def dispatch_command_and_wait(
        self,
        user_id: int,
        tool: str,
        arguments: Dict[str, Any],
        timeout: float = 30.0,
    ) -> ExecutionResult:
        """Dispatches a command to the user's connected Desktop Agent and synchronously waits for result."""
        if not self.is_user_agent_online(user_id):
            return ExecutionResult(
                success=False,
                tool=tool,
                action=tool,
                target=arguments.get("application") or arguments.get("path") or arguments.get("url") or "",
                error="Your SIMBA Desktop Agent is offline. Please launch the Desktop Agent on your PC to execute local actions.",
                output="",
                details={"agent_offline": True},
            )

        command_id = f"cmd_{int(time.time()*1000)}_{secrets.token_hex(4)}"
        cmd = PendingCommand(
            command_id=command_id,
            user_id=user_id,
            tool=tool,
            arguments=arguments,
            status="QUEUED",
            created_at=time.time(),
            timeout=timeout,
        )

        with self.lock:
            self.pending_commands[command_id] = cmd
            if user_id not in self.command_queues:
                self.command_queues[user_id] = queue.Queue()
            self.command_queues[user_id].put(cmd)

        logger.info("Dispatched command %s [%s] to user %s queue", command_id, tool, user_id)

        # Wait for Desktop Agent to complete execution
        signaled = cmd.event.wait(timeout=timeout)

        with self.lock:
            self.pending_commands.pop(command_id, None)

        if not signaled:
            logger.warning("Command %s timed out after %ss", command_id, timeout)
            return ExecutionResult(
                success=False,
                tool=tool,
                action=tool,
                target=arguments.get("application") or arguments.get("path") or arguments.get("url") or "",
                error=f"Command execution timed out after {timeout} seconds on your Desktop Agent.",
                output="",
                details={"timeout": True},
            )

        if cmd.result is not None:
            return cmd.result

        return ExecutionResult(
            success=False,
            tool=tool,
            action=tool,
            error="Desktop Agent returned an empty result.",
            output="",
        )


default_agent_hub = DesktopAgentHub()
