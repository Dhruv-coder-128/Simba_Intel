"""Hybrid Agent Planner for SIMBA_INTEL.
Accurately distinguishes between local desktop/browser execution actions vs code generation/questions,
with first-priority Ox Alpha planning for complex reasoning and tasks.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .tools.browser_tools import ENGINE_DISPLAY_NAMES, POPULAR_SITES, resolve_site_url
from .tools.desktop_tools import ALLOWED_APPLICATIONS
from .tools.registry import ToolRegistry, global_tool_registry

logger = logging.getLogger("simba_intel.agent.planner")


@dataclass
class PlannedStep:
    tool: str
    args: Dict[str, Any]
    description: str
    needs_generation: bool = False
    generation_prompt: Optional[str] = None
    target_app: Optional[str] = None


@dataclass
class AgentPlan:
    is_agent_action: bool
    summary: str
    steps: List[PlannedStep] = field(default_factory=list)
    raw_query: str = ""
    chat_response: Optional[str] = None
    error: Optional[str] = None
    raw_plan: Optional[Dict[str, Any]] = None


def is_coding_or_question_prompt(query: str) -> bool:
    """Checks if the user is asking to write code, explain concepts, or asking a conversational question
    rather than executing an immediate desktop action.
    """
    q = query.strip().lower()

    # If it's explicitly an open app and write command, it is an action
    if re.match(r"^(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?(?:notepad|vscode|vs\s+code|code|text\s+editor)\s+(?:and|then)\s+", q):
        return False

    # If it's a direct calculate command or system telemetry/active window/clipboard, it is an action
    if re.search(r"\b(?:cpu|ram|memory|system\s+info|telemetry|clipboard|active\s+window)\b", q):
        return False
    if re.match(r"^(?:calculate|compute|solve|eval)\s+", q) or re.match(r"^what\s+is\s+[0-9\.\+\-\*\/]", q):
        return False

    # 1. Code generation request markers (e.g., "write Python code to open Facebook")
    code_gen_patterns = [
        r"^(?:write|create|generate|provide|give\s+me|show\s+me|sample|example)\s+(?:a\s+)?(?:python|js|javascript|html|css|bash|powershell|c\+\+|java|rust|go|sql|node|script|code|snippet|program|function|class)",
        r"^(?:write|create|generate)\s+.*?\s+(?:code|script|program|function)",
        r"^how\s+(?:to|do\s+i|can\s+i)\s+(?:write|code|build|program|create|implement)",
        r"^how\s+(?:to|do\s+i|can\s+i)\s+(?:open|launch)\s+.*?\s+(?:in|using|with)\s+(?:python|javascript|js|code|script|powershell|cmd|terminal)",
        r"^(?:code|script)\s+(?:to|for|that)\s+",
    ]
    for pat in code_gen_patterns:
        if re.search(pat, q, re.IGNORECASE):
            return True

    # 2. Informational and chat questions (e.g., "what is facebook?", "explain VS Code", "what is 25 * 8?")
    question_patterns = [
        r"^(?:what|who|where|why|when|which)\s+(?:is|are|was|were|do|does|did)\b",
        r"^(?:explain|describe|tell\s+me\s+about|define)\b",
        r"^(?:is|are|can|could|should|would)\s+(?:facebook|youtube|google|github|reddit|instagram|gmail|vs\s+code|vscode|notepad|calculator)\b",
    ]
    for pat in question_patterns:
        if re.search(pat, q, re.IGNORECASE):
            return True

    return False


class AgentPlanner:
    """Plans desktop actions from user natural language input."""

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or global_tool_registry

    def fast_match_plan(self, query: str) -> Optional[AgentPlan]:
        """Tries to quickly match known high-frequency intent patterns with 0ms overhead."""
        q = (query or "").strip()
        if not q:
            return None

        # Guard: If user wants code generation or is asking a conversational question, skip action execution
        if is_coding_or_question_prompt(q):
            return AgentPlan(is_agent_action=False, summary="", raw_query=q)

        from .fast_router import default_fast_router
        return default_fast_router.detect_fast_command(q)

    def plan_with_ox_alpha(self, query: str, llm_fn: Callable[[str], str]) -> AgentPlan:
        """Uses Ox Alpha in 1 single model call to understand, classify, and plan the user's request.
        Returns a structured agent plan for automation tasks, or chat text for normal conversations.
        """
        schemas = self.registry.get_llm_schemas()
        tool_descriptions = "\n".join(f"- {s['name']}: {s['description']}" for s in schemas)

        planner_prompt = f"""You are the SIMBA_INTEL Desktop Agent Planner.
Analyze the user's input and determine whether it is a DESKTOP/BROWSER/FILESYSTEM AUTOMATION TASK (intent="desktop_automation") or a NORMAL CONVERSATION/QUESTION (intent="chat").

AVAILABLE LOCAL TOOLS:
{tool_descriptions}

RULES:
1. If the user asks an informational question, asks to explain a concept, or wants normal conversation (e.g. "Explain Java interfaces", "What is YouTube?", "How does React work?"):
Output strictly valid JSON:
{{"intent": "chat", "response": "<Your full, helpful answer>"}}

2. If the user commands one or more desktop/browser/file actions on their computer (e.g. "Open YouTube and search Roblox", "Open Notepad and write hello world", "Open VS Code and create calculator.py", "Switch to Notepad", "Minimize Notepad", "Maximize VS Code", "Restore Notepad", "Press Ctrl+S", "Scroll down", "Click the search box", "Calculate 25 * 8", "Open Downloads", "Rename calculator.py to calculator_old.py", "Delete test.txt"):
Output strictly valid JSON:
{{
  "intent": "desktop_automation",
  "summary": "Short concise title of the overall task",
  "actions": [
    {{"tool": "<tool_name>", "args": {{<arguments>}}, "description": "Action description"}}
  ]
}}

User Command: "{query}"
JSON Output:"""

        try:
            raw_output = llm_fn(planner_prompt)
            clean_json = (raw_output or "").strip()
            if clean_json.startswith("```"):
                lines = clean_json.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean_json = "\n".join(lines).strip()

            start_idx = clean_json.find("{")
            end_idx = clean_json.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                clean_json = clean_json[start_idx : end_idx + 1]

            data = json.loads(clean_json)
            intent = data.get("intent", "chat")

            if intent == "desktop_automation":
                summary = data.get("summary") or query
                actions = data.get("actions", [])
                steps = []
                for act in actions:
                    tool_name = act.get("tool") or act.get("name") or ""
                    # Normalize tool aliases
                    if tool_name in ["open_app", "launch_app"]:
                        tool_name = "open_application"
                    elif tool_name in ["search_web", "web_search"]:
                        tool_name = "browser_search"
                    elif tool_name in ["save_file"]:
                        tool_name = "write_file"
                    elif tool_name in ["close_app"]:
                        tool_name = "close_application"
                    elif tool_name in ["switch_app", "switch_window", "focus_app"]:
                        tool_name = "switch_to_application"
                    elif tool_name in ["minimize_app", "minimize_window", "min_app"]:
                        tool_name = "minimize_application"
                    elif tool_name in ["maximize_app", "maximize_window", "max_app"]:
                        tool_name = "maximize_application"
                    elif tool_name in ["restore_app", "restore_window"]:
                        tool_name = "restore_application"
                    elif tool_name in ["keyboard_shortcut", "shortcut"]:
                        tool_name = "hotkey"
                    elif tool_name in ["open_site"]:
                        tool_name = "open_url"

                    args = act.get("args") or act.get("arguments") or {}
                    if "target" in act:
                        if tool_name == "open_url" and "url" not in args:
                            args["url"] = act["target"]
                        elif tool_name == "open_application" and "application" not in args:
                            args["application"] = act["target"]
                        elif tool_name == "browser_search" and "query" not in args:
                            args["query"] = act["target"]

                    desc = act.get("description") or f"Execute {tool_name}"
                    steps.append(PlannedStep(tool=tool_name, args=args, description=desc))

                if steps:
                    return AgentPlan(
                        is_agent_action=True,
                        summary=summary,
                        steps=steps,
                        raw_query=query,
                        raw_plan=data,
                    )

            elif intent == "chat":
                return AgentPlan(
                    is_agent_action=False,
                    summary="",
                    raw_query=query,
                    chat_response=data.get("response", ""),
                    raw_plan=data,
                )

        except Exception as e:
            logger.warning("Ox Alpha planning failed: %s. Falling back to local fast matcher.", e)

        # Fallback to local fast matcher
        return self.fast_match_plan(query) or AgentPlan(is_agent_action=False, summary="", raw_query=query)

    def plan_query(self, query: str) -> AgentPlan:
        """Determines if the query is an executable agent action using the fast deterministic matcher."""
        fast_plan = self.fast_match_plan(query)
        if fast_plan:
            return fast_plan

        return AgentPlan(is_agent_action=False, summary="", raw_query=query)

    def plan(self, query: str, llm_fn: Optional[Callable[[str], str]] = None) -> AgentPlan:
        """Plans the query. Deterministic actions are resolved immediately with 0 LLM calls;
        complex queries fall back to Ox Alpha planning if an LLM function is provided."""
        fast_plan = self.fast_match_plan(query)
        if fast_plan and fast_plan.is_agent_action and len(fast_plan.steps) > 0:
            return fast_plan
        if llm_fn:
            return self.plan_with_ox_alpha(query, llm_fn)
        return fast_plan or AgentPlan(is_agent_action=False, summary="", raw_query=query)


default_planner = AgentPlanner()
