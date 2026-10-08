from types import SimpleNamespace

import pytest

from platform_agent import llm
from platform_agent.contracts import Confidence, ToolResult


def sample_trace() -> list[ToolResult]:
    return [
        ToolResult(
            tool="get_deployment",
            arguments={
                "name": "aws-platform-app",
                "namespace": "dev",
            },
            success=True,
            data={
                "desired_replicas": 2,
                "ready_replicas": 1,
                "unavailable_replicas": 1,
            },
        ),
        ToolResult(
            tool="get_pod_logs",
            arguments={
                "pod": "aws-platform-app-abc123",
                "namespace": "dev",
            },
            success=True,
            data={
                "logs": [
                    "Database connection timed out.",
                ]
            },
        ),
    ]


def test_build_diagnosis_prompt_contains_evidence() -> None:
    prompt = llm.build_diagnosis_prompt(sample_trace())

    assert "get_deployment" in prompt
    assert "get_pod_logs" in prompt
    assert "Database connection timed out." in prompt
    assert "Do not invent evidence." in prompt


def test_diagnose_tool_trace_returns_valid_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(
        message=SimpleNamespace(
            content=(
                "{"
                '"summary":"The deployment is degraded.",'
                '"probable_cause":"A database connection problem is affecting one replica.",'
                '"confidence":"high",'
                '"recommended_action":"Verify database connectivity before changing the workload."'
                "}"
            )
        )
    )

    def fake_chat(**kwargs):
        return response

    monkeypatch.setattr(
        llm.ollama,
        "chat",
        fake_chat,
    )

    diagnosis = llm.diagnose_tool_trace(sample_trace())

    assert diagnosis.summary == "The deployment is degraded."
    assert diagnosis.confidence == Confidence.HIGH
    assert "database" in diagnosis.probable_cause.lower()


def test_diagnose_tool_trace_rejects_invalid_model_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(
        message=SimpleNamespace(
            content='{"summary":"Incomplete response"}'
        )
    )

    monkeypatch.setattr(
        llm.ollama,
        "chat",
        lambda **kwargs: response,
    )

    with pytest.raises(
        llm.LLMError,
        match="schema validation",
    ):
        llm.diagnose_tool_trace(sample_trace())


def test_diagnose_tool_trace_reports_ollama_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_chat(**kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(
        llm.ollama,
        "chat",
        failed_chat,
    )

    with pytest.raises(
        llm.LLMError,
        match="Ollama request failed",
    ):
        llm.diagnose_tool_trace(sample_trace())


def test_diagnose_tool_trace_rejects_empty_trace() -> None:
    with pytest.raises(
        ValueError,
        match="at least one tool result",
    ):
        llm.diagnose_tool_trace([])
def test_diagnose_tool_trace_rejects_state_changing_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(
        message=SimpleNamespace(
            content=(
                "{"
                '"summary":"The pod is unhealthy.",'
                '"probable_cause":"The container is repeatedly failing.",'
                '"confidence":"high",'
                '"recommended_action":"Run kubectl delete pod app-123."'
                "}"
            )
        )
    )

    monkeypatch.setattr(
        llm.ollama,
        "chat",
        lambda **kwargs: response,
    )

    with pytest.raises(
        llm.LLMError,
        match="unsafe recommendation",
    ):
        llm.diagnose_tool_trace(sample_trace())


def test_diagnose_tool_trace_rejects_unsupported_restart_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(
        message=SimpleNamespace(
            content=(
                "{"
                '"summary":"The pod is in CrashLoopBackOff.",'
                '"probable_cause":"The container is repeatedly exiting.",'
                '"confidence":"high",'
                '"recommended_action":"Consider increasing the restart limit for the Deployment."'
                "}"
            )
        )
    )

    monkeypatch.setattr(
        llm.ollama,
        "chat",
        lambda **kwargs: response,
    )

    with pytest.raises(
        llm.LLMError,
        match="unsafe recommendation",
    ):
        llm.diagnose_tool_trace(sample_trace())
