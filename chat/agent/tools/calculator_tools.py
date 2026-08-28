"""Safe mathematical evaluation tool for SIMBA_INTEL Agent.
Evaluates arithmetic expressions locally with 0 tokens and zero external LLM calls.
"""
import ast
import logging
import math
import operator
from typing import Any, Dict, Union

from .registry import ExecutionResult, Tool, ToolParameter, global_tool_registry

logger = logging.getLogger("simba_intel.agent.calculator")

# Supported safe operators
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Safe mathematical functions
SAFE_FUNCTIONS: Dict[str, Any] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "abs": abs,
    "round": round,
    "ceil": math.ceil,
    "floor": math.floor,
    "exp": math.exp,
    "factorial": math.factorial,
}

# Safe mathematical constants
SAFE_CONSTANTS: Dict[str, Union[int, float]] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}


def _eval_ast(node: ast.AST) -> Union[int, float]:
    """Recursively evaluates an AST node containing only safe mathematical operations."""
    if isinstance(node, ast.Constant):  # Python 3.8+ numbers/constants
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")

    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type in SAFE_OPERATORS:
            operand = _eval_ast(node.operand)
            return SAFE_OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type.__name__}")

    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type in SAFE_OPERATORS:
            left = _eval_ast(node.left)
            right = _eval_ast(node.right)
            if op_type == ast.Div and right == 0:
                raise ZeroDivisionError("Division by zero")
            if op_type == ast.FloorDiv and right == 0:
                raise ZeroDivisionError("Integer division by zero")
            if op_type == ast.Mod and right == 0:
                raise ZeroDivisionError("Modulo by zero")
            if op_type == ast.Pow and (abs(left) > 1000 or abs(right) > 1000):
                raise ValueError("Exponentiation values too large")
            return SAFE_OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported binary operator: {op_type.__name__}")

    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id.lower() in SAFE_FUNCTIONS:
            func = SAFE_FUNCTIONS[node.func.id.lower()]
            args = [_eval_ast(arg) for arg in node.args]
            return func(*args)
        raise ValueError("Unsupported function call")

    elif isinstance(node, ast.Name):
        var_name = node.id.lower()
        if var_name in SAFE_CONSTANTS:
            return SAFE_CONSTANTS[var_name]
        raise ValueError(f"Undefined variable/constant: '{node.id}'")

    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def evaluate_expression(expression: str) -> ExecutionResult:
    """Safely evaluates a mathematical arithmetic expression without using unsafe eval()."""
    clean_expr = expression.strip()
    if not clean_expr:
        return ExecutionResult(success=False, error="Expression cannot be empty", action_type="calculator")

    # Replace common notation
    expr_normalized = (
        clean_expr.replace("×", "*")
        .replace("÷", "/")
        .replace("^", "**")
        .replace("x", "*")
    )

    try:
        parsed = ast.parse(expr_normalized, mode="eval")
        result = _eval_ast(parsed.body)

        # Format result cleanly (strip trailing .0 if integer)
        if isinstance(result, float) and result.is_integer():
            formatted_result = str(int(result))
        elif isinstance(result, float):
            formatted_result = f"{result:.6g}"
        else:
            formatted_result = str(result)

        return ExecutionResult(
            success=True,
            output=f"{clean_expr} = {formatted_result}",
            details={"expression": clean_expr, "result": formatted_result, "numeric_value": result},
            action_type="calculator",
        )
    except ZeroDivisionError:
        return ExecutionResult(
            success=False,
            error="Error: Division by zero",
            details={"expression": clean_expr},
            action_type="calculator",
        )
    except Exception as e:
        logger.debug("Calculator evaluation failed for '%s': %s", clean_expr, e)
        return ExecutionResult(
            success=False,
            error=f"Could not calculate '{clean_expr}': {str(e)}",
            details={"expression": clean_expr},
            action_type="calculator",
        )


# Register calculator tool
global_tool_registry.register(
    Tool(
        name="calculator",
        description="Safely computes mathematical and arithmetic expressions (e.g. '25 * 8', '125 / 5', 'sqrt(144)', '2 + 2').",
        parameters=[
            ToolParameter(
                name="expression",
                type="string",
                description="The arithmetic or mathematical expression to evaluate.",
                required=True,
            )
        ],
        func=evaluate_expression,
        action_type="calculator",
    )
)
