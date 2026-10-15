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
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 1
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["ready_containers"] = 0
    pod["containers"] = [
        {
            "name": "app",
            "ready": False,
            "restart_count": 0,
            "state": "running",
            "state_reason": None,
            "last_state": None,
            "last_reason": None,
            "last_exit_code": None,
        }
    ]

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "Unhealthy",
            "message": (
                "Readiness probe failed: "
                "HTTP probe failed with statuscode: 404"
            ),
            "object_name": "app-123",
        }
    ]

    log_result = tool_result(
        "get_pod_logs",
        {
            "pod": "app-123",
            "line_count": 2,
            "truncated": False,
            "logs": [
                "GET /health HTTP/1.1 404",
                "Readiness probe failed.",
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

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The pod has a readiness probe failure.",
            probable_cause=(
                "The readiness endpoint is returning HTTP 404."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "Verify the configured readiness path and response."
            ),
        ),
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
    assert report.confidence == Confidence.HIGH
    assert report.approval_required is True
    assert report.errors == []


def test_image_pull_failure_skips_log_collection(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["phase"] = "Pending"
    pod["ready_containers"] = 0
    pod["restarts"] = 0
    pod["containers"] = [
        {
            "name": "busybox",
            "ready": False,
            "restart_count": 0,
            "state": "waiting",
            "state_reason": "ImagePullBackOff",
            "last_state": None,
            "last_reason": None,
            "last_exit_code": None,
        }
    ]

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "Failed",
            "message": (
                'Failed to pull image '
                '"busybox:this-tag-does-not-exist": not found'
            ),
            "object_name": "app-123",
        }
    ]

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

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The pod cannot pull its container image.",
            probable_cause=(
                "The configured container image could not be found."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "Verify the configured image repository and tag."
            ),
        ),
    )

    report = kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
    )

    assert [name for name, _ in calls] == [
        "get_deployment",
        "get_pods",
        "get_events",
    ]

    assert "get_pod_logs" not in [
        name
        for name, _ in calls
    ]

    assert report.confidence == Confidence.HIGH
    assert report.approval_required is True
    assert report.errors == []


def test_healthy_investigation_does_not_call_llm(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter(healthy_trace)

    def fake_execute(
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        return next(results)

    def forbidden_llm_call(
        trace: list[ToolResult],
    ):
        raise AssertionError(
            "LLM must not be called for a healthy investigation."
        )

    monkeypatch.setattr(
        kubernetes_investigation,
        "execute_tool",
        fake_execute,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        forbidden_llm_call,
    )

    report = kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
    )

    assert report.approval_required is False
    assert report.errors == []
    assert "is healthy" in report.summary
    assert len(report.tool_trace) == 3


def test_llm_enriches_unhealthy_report(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 1
    healthy_trace[0].data["unavailable_replicas"] = 1

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The application deployment is degraded.",
            probable_cause=(
                "One replica is currently unavailable."
            ),
            confidence=Confidence.MEDIUM,
            recommended_action=(
                "Verify pod health and dependency connectivity."
            ),
        ),
    )

    enriched = kubernetes_investigation.enrich_report_with_llm(
        report=report,
        trace=healthy_trace,
    )

    assert enriched.summary == (
        "The application deployment is degraded."
    )
    assert enriched.probable_cause == (
        "One replica is currently unavailable."
    )
    assert enriched.confidence == Confidence.MEDIUM
    assert enriched.recommended_action == (
        "Verify pod health and dependency connectivity."
    )

    # Safety-critical fields remain deterministic.
    assert enriched.approval_required is True
    assert enriched.evidence == report.evidence
    assert enriched.tool_trace == report.tool_trace
    assert enriched.errors == report.errors


def test_llm_failure_falls_back_to_deterministic_report(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_trace[0].data["ready_replicas"] = 1
    healthy_trace[0].data["unavailable_replicas"] = 1

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    def failed_diagnosis(
        trace: list[ToolResult],
    ):
        raise kubernetes_investigation.LLMError(
            "Ollama is unavailable."
        )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        failed_diagnosis,
    )

    result = kubernetes_investigation.enrich_report_with_llm(
        report=report,
        trace=healthy_trace,
    )

    assert result == report

def test_llm_does_not_receive_unrelated_namespace_events(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 1

    healthy_trace[1].data["pods"][0]["ready_containers"] = 0
    healthy_trace[1].data["pods"][0]["restarts"] = 5

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "BackOff",
            "message": "Back-off restarting failed container.",
            "object_kind": "Pod",
            "object_name": "app-123",
        },
        {
            "type": "Warning",
            "reason": "FailedDeployModel",
            "message": "UnsupportedCertificate from unrelated ingress.",
            "object_kind": "Ingress",
            "object_name": "nginx-ingress",
        },
    ]

    log_result = tool_result(
        "get_pod_logs",
        {
            "pod": "app-123",
            "line_count": 1,
            "truncated": False,
            "logs": [
                "Simulated application startup failure",
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

    def fake_execute(
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        return next(results)

    captured_trace: list[ToolResult] = []

    def fake_diagnose(
        trace: list[ToolResult],
    ) -> LLMDiagnosis:
        captured_trace.extend(trace)

        return LLMDiagnosis(
            summary="The container is repeatedly crashing.",
            probable_cause=(
                "The workload is repeatedly exiting during startup."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "Review the failing container startup logs."
            ),
        )

    monkeypatch.setattr(
        kubernetes_investigation,
        "execute_tool",
        fake_execute,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        fake_diagnose,
    )

    report = kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
    )

    llm_events_result = next(
        result
        for result in captured_trace
        if result.tool == "get_events"
    )

    llm_messages = [
        event["message"]
        for event in llm_events_result.data["events"]
    ]

    assert any(
        "Back-off restarting failed container" in message
        for message in llm_messages
    )

    assert not any(
        "UnsupportedCertificate" in message
        for message in llm_messages
    )

    original_events_result = next(
        result
        for result in report.tool_trace
        if result.tool == "get_events"
    )

    assert len(original_events_result.data["events"]) == 2

def test_llm_readiness_mismatch_falls_back_to_deterministic_report(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 1
    healthy_trace[0].data["unavailable_replicas"] = 1

    healthy_trace[1].data["pods"][0]["ready_containers"] = 0

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "Unhealthy",
            "message": (
                "Readiness probe failed: "
                "HTTP probe failed with statuscode: 404"
            ),
            "object_name": "app-123",
        }
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="NGINX cannot find a requested file.",
            probable_cause=(
                "The requested file does not exist."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "Verify whether the requested file exists."
            ),
        ),
    )

    enriched = kubernetes_investigation.enrich_report_with_llm(
        report=report,
        trace=healthy_trace,
    )

    assert enriched.summary == report.summary
    assert enriched.probable_cause == report.probable_cause
    assert enriched.confidence == report.confidence
    assert enriched.recommended_action == report.recommended_action


def test_llm_failed_scheduling_mismatch_falls_back_to_deterministic_report(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 1
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["phase"] = "Pending"
    pod["ready_containers"] = 0
    pod["total_containers"] = 0
    pod["containers"] = []
    pod["node"] = None
    pod["pod_ip"] = None

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "FailedScheduling",
            "message": (
                "0/2 nodes are available: "
                "2 Insufficient cpu. "
                "preemption: 0/2 nodes are available: "
                "2 Preemption is not helpful for scheduling."
            ),
            "object_name": "app-123",
        }
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary=(
                "The deployment has a pod in a Pending state."
            ),
            probable_cause=(
                "The deployment may have a generic scheduling issue."
            ),
            confidence=Confidence.MEDIUM,
            recommended_action=(
                "Review the deployment and node state."
            ),
        ),
    )

    enriched = kubernetes_investigation.enrich_report_with_llm(
        report=report,
        trace=healthy_trace,
    )

    assert enriched.summary == report.summary
    assert enriched.probable_cause == report.probable_cause
    assert enriched.confidence == report.confidence
    assert enriched.recommended_action == report.recommended_action

def test_failed_scheduling_does_not_collect_logs_from_unrelated_running_pod(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_pod = healthy_trace[1].data["pods"][0]
    pending_pod["name"] = "app-pending"
    pending_pod["phase"] = "Pending"
    pending_pod["ready_containers"] = 0
    pending_pod["total_containers"] = 0
    pending_pod["restarts"] = 0
    pending_pod["containers"] = []
    pending_pod["node"] = None
    pending_pod["pod_ip"] = None

    running_pod = {
        "name": "app-old",
        "phase": "Running",
        "ready_containers": 1,
        "total_containers": 1,
        "restarts": 3,
        "containers": [
            {
                "name": "app",
                "ready": True,
                "restart_count": 3,
                "state": "running",
                "state_reason": None,
                "last_state": "terminated",
                "last_reason": "Completed",
                "last_exit_code": 0,
            }
        ],
        "node": "node-a",
        "pod_ip": "10.0.0.10",
    }

    healthy_trace[1].data["pods"].append(running_pod)

    healthy_trace[0].data["ready_replicas"] = 1
    healthy_trace[0].data["unavailable_replicas"] = 1

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "FailedScheduling",
            "message": (
                "0/2 nodes are available: "
                "2 Insufficient cpu."
            ),
            "object_name": "app-pending",
        }
    ]

    results = iter(healthy_trace[:3])

    calls: list[str] = []

    def fake_execute(
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        calls.append(name)
        return next(results)

    monkeypatch.setattr(
        kubernetes_investigation,
        "execute_tool",
        fake_execute,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: (_ for _ in ()).throw(
            kubernetes_investigation.LLMError("skip llm")
        ),
    )

    kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
    )

    assert calls == [
        "get_deployment",
        "get_pods",
        "get_events",
    ]


def test_report_preserves_oomkilled_container_evidence(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["available_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["ready_containers"] = 0
    pod["restarts"] = 4
    pod["containers"] = [
        {
            "name": "app",
            "ready": False,
            "restart_count": 4,
            "state": "waiting",
            "state_reason": "CrashLoopBackOff",
            "last_state": "terminated",
            "last_reason": "OOMKilled",
            "last_exit_code": 137,
        }
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    assert "OOMKilled" in report.probable_cause
    assert "exit code 137" in report.probable_cause


def test_llm_oomkilled_mismatch_falls_back_to_deterministic_report(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["available_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["ready_containers"] = 0
    pod["restarts"] = 4
    pod["containers"] = [
        {
            "name": "app",
            "ready": False,
            "restart_count": 4,
            "state": "waiting",
            "state_reason": "CrashLoopBackOff",
            "last_state": "terminated",
            "last_reason": "OOMKilled",
            "last_exit_code": 137,
        }
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The application container is repeatedly restarting.",
            probable_cause=(
                "The application may be encountering a generic runtime failure."
            ),
            confidence=Confidence.MEDIUM,
            recommended_action=(
                "Review the collected Kubernetes evidence."
            ),
        ),
    )

    enriched = kubernetes_investigation.enrich_report_with_llm(
        report=report,
        trace=healthy_trace,
    )

    assert enriched.summary == report.summary
    assert enriched.probable_cause == report.probable_cause
    assert "OOMKilled" in enriched.probable_cause
    assert "exit code 137" in enriched.probable_cause


def test_llm_liveness_mismatch_falls_back_to_deterministic_report(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["available_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["ready_containers"] = 0
    pod["restarts"] = 4
    pod["containers"] = [
        {
            "name": "nginx",
            "ready": False,
            "restart_count": 4,
            "state": "waiting",
            "state_reason": "CrashLoopBackOff",
            "last_state": "terminated",
            "last_reason": "Completed",
            "last_exit_code": 0,
        }
    ]

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "Unhealthy",
            "message": (
                "Liveness probe failed: "
                "HTTP probe failed with statuscode: 404"
            ),
            "object_name": "app-123",
        }
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=healthy_trace,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The application is shutting down gracefully.",
            probable_cause="The process received a termination signal.",
            confidence=Confidence.HIGH,
            recommended_action="No immediate action is required.",
        ),
    )

    enriched = kubernetes_investigation.enrich_report_with_llm(
        report=report,
        trace=healthy_trace,
    )

    assert enriched.summary == report.summary
    assert enriched.probable_cause == report.probable_cause
    assert "Liveness probe failed" in enriched.probable_cause


def test_llm_missing_secret_mismatch_falls_back_to_deterministic_report(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["ready_replicas"] = 1
    healthy_trace[0].data["available_replicas"] = 1
    healthy_trace[0].data["unavailable_replicas"] = 1

    healthy_trace[1].data["pods"] = [
        {
            "name": "secret-demo-123",
            "phase": "Pending",
            "ready_containers": 0,
            "total_containers": 1,
            "restarts": 0,
            "containers": [
                {
                    "name": "nginx",
                    "ready": False,
                    "restart_count": 0,
                    "state": "waiting",
                    "state_reason": "CreateContainerConfigError",
                    "last_state": None,
                    "last_reason": None,
                    "last_exit_code": None,
                }
            ],
        }
    ]

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "Failed",
            "message": 'Error: secret "missing-secret-demo" not found',
            "object_kind": "Pod",
            "object_name": "secret-demo-123",
        }
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="secret-demo",
        namespace="dev",
        trace=healthy_trace,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The container cannot start.",
            probable_cause=(
                "The nginx image may be corrupted or incorrectly configured."
            ),
            confidence=Confidence.MEDIUM,
            recommended_action="Review the collected evidence.",
        ),
    )

    enriched = kubernetes_investigation.enrich_report_with_llm(
        report=report,
        trace=healthy_trace,
    )

    assert enriched.summary == report.summary
    assert enriched.probable_cause == report.probable_cause
    assert "missing-secret-demo" in enriched.probable_cause


def test_evicted_terminated_pod_skips_log_collection(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["desired_replicas"] = 0
    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 0

    pod = healthy_trace[1].data["pods"][0]
    pod["name"] = "eviction-demo-pod"
    pod["phase"] = "Failed"
    pod["ready_containers"] = 0
    pod["total_containers"] = 1
    pod["restarts"] = 1
    pod["containers"] = [
        {
            "name": "busybox",
            "ready": False,
            "restart_count": 1,
            "state": "terminated",
            "state_reason": "ContainerStatusUnknown",
            "last_state": "terminated",
            "last_reason": "ContainerStatusUnknown",
            "last_exit_code": 137,
        }
    ]

    healthy_trace[2].data["events"] = [
        {
            "type": "Warning",
            "reason": "Evicted",
            "message": (
                "Pod ephemeral local storage usage exceeds "
                "the total limit of containers 32Mi."
            ),
            "object_kind": "Pod",
            "object_name": "eviction-demo-pod",
        }
    ]

    results = iter(
        [
            healthy_trace[0],
            healthy_trace[1],
            healthy_trace[2],
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

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The pod was evicted.",
            probable_cause=(
                "Ephemeral local storage usage exceeded "
                "the configured 32Mi limit."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "Review ephemeral-storage usage and limits."
            ),
        ),
    )

    report = kubernetes_investigation.run_kubernetes_investigation(
        name="aws-platform-app",
        namespace="dev",
    )

    assert "get_pod_logs" not in [
        name
        for name, _ in calls
    ]

    assert report.confidence == Confidence.HIGH
    assert report.errors == []


def test_eviction_diagnosis_must_preserve_eviction_signal() -> None:
    trace = [
        ToolResult(
            tool="get_events",
            arguments={},
            success=True,
            data={
                "events": [
                    {
                        "type": "Warning",
                        "reason": "Evicted",
                        "message": (
                            "Pod ephemeral local storage usage exceeds "
                            "the total limit of containers 32Mi."
                        ),
                        "object_kind": "Pod",
                        "object_name": "eviction-demo-pod",
                    }
                ]
            },
            error=None,
        )
    ]

    assert kubernetes_investigation._trace_has_eviction(trace) is True

    assert (
        kubernetes_investigation._diagnosis_preserves_eviction(
            "The container exited with code 137.",
            "ContainerStatusUnknown was reported.",
        )
        is False
    )

    assert (
        kubernetes_investigation._diagnosis_preserves_eviction(
            "The pod was evicted.",
            (
                "Ephemeral local storage usage exceeded "
                "the configured container limit."
            ),
        )
        is True
    )


def test_trace_has_eviction_from_pod_status() -> None:
    trace = [
        ToolResult(
            tool="get_pods",
            arguments={},
            success=True,
            data={
                "pods": [
                    {
                        "name": "eviction-demo-pod",
                        "phase": "Failed",
                        "reason": "Evicted",
                        "message": (
                            "Pod ephemeral local storage usage exceeds "
                            "the total limit of containers 32Mi."
                        ),
                    }
                ]
            },
            error=None,
        )
    ]

    assert kubernetes_investigation._trace_has_eviction(trace) is True
