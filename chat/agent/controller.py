"""Agent Controller for SIMBA_INTEL.
Coordinates planning, local execution, streaming status, Action Card rendering, and response synthesis.
"""
import json
import logging
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from .executor import LocalExecutor, default_executor
from .planner import AgentPlan, AgentPlanner, PlannedStep, default_planner
from .tools.browser_tools import ENGINE_DISPLAY_NAMES
from .tools.registry import ExecutionResult

logger = logging.getLogger("simba_intel.agent.controller")


class AgentController:
    """Orchestrates agent execution flow for SIMBA_INTEL."""

    def __init__(self, planner: Optional[AgentPlanner] = None, executor: Optional[LocalExecutor] = None):
        self.planner = planner or default_planner
        self.executor = executor or default_executor

    def can_handle(self, query: str) -> bool:
        """Returns True if the user query contains executable agent intent."""
        if not query or not query.strip():
            return False
        from .fast_router import default_fast_router
        if default_fast_router.is_deterministic_command(query):
            return True
        plan = self.planner.plan_query(query)
        return plan.is_agent_action and len(plan.steps) > 0

    def generate_action_card_html(self, plan: AgentPlan, step_results: List[Tuple[PlannedStep, ExecutionResult]]) -> str:
        """Renders a sleek, compact, theme-adaptive Action Card HTML with verification checklist and confirmation buttons."""
        has_pending_confirmation = any(res.requires_confirmation for _, res in step_results)
        all_success = len(step_results) > 0 and all(res.success for _, res in step_results)

        if has_pending_confirmation:
            overall_status_class = "pending"
            overall_status_icon = "fa-triangle-exclamation"
            overall_status_text = "Confirmation Required"
        elif all_success:
            overall_status_class = "success"
            overall_status_icon = "fa-circle-check"
            overall_status_text = "Completed"
        else:
            overall_status_class = "failed"
            overall_status_icon = "fa-circle-xmark"
            overall_status_text = "Failed"

        step_html_list = []
        for step, res in step_results:
            if res.requires_confirmation:
                step_status_class = "pending"
            elif res.success:
                step_status_class = "completed"
            else:
                step_status_class = "error"

            icon_html = self._get_tool_icon_html(step.tool, step.args)
            action_name = self._format_action_title(step.tool, step.args)

            # Build sub-step verification check items
            verification = res.details.get("verification") if isinstance(res.details, dict) else None
            substep_items = []
            if verification and isinstance(verification, dict):
                if verification.get("launch_executed"):
                    substep_items.append('<div class="action-substep"><i class="fa-solid fa-check" style="color:var(--accent,#0edb2a);"></i> Launch command executed</div>')
                elif not res.success:
                    substep_items.append('<div class="action-substep"><i class="fa-solid fa-xmark text-danger" style="color:#ff4b4b;"></i> Launch command failed</div>')

                if verification.get("process_detected"):
                    substep_items.append('<div class="action-substep"><i class="fa-solid fa-check" style="color:var(--accent,#0edb2a);"></i> Process detected</div>')
                elif not res.success and verification.get("launch_executed"):
                    substep_items.append('<div class="action-substep"><i class="fa-solid fa-xmark text-danger" style="color:#ff4b4b;"></i> Process not detected</div>')

                if verification.get("window_detected"):
                    substep_items.append('<div class="action-substep"><i class="fa-solid fa-check" style="color:var(--accent,#0edb2a);"></i> Application window verified</div>')

            elif res.requires_confirmation:
                prompt_text = res.confirmation_prompt or f"Confirm execution of {action_name}?"
                substep_items.append(f'<div class="action-substep text-warning"><i class="fa-solid fa-triangle-exclamation" style="color:#ffbb00;"></i> {prompt_text}</div>')
                # Render interactive confirm/cancel buttons
                action_data = res.sensitive_action_data or {"tool_name": step.tool, "args": step.args}
                action_json_escaped = json.dumps(action_data).replace('"', '&quot;')
                substep_items.append(f"""
                    <div class="agent-confirm-actions" style="margin-top:8px; display:flex; gap:8px;">
                        <button type="button" class="agent-btn-confirm" onclick="confirmAgentAction(this, '{action_json_escaped}')" style="background:var(--accent,#0edb2a); color:#000; font-weight:700; border:none; padding:4px 12px; border-radius:4px; cursor:pointer; font-size:12px;">
                            <i class="fa-solid fa-check"></i> Confirm
                        </button>
                        <button type="button" class="agent-btn-cancel" onclick="cancelAgentAction(this)" style="background:rgba(255,255,255,0.1); color:var(--text,#fff); border:1px solid rgba(255,255,255,0.2); padding:4px 12px; border-radius:4px; cursor:pointer; font-size:12px;">
                            <i class="fa-solid fa-xmark"></i> Cancel
                        </button>
                    </div>
                """)

            elif res.success:
                substep_items.append(f'<div class="action-substep"><i class="fa-solid fa-check" style="color:var(--accent,#0edb2a);"></i> {res.output}</div>')
            else:
                err_text = res.error or "Execution failed"
                substep_items.append(f'<div class="action-substep"><i class="fa-solid fa-xmark text-danger" style="color:#ff4b4b;"></i> {err_text}</div>')

            substeps_html = "".join(substep_items)

            step_html_list.append(f"""
                <div class="action-step {step_status_class}">
                    <div class="action-icon-wrap">{icon_html}</div>
                    <div class="action-info">
                        <span class="action-name">{action_name}</span>
                        <div class="action-substeps-list">{substeps_html}</div>
                    </div>
                </div>
            """)

        steps_joined = "".join(step_html_list)

        return f"""
<div class="simba-action-card">
    <div class="action-card-header">
        <div class="action-header-left">
            <span class="action-badge"><i class="fa-solid fa-bolt"></i> SIMBA AGENT</span>
            <span class="action-title">{plan.summary}</span>
        </div>
        <span class="action-status {overall_status_class}">
            <i class="fa-solid {overall_status_icon}"></i> {overall_status_text}
        </span>
    </div>
    <div class="action-card-body">
        {steps_joined}
    </div>
</div>
"""

    def _get_tool_icon_html(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name in ["browser_search", "search_web"]:
            engine = args.get("engine", "google").lower()
            if "youtube" in engine or "yt" in engine:
                return '<i class="fa-brands fa-youtube action-icon youtube"></i>'
            elif "facebook" in engine or "fb" in engine:
                return '<i class="fa-brands fa-facebook action-icon" style="color:#1877f2;"></i>'
            elif "github" in engine:
                return '<i class="fa-brands fa-github action-icon github"></i>'
            elif "reddit" in engine:
                return '<i class="fa-brands fa-reddit action-icon reddit"></i>'
            elif "instagram" in engine or "insta" in engine:
                return '<i class="fa-brands fa-instagram action-icon" style="color:#e4405f;"></i>'
            elif "google" in engine:
                return '<i class="fa-brands fa-google action-icon google"></i>'
            return '<i class="fa-solid fa-magnifying-glass action-icon"></i>'
        elif tool_name in ["open_url", "launch_url"]:
            url = args.get("url", "").lower()
            if "facebook" in url:
                return '<i class="fa-brands fa-facebook action-icon" style="color:#1877f2;"></i>'
            elif "youtube" in url:
                return '<i class="fa-brands fa-youtube action-icon youtube"></i>'
            elif "github" in url:
                return '<i class="fa-brands fa-github action-icon github"></i>'
            elif "reddit" in url:
                return '<i class="fa-brands fa-reddit action-icon reddit"></i>'
            elif "instagram" in url:
                return '<i class="fa-brands fa-instagram action-icon" style="color:#e4405f;"></i>'
            elif "google" in url:
                return '<i class="fa-brands fa-google action-icon google"></i>'
            return '<i class="fa-solid fa-globe action-icon"></i>'
        elif tool_name in ["open_application", "open_app"]:
            app = args.get("application", "").lower()
            if "calc" in app:
                return '<i class="fa-solid fa-calculator action-icon"></i>'
            elif "code" in app or "vs" in app:
                return '<i class="fa-solid fa-code action-icon"></i>'
            elif "note" in app:
                return '<i class="fa-solid fa-file-lines action-icon"></i>'
            elif "cmd" in app or "terminal" in app or "power" in app:
                return '<i class="fa-solid fa-terminal action-icon"></i>'
            return '<i class="fa-solid fa-window-maximize action-icon"></i>'
        elif tool_name in ["close_application", "close_app", "window_close"]:
            return '<i class="fa-solid fa-rectangle-xmark action-icon" style="color:#ff4b4b;"></i>'
        elif tool_name == "calculator":
            return '<i class="fa-solid fa-calculator action-icon" style="color:var(--accent);"></i>'
        elif tool_name == "open_folder":
            return '<i class="fa-solid fa-folder-open action-icon"></i>'
        elif tool_name in ["create_folder", "folder_create"]:
            return '<i class="fa-solid fa-folder-plus action-icon"></i>'
        elif tool_name in ["delete_folder", "folder_delete"]:
            return '<i class="fa-solid fa-folder-minus action-icon" style="color:#ff4b4b;"></i>'
        elif tool_name in ["create_file", "write_file", "save_file"]:
            return '<i class="fa-solid fa-file-circle-plus action-icon"></i>'
        elif tool_name in ["edit_file", "file_edit"]:
            return '<i class="fa-solid fa-file-pen action-icon"></i>'
        elif tool_name in ["delete_file", "file_delete"]:
            return '<i class="fa-solid fa-file-circle-xmark action-icon" style="color:#ff4b4b;"></i>'
        elif tool_name in ["read_file", "open_file"]:
            return '<i class="fa-solid fa-book-open action-icon"></i>'
        elif tool_name in ["find_files", "file_find", "list_directory"]:
            return '<i class="fa-solid fa-folder-tree action-icon"></i>'
        elif tool_name == "type_text":
            return '<i class="fa-solid fa-keyboard action-icon"></i>'
        elif tool_name in ["switch_to_application", "focus_application"]:
            return '<i class="fa-solid fa-arrow-right-to-bracket action-icon" style="color:var(--accent);"></i>'
        elif tool_name in ["minimize_application", "window_minimize"]:
            return '<i class="fa-solid fa-window-minimize action-icon"></i>'
        elif tool_name in ["maximize_application", "window_maximize"]:
            return '<i class="fa-solid fa-window-maximize action-icon"></i>'
        elif tool_name in ["restore_application", "window_restore"]:
            return '<i class="fa-solid fa-window-restore action-icon"></i>'
        elif tool_name in ["hotkey", "press_key", "press_keys"]:
            return '<i class="fa-solid fa-keyboard action-icon" style="color:var(--accent);"></i>'
        elif tool_name in ["click", "double_click", "right_click"]:
            return '<i class="fa-solid fa-arrow-pointer action-icon" style="color:var(--accent);"></i>'
        elif tool_name == "scroll":
            return '<i class="fa-solid fa-arrows-up-down action-icon"></i>'
        elif tool_name in ["get_system_information", "system_info"]:
            return '<i class="fa-solid fa-microchip action-icon" style="color:var(--accent);"></i>'
        elif tool_name in ["clipboard_read", "clipboard_write"]:
            return '<i class="fa-solid fa-clipboard action-icon"></i>'
        return '<i class="fa-solid fa-gear action-icon"></i>'

    def _format_action_title(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name in ["browser_search", "search_web"]:
            engine_key = args.get("engine", "google").lower()
            engine_title = ENGINE_DISPLAY_NAMES.get(engine_key, engine_key.capitalize())
            return f"Search on {engine_title}"
        elif tool_name == "calculator":
            expr = args.get("expression", "math")
            return f"Calculate {expr}"
        elif tool_name in ["open_url", "launch_url"]:
            url = args.get("url", "").lower()
            for key, name in ENGINE_DISPLAY_NAMES.items():
                if key in url:
                    return f"Open {name}"
            return "Open Website"
        elif tool_name in ["open_application", "open_app"]:
            app = args.get("application", "Application").capitalize()
            if "code" in app.lower():
                app = "VS Code"
            return f"Launch {app}"
        elif tool_name in ["close_application", "close_app"]:
            app = args.get("application", "Application").capitalize()
            return f"Close {app}"
        elif tool_name in ["switch_to_application", "focus_application"]:
            app = args.get("application") or args.get("title") or "Application"
            return f"Switch to {app.capitalize()}"
        elif tool_name == "minimize_application":
            app = args.get("application", "Window").capitalize()
            return f"Minimize {app}"
        elif tool_name == "maximize_application":
            app = args.get("application", "Window").capitalize()
            return f"Maximize {app}"
        elif tool_name == "restore_application":
            app = args.get("application", "Window").capitalize()
            return f"Restore {app}"
        elif tool_name == "hotkey":
            keys = args.get("keys", "hotkey")
            combo = " + ".join(k.upper() for k in keys) if isinstance(keys, list) else str(keys).upper()
            return f"Press {combo}"
        elif tool_name in ["press_key", "press_keys"]:
            k = args.get("key") or args.get("keys") or "key"
            return f"Press '{k}'"
        elif tool_name == "click":
            btn = args.get("button", "left").capitalize()
            return f"Mouse {btn}-Click"
        elif tool_name == "double_click":
            return "Mouse Double-Click"
        elif tool_name == "right_click":
            return "Mouse Right-Click"
        elif tool_name == "scroll":
            d = args.get("direction", "down").capitalize()
            return f"Scroll {d}"
        elif tool_name == "open_folder":
            folder = args.get("folder_name_or_path", "Folder").capitalize()
            return f"Open {folder} Folder"
        elif tool_name == "create_folder":
            folder = args.get("folder_path", "Folder")
            return f"Create Folder '{folder}'"
        elif tool_name == "delete_folder":
            folder = args.get("folder_path", "Folder")
            return f"Delete Folder '{folder}'"
        elif tool_name == "type_text":
            app = args.get("target_app", "window").capitalize() if args.get("target_app") else "Window"
            if "code" in app.lower():
                app = "VS Code"
            return f"Type Text into {app}"
        elif tool_name == "create_file":
            path = args.get("path", "file")
            return f"Create File ({path})"
        elif tool_name == "read_file":
            path = args.get("path", "file")
            return f"Read File ({path})"
        elif tool_name == "edit_file":
            path = args.get("path", "file")
            return f"Edit File ({path})"
        elif tool_name == "delete_file":
            path = args.get("path", "file")
            return f"Delete File ({path})"
        elif tool_name == "move_file":
            src = args.get("source", "file")
            dst = args.get("destination", "target")
            return f"Move '{src}' to '{dst}'"
        elif tool_name == "copy_file":
            src = args.get("source", "file")
            dst = args.get("destination", "target")
            return f"Copy '{src}' to '{dst}'"
        elif tool_name == "rename_file":
            src = args.get("source", "file")
            dst = args.get("new_name", "target")
            return f"Rename '{src}' to '{dst}'"
        elif tool_name == "find_files":
            q = args.get("query") or args.get("extension") or "files"
            return f"Find Files '{q}'"
        elif tool_name == "list_directory":
            p = args.get("path", "folder")
            return f"List Directory '{p}'"
        elif tool_name == "get_system_information":
            return "System Information"
        return tool_name.replace("_", " ").title()

    def _synthesize_natural_reply(self, plan: AgentPlan, step_results: List[Tuple[PlannedStep, ExecutionResult]]) -> str:
        has_pending = any(res.requires_confirmation for _, res in step_results)
        if has_pending:
            pending_res = next(res for _, res in step_results if res.requires_confirmation)
            return f"⚠️ **Confirmation Required**: {pending_res.confirmation_prompt or 'Please confirm this action to proceed.'}"

        all_success = all(res.success for _, res in step_results)
        if all_success:
            if len(step_results) == 1:
                step, res = step_results[0]
                if step.tool == "calculator":
                    return f"**{res.output}**"
                elif step.tool in ["open_url", "launch_url"]:
                    return f"{res.output}"
                elif step.tool in ["browser_search", "search_web"]:
                    engine_key = step.args.get("engine", "google").lower()
                    engine_title = ENGINE_DISPLAY_NAMES.get(engine_key, engine_key.capitalize())
                    query = step.args.get("query", "")
                    return f"Opened {engine_title} and searched for **\"{query}\"**.\n\nDone."
                elif step.tool in ["open_application", "open_app"]:
                    return f"{res.output}"
                elif step.tool == "switch_to_application":
                    return f"{res.output}\n\nDone."
                elif step.tool in ["minimize_application", "maximize_application", "restore_application"]:
                    return f"{res.output}\n\nDone."
                elif step.tool == "hotkey":
                    return f"Sent keyboard shortcut {res.target or ''}.\n\nDone."
                elif step.tool == "scroll":
                    return f"{res.output}\n\nDone."
                elif step.tool in ["click", "double_click", "right_click"]:
                    return f"{res.output}\n\nDone."
                elif step.tool == "open_folder":
                    folder = step.args.get("folder_name_or_path", "").capitalize()
                    return f"Opened your **{folder}** folder in File Explorer.\n\nDone."
                elif step.tool == "create_file":
                    path = step.args.get("path", "")
                    return f"Created text file **`{path}`**.\n\nDone."
                return f"{res.output}\n\nDone."
            else:
                tools_used = [s.tool for s, _ in step_results]
                if "type_text" in tools_used and any(t in tools_used for t in ["open_application", "launch_application", "focus_application"]):
                    type_step = next(s for s, _ in step_results if s.tool == "type_text")
                    app_name = type_step.target_app or type_step.args.get("target_app", "application")
                    text_prev = type_step.args.get("text", "")
                    if len(text_prev) > 40:
                        text_prev = text_prev[:40] + "..."
                    has_save = "hotkey" in tools_used
                    suffix = " and saved." if has_save else "."
                    return f"Done — Opened {app_name.capitalize()}, typed \"{text_prev}\"{suffix}"
                return "Successfully completed all requested desktop actions.\n\nDone."
        else:
            offline_res = next((res for _, res in step_results if res.details.get("agent_offline")), None)
            if offline_res:
                return (
                    "🔴 **Your SIMBA Desktop Agent is offline.**\n\n"
                    "To execute local actions on your Windows PC, please launch the Desktop Agent:\n\n"
                    "```bash\n"
                    "python simba_agent.py\n"
                    "```\n\n"
                    "Once your agent is connected, retry your command."
                )
            errors = [res.error for _, res in step_results if not res.success and res.error]
            error_msg = "; ".join(errors) if errors else "Encountered an issue executing the action."
            return f"SIMBA couldn't complete the desktop action: {error_msg}"

    def execute_and_stream(
        self,
        query: str,
        user_id: Optional[int] = None,
        planner_llm_fn: Optional[Callable[[str], str]] = None,
        text_generator_fn: Optional[Callable[[str], str]] = None,
    ) -> Generator[str, None, Dict[str, Any]]:
        """Executes the agent plan and yields streaming progress tokens."""
        from .fast_router import default_fast_router
        fast_plan = default_fast_router.detect_fast_command(query)
        if fast_plan and fast_plan.is_agent_action and len(fast_plan.steps) > 0:
            gen = default_fast_router.execute_fast_stream(
                fast_plan, self, user_id=user_id, text_generator_fn=text_generator_fn
            )
            for chunk in gen:
                yield chunk
            return

        yield "SIMBA_STATUS: INITIALIZING...\n\n"
        yield "SIMBA_STATUS: PLANNING ACTION WITH OX ALPHA...\n\n"
        plan = self.planner.plan(query, llm_fn=planner_llm_fn)

        if plan.chat_response:
            yield "SIMBA_STATUS: GENERATING RESPONSE...\n\n"
            yield plan.chat_response
            return {"plan": plan, "results": [], "card_html": "", "full_response": plan.chat_response}

        if not plan.is_agent_action or not plan.steps:
            yield "SIMBA_STATUS: EXECUTING...\n\n"
            return {"plan": plan, "results": [], "card_html": "", "full_response": ""}

        step_results: List[Tuple[PlannedStep, ExecutionResult]] = []

        for i, step in enumerate(plan.steps):
            step_num = i + 1
            total_steps = len(plan.steps)
            status_label = f"STEP {step_num}/{total_steps}: {step.description.upper()}"
            yield f"SIMBA_STATUS: {status_label}...\n\n"

            if step.needs_generation and step.generation_prompt:
                yield "SIMBA_STATUS: SYNTHESIZING CODE/CONTENT...\n\n"
                gen_content = ""
                if text_generator_fn:
                    try:
                        gen_content = text_generator_fn(step.generation_prompt)
                    except Exception as e:
                        logger.warning("Generation error in agent controller: %s", e)
                        gen_content = f"# Generated content for: {step.generation_prompt}\n"
                else:
                    gen_content = f"# Generated content for: {step.generation_prompt}\n"
                step.args["text"] = gen_content

            yield f"SIMBA_STATUS: EXECUTING {step.tool.upper()}...\n\n"
            res = self.executor.execute_tool(step.tool, step.args, user_id=user_id)

            yield f"SIMBA_STATUS: VERIFYING {step.tool.upper()}...\n\n"
            step_results.append((step, res))

            if not res.success or res.requires_confirmation:
                if not res.success:
                    logger.warning("Agent step %s failed: %s", step.tool, res.error)
                break

        card_html = self.generate_action_card_html(plan, step_results)
        natural_reply = self._synthesize_natural_reply(plan, step_results)

        full_output = f"{card_html}\n\n{natural_reply}"
        yield full_output

        has_pending = any(r.requires_confirmation for _, r in step_results)
        all_success = len(step_results) > 0 and all(r.success for _, r in step_results)
        has_offline = any(r.details.get("agent_offline") for _, r in step_results)

        if has_offline:
            final_status = "AGENT_OFFLINE"
        elif has_pending:
            final_status = "PENDING_CONFIRMATION"
        elif all_success:
            final_status = "SUCCESS"
        else:
            final_status = "FAILED"

        yield f"SIMBA_STATUS: {final_status}\n\n"

        return {
            "plan": plan,
            "results": step_results,
            "card_html": card_html,
            "natural_reply": natural_reply,
            "full_response": full_output,
        }


default_agent_controller = AgentController()
