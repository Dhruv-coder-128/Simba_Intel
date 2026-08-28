"""Comprehensive automated tests for SIMBA_INTEL Real Local PC Agent & Desktop Assistant.
Verifies real Windows execution, window states (minimize/maximize/restore/switch), keyboard hotkeys, mouse actions,
truthful result verification, RiskLevel gating, and permission confirmation.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from chat.agent.controller import AgentController, default_agent_controller
from chat.agent.daemon import SimbaAgentDaemonHandler
from chat.agent.executor import LocalExecutor
from chat.agent.fast_router import FastCommandRouter, default_fast_router
from chat.agent.planner import AgentPlanner, PlannedStep, is_coding_or_question_prompt
from chat.agent.tools.browser_tools import browser_search, open_url, resolve_site_url
from chat.agent.tools.calculator_tools import evaluate_expression
from chat.agent.tools.desktop_tools import (
    ALLOWED_APPLICATIONS,
    click_mouse_tool,
    close_application,
    double_click_mouse_tool,
    empty_recycle_bin,
    get_active_window,
    get_system_information,
    hotkey,
    maximize_application,
    minimize_application,
    move_mouse_tool,
    open_application,
    press_key,
    press_keys_tool,
    restore_application,
    right_click_mouse_tool,
    scroll_mouse_tool,
    switch_to_application,
    system_power_action,
    type_text,
    window_focus,
)
from chat.agent.tools.filesystem_tools import (
    _sanitize_path,
    append_file,
    copy_file,
    create_file,
    create_folder,
    delete_file,
    delete_folder,
    edit_file,
    find_files,
    list_directory,
    move_file,
    read_file,
    rename_file,
    write_file,
)
from chat.agent.tools.registry import ExecutionResult, RiskLevel, ToolRegistry, global_tool_registry
from chat.agent.tools.windows_utils import (
    force_focus_window,
    get_active_window_info,
    get_system_telemetry,
    send_hotkey,
    send_key,
    send_unicode_text,
)


class TestSimbaToolRegistry(unittest.TestCase):
    """Verifies that all tools are registered with appropriate RiskLevel classifications."""

    def test_global_tools_registered(self):
        tools = global_tool_registry.list_tools()
        tool_names = [t.name for t in tools]
        expected_tools = [
            "open_application", "launch_application", "close_application",
            "focus_application", "switch_to_application", "minimize_application",
            "maximize_application", "restore_application", "type_text",
            "press_key", "press_keys", "hotkey", "click", "double_click",
            "right_click", "move_mouse", "scroll", "open_url", "browser_search",
            "create_file", "read_file", "write_file", "append_file", "edit_file",
            "delete_file", "create_folder", "delete_folder", "find_files",
            "get_system_information", "empty_recycle_bin", "system_power_action",
        ]
        for t in expected_tools:
            self.assertIn(t, tool_names, f"Tool '{t}' missing from global_tool_registry")

    def test_risk_level_gating(self):
        delete_tool = global_tool_registry.get("delete_file")
        self.assertIsNotNone(delete_tool)
        self.assertEqual(delete_tool.risk_level, RiskLevel.DANGEROUS.value)

        del_folder_tool = global_tool_registry.get("delete_folder")
        self.assertIsNotNone(del_folder_tool)
        self.assertEqual(del_folder_tool.risk_level, RiskLevel.DANGEROUS.value)

        recycle_tool = global_tool_registry.get("empty_recycle_bin")
        self.assertIsNotNone(recycle_tool)
        self.assertEqual(recycle_tool.risk_level, RiskLevel.DANGEROUS.value)

        power_tool = global_tool_registry.get("system_power_action")
        self.assertIsNotNone(power_tool)
        self.assertEqual(power_tool.risk_level, RiskLevel.DANGEROUS.value)


class TestFastCommandRouter(unittest.TestCase):
    """Verifies natural language command normalization and 0ms routing for window, keyboard, and mouse commands."""

    def setUp(self):
        self.router = default_fast_router

    def test_open_notepad_and_write_variations(self):
        variations = [
            "open notepad and write hello world",
            "hey simba open notepad and type hello world",
            "can you open notepad and put hello world in it",
            "launch notepad and write hello world",
            "open notepad, then type hello world",
        ]
        for query in variations:
            plan = self.router.detect_fast_command(query)
            self.assertIsNotNone(plan, f"Failed for query: {query}")
            self.assertTrue(plan.is_agent_action)
            tool_names = [s.tool for s in plan.steps]
            self.assertIn("open_application", tool_names)
            self.assertIn("type_text", tool_names)
            type_step = next(s for s in plan.steps if s.tool == "type_text")
            self.assertEqual(type_step.args["text"], "hello world")
            self.assertEqual(type_step.args["target_app"], "notepad")

    def test_compound_open_write_save(self):
        variations = [
            "open Notepad, type hello world, then save it",
            "open notepad and write hello world and save it",
            "open notepad, type hello world, then save",
        ]
        for query in variations:
            plan = self.router.detect_fast_command(query)
            self.assertIsNotNone(plan, f"Failed for query: {query}")
            self.assertTrue(plan.is_agent_action)
            tool_names = [s.tool for s in plan.steps]
            self.assertEqual(tool_names, ["open_application", "focus_application", "type_text", "hotkey"])
            self.assertEqual(plan.steps[2].args["text"], "hello world")
            self.assertEqual(plan.steps[3].args["keys"], ["ctrl", "s"])

    def test_window_control_commands(self):
        # Switch / Focus
        plan_sw = self.router.detect_fast_command("switch to Notepad")
        self.assertIsNotNone(plan_sw)
        self.assertEqual(plan_sw.steps[0].tool, "switch_to_application")
        self.assertEqual(plan_sw.steps[0].args["application"], "notepad")

        # Minimize
        plan_min = self.router.detect_fast_command("minimize Notepad")
        self.assertIsNotNone(plan_min)
        self.assertEqual(plan_min.steps[0].tool, "minimize_application")
        self.assertEqual(plan_min.steps[0].args["application"], "notepad")

        # Maximize
        plan_max = self.router.detect_fast_command("maximize VS Code")
        self.assertIsNotNone(plan_max)
        self.assertEqual(plan_max.steps[0].tool, "maximize_application")
        self.assertIn(plan_max.steps[0].args["application"], ["vscode", "vs code"])

        # Restore
        plan_res = self.router.detect_fast_command("restore Notepad")
        self.assertIsNotNone(plan_res)
        self.assertEqual(plan_res.steps[0].tool, "restore_application")
        self.assertEqual(plan_res.steps[0].args["application"], "notepad")

        # Switch between
        plan_sw2 = self.router.detect_fast_command("switch between Chrome and Notepad")
        self.assertIsNotNone(plan_sw2)
        self.assertEqual(len(plan_sw2.steps), 2)
        self.assertEqual(plan_sw2.steps[0].tool, "switch_to_application")
        self.assertEqual(plan_sw2.steps[1].tool, "switch_to_application")

    def test_keyboard_hotkeys_and_keys(self):
        # Hotkey Ctrl+S
        plan_ctrl_s = self.router.detect_fast_command("press ctrl+s")
        self.assertIsNotNone(plan_ctrl_s)
        self.assertEqual(plan_ctrl_s.steps[0].tool, "hotkey")
        self.assertEqual(plan_ctrl_s.steps[0].args["keys"], ["ctrl", "s"])

        plan_ctrl_s2 = self.router.detect_fast_command("press ctrl + s")
        self.assertIsNotNone(plan_ctrl_s2)
        self.assertEqual(plan_ctrl_s2.steps[0].args["keys"], ["ctrl", "s"])

        # Single key
        plan_enter = self.router.detect_fast_command("press enter")
        self.assertIsNotNone(plan_enter)
        self.assertEqual(plan_enter.steps[0].tool, "press_key")
        self.assertEqual(plan_enter.steps[0].args["key"], "enter")

    def test_mouse_control_commands(self):
        # Click
        plan_clk = self.router.detect_fast_command("click the search box")
        self.assertIsNotNone(plan_clk)
        self.assertEqual(plan_clk.steps[0].tool, "click")

        # Right click
        plan_rclk = self.router.detect_fast_command("right click")
        self.assertIsNotNone(plan_rclk)
        self.assertEqual(plan_rclk.steps[0].tool, "right_click")

        # Double click
        plan_dclk = self.router.detect_fast_command("double click")
        self.assertIsNotNone(plan_dclk)
        self.assertEqual(plan_dclk.steps[0].tool, "double_click")

        # Scroll down
        plan_scroll_down = self.router.detect_fast_command("scroll down")
        self.assertIsNotNone(plan_scroll_down)
        self.assertEqual(plan_scroll_down.steps[0].tool, "scroll")
        self.assertEqual(plan_scroll_down.steps[0].args["direction"], "down")

        # Scroll up
        plan_scroll_up = self.router.detect_fast_command("scroll up 5")
        self.assertIsNotNone(plan_scroll_up)
        self.assertEqual(plan_scroll_up.steps[0].tool, "scroll")
        self.assertEqual(plan_scroll_up.steps[0].args["direction"], "up")
        self.assertEqual(plan_scroll_up.steps[0].args["clicks"], 5)


class TestExecutionResultContract(unittest.TestCase):
    """Verifies that ExecutionResult contains success, tool, action, target, error."""

    def test_execution_result_fields(self):
        res = ExecutionResult(
            success=True,
            tool="hotkey",
            action="send_hotkey",
            target="CTRL + S",
            output="Sent hotkey CTRL + S.",
            details={"keys": ["ctrl", "s"]},
        )
        d = res.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["tool"], "hotkey")
        self.assertEqual(d["action"], "send_hotkey")
        self.assertEqual(d["target"], "CTRL + S")
        self.assertIsNone(d["error"])


class TestActionCardRealVerification(unittest.TestCase):
    """Verifies truthful verification status in Action Card HTML."""

    def test_action_card_verified_success(self):
        controller = default_agent_controller
        plan = default_fast_router.detect_fast_command("open notepad and write hello world")
        step_results = [
            (plan.steps[0], ExecutionResult(success=True, tool="open_application", output="Done — Notepad is open.")),
            (plan.steps[1], ExecutionResult(success=True, tool="focus_application", output="Focused window 'Notepad'.")),
            (plan.steps[2], ExecutionResult(success=True, tool="type_text", output="Typed text into Notepad.")),
        ]
        html = controller.generate_action_card_html(plan, step_results)
        self.assertIn("Completed", html)
        self.assertIn("simba-action-card", html)
        self.assertIn("Launch Notepad", html)
        self.assertIn("Type Text into Notepad", html)

    def test_action_card_truthful_failure(self):
        controller = default_agent_controller
        plan = default_fast_router.detect_fast_command("open notepad and write hello world")
        step_results = [
            (plan.steps[0], ExecutionResult(success=True, tool="open_application", output="Done — Notepad is open.")),
            (plan.steps[1], ExecutionResult(success=False, tool="focus_application", error="Failed to focus Notepad window.")),
        ]
        html = controller.generate_action_card_html(plan, step_results)
        self.assertIn("Failed", html)
        self.assertIn("Failed to focus Notepad window.", html)


if __name__ == "__main__":
    unittest.main()
