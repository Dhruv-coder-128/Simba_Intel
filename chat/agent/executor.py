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
        
        Separates CLOUD tools (executed in-process on server/Render) from
        DESKTOP tools (dispatched to the user's connected Windows Desktop Agent).
        """
        tool = self.registry.get(tool_name)
        if not tool:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool_name,
                error=f"Tool '{tool_name}' is not recognized or allowed.",
            )

        execution_target = getattr(tool, "execution_target", "desktop")

        # 1. CLOUD TOOLS: Execute in-process on server (Render/Linux compatible)
        if execution_target == "cloud":
            start_time = time.time()
            try:
                logger.info("Executing cloud tool '%s' with args: %s", tool_name, args)
                result = tool.execute(**args)
                result.details["latency"] = round(time.time() - start_time, 3)
                result.details["tool_name"] = tool_name
                result.execution_target = "cloud"
                return result
            except ValueError as ve:
                return ExecutionResult(
                    success=False,
                    tool=tool_name,
                    action=tool.action_type,
                    error=f"Invalid arguments for '{tool_name}': {str(ve)}",
                    details={"tool_name": tool_name, "args": args},
                    execution_target="cloud",
                )
            except Exception as e:
                logger.exception("Error executing cloud tool '%s': %s", tool_name, e)
                return ExecutionResult(
                    success=False,
                    tool=tool_name,
                    action=tool.action_type,
                    error=f"Cloud execution error in '{tool_name}': {str(e)}",
                    details={"tool_name": tool_name},
                    execution_target="cloud",
                )

        # 2. DESKTOP TOOLS: Dispatch to connected Desktop Agent if user_id is provided
        if user_id is not None:
            if default_agent_hub.is_user_agent_online(user_id):
                logger.info("Dispatching tool '%s' to Desktop Agent for user_id=%s", tool_name, user_id)
                res = default_agent_hub.dispatch_command_and_wait(
                    user_id=user_id,
                    tool=tool_name,
                    arguments=args,
                    timeout=30.0,
                )
                res.execution_target = "desktop"
                return res
            else:
                logger.warning("Desktop Agent offline for user_id=%s on desktop tool '%s'", user_id, tool_name)
                target = args.get("application") or args.get("path") or args.get("url") or args.get("target_app") or ""
                return ExecutionResult(
                    success=False,
                    tool=tool_name,
                    action=tool_name,
                    target=target,
                    output="",
                    error="🔴 **Your SIMBA Desktop Agent is offline.**\n\nTo execute local actions on your Windows PC, please launch the Desktop Agent:\n\n```bash\npython simba_agent.py\n```",
                    details={"agent_offline": True, "tool": tool_name},
                    execution_target="desktop",
                )

        # 3. Try legacy standalone daemon if configured
        daemon_res = self._execute_via_daemon(tool_name, args)
        if daemon_res is not None:
            daemon_res.execution_target = "desktop"
            return daemon_res

        # 4. Local execution fallback (when running directly on Windows PC in development)
        if os.name != "nt":
            target = args.get("application") or args.get("path") or args.get("url") or args.get("target_app") or ""
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool_name,
                target=target,
                output="",
                error="🔴 **Desktop Agent is offline.**\n\nThis server is running on a cloud/Linux host without direct PC desktop access. Start your Desktop Agent to control your Windows machine.",
                details={"agent_offline": True, "tool": tool_name},
                execution_target="desktop",
            )

        start_time = time.time()
        try:
            logger.info("Executing local Windows tool '%s' with args: %s", tool_name, args)
            result = tool.execute(**args)
            result.details["latency"] = round(time.time() - start_time, 3)
            result.details["tool_name"] = tool_name
            result.execution_target = "desktop"
            return result
        except ValueError as ve:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool.action_type,
                error=f"Invalid arguments for '{tool_name}': {str(ve)}",
                details={"tool_name": tool_name, "args": args},
                execution_target="desktop",
            )
        except PermissionError as pe:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool.action_type,
                error=f"Permission denied: {str(pe)}",
                details={"tool_name": tool_name},
                execution_target="desktop",
            )
        except Exception as e:
            logger.exception("Error executing local tool '%s': %s", tool_name, e)
            return ExecutionResult(
                success=False,
                tool=tool_name,
                action=tool.action_type,
                error=f"Execution error in '{tool_name}': {str(e)}",
                details={"tool_name": tool_name},
                execution_target="desktop",
            )


# Default local executor
default_executor = LocalExecutor()

