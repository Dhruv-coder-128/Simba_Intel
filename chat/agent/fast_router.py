"""Fast Local Command Router for SIMBA_INTEL.
Detects and executes deterministic agent actions (apps, windows, keyboard, mouse, websites, searches, calculations, folders, files, system info)
immediately with 0ms LLM overhead, zero API tokens, and native Windows OS execution.
"""
import logging
import os
import re
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from .executor import LocalExecutor, default_executor
from .planner import AgentPlan, PlannedStep, is_coding_or_question_prompt
from .tools.browser_tools import ENGINE_DISPLAY_NAMES, POPULAR_SITES, SEARCH_ENGINES, resolve_site_url
from .tools.desktop_tools import ALLOWED_APPLICATIONS
from .tools.registry import ExecutionResult, RiskLevel

logger = logging.getLogger("simba_intel.agent.fast_router")


class FastCommandRouter:
    """High-speed deterministic router that intercepts known actions before any LLM/agent call."""

    def __init__(self, executor: Optional[LocalExecutor] = None):
        self.executor = executor or default_executor

    def is_deterministic_command(self, query: str) -> bool:
        """Returns True if the query is a deterministic command that should execute locally."""
        plan = self.detect_fast_command(query)
        return plan is not None and plan.is_agent_action and len(plan.steps) > 0

    def detect_fast_command(self, query: str) -> Optional[AgentPlan]:
        """Analyzes the raw user query and returns an AgentPlan if it matches a deterministic pattern."""
        q = (query or "").strip()
        if not q:
            return None

        # Guard: Coding requests or general informational questions must not trigger local execution
        if is_coding_or_question_prompt(q):
            return None

        # Normalize clean query for regex checking (strips common conversational prefixes)
        clean_q = re.sub(
            r"^(?:please\s+|can\s+you\s+|could\s+you\s+|will\s+you\s+|hey\s+simba\s*,?\s*|simba\s*,?\s*|simba\s+can\s+you\s+|i\s+want\s+you\s+to\s+)",
            "",
            q,
            flags=re.IGNORECASE,
        ).strip()
        clean_q = clean_q.rstrip("?.!")

        # -------------------------------------------------------------------------
        # 1. Stop / Cancel Task Command
        # e.g., "stop", "cancel", "stop what you're doing", "cancel that task", "abort"
        # -------------------------------------------------------------------------
        if re.match(r"^(?:stop|cancel|abort)(?:\s+(?:it|task|command|action|what\s+you(?:'re|\s+are)\s+doing))?$", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Cancel Current Task",
                raw_query=q,
                steps=[],
                chat_response="Task execution stopped.",
            )

        # -------------------------------------------------------------------------
        # 2. Math / Arithmetic Expressions (e.g. "25 * 8", "calculate 25 * 8", "125 / 5")
        # -------------------------------------------------------------------------
        match_math_prefix = re.match(
            r"^(?:calculate|compute|solve|eval|what\s+is)\s+([0-9\.\+\-\*\/\^\(\)\s\%\×\÷xX]+)$",
            clean_q,
            re.IGNORECASE,
        )
        match_pure_math = re.match(
            r"^([0-9]+(?:\.[0-9]+)?\s*[\+\-\*\/\^\%\×\÷xX]\s*[0-9\.\+\-\*\/\^\(\)\s\%\×\÷xX]+)$",
            clean_q,
        )
        math_expr = None
        if match_math_prefix:
            math_expr = match_math_prefix.group(1).strip()
        elif match_pure_math and not re.search(r"[a-wy-zA-WY-Z]", clean_q):
            math_expr = match_pure_math.group(1).strip()

        if math_expr:
            plan = AgentPlan(
                is_agent_action=True,
                summary=f"Calculate {math_expr}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="calculator",
                        args={"expression": math_expr},
                        description=f"Calculate {math_expr}",
                    )
                ],
            )
            logger.info("FAST_ROUTE → action detected: %s (tools=['calculator'])", plan.summary)
            return plan

        # -------------------------------------------------------------------------
        # 3. System Status, Active Window, Telemetry & Recycle Bin
        # -------------------------------------------------------------------------
        if re.search(r"\b(?:system\s+(?:info|information|stats|telemetry)|cpu\s+usage|ram\s+usage|memory\s+usage)\b", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Get System Information",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="get_system_information",
                        args={},
                        description="Retrieve system telemetry and hardware statistics",
                    )
                ],
            )

        if re.match(r"^(?:show|get|read|what\s+is\s+on)\s+(?:the\s+)?clipboard$", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Read Clipboard",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="clipboard_read",
                        args={},
                        description="Read current clipboard contents",
                    )
                ],
            )

        if re.match(r"^(?:what\s+is\s+(?:the\s+)?active\s+window|get\s+active\s+window|read\s+active\s+window)$", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Get Active Window",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="read_active_window",
                        args={},
                        description="Identify currently active window",
                    )
                ],
            )

        if re.search(r"\bempty\s+(?:the\s+)?recycle\s+bin\b", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Empty Recycle Bin",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="empty_recycle_bin",
                        args={"confirmed": False},
                        description="Empty Windows Recycle Bin (requires confirmation)",
                    )
                ],
            )

        if re.match(r"^(?:shutdown|shut\s+down|restart|reboot|lock)\s+(?:my\s+)?(?:pc|computer|system|windows)$", clean_q, re.IGNORECASE):
            act = "shutdown" if ("shut" in clean_q) else ("restart" if "re" in clean_q else "lock")
            return AgentPlan(
                is_agent_action=True,
                summary=f"System {act.capitalize()}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="system_power_action",
                        args={"action": act, "confirmed": False},
                        description=f"{act.capitalize()} PC (requires confirmation)",
                    )
                ],
            )

        # -------------------------------------------------------------------------
        # 4. Mouse Control Commands: Click, Double Click, Right Click, Scroll, Move
        # e.g., "click", "click the search box", "double click", "right click", "scroll down", "scroll up"
        # -------------------------------------------------------------------------
        match_scroll = re.match(
            r"^(?:scroll|scroll\s+the\s+page|scroll\s+a\s+webpage)\s*(down|up)?(?:\s+(?:by\s+)?(\d+)(?:\s+clicks|\s+steps|\s+times)?)?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_scroll:
            direction = (match_scroll.group(1) or "down").lower().strip()
            amount_raw = match_scroll.group(2)
            clicks = int(amount_raw) if amount_raw else 4
            return AgentPlan(
                is_agent_action=True,
                summary=f"Scroll {direction.capitalize()} ({clicks} steps)",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="scroll",
                        args={"clicks": clicks, "direction": direction},
                        description=f"Scroll mouse {direction} by {clicks} steps",
                    )
                ],
            )

        if re.match(r"^(?:scroll\s+(?:down|the\s+webpage|page\s+down))$", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Scroll Down",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="scroll",
                        args={"clicks": 4, "direction": "down"},
                        description="Scroll mouse down",
                    )
                ],
            )

        if re.match(r"^(?:scroll\s+(?:up|page\s+up))$", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Scroll Up",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="scroll",
                        args={"clicks": 4, "direction": "up"},
                        description="Scroll mouse up",
                    )
                ],
            )

        if re.match(r"^(?:right\s*click|mouse\s+right\s*click)(?:\s+(?:here|on\s+screen|the\s+mouse))?$", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Right Click",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="right_click",
                        args={},
                        description="Simulate mouse right-click",
                    )
                ],
            )

        if re.match(r"^(?:double\s*click|mouse\s+double\s*click)(?:\s+(?:here|on\s+screen|the\s+mouse))?$", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Double Click",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="double_click",
                        args={"button": "left"},
                        description="Simulate mouse double-click",
                    )
                ],
            )

        if re.match(r"^(?:click|click\s+here|click\s+(?:the\s+)?search\s*box|left\s*click|mouse\s+click)$", clean_q, re.IGNORECASE):
            return AgentPlan(
                is_agent_action=True,
                summary="Mouse Click",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="click",
                        args={"button": "left"},
                        description="Simulate mouse left-click",
                    )
                ],
            )

        match_move_mouse = re.match(
            r"^(?:move\s+mouse|set\s+cursor)(?:\s+to)?\s+(\d+)\s*[,xX\s]\s*(\d+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_move_mouse:
            mx = int(match_move_mouse.group(1))
            my = int(match_move_mouse.group(2))
            return AgentPlan(
                is_agent_action=True,
                summary=f"Move Mouse to ({mx}, {my})",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="move_mouse",
                        args={"x": mx, "y": my},
                        description=f"Move mouse cursor to ({mx}, {my})",
                    )
                ],
            )

        # -------------------------------------------------------------------------
        # 5. Keyboard Control: Hotkeys & Single Key Press
        # e.g., "press ctrl+s", "press ctrl + s", "use ctrl+s", "press enter", "press esc", "press f5", "press alt+tab"
        # -------------------------------------------------------------------------
        match_hotkey = re.match(
            r"^(?:press|use|send|hit|trigger)\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)?(ctrl|alt|shift|win|windows)\s*[\+\s\-]\s*([a-zA-Z0-9\+\-\s]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_hotkey:
            mod = match_hotkey.group(1).strip().lower()
            rest = match_hotkey.group(2).strip().lower().replace("+", " ").replace("-", " ")
            keys = [mod] + rest.split()
            combo_display = " + ".join(k.upper() for k in keys)
            return AgentPlan(
                is_agent_action=True,
                summary=f"Press {combo_display}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="hotkey",
                        args={"keys": keys},
                        description=f"Send keyboard shortcut {combo_display}",
                    )
                ],
            )

        match_single_key = re.match(
            r"^(?:press|hit|send)\s+(?:the\s+)?(enter|return|tab|escape|esc|backspace|delete|del|space|spacebar|up|down|left|right|f1|f2|f3|f4|f5|f6|f7|f8|f9|f10|f11|f12)(?:\s+key)?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_single_key:
            key_name = match_single_key.group(1).strip().lower()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Press '{key_name.upper()}' Key",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="press_key",
                        args={"key": key_name},
                        description=f"Press {key_name.upper()} key",
                    )
                ],
            )

        # -------------------------------------------------------------------------
        # 6. Window State Control: Switch To, Minimize, Maximize, Restore
        # e.g., "switch to Notepad", "switch to Chrome", "minimize Notepad", "maximize VS Code", "restore Notepad"
        # -------------------------------------------------------------------------
        match_switch_between = re.match(
            r"^(?:switch|toggle)\s+between\s+([a-zA-Z0-9_\s]+?)\s+and\s+([a-zA-Z0-9_\s]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_switch_between:
            app1_raw = match_switch_between.group(1).strip()
            app2_raw = match_switch_between.group(2).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Switch between {app1_raw.capitalize()} and {app2_raw.capitalize()}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="switch_to_application",
                        args={"application": app1_raw},
                        description=f"Switch to {app1_raw.capitalize()}",
                    ),
                    PlannedStep(
                        tool="switch_to_application",
                        args={"application": app2_raw},
                        description=f"Switch to {app2_raw.capitalize()}",
                    ),
                ],
            )

        match_switch = re.match(
            r"^(?:switch\s+to|bring\s+up|focus|go\s+to\s+app)\s+(?:the\s+)?(notepad|note\s+pad|vscode|vs\s+code|code|visual\s+studio\s+code|chrome|google\s+chrome|edge|calculator|calc|paint|explorer|task\s+manager|spotify|[a-zA-Z0-9_\.\-]+)(?:\s+(?:app|application|window))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_switch:
            target_app = match_switch.group(1).strip().lower()
            config = ALLOWED_APPLICATIONS.get(target_app)
            display_name = config["name"] if config else target_app.capitalize()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Switch to {display_name}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="switch_to_application",
                        args={"application": target_app},
                        description=f"Focus and switch to {display_name}",
                    )
                ],
            )

        match_minimize = re.match(
            r"^minimize\s+(?:the\s+)?(notepad|note\s+pad|vscode|vs\s+code|code|visual\s+studio\s+code|chrome|google\s+chrome|edge|calculator|calc|paint|explorer|task\s+manager|spotify|[a-zA-Z0-9_\.\-]+)(?:\s+(?:app|application|window))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_minimize:
            target_app = match_minimize.group(1).strip().lower()
            config = ALLOWED_APPLICATIONS.get(target_app)
            display_name = config["name"] if config else target_app.capitalize()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Minimize {display_name}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="minimize_application",
                        args={"application": target_app},
                        description=f"Minimize {display_name} window",
                    )
                ],
            )

        match_maximize = re.match(
            r"^maximize\s+(?:the\s+)?(notepad|note\s+pad|vscode|vs\s+code|code|visual\s+studio\s+code|chrome|google\s+chrome|edge|calculator|calc|paint|explorer|task\s+manager|spotify|[a-zA-Z0-9_\.\-]+)(?:\s+(?:app|application|window))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_maximize:
            target_app = match_maximize.group(1).strip().lower()
            config = ALLOWED_APPLICATIONS.get(target_app)
            display_name = config["name"] if config else target_app.capitalize()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Maximize {display_name}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="maximize_application",
                        args={"application": target_app},
                        description=f"Maximize {display_name} window",
                    )
                ],
            )

        match_restore = re.match(
            r"^restore\s+(?:the\s+)?(notepad|note\s+pad|vscode|vs\s+code|code|visual\s+studio\s+code|chrome|google\s+chrome|edge|calculator|calc|paint|explorer|task\s+manager|spotify|[a-zA-Z0-9_\.\-]+)(?:\s+(?:app|application|window))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_restore:
            target_app = match_restore.group(1).strip().lower()
            config = ALLOWED_APPLICATIONS.get(target_app)
            display_name = config["name"] if config else target_app.capitalize()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Restore {display_name}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="restore_application",
                        args={"application": target_app},
                        description=f"Restore {display_name} window",
                    )
                ],
            )

        # -------------------------------------------------------------------------
        # 7. Compound Action: Open App, Write Text, Then Save It
        # e.g., "open notepad, type hello world, then save it", "open notepad and write hello world and save"
        # -------------------------------------------------------------------------
        match_app_write_save = re.match(
            r"^(?:open|launch)\s+(?:the\s+)?(notepad|note\s+pad|vscode|vs\s+code|code|text\s+editor)(?:\s*,\s*|\s+and\s+)(?:type|write|put)\s+(.+?)(?:\s*,\s*then\s+save(?:\s+it)?|\s+and\s+save(?:\s+it)?|\s+then\s+save(?:\s+it)?)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_app_write_save:
            app_raw = match_app_write_save.group(1).strip().lower()
            text_to_write = match_app_write_save.group(2).strip().strip('"\'')
            canonical_app = "notepad" if ("note" in app_raw or "text" in app_raw) else "vscode"
            app_name = "Notepad" if canonical_app == "notepad" else "VS Code"

            return AgentPlan(
                is_agent_action=True,
                summary=f"Open {app_name}, type \"{text_to_write}\", and save",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="open_application",
                        args={"application": canonical_app},
                        description=f"Launch {app_name}",
                    ),
                    PlannedStep(
                        tool="focus_application",
                        args={"title": app_name},
                        description=f"Focus {app_name}",
                    ),
                    PlannedStep(
                        tool="type_text",
                        args={"text": text_to_write, "target_app": canonical_app},
                        description=f"Write \"{text_to_write}\" into {app_name}",
                    ),
                    PlannedStep(
                        tool="hotkey",
                        args={"keys": ["ctrl", "s"]},
                        description="Save file (Ctrl+S)",
                    ),
                ],
            )

        # -------------------------------------------------------------------------
        # 8. Multi-Action: Open App and Write / Type Text
        # e.g., "open notepad and write hello world", "open notepad, then type hello world",
        #       "launch notepad and write hello world", "can you open notepad and put hello world in it"
        # -------------------------------------------------------------------------
        match_app_and_write = re.match(
            r"^(?:open|launch|start)\s+(?:the\s+)?(notepad|note\s+pad|vscode|vs\s+code|code|visual\s+studio\s+code|text\s+editor)(?:\s*,\s*(?:then\s+|and\s+)?|\s+(?:and\s+then|then|and|to|with|and\s+put)\s+|\s+)(?:write|type|put|insert|create)\s+(.+?)(?:\s+in\s+it)?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_app_and_write:
            app_raw = match_app_and_write.group(1).strip().lower()
            text_or_prompt = match_app_and_write.group(2).strip()

            canonical_app = "notepad" if ("note" in app_raw or "text" in app_raw) else "vscode"
            app_name = "Notepad" if canonical_app == "notepad" else "VS Code"

            is_quoted = (
                (text_or_prompt.startswith('"') and text_or_prompt.endswith('"') and len(text_or_prompt) >= 2)
                or (text_or_prompt.startswith("'") and text_or_prompt.endswith("'") and len(text_or_prompt) >= 2)
            )
            is_code_synthesis = re.search(
                r"\b(?:python|javascript|js|html|css|code|script|program|function|class|algorithm|calculator\.py)\b",
                text_or_prompt,
                re.IGNORECASE,
            )

            if is_quoted or not is_code_synthesis:
                literal_text = text_or_prompt.strip('"\'')
                plan = AgentPlan(
                    is_agent_action=True,
                    summary=f"Open {app_name} and write \"{literal_text}\"",
                    raw_query=q,
                    steps=[
                        PlannedStep(
                            tool="open_application",
                            args={"application": canonical_app},
                            description=f"Launch {app_name}",
                        ),
                        PlannedStep(
                            tool="focus_application",
                            args={"title": app_name},
                            description=f"Focus {app_name}",
                        ),
                        PlannedStep(
                            tool="type_text",
                            args={"text": literal_text, "target_app": canonical_app},
                            description=f"Write \"{literal_text}\" into {app_name}",
                            needs_generation=False,
                            target_app=canonical_app,
                        ),
                    ],
                )
                logger.info("FAST_ROUTE → action detected: %s (tools=['open_application', 'focus_application', 'type_text'])", plan.summary)
                return plan
            else:
                # Generative synthesis plan
                plan = AgentPlan(
                    is_agent_action=True,
                    summary=f"Open {app_name} and generate code/content",
                    raw_query=q,
                    steps=[
                        PlannedStep(
                            tool="open_application",
                            args={"application": canonical_app},
                            description=f"Launch {app_name}",
                        ),
                        PlannedStep(
                            tool="focus_application",
                            args={"title": app_name},
                            description=f"Focus {app_name}",
                        ),
                        PlannedStep(
                            tool="type_text",
                            args={"text": "", "target_app": canonical_app},
                            description=f"Generate and write content into {app_name}",
                            needs_generation=True,
                            generation_prompt=text_or_prompt,
                            target_app=canonical_app,
                        ),
                    ],
                )
                logger.info("FAST_ROUTE → action detected: %s (tools=['open_application', 'focus_application', 'type_text (generative)'])", plan.summary)
                return plan

        # -------------------------------------------------------------------------
        # 9. Type Text into Active Window (e.g. "type hello world", "write hello world")
        # -------------------------------------------------------------------------
        match_direct_type = re.match(
            r"^(?:type|write)\s+(?:the\s+text\s+|the\s+words?\s+)?(.+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_direct_type and not clean_q.lower().startswith(("write into", "write file", "write to")):
            text_val = match_direct_type.group(1).strip().strip('"\'')
            if text_val:
                return AgentPlan(
                    is_agent_action=True,
                    summary=f"Type \"{text_val}\"",
                    raw_query=q,
                    steps=[
                        PlannedStep(
                            tool="type_text",
                            args={"text": text_val},
                            description=f"Type \"{text_val}\" into active window",
                        )
                    ],
                )

        # -------------------------------------------------------------------------
        # 10. Close Application
        # -------------------------------------------------------------------------
        match_close_app = re.match(
            r"^(?:close|shut|exit|terminate|kill)\s+(?:the\s+)?(notepad|note\s+pad|calculator|calc|vscode|vs\s+code|code|visual\s+studio\s+code|chrome|google\s+chrome|edge|microsoft\s+edge|paint|mspaint|explorer|file\s+explorer|spotify|task\s+manager|taskmgr|terminal|powershell|cmd)(?:\s+(?:app|application|program|window))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_close_app:
            app_raw = match_close_app.group(1).strip().lower()
            config = ALLOWED_APPLICATIONS.get(app_raw)
            app_name = config["name"] if config else app_raw.capitalize()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Close {app_name}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="close_application",
                        args={"application": app_raw},
                        description=f"Close {app_name}",
                    )
                ],
            )

        # -------------------------------------------------------------------------
        # 11. Compound Command: Open Site / Engine and Search Query
        # e.g., "open youtube and search roblox", "open chrome and search React tutorials"
        # -------------------------------------------------------------------------
        match_site_and_search = re.match(
            r"^(?:open|launch|start|go\s+to|visit)\s+(?:the\s+)?([a-zA-Z0-9_\.\s]+?)\s+(?:and|then|to)\s+(?:search|look\s+for|find|query)\s+(?:for\s+)?(.+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_site_and_search:
            raw_engine = match_site_and_search.group(1).strip().lower()
            search_term = match_site_and_search.group(2).strip().strip('"\'')

            engine_key = raw_engine
            if engine_key in ["chrome", "google chrome", "browser", "default browser", "web"]:
                engine_key = "google"

            engine_title = ENGINE_DISPLAY_NAMES.get(raw_engine, ENGINE_DISPLAY_NAMES.get(engine_key, raw_engine.capitalize()))
            plan = AgentPlan(
                is_agent_action=True,
                summary=f"Search '{search_term}' on {engine_title}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="browser_search",
                        args={"query": search_term, "engine": engine_key},
                        description=f"Open {engine_title} and search '{search_term}'",
                    )
                ],
            )
            logger.info("FAST_ROUTE → action detected: %s (tools=['browser_search'])", plan.summary)
            return plan

        # -------------------------------------------------------------------------
        # 12. Direct Search Command
        # e.g., "search the web for the best React tutorials", "search YouTube for Roblox"
        # -------------------------------------------------------------------------
        match_search_platform = re.match(
            r"^search\s+([a-zA-Z0-9_\.\s]+?)\s+for\s+(.+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_search_platform:
            raw_engine = match_search_platform.group(1).strip().lower()
            search_term = match_search_platform.group(2).strip().strip('"\'')
            engine_key = raw_engine
            if engine_key in ["chrome", "google chrome", "browser", "default browser", "web", "internet", "the web", "the internet"]:
                engine_key = "google"
            engine_title = ENGINE_DISPLAY_NAMES.get(raw_engine, ENGINE_DISPLAY_NAMES.get(engine_key, raw_engine.capitalize()))
            return AgentPlan(
                is_agent_action=True,
                summary=f"Search '{search_term}' on {engine_title}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="browser_search",
                        args={"query": search_term, "engine": engine_key},
                        description=f"Search '{search_term}' on {engine_title}",
                    )
                ],
            )

        match_direct_search = re.match(
            r"^(?:search|look\s+up|google)\s+(.+?)(?:\s+(?:on|in)\s+([a-zA-Z0-9_\.\s]+))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_direct_search:
            search_term = match_direct_search.group(1).strip().strip('"\'')
            raw_engine = (match_direct_search.group(2) or "google").strip().lower()

            if search_term.lower().startswith("the web for "):
                search_term = search_term[12:].strip()
            elif search_term.lower().startswith("the web "):
                search_term = search_term[8:].strip()
            elif search_term.lower().startswith("the internet for "):
                search_term = search_term[17:].strip()
            elif search_term.lower().startswith("the internet "):
                search_term = search_term[13:].strip()

            engine_key = raw_engine
            if engine_key in ["chrome", "google chrome", "browser", "default browser", "web"]:
                engine_key = "google"

            engine_title = ENGINE_DISPLAY_NAMES.get(raw_engine, ENGINE_DISPLAY_NAMES.get(engine_key, raw_engine.capitalize()))
            plan = AgentPlan(
                is_agent_action=True,
                summary=f"Search '{search_term}' on {engine_title}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="browser_search",
                        args={"query": search_term, "engine": engine_key},
                        description=f"Search '{search_term}' on {engine_title}",
                    )
                ],
            )
            logger.info("FAST_ROUTE → action detected: %s (tools=['browser_search'])", plan.summary)
            return plan

        # -------------------------------------------------------------------------
        # 13. Open Desktop Application
        # -------------------------------------------------------------------------
        match_open_app = re.match(
            r"^(?:open|launch|start|run)\s+(?:the\s+)?(notepad|note\s+pad|text\s+editor|calculator|calc|windows\s+calculator|vscode|vs\s+code|code|visual\s+studio\s+code|visual\s+studio|paint|mspaint|explorer|file\s+explorer|files|windows\s+explorer|task\s+manager|taskmgr|cmd|command\s+prompt|terminal|windows\s+terminal|wt|powershell|chrome|google\s+chrome|edge|microsoft\s+edge|spotify|settings|windows\s+settings|control\s+panel|snipping\s+tool)(?:\s+(?:app|application|program|window))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_open_app:
            app_raw = match_open_app.group(1).strip().lower()
            config = ALLOWED_APPLICATIONS.get(app_raw)
            app_display = config["name"] if config else app_raw.capitalize()

            plan = AgentPlan(
                is_agent_action=True,
                summary=f"Open {app_display}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="open_application",
                        args={"application": app_raw},
                        description=f"Launch {app_display}",
                    )
                ],
            )
            logger.info("FAST_ROUTE → action detected: %s (tools=['open_application'])", plan.summary)
            return plan

        # -------------------------------------------------------------------------
        # 14. Open Folder / Create Folder
        # -------------------------------------------------------------------------
        match_open_folder = re.match(
            r"^(?:open|launch|show)\s+(?:my\s+)?(?:the\s+)?(downloads|download|documents|document|desktop|pictures|photos|images|videos|movies|music|home)(?:\s+folder|\s+directory)?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_open_folder:
            folder_name = match_open_folder.group(1).strip().lower()
            plan = AgentPlan(
                is_agent_action=True,
                summary=f"Open {folder_name.capitalize()} Folder",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="open_folder",
                        args={"folder_name_or_path": folder_name},
                        description=f"Open {folder_name.capitalize()} in File Explorer",
                    )
                ],
            )
            logger.info("FAST_ROUTE → action detected: %s (tools=['open_folder'])", plan.summary)
            return plan

        match_create_folder = re.match(
            r"^(?:create|make)\s+(?:a\s+)?(?:new\s+)?folder\s+(?:called|named)?\s*([^\s:]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_create_folder:
            folder_name = match_create_folder.group(1).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Create folder '{folder_name}'",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="create_folder",
                        args={"folder_path": folder_name},
                        description=f"Create folder '{folder_name}'",
                    )
                ],
            )

        # -------------------------------------------------------------------------
        # 15. Create File, Write File, Append File, Read File
        # -------------------------------------------------------------------------
        match_write_into = re.match(
            r"^(?:write|put|save)\s+(.+?)\s+(?:in|into)\s+([^\s:]+\.[a-zA-Z0-9]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_write_into:
            content = match_write_into.group(1).strip().strip('"\'')
            filename = match_write_into.group(2).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Write into '{filename}'",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="write_file",
                        args={"path": filename, "content": content, "overwrite": True},
                        description=f"Write content into '{filename}'",
                    )
                ],
            )

        match_create_file = re.match(
            r"^(?:create|make)\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?file\s+(?:called|named)?\s*([^\s:]+)(?:\s+with\s+(?:content|text)\s*[:\s]*(.+))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_create_file:
            filename = match_create_file.group(1).strip()
            content = match_create_file.group(2) or ""
            return AgentPlan(
                is_agent_action=True,
                summary=f"Create file '{filename}'",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="create_file",
                        args={"path": filename, "content": content.strip().strip('"\'')},
                        description=f"Create file '{filename}'",
                    )
                ],
            )

        match_read_file = re.match(
            r"^(?:read|display|view|show)\s+(?:the\s+)?(?:content\s+of\s+)?(?:file\s+)?([^\s]+\.[a-zA-Z0-9]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_read_file:
            filename = match_read_file.group(1).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Read file '{filename}'",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="read_file",
                        args={"path": filename},
                        description=f"Read contents of '{filename}'",
                    )
                ],
            )

        # -------------------------------------------------------------------------
        # 16. Rename, Move, Copy, Delete File / Folder (With Risk Level DANGEROUS)
        # -------------------------------------------------------------------------
        match_rename = re.match(
            r"^rename\s+(?:file\s+|folder\s+)?([^\s]+)\s+to\s+([^\s]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_rename:
            src = match_rename.group(1).strip()
            dst = match_rename.group(2).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Rename '{src}' to '{dst}'",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="rename_file",
                        args={"source": src, "new_name": dst},
                        description=f"Rename '{src}' to '{dst}'",
                    )
                ],
            )

        match_move = re.match(
            r"^move\s+(?:file\s+)?([^\s]+)\s+(?:in|into|to)\s+(?:my\s+)?([a-zA-Z0-9_\.\s\\\/]+?)(?:\s+folder)?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_move:
            src = match_move.group(1).strip()
            dst = match_move.group(2).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Move '{src}' to {dst}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="move_file",
                        args={"source": src, "destination": dst},
                        description=f"Move '{src}' to '{dst}'",
                    )
                ],
            )

        match_copy = re.match(
            r"^copy\s+(?:file\s+)?([^\s]+)\s+(?:in|into|to)\s+(?:my\s+)?([a-zA-Z0-9_\.\s\\\/]+?)(?:\s+folder)?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_copy:
            src = match_copy.group(1).strip()
            dst = match_copy.group(2).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Copy '{src}' to {dst}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="copy_file",
                        args={"source": src, "destination": dst},
                        description=f"Copy '{src}' to '{dst}'",
                    )
                ],
            )

        match_delete_file = re.match(
            r"^delete\s+(?:file\s+)?([^\s]+\.[a-zA-Z0-9]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_delete_file:
            filename = match_delete_file.group(1).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Delete file '{filename}'",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="delete_file",
                        args={"path": filename, "confirmed": False},
                        description=f"Delete file '{filename}' (requires confirmation)",
                    )
                ],
            )

        match_delete_folder = re.match(
            r"^delete\s+folder\s+([^\s]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_delete_folder:
            folder_name = match_delete_folder.group(1).strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Delete folder '{folder_name}'",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="delete_folder",
                        args={"folder_path": folder_name, "confirmed": False},
                        description=f"Delete folder '{folder_name}' (requires confirmation)",
                    )
                ],
            )

        # -------------------------------------------------------------------------
        # 17. Find / Search Files
        # -------------------------------------------------------------------------
        match_find_ext = re.match(
            r"^find\s+(?:all\s+)?([a-zA-Z0-9]+)\s+files?(?:\s+in\s+([a-zA-Z0-9_\s]+))?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_find_ext:
            ext = match_find_ext.group(1).strip()
            folder = (match_find_ext.group(2) or "").strip()
            return AgentPlan(
                is_agent_action=True,
                summary=f"Find all {ext.upper()} files" + (f" in {folder.capitalize()}" if folder else ""),
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="find_files",
                        args={"extension": ext, "folder": folder if folder else None},
                        description=f"Find all .{ext} files",
                    )
                ],
            )

        match_find_file = re.match(
            r"^find\s+(?:my\s+)?(?:file\s+)?([^\s:]+?)(?:\s+file)?$",
            clean_q,
            re.IGNORECASE,
        )
        if match_find_file:
            query_term = match_find_file.group(1).strip()
            if query_term.lower() not in ["it", "that", "this", "them", "out", "more"]:
                return AgentPlan(
                    is_agent_action=True,
                    summary=f"Find file '{query_term}'",
                    raw_query=q,
                    steps=[
                        PlannedStep(
                            tool="find_files",
                            args={"query": query_term},
                            description=f"Search for '{query_term}' across user folders",
                        )
                    ],
                )

        # -------------------------------------------------------------------------
        # 18. Open Website / URL
        # e.g., "open youtube", "take me to github", "open facebook", "visit reddit"
        # -------------------------------------------------------------------------
        match_open_site = re.match(
            r"^(?:open|launch|start|go\s+to|visit|navigate\s+to|take\s+me\s+to)\s+(?:the\s+)?(?:website|site|url|link|page)?\s*[:\s]*([a-zA-Z0-9_\.\-\/:]+)$",
            clean_q,
            re.IGNORECASE,
        )
        if match_open_site:
            target_raw = match_open_site.group(1).strip()
            target_lower = target_raw.lower()

            if target_lower in ALLOWED_APPLICATIONS:
                display_app = ALLOWED_APPLICATIONS[target_lower]["name"]
                return AgentPlan(
                    is_agent_action=True,
                    summary=f"Open {display_app}",
                    raw_query=q,
                    steps=[
                        PlannedStep(
                            tool="open_application",
                            args={"application": target_lower},
                            description=f"Launch {display_app}",
                        )
                    ],
                )

            if target_lower in ["downloads", "download", "documents", "document", "desktop", "pictures", "photos", "videos", "music"]:
                return AgentPlan(
                    is_agent_action=True,
                    summary=f"Open {target_lower.capitalize()} Folder",
                    raw_query=q,
                    steps=[
                        PlannedStep(
                            tool="open_folder",
                            args={"folder_name_or_path": target_lower},
                            description=f"Open {target_lower.capitalize()} in File Explorer",
                        )
                    ],
                )

            target_url = resolve_site_url(target_raw)
            site_name = target_lower
            if site_name in ENGINE_DISPLAY_NAMES:
                site_name = ENGINE_DISPLAY_NAMES[site_name]
            elif "." in target_raw:
                site_name = target_raw.replace("https://", "").replace("http://", "").replace("www.", "").split(".")[0].capitalize()
            else:
                site_name = target_raw.capitalize()

            return AgentPlan(
                is_agent_action=True,
                summary=f"Open {site_name}",
                raw_query=q,
                steps=[
                    PlannedStep(
                        tool="open_url",
                        args={"url": target_url},
                        description=f"Open {site_name} in default browser",
                    )
                ],
            )

        return None

    def execute_fast_stream(
        self,
        plan: AgentPlan,
        controller: Any,
        user_id: Optional[int] = None,
        text_generator_fn: Optional[Callable[[str], str]] = None,
    ) -> Generator[str, None, Dict[str, Any]]:
        """Executes a deterministic fast command plan and yields streaming status tokens and action card."""
        start_time = time.time()
        yield "SIMBA_STATUS: INITIALIZING...\n\n"

        if plan.chat_response:
            yield "SIMBA_STATUS: EXECUTING...\n\n"
            yield plan.chat_response
            yield "\n\nSIMBA_STATUS: SUCCESS\n\n"
            return {
                "plan": plan,
                "results": [],
                "card_html": "",
                "natural_reply": plan.chat_response,
                "full_response": plan.chat_response,
                "latency": round(time.time() - start_time, 3),
            }

        step_results: List[Tuple[PlannedStep, ExecutionResult]] = []

        for i, step in enumerate(plan.steps):
            yield f"SIMBA_STATUS: EXECUTING {step.tool.upper()}...\n\n"
            logger.info("FAST_EXECUTE → action executed: %s args=%s user_id=%s", step.tool, step.args, user_id)

            if step.needs_generation and step.generation_prompt:
                yield "SIMBA_STATUS: SYNTHESIZING CODE/CONTENT...\n\n"
                gen_content = ""
                if text_generator_fn:
                    try:
                        gen_content = text_generator_fn(step.generation_prompt)
                    except Exception as e:
                        logger.warning("Generation error in fast router: %s", e)
                        gen_content = f"# Generated content for: {step.generation_prompt}\n"
                else:
                    gen_content = f"# Generated content for: {step.generation_prompt}\n"
                step.args["text"] = gen_content

            res = self.executor.execute_tool(step.tool, step.args, user_id=user_id)
            step_results.append((step, res))

            if not res.success or res.requires_confirmation:
                if not res.success:
                    logger.warning("FAST_FAILED → action failed: %s (error=%s)", step.tool, res.error)
                break

        elapsed = round(time.time() - start_time, 3)
        has_pending = any(r.requires_confirmation for _, r in step_results)
        all_success = len(step_results) > 0 and all(r.success for _, r in step_results)
        has_offline = any(r.details.get("agent_offline") for _, r in step_results)

        if all_success:
            logger.info("FAST_SUCCESS → action completed in %.3fs: %s", elapsed, plan.summary)
        elif has_offline:
            logger.warning("FAST_OFFLINE → Desktop Agent offline for user_id=%s", user_id)
        elif has_pending:
            logger.info("FAST_PENDING → action requires confirmation: %s", plan.summary)
        else:
            logger.warning("FAST_FAILED → action execution incomplete after %.3fs", elapsed)

        card_html = controller.generate_action_card_html(plan, step_results)
        natural_reply = controller._synthesize_natural_reply(plan, step_results)

        full_output = f"{card_html}\n\n{natural_reply}"
        yield full_output

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
            "latency": elapsed,
        }


default_fast_router = FastCommandRouter()
