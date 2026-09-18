from collections.abc import Callable
from typing import Any

from platform_agent.contracts import ToolResult
from platform_agent.tools.terraform import (
    check_module_files,
    list_terraform_files,
)


ToolFunction = Callable[..., dict[str, Any]]


TOOLS: dict[str, ToolFunction] = {
    "list_terraform_files": list_terraform_files,
    "check_module_files": check_module_files,
}


def execute_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
) -> ToolResult:
    """Validate and execute an allowlisted tool."""

    received_arguments = (
        arguments
        if isinstance(arguments, dict)
        else {}
    )

    if name not in TOOLS:
        return ToolResult(
            tool=name or "unknown",
            arguments=received_arguments,
            success=False,
            error=f"Tool '{name}' is not allowed.",
        )

    if arguments is None:
        arguments = {}

    if not isinstance(arguments, dict):
        return ToolResult(
            tool=name,
            arguments={},
            success=False,
            error="Tool arguments must be a dictionary.",
        )

    try:
        data = TOOLS[name](**arguments)

        return ToolResult(
            tool=name,
            arguments=arguments,
            success=True,
            data=data,
        )

    except (TypeError, ValueError, OSError) as error:
        return ToolResult(
            tool=name,
            arguments=arguments,
            success=False,
            error=str(error),
        )

    except Exception:
        return ToolResult(
            tool=name,
            arguments=arguments,
            success=False,
            error="The tool failed with an unexpected internal error.",
        )
