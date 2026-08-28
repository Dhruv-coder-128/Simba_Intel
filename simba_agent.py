#!/usr/bin/env python3
"""SIMBA INTEL — Windows Desktop Agent Client (Phase 1).

Connects your local Windows PC to the SIMBA server (Cloud/Render or Local).
Executes verified local computer actions (Apps, Windows, Typing, Hotkeys, Mouse, Browser, Files)
and streams verified results back with zero fake completed states.

Usage:
    python simba_agent.py
    python simba_agent.py --server https://simba-intel.onrender.com --token <AGENT_TOKEN>
"""
import argparse
import json
import logging
import os
import platform
import signal
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure project root is in sys.path if running from within the workspace
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Color formatting for terminal
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("simba_agent")

CONFIG_FILE = BASE_DIR / "simba_agent.json"
AGENT_VERSION = "1.0.0"


class SimbaDesktopAgent:
    """Standalone client connecting local Windows PC to SIMBA Server."""

    def __init__(self, server_url: str, token: str, auto_save: bool = True):
        self.server_url = server_url.rstrip("/")
        self.token = token.strip()
        self.auto_save = auto_save
        self.agent_id = f"win_{socket.gethostname().lower()}_{os.getpid()}"
        self.connection_id: Optional[str] = None
        self.username: Optional[str] = None
        self.running = True
        self.executed_commands = set()

        # Load tool registry
        self._init_tools()

    def _init_tools(self):
        """Initializes the safe Windows tool registry."""
        try:
            from chat.agent.tools.registry import global_tool_registry
            import chat.agent.tools  # Ensure all tools are registered
            self.tool_registry = global_tool_registry
            logger.info("Initialized %d safe local PC tools.", len(self.tool_registry.list_tools()))
        except Exception as e:
            logger.error("Failed importing local tool registry: %s", e)
            self.tool_registry = None

    def _http_post(self, endpoint: str, data: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Sends an authenticated HTTP POST request to the SIMBA server."""
        url = f"{self.server_url}{endpoint}"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": f"SimbaDesktopAgent/{AGENT_VERSION} ({platform.system()} {platform.release()})",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error") or err_json.get("message") or str(he)
            except Exception:
                err_msg = str(he)
            logger.error("Server returned HTTP %s on %s: %s", he.code, endpoint, err_msg)
            if he.code == 401:
                logger.error("%sInvalid Desktop Agent token. Please check your token in SIMBA Settings.%s", RED, RESET)
            return None
        except urllib.error.URLError as ue:
            logger.debug("Network error on %s: %s", endpoint, ue.reason)
            return None
        except Exception as e:
            logger.debug("Request exception on %s: %s", endpoint, e)
            return None

    def connect(self) -> bool:
        """Handshake with the SIMBA server to authenticate and establish session."""
        print(f"\n{CYAN}{BOLD}======================================================{RESET}")
        print(f"{CYAN}{BOLD}   SIMBA INTEL -- WINDOWS DESKTOP AGENT (v{AGENT_VERSION})   {RESET}")
        print(f"{CYAN}{BOLD}======================================================{RESET}\n")
        print(f"Target Server: {BOLD}{self.server_url}{RESET}")
        print(f"Local Host:    {BOLD}{socket.gethostname()} ({platform.system()} {platform.release()}){RESET}")
        print(f"Connecting to SIMBA server...")

        data = {
            "agent_id": self.agent_id,
            "hostname": socket.gethostname(),
            "platform": f"{platform.system()} {platform.release()} ({platform.architecture()[0]})",
            "agent_version": AGENT_VERSION,
        }

        res = self._http_post("/api/agent/connect/", data, timeout=12.0)
        if res and res.get("status") == "ok":
            self.connection_id = res.get("connection_id")
            self.username = res.get("username", "Unknown User")
            print(f"\n{GREEN}{BOLD}[OK] AUTHENTICATED SUCCESSFULLY!{RESET}")
            print(f"Connected User: {BOLD}{self.username}{RESET}")
            print(f"Agent Status:   {GREEN}{BOLD}ONLINE (ACTIVE){RESET}")
            print(f"Standing by for local automation commands from SIMBA UI...\n")
            return True

        print(f"\n{RED}{BOLD}[FAIL] Connection failed.{RESET} Check server URL and token.")
        return False

    def execute_command(self, cmd_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Safely executes a received tool command on the local Windows OS."""
        command_id = cmd_dict.get("command_id", f"cmd_{int(time.time()*1000)}")
        tool_name = cmd_dict.get("tool", "")
        arguments = cmd_dict.get("arguments", {})

        # Idempotency guard
        if command_id in self.executed_commands:
            logger.warning("Duplicate command received [%s], ignoring.", command_id)
            return {"command_id": command_id, "success": True, "tool": tool_name, "message": "Already executed"}

        print(f"\n{YELLOW}{BOLD}[COMMAND] Received command [{command_id}]:{RESET} {BOLD}{tool_name}{RESET}")
        if arguments:
            print(f"  Arguments: {json.dumps(arguments, indent=2)}")

        start_time = time.time()
        result_dict = {
            "command_id": command_id,
            "tool": tool_name,
            "action": tool_name,
            "target": arguments.get("application") or arguments.get("path") or arguments.get("url") or "",
            "success": False,
            "output": "",
            "error": None,
            "details": {},
            "is_sensitive": False,
            "requires_confirmation": False,
        }

        if not self.tool_registry:
            result_dict["error"] = "Tool registry not initialized on Desktop Agent."
            print(f"  {RED}[FAIL] Failed: Tool registry missing{RESET}")
            return result_dict

        tool = self.tool_registry.get(tool_name)
        if not tool:
            result_dict["error"] = f"Tool '{tool_name}' is not recognized or allowed on this client."
            print(f"  {RED}[FAIL] Failed: Tool not recognized ({tool_name}){RESET}")
            return result_dict

        try:
            # Execute on native Windows OS
            res = tool.execute(**arguments)
            elapsed = round(time.time() - start_time, 3)

            result_dict["success"] = res.success
            result_dict["tool"] = res.tool or tool_name
            result_dict["action"] = res.action or tool_name
            result_dict["target"] = res.target or result_dict["target"]
            result_dict["output"] = res.output
            result_dict["error"] = res.error
            result_dict["details"] = res.details
            result_dict["details"]["latency"] = elapsed
            result_dict["is_sensitive"] = res.is_sensitive
            result_dict["requires_confirmation"] = res.requires_confirmation
            result_dict["confirmation_prompt"] = res.confirmation_prompt

            if res.success:
                print(f"  {GREEN}[OK] Executed successfully ({elapsed}s):{RESET} {res.output}")
            elif res.requires_confirmation:
                print(f"  {YELLOW}[WARN] Requires confirmation:{RESET} {res.confirmation_prompt}")
            else:
                print(f"  {RED}[FAIL] Failed ({elapsed}s):{RESET} {res.error}")

        except Exception as e:
            elapsed = round(time.time() - start_time, 3)
            logger.exception("Exception executing '%s': %s", tool_name, e)
            result_dict["success"] = False
            result_dict["error"] = str(e)
            print(f"  {RED}[ERROR] Error ({elapsed}s):{RESET} {str(e)}")

        self.executed_commands.add(command_id)
        return result_dict

    def run_loop(self):
        """Main long-polling and heartbeat loop with automatic reconnection."""
        backoff = 1.0
        max_backoff = 15.0

        while self.running:
            # 1. Connect if not currently connected
            if not self.connection_id:
                connected = self.connect()
                if not connected:
                    print(f"Retrying connection in {int(backoff)}s... (Press Ctrl+C to exit)")
                    time.sleep(backoff)
                    backoff = min(backoff * 2.0, max_backoff)
                    continue
                else:
                    backoff = 1.0

            # 2. Long-poll for commands
            poll_data = {
                "agent_id": self.agent_id,
                "connection_id": self.connection_id,
                "timeout": 25.0,
            }

            res = self._http_post("/api/agent/poll/", poll_data, timeout=35.0)
            if res is None:
                # Connection dropped
                print(f"\n{YELLOW}⚠ Connection lost. Reconnecting...{RESET}")
                self.connection_id = None
                time.sleep(1.0)
                continue

            # 3. Process returned commands
            commands = res.get("commands", [])
            for cmd in commands:
                if not self.running:
                    break
                exec_result = self.execute_command(cmd)
                # Submit result back to server
                sub_res = self._http_post("/api/agent/result/", exec_result, timeout=15.0)
                if sub_res and sub_res.get("status") == "ok":
                    logger.debug("Result submitted successfully for command %s", exec_result.get("command_id"))
                else:
                    logger.warning("Failed submitting result for command %s", exec_result.get("command_id"))

    def stop(self):
        """Gracefully disconnects and shuts down the Desktop Agent."""
        print(f"\n{YELLOW}Disconnecting Desktop Agent...{RESET}")
        self.running = False
        if self.connection_id:
            try:
                self._http_post("/api/agent/disconnect/", {"agent_id": self.agent_id}, timeout=3.0)
            except Exception:
                pass
        print(f"{GREEN}SIMBA Desktop Agent safely stopped.{RESET}\n")


def load_saved_config() -> Dict[str, str]:
    """Loads saved server URL and token from simba_agent.json if present."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(server_url: str, token: str):
    """Saves server URL and token to simba_agent.json for easy restart."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"server_url": server_url, "token": token}, f, indent=2)
    except Exception as e:
        logger.debug("Could not save config file: %s", e)


def main():
    parser = argparse.ArgumentParser(description="SIMBA INTEL Windows Desktop Agent")
    parser.add_argument("--server", help="SIMBA Django server URL (e.g. http://localhost:8000 or https://simba-intel.onrender.com)")
    parser.add_argument("--token", help="Desktop Agent Secret Token (found in SIMBA Settings > Desktop Agent)")
    parser.add_argument("--no-save", action="store_true", help="Do not save token to local config file")
    args = parser.parse_args()

    saved_cfg = load_saved_config()

    server_url = (
        args.server
        or os.environ.get("SIMBA_SERVER_URL")
        or saved_cfg.get("server_url")
        or "http://localhost:8000"
    )

    token = (
        args.token
        or os.environ.get("SIMBA_AGENT_TOKEN")
        or saved_cfg.get("token")
    )

    # If token not provided, prompt interactively
    if not token:
        print(f"\n{CYAN}{BOLD}SIMBA Desktop Agent Setup{RESET}")
        print(f"Server: {server_url}")
        print("To connect, enter your Desktop Agent Token (found in SIMBA Web Chat or Settings).")
        try:
            token = input(f"{BOLD}Agent Token: {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            sys.exit(0)

    if not token:
        print(f"{RED}Error: Agent Token is required to connect.{RESET}")
        sys.exit(1)

    if not args.no_save:
        save_config(server_url, token)

    agent = SimbaDesktopAgent(server_url=server_url, token=token)

    # Handle Ctrl+C gracefully
    def _sig_handler(sig, frame):
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    agent.run_loop()


if __name__ == "__main__":
    main()
