#!/usr/bin/env python
"""SIMBA Desktop Agent Daemon Entrypoint.
Run this script on your local Windows PC to start the SIMBA Desktop Agent Daemon.

Usage:
    python simba_daemon.py [--port 8765] [--token YOUR_SECRET_TOKEN]
"""
import argparse
import os
import sys

from chat.agent.daemon import DEFAULT_HOST, DEFAULT_PORT, run_daemon

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIMBA Local Desktop Agent Daemon")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SIMBA_DAEMON_PORT", DEFAULT_PORT)), help="Port to bind (default: 8765)")
    parser.add_argument("--token", default=os.environ.get("SIMBA_AGENT_SECRET_KEY", ""), help="Secret auth token")
    args = parser.parse_args()

    run_daemon(host=args.host, port=args.port, token=args.token)
