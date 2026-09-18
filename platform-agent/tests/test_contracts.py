import pytest
from pydantic import ValidationError

from platform_agent.contracts import (
    Confidence,
    Evidence,
    IncidentReport,
    ToolResult,
)


def test_successful_tool_result() -> None:
    result = ToolResult(
        tool="terraform_validate",
        success=True,
        data={"valid": True},
    )

    assert result.tool == "terraform_validate"
    assert result.success is True
    assert result.error is None


def test_failed_tool_requires_error() -> None:
    with pytest.raises(
        ValidationError,
        match="failed tool result must include an error",
    ):
        ToolResult(
            tool="get_pods",
            success=False,
        )


def test_incident_report_serializes_to_json() -> None:
    tool_result = ToolResult(
        tool="get_pods",
        success=True,
        data={"pods": 2},
    )

    report = IncidentReport(
        summary="The application has two running pods.",
        probable_cause="No active pod failure was detected.",
        evidence=[
            Evidence(
                source="get_pods",
                observation="Two out of two pods are running.",
            )
        ],
        confidence=Confidence.HIGH,
        recommended_action="Continue monitoring the deployment.",
        approval_required=False,
        tool_trace=[tool_result],
    )

    payload = report.model_dump(mode="json")

    assert payload["confidence"] == "high"
    assert payload["approval_required"] is False
    assert payload["tool_trace"][0]["tool"] == "get_pods"
