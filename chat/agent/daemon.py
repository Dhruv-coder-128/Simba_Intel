"""Standalone SIMBA Desktop Agent Daemon.
Runs locally on the user's Windows machine to receive and execute authenticated, safe desktop tool calls
from the SIMBA_INTEL web application over a secure authenticated HTTP channel.
"""
import argparse
import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from chat.agent.tools.registry import global_tool_registry
from chat.agent.tools.windows_utils import get_system_telemetry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SIMBA_DAEMON] %(message)s",
)
logger = logging.getLogger("simba_daemon")

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"


class SimbaAgentDaemonHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for SIMBA Local Desktop Agent Daemon."""

    server_secret_token: str = ""

    def _set_headers(self, status: int = 200, content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Simba-Agent-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def _verify_auth(self) -> bool:
        if not self.server_secret_token:
            # If no token configured on server, allow loopback only
            client_ip = self.client_address[0]
            return client_ip in ("127.0.0.1", "::1", "localhost")

        token = self.headers.get("X-Simba-Agent-Token")
        if not token:
            auth_header = self.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()

        return token == self.server_secret_token

    def do_GET(self):
        if not self._verify_auth():
            self._set_headers(401)
            self.wfile.write(json.dumps({"error": "Unauthorized: Invalid or missing agent token."}).encode("utf-8"))
            return

        path = self.path.split("?")[0]

        if path in ("/health", "/status"):
            telemetry = get_system_telemetry()
            data = {
                "status": "ok",
                "connected": True,
                "agent_name": "SIMBA_DESKTOP_AGENT",
                "version": "2.0.0",
                "os": telemetry.get("os", "Windows"),
                "telemetry": telemetry,
                "timestamp": time.time(),
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode("utf-8"))

        elif path == "/tools":
            schemas = global_tool_registry.get_llm_schemas()
            self._set_headers(200)
            self.wfile.write(json.dumps({"tools": schemas}).encode("utf-8"))

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found."}).encode("utf-8"))

    def do_POST(self):
        if not self._verify_auth():
            self._set_headers(401)
            self.wfile.write(json.dumps({"error": "Unauthorized: Invalid or missing agent token."}).encode("utf-8"))
            return

        path = self.path.split("?")[0]

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception as e:
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": f"Invalid JSON payload: {str(e)}"}).encode("utf-8"))
            return

        if path == "/execute":
            command_id = payload.get("command_id", f"cmd_{int(time.time()*1000)}")
            tool_name = payload.get("tool", "")
            args = payload.get("args", {})

            logger.info("Executing command [%s]: tool='%s' args=%s", command_id, tool_name, args)
            start_time = time.time()

            tool = global_tool_registry.get(tool_name)
            if not tool:
                self._set_headers(400)
                self.wfile.write(json.dumps({
                    "command_id": command_id,
                    "success": False,
                    "action": tool_name,
                    "error": f"Tool '{tool_name}' is not recognized or allowlisted.",
                }).encode("utf-8"))
                return

            try:
                result = tool.execute(**args)
                duration = round(time.time() - start_time, 3)

                response_data = {
                    "command_id": command_id,
                    "success": result.success,
                    "action": tool_name,
                    "target": args.get("application") or args.get("url") or args.get("path") or args.get("query") or "",
                    "output": result.output,
                    "error": result.error,
                    "details": result.details,
                    "duration": duration,
                    "is_sensitive": result.is_sensitive,
                    "requires_confirmation": result.requires_confirmation,
                    "confirmation_prompt": result.confirmation_prompt,
                    "sensitive_action_data": result.sensitive_action_data,
                }
                self._set_headers(200)
                self.wfile.write(json.dumps(response_data).encode("utf-8"))
                logger.info("Completed command [%s]: success=%s duration=%.3fs", command_id, result.success, duration)
            except Exception as e:
                logger.exception("Error executing command [%s]: %s", command_id, e)
                self._set_headers(500)
                self.wfile.write(json.dumps({
                    "command_id": command_id,
                    "success": False,
                    "action": tool_name,
                    "error": f"Execution exception: {str(e)}",
                }).encode("utf-8"))

        elif path == "/cancel":
            command_id = payload.get("command_id", "")
            logger.info("Cancel request for command [%s]", command_id)
            self._set_headers(200)
            self.wfile.write(json.dumps({"command_id": command_id, "status": "cancelled"}).encode("utf-8"))

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found."}).encode("utf-8"))

    def log_message(self, format, *args):
        # Override to use Python standard logger
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)


def run_daemon(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, token: str = ""):
    """Starts the SIMBA Desktop Agent Daemon."""
    SimbaAgentDaemonHandler.server_secret_token = token
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, SimbaAgentDaemonHandler)
    logger.info("==================================================")
    logger.info("       SIMBA DESKTOP AGENT DAEMON STARTED         ")
    logger.info("==================================================")
    logger.info("Listening on: http://%s:%d", host, port)
    logger.info("Auth Token:   %s", "[CONFIGURED]" if token else "[NONE - LOCAL ONLY]")
    logger.info("Tools:        %d registered desktop tools", len(global_tool_registry.list_tools()))
    logger.info("Press Ctrl+C to stop.")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down SIMBA Desktop Agent Daemon...")
        httpd.server_close()
        logger.info("Daemon stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIMBA Desktop Agent Daemon")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind (default: 8765)")
    parser.add_argument("--token", default=os.environ.get("SIMBA_AGENT_SECRET_KEY", ""), help="Secret auth token")
    args = parser.parse_args()

    run_daemon(host=args.host, port=args.port, token=args.token)
