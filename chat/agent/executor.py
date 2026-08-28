"""Local and Remote Dispatch Executor for SIMBA_INTEL Agent.
Executes validated tools securely on the user's Windows environment (via connected Desktop Agent or local Win32 tool registry).
"""
import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

from .agent_hub import default_agent_hub
from .tools.registry import ExecutionResult, ToolRegistry, global_tool_registry

logger = logging.getLogger("simba_intel.agent.executor")


class LocalExecutor:
    """Safely executes tool calls on the Windows machine via the connected Desktop Agent or local registry."""

    def __init__(self, registry: Optional[ToolRegistry] = None, daemon_url: Optional[str] = None):
        self.registry = registry or global_tool_registry
        self.daemon_url = daemon_url or os.environ.get("SIMBA_DESKTOP_AGENT_URL", "").rstrip("/")
        self.daemon_token = os.environ.get("SIMBA_AGENT_SECRET_KEY", "")

    def _execute_via_daemon(self, tool_name: str, args: Dict[str, Any]) -> Optional[ExecutionResult]:
        """Dispatches tool execution to a legacy standalone daemon if configured."""
        if not self.daemon_url:
            return None

        url = f"{self.daemon_url}/execute"
        payload = json.dumps({
            "command_id": f"exec_{int(time.time() * 1000)}",
            "tool": tool_name,
            "args": args,
            "timeout": 15,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        if self.daemon_token:
            req.add_header("X-Simba-Agent-Token", self.daemon_token)

        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    return ExecutionResult(
                        success=data.get("success", False),
                        tool=data.get("tool", tool_name),
                        action=data.get("action", tool_name),
                        target=data.get("target"),
                        output=data.get("output", ""),
                        error=data.get("error"),
                        details=data.get("details", {}),
                        is_sensitive=data.get("is_sensitive", False),
                        requires_confirmation=data.get("requires_confirmation", False),
                        confirmation_prompt=data.get("confirmation_prompt"),
                        sensitive_action_data=data.get("sensitive_action_data"),
                    )
        except Exception as e:
            logger.warning("Desktop daemon dispatch failed: %s. Falling back to hub/local execution.", e)
            return None

    def execute_tool(self, tool_name: str, args: Dict[str, Any], user_id: Optional[int] = None) -> ExecutionResult:
        """Executes a single tool by name with arguments.
        
        If user_id is provided, priority is given to dispatching to the user's connected Desktop Agent.
        """
        # 1. Dispatch to connected Desktop Agent if user_id is provided
        if user_id is not None:
            if default_agent_hub.is_user_agent_online(user_id):
                logger.info("Dispatching tool '%s' to Desktop Agent for user_id=%s", tool_name, user_id)
                return default_agent_hub.dispatch_command_and_wait(
                    user_id=user_id,
                    tool=tool_name,
                    arguments=args,
                    timeout=30.0,
                )
            else:
                logger.warning("Desktop Agent offline for user_id=%s", user_id)
                target = args.get("application") or args.get("path") or args.get("url") or args.get("target_app") or ""
                return ExecutionResult(
                    success=False,
                    tool=tool_name,
                    action=tool_name,
                    target=target,
                    output="",
                    error="Your SIMBA Desktop Agent is offline. Please launch the Desktop Agent on your Windows PC to execute local actions.",
                    details={"agent_offline": True},
                )

        # 2. Try legacy standalone daemon if configured
        daemon_res = self._execute_via_daemon(tool_name, args)
        if daemon_res is not None:
            return daemon_res

        # 3. In-process local execution via Safe Tool Registry
        tool = self.registry.get(tool_name)
        if not tool:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool_name,
                error=f"Tool '{tool_name}' is not recognized or allowed.",
            )

        start_time = time.time()
        try:
            logger.info("Executing local tool '%s' with args: %s", tool_name, args)
            result = tool.execute(**args)
            result.details["latency"] = round(time.time() - start_time, 3)
            result.details["tool_name"] = tool_name
            return result
        except ValueError as ve:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool.action_type,
                error=f"Invalid arguments for '{tool_name}': {str(ve)}",
                details={"tool_name": tool_name, "args": args},
            )
        except PermissionError as pe:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool.action_type,
                error=f"Permission denied: {str(pe)}",
                details={"tool_name": tool_name},
            )
        except Exception as e:
            logger.exception("Error executing tool '%s': %s", tool_name, e)
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool.action_type,
                error=f"Execution error in '{tool_name}': {str(e)}",
                details={"tool_name": tool_name},
            )


# Default local executor
default_executor = LocalExecutor()
