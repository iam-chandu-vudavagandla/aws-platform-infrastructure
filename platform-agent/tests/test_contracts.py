import pytest
from platform_agent.contracts import (
    Confidence,
    Evidence,
    IncidentReport,
    ToolResult,
)
from pydantic import ValidationError


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


def test_llm_diagnosis_serializes_to_json() -> None:
    from platform_agent.contracts import LLMDiagnosis

    diagnosis = LLMDiagnosis(
        summary="The Kubernetes deployment is degraded.",
        probable_cause=(
            "One replica is unavailable and the affected pod "
            "is failing readiness checks."
        ),
        confidence=Confidence.HIGH,
        recommended_action=(
            "Review the affected pod logs and dependency connectivity."
        ),
    )

    payload = diagnosis.model_dump(mode="json")

    assert payload["summary"] == "The Kubernetes deployment is degraded."
    assert payload["confidence"] == "high"
    assert "readiness" in payload["probable_cause"]


def test_llm_diagnosis_rejects_unexpected_fields() -> None:
    from platform_agent.contracts import LLMDiagnosis

    with pytest.raises(ValidationError):
        LLMDiagnosis(
            summary="Deployment is unhealthy.",
            probable_cause="Readiness checks are failing.",
            confidence=Confidence.HIGH,
            recommended_action="Review the workload.",
            shell_command="kubectl delete pod app-123",
        )
