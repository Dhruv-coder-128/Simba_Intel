"""Tool registry, risk classification, and execution result structures for SIMBA_INTEL Agent.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class RiskLevel(str, Enum):
    SAFE = "SAFE"            # Auto-executed
    CAUTION = "CAUTION"      # Briefly explained & confirmed
    DANGEROUS = "DANGEROUS"  # Strictly requires explicit user confirmation


@dataclass
class ToolParameter:
    name: str
    type: str  # "string", "integer", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class ExecutionResult:
    success: bool
    tool: str = ""
    action: str = ""
    target: Optional[str] = None
    output: str = ""
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = RiskLevel.SAFE.value
    is_sensitive: bool = False
    action_type: str = "general"
    requires_confirmation: bool = False
    confirmation_prompt: Optional[str] = None
    sensitive_action_data: Optional[Dict[str, Any]] = None
    duration_ms: Optional[float] = None
    command_id: Optional[str] = None
    execution_target: str = "desktop"  # "cloud" or "desktop"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "action": self.action,
            "target": self.target,
            "output": self.output,
            "error": self.error,
            "details": self.details,
            "risk_level": self.risk_level,
            "is_sensitive": self.is_sensitive,
            "action_type": self.action_type,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_prompt": self.confirmation_prompt,
            "sensitive_action_data": self.sensitive_action_data,
            "duration_ms": self.duration_ms,
            "command_id": self.command_id,
            "execution_target": self.execution_target,
        }


@dataclass
class Tool:
    name: str
    description: str
    parameters: List[ToolParameter]
    func: Callable[..., ExecutionResult]
    risk_level: str = RiskLevel.SAFE.value
    is_sensitive: bool = False
    action_type: str = "general"
    execution_target: str = "desktop"  # "cloud" or "desktop"
    timeout_seconds: float = 10.0
    verify_func: Optional[Callable[..., bool]] = None
    display_name: str = ""
    icon: str = "fa-terminal"
    category: str = "system"  # "computer", "web", "files", "development", "system"
    example_prompt: str = ""
    requires_confirmation: bool = False

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()
        if not self.requires_confirmation and self.risk_level == RiskLevel.DANGEROUS.value:
            self.requires_confirmation = True

    def validate_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Validates arguments against parameter definitions and applies defaults."""
        validated = {}
        for param in self.parameters:
            if param.name in args:
                val = args[param.name]
                if param.enum and val not in param.enum:
                    raise ValueError(
                        f"Invalid value '{val}' for parameter '{param.name}'. "
                        f"Allowed values: {', '.join(param.enum)}"
                    )
                validated[param.name] = val
            elif param.required:
                if param.default is not None:
                    validated[param.name] = param.default
                else:
                    raise ValueError(f"Missing required parameter '{param.name}' for tool '{self.name}'.")
            else:
                validated[param.name] = param.default
        return validated

    def execute(self, **kwargs) -> ExecutionResult:
        validated = self.validate_args(kwargs)
        result = self.func(**validated)
        if not isinstance(result, ExecutionResult):
            return ExecutionResult(
                success=True,
                tool=self.name,
                action=self.name,
                output=str(result),
                action_type=self.action_type,
                risk_level=self.risk_level,
                execution_target=self.execution_target,
            )
        if not result.tool:
            result.tool = self.name
        if not result.action:
            result.action = self.name
        if not result.action_type:
            result.action_type = self.action_type
        if not getattr(result, 'execution_target', None):
            result.execution_target = self.execution_target
        if result.risk_level == RiskLevel.SAFE.value and self.risk_level != RiskLevel.SAFE.value:
            result.risk_level = self.risk_level
        return result


class ToolRegistry:
    """Central registry of all allowed agent tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def list_ui_tools(self, desktop_online: bool = False) -> List[Dict[str, Any]]:
        """Returns clean metadata for UI display / Action Discovery."""
        ui_tools = []
        for tool in self._tools.values():
            ui_tools.append({
                "id": tool.name,
                "display_name": tool.display_name or tool.name.replace("_", " ").title(),
                "description": tool.description,
                "icon": tool.icon,
                "category": tool.category,
                "execution_target": tool.execution_target,
                "risk_level": tool.risk_level,
                "requires_confirmation": tool.requires_confirmation or tool.risk_level == RiskLevel.DANGEROUS.value,
                "example_prompt": tool.example_prompt,
                "available": True if tool.execution_target == "cloud" else desktop_online,
            })
        return ui_tools

    def get_llm_schemas(self) -> List[Dict[str, Any]]:
        """Returns JSON schema representation of tools for LLM prompts."""
        schemas = []
        for tool in self._tools.values():
            properties = {}
            required = []
            for param in tool.parameters:
                prop = {
                    "type": param.type,
                    "description": param.description,
                }
                if param.enum:
                    prop["enum"] = param.enum
                properties[param.name] = prop
                if param.required and param.default is None:
                    required.append(param.name)

            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
                "risk_level": tool.risk_level,
                "is_sensitive": tool.is_sensitive,
                "execution_target": tool.execution_target,
            })
        return schemas


# Global registry instance
global_tool_registry = ToolRegistry()

