from typing import Any

import pytest
from platform_agent import kubernetes_investigation
from platform_agent.contracts import Confidence, ToolResult


def tool_result(
    tool: str,
    data: dict[str, Any],
) -> ToolResult:
    return ToolResult(
        tool=tool,
        arguments={},
        success=True,
        data=data,
    )


@pytest.fixture
def healthy_trace() -> list[ToolResult]:
    return [
        tool_result(
            "get_deployment",
            {
                "selector": "app=aws-platform-app",
                "generation": 2,
                "observed_generation": 2,
                "desired_replicas": 2,
                "ready_replicas": 2,
                "unavailable_replicas": 0,
            },
        ),
        tool_result(
            "get_pods",
            {
                "pods": [
                    {
                        "name": "app-123",
                        "phase": "Running",
                        "ready_containers": 1,
                        "total_containers": 1,
                        "restarts": 0,
                    }
                ]
            },
        ),
        tool_result(
            "get_events",
            {
                "events": [],
            },
        ),
    ]


def test_healthy_evidence_produces_healthy_report(
    healthy_trace: list[ToolResult],
) -> None:
    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    assert report.confidence == Confidence.HIGH
    assert report.approval_required is False
    assert report.errors == []
    assert "is healthy" in report.summary
    assert len(report.tool_trace) == 3


def test_unavailable_replica_requires_approval(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace[0].data["ready_replicas"] = 1
    healthy_trace[0].data["unavailable_replicas"] = 1

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    assert report.approval_required is True
    assert "Only 1 of 2" in report.probable_cause
    assert "1 unavailable" in report.probable_cause


def test_warning_event_is_reported(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "Unhealthy",
            "message": "Readiness probe failed.",
            "object_name": "app-123",
        }
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )
    assert report.approval_required is True
    assert "Readiness probe failed" in report.probable_cause


def test_tool_failure_stops_investigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def failed_execute(
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        calls.append(name)

        return ToolResult(
            tool=name,
            arguments=arguments,
            success=False,
            error="kubectl command timed out.",
        )

    monkeypatch.setattr(
        kubernetes_investigation,
        "execute_tool",
        failed_execute,
    )

    report = kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
    )

    assert calls == ["get_deployment"]
    assert report.confidence == Confidence.LOW
    assert report.approval_required is False
    assert report.errors == ["kubectl command timed out."]


def test_investigation_calls_tools_in_safe_order(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter(healthy_trace)
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_execute(
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        calls.append((name, arguments))
        return next(results)

    monkeypatch.setattr(
        kubernetes_investigation,
        "execute_tool",
        fake_execute,
    )

    report = kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
        event_limit=10,
    )

    assert [name for name, _ in calls] == [
        "get_deployment",
        "get_pods",
        "get_events",
    ]
    assert calls[2][1]["limit"] == 10
    assert report.approval_required is False
    assert calls[1][1] == {
        "namespace": "dev",
        "selector": "app=aws-platform-app",
    }


def test_unrelated_warning_event_is_ignored(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "Unhealthy",
            "message": "An unrelated workload failed.",
            "object_name": "different-application",
        }
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    assert report.approval_required is False
    assert "is healthy" in report.summary


def test_unhealthy_pod_triggers_log_collection(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_trace[1].data["pods"][0]["ready_containers"] = 0

    log_result = tool_result(
        "get_pod_logs",
        {
            "pod": "app-123",
            "line_count": 2,
            "truncated": False,
            "logs": [
                "Readiness probe failed.",
                "Database connection timed out.",
            ],
        },
    )

    results = iter(
        [
            healthy_trace[0],
            healthy_trace[1],
            healthy_trace[2],
            log_result,
        ]
    )

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_execute(
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        calls.append((name, arguments))
        return next(results)

    monkeypatch.setattr(
        kubernetes_investigation,
        "execute_tool",
        fake_execute,
    )

    report = kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
    )

    assert [name for name, _ in calls] == [
        "get_deployment",
        "get_pods",
        "get_events",
        "get_pod_logs",
    ]

    assert calls[3][1]["pod"] == "app-123"
    assert calls[3][1]["namespace"] == "dev"
    assert calls[3][1]["tail_lines"] == 100
    assert calls[3][1]["since_seconds"] == 600

    assert report.approval_required is True
    assert len(report.tool_trace) == 4


def test_unhealthy_pod_triggers_log_collection(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_trace[1].data["pods"][0]["ready_containers"] = 0

    log_result = tool_result(
        "get_pod_logs",
        {
            "pod": "app-123",
            "line_count": 2,
            "truncated": False,
            "logs": [
                "Readiness probe failed.",
                "Database connection timed out.",
            ],
        },
    )

    results = iter(
        [
            healthy_trace[0],
            healthy_trace[1],
            healthy_trace[2],
            log_result,
        ]
    )

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_execute(
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        calls.append((name, arguments))
        return next(results)

    monkeypatch.setattr(
        kubernetes_investigation,
        "execute_tool",
        fake_execute,
    )

    report = kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
    )

    assert [name for name, _ in calls] == [
        "get_deployment",
        "get_pods",
        "get_events",
        "get_pod_logs",
    ]

    assert calls[3][1]["pod"] == "app-123"
    assert calls[3][1]["namespace"] == "dev"
    assert calls[3][1]["tail_lines"] == 100
    assert calls[3][1]["since_seconds"] == 600

    assert report.approval_required is True
    assert len(report.tool_trace) == 4
