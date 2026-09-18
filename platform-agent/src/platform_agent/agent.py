import json
from typing import Any

from platform_agent.contracts import (
    Confidence,
    Evidence,
    IncidentReport,
    ToolResult,
)
from platform_agent.tool_registry import execute_tool


DEFAULT_MAX_TOOL_CALLS = 4


def decide_next_action(
    module: str,
    trace: list[ToolResult],
) -> tuple[str, dict[str, Any]] | None:
    """Choose the next action using deterministic rules."""

    if trace and not trace[-1].success:
        return None

    completed_tools = {
        result.tool
        for result in trace
    }

    if "list_terraform_files" not in completed_tools:
        return (
            "list_terraform_files",
            {"path": module},
        )

    if "check_module_files" not in completed_tools:
        return (
            "check_module_files",
            {"module": module},
        )

    return None


def evidence_from_trace(
    trace: list[ToolResult],
) -> list[Evidence]:
    """Convert successful tool results into report evidence."""

    return [
        Evidence(
            source=result.tool,
            observation=json.dumps(
                result.data,
                sort_keys=True,
            ),
        )
        for result in trace
        if result.success
    ]


def create_report(
    module: str,
    trace: list[ToolResult],
    limit_reached: bool,
) -> IncidentReport:
    """Create the final report from collected evidence."""

    errors = [
        result.error
        for result in trace
        if result.error is not None
    ]

    evidence = evidence_from_trace(trace)

    if errors:
        return IncidentReport(
            summary=(
                f"Investigation of {module} stopped because "
                "a tool failed."
            ),
            probable_cause=(
                "The agent could not determine whether the "
                "Terraform module is complete."
            ),
            evidence=evidence,
            confidence=Confidence.LOW,
            recommended_action=(
                "Review the reported tool error, correct the "
                "input and run the investigation again."
            ),
            approval_required=False,
            tool_trace=trace,
            errors=errors,
        )

    module_check = next(
        (
            result
            for result in trace
            if result.tool == "check_module_files"
        ),
        None,
    )

    if module_check is None:
        report_errors = []

        if limit_reached:
            report_errors.append(
                "Maximum tool-call limit reached before "
                "the investigation completed."
            )
        else:
            report_errors.append(
                "The module inspection did not complete."
            )

        return IncidentReport(
            summary=(
                f"Investigation of {module} is incomplete."
            ),
            probable_cause=(
                "Insufficient evidence was collected."
            ),
            evidence=evidence,
            confidence=Confidence.LOW,
            recommended_action=(
                "Review the tool-call limit and retry."
            ),
            approval_required=False,
            tool_trace=trace,
            errors=report_errors,
        )

    missing = module_check.data["missing"]
    complete = module_check.data["complete"]

    if complete:
        return IncidentReport(
            summary=(
                f"Terraform module {module} contains all "
                "expected standard files."
            ),
            probable_cause=(
                "No missing standard Terraform module files "
                "were detected."
            ),
            evidence=evidence,
            confidence=Confidence.HIGH,
            recommended_action=(
                "Continue with Terraform formatting and "
                "validation checks."
            ),
            approval_required=False,
            tool_trace=trace,
            errors=[],
        )

    missing_text = ", ".join(missing)

    return IncidentReport(
        summary=(
            f"Terraform module {module} is missing one or "
            "more expected files."
        ),
        probable_cause=(
            f"Missing standard module files: {missing_text}."
        ),
        evidence=evidence,
        confidence=Confidence.HIGH,
        recommended_action=(
            f"Review and create the required files: "
            f"{missing_text}."
        ),
        approval_required=True,
        tool_trace=trace,
        errors=[],
    )


def run_terraform_module_investigation(
    module: str,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> IncidentReport:
    """Run a bounded Terraform module investigation."""

    if max_tool_calls < 1:
        raise ValueError(
            "max_tool_calls must be at least 1."
        )

    trace: list[ToolResult] = []

    while len(trace) < max_tool_calls:
        action = decide_next_action(
            module=module,
            trace=trace,
        )

        if action is None:
            break

        tool_name, arguments = action
        result = execute_tool(
            tool_name,
            arguments,
        )

        trace.append(result)

        if not result.success:
            break

    pending_action = decide_next_action(
        module=module,
        trace=trace,
    )

    limit_reached = (
        len(trace) >= max_tool_calls
        and pending_action is not None
    )

    return create_report(
        module=module,
        trace=trace,
        limit_reached=limit_reached,
    )
