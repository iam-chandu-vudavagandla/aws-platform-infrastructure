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


def test_incident_scoped_trace_keeps_node_event_for_pod_node() -> None:
    trace = [
        ToolResult(
            tool="get_pods",
            arguments={},
            success=True,
            data={
                "pods": [
                    {
                        "name": "app-123",
                        "node": "worker-node-1",
                    }
                ]
            },
            error=None,
        ),
        ToolResult(
            tool="get_events",
            arguments={},
            success=True,
            data={
                "events": [
                    {
                        "type": "Warning",
                        "reason": "NodeNotReady",
                        "message": "Node worker-node-1 is not ready.",
                        "object_kind": "Node",
                        "object_name": "worker-node-1",
                    },
                    {
                        "type": "Warning",
                        "reason": "FailedDeployModel",
                        "message": "Unrelated ingress warning.",
                        "object_kind": "Ingress",
                        "object_name": "nginx-ingress",
                    },
                ],
                "returned_events": 2,
            },
            error=None,
        ),
    ]

    scoped = kubernetes_investigation._incident_scoped_trace(
        name="aws-platform-app",
        trace=trace,
    )

    events_result = next(
        result
        for result in scoped
        if result.tool == "get_events"
    )

    events = events_result.data["events"]

    assert len(events) == 1
    assert events[0]["reason"] == "NodeNotReady"
    assert events[0]["object_name"] == "worker-node-1"


def test_deterministic_report_keeps_node_warning_for_pod_node() -> None:
    trace = [
        ToolResult(
            tool="get_deployment",
            arguments={},
            success=True,
            data={
                "generation": 1,
                "observed_generation": 1,
                "desired_replicas": 1,
                "ready_replicas": 0,
                "unavailable_replicas": 1,
            },
            error=None,
        ),
        ToolResult(
            tool="get_pods",
            arguments={},
            success=True,
            data={
                "pods": [
                    {
                        "name": "app-123",
                        "phase": "Running",
                        "ready_containers": 0,
                        "total_containers": 1,
                        "restarts": 0,
                        "containers": [],
                        "node": "worker-node-1",
                    }
                ]
            },
            error=None,
        ),
        ToolResult(
            tool="get_events",
            arguments={},
            success=True,
            data={
                "events": [
                    {
                        "type": "Warning",
                        "reason": "NodeNotReady",
                        "message": "Node worker-node-1 is not ready.",
                        "object_kind": "Node",
                        "object_name": "worker-node-1",
                    }
                ]
            },
            error=None,
        ),
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=trace,
    )

    assert "NodeNotReady" in report.probable_cause
    assert "worker-node-1 is not ready" in report.probable_cause


def test_node_not_ready_diagnosis_must_preserve_node_signal() -> None:
    trace = [
        ToolResult(
            tool="get_events",
            arguments={},
            success=True,
            data={
                "events": [
                    {
                        "type": "Warning",
                        "reason": "NodeNotReady",
                        "message": "Node worker-node-1 is not ready.",
                        "object_kind": "Node",
                        "object_name": "worker-node-1",
                    }
                ]
            },
            error=None,
        )
    ]

    assert (
        kubernetes_investigation._trace_has_node_not_ready(trace)
        is True
    )

    assert (
        kubernetes_investigation._diagnosis_preserves_node_not_ready(
            "The application container crashed.",
            "The workload failed during startup.",
        )
        is False
    )

    assert (
        kubernetes_investigation._diagnosis_preserves_node_not_ready(
            "The workload is affected by a NodeNotReady condition.",
            "The worker node is not ready.",
        )
        is True
    )


def test_node_pressure_diagnosis_must_preserve_pressure_signal() -> None:
    for pressure_reason in (
        "MemoryPressure",
        "DiskPressure",
        "PIDPressure",
    ):
        trace = [
            ToolResult(
                tool="get_events",
                arguments={},
                success=True,
                data={
                    "events": [
                        {
                            "type": "Warning",
                            "reason": pressure_reason,
                            "message": (
                                f"Node worker-node-1 reports "
                                f"{pressure_reason}."
                            ),
                            "object_kind": "Node",
                            "object_name": "worker-node-1",
                        }
                    ]
                },
                error=None,
            )
        ]

        assert (
            kubernetes_investigation._trace_node_pressure_reason(
                trace
            )
            == pressure_reason
        )

        assert (
            kubernetes_investigation._diagnosis_preserves_node_pressure(
                pressure_reason,
                "The application container crashed.",
                "The workload failed during startup.",
            )
            is False
        )

        assert (
            kubernetes_investigation._diagnosis_preserves_node_pressure(
                pressure_reason,
                f"The node reports {pressure_reason}.",
                "The problem originates from worker-node-1.",
            )
            is True
        )


def test_llm_node_failure_mismatch_falls_back_to_deterministic_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    trace = [
        ToolResult(
            tool="get_deployment",
            arguments={},
            success=True,
            data={
                "generation": 1,
                "observed_generation": 1,
                "desired_replicas": 1,
                "ready_replicas": 0,
                "unavailable_replicas": 1,
            },
            error=None,
        ),
        ToolResult(
            tool="get_pods",
            arguments={},
            success=True,
            data={
                "pods": [
                    {
                        "name": "app-123",
                        "phase": "Running",
                        "ready_containers": 0,
                        "total_containers": 1,
                        "restarts": 0,
                        "containers": [],
                        "node": "worker-node-1",
                    }
                ]
            },
            error=None,
        ),
        ToolResult(
            tool="get_events",
            arguments={},
            success=True,
            data={
                "events": [
                    {
                        "type": "Warning",
                        "reason": "NodeNotReady",
                        "message": "Node worker-node-1 is not ready.",
                        "object_kind": "Node",
                        "object_name": "worker-node-1",
                    }
                ]
            },
            error=None,
        ),
    ]

    report = kubernetes_investigation.create_kubernetes_report(
        name="aws-platform-app",
        namespace="dev",
        trace=trace,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The application container crashed.",
            probable_cause="The workload failed during startup.",
            confidence=Confidence.HIGH,
            recommended_action="Restart the application container.",
        ),
    )

    enriched = kubernetes_investigation.enrich_report_with_llm(
        report=report,
        trace=trace,
    )

    assert enriched.summary == report.summary
    assert enriched.probable_cause == report.probable_cause
    assert "NodeNotReady" in enriched.probable_cause
    assert "worker-node-1 is not ready" in enriched.probable_cause


def test_node_pressure_recognizes_kubernetes_event_reasons() -> None:
    cases = {
        "NodeHasInsufficientMemory": "MemoryPressure",
        "NodeHasDiskPressure": "DiskPressure",
        "NodeHasInsufficientPID": "PIDPressure",
    }

    for event_reason, expected_pressure in cases.items():
        trace = [
            ToolResult(
                tool="get_events",
                arguments={},
                success=True,
                data={
                    "events": [
                        {
                            "type": "Warning",
                            "reason": event_reason,
                            "message": (
                                f"Node worker-node-1 reports "
                                f"{event_reason}."
                            ),
                            "object_kind": "Node",
                            "object_name": "worker-node-1",
                        }
                    ]
                },
                error=None,
            )
        ]

        assert (
            kubernetes_investigation._trace_node_pressure_reason(
                trace
            )
            == expected_pressure
        )
def test_node_not_ready_investigation_runs_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter(
        [
            ToolResult(
                tool="get_deployment",
                arguments={},
                success=True,
                data={
                    "selector": "app=aws-platform-app",
                    "generation": 1,
                    "observed_generation": 1,
                    "desired_replicas": 1,
                    "ready_replicas": 0,
                    "unavailable_replicas": 1,
                },
                error=None,
            ),
            ToolResult(
                tool="get_pods",
                arguments={},
                success=True,
                data={
                    "pods": [
                        {
                            "name": "app-123",
                            "phase": "Running",
                            "ready_containers": 0,
                            "total_containers": 1,
                            "restarts": 0,
                            "containers": [],
                            "node": "worker-node-1",
                        }
                    ]
                },
                error=None,
            ),
            ToolResult(
                tool="get_events",
                arguments={},
                success=True,
                data={
                    "events": [
                        {
                            "type": "Warning",
                            "reason": "NodeNotReady",
                            "message": (
                                "Node worker-node-1 is not ready."
                            ),
                            "object_kind": "Node",
                            "object_name": "worker-node-1",
                        }
                    ]
                },
                error=None,
            ),
        ]
    )

    calls: list[str] = []

    def fake_execute(
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        result = next(results)

        assert result.tool == name
        calls.append(name)

        return result.model_copy(
            update={"arguments": arguments}
        )

    monkeypatch.setattr(
        kubernetes_investigation,
        "execute_tool",
        fake_execute,
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "enrich_report_with_llm",
        lambda report, trace: report,
    )

    report = (
        kubernetes_investigation
        .run_kubernetes_investigation(
            name="aws-platform-app",
            namespace="dev",
        )
    )

    assert calls == [
        "get_deployment",
        "get_pods",
        "get_events",
    ]
    assert len(report.tool_trace) == 3
    assert report.approval_required is True
    assert report.errors == []
    assert "NodeNotReady" in report.probable_cause
    assert "worker-node-1 is not ready" in (
        report.probable_cause
    )

def test_deterministic_report_preserves_dns_log_evidence(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["ready_containers"] = 0
    pod["restarts"] = 1
    pod["containers"] = [
        {
            "name": "app",
            "ready": False,
            "restart_count": 1,
            "state": "running",
            "state_reason": None,
            "last_state": None,
            "last_reason": None,
            "last_exit_code": None,
        }
    ]

    healthy_trace.append(
        tool_result(
            "get_pod_logs",
            {
                "pod": "app-123",
                "line_count": 1,
                "truncated": False,
                "logs": [
                    (
                        "dial tcp: lookup "
                        "database.default.svc.cluster.local "
                        "on 10.100.0.10:53: no such host"
                    )
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = (
        f"{report.summary} "
        f"{report.probable_cause}"
    ).lower()

    assert "dns" in diagnosis
    assert (
        "database.default.svc.cluster.local"
        in diagnosis
    )
    assert "no such host" in diagnosis
    assert report.approval_required is True

def test_llm_dns_mismatch_falls_back_to_deterministic_report(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace.append(
        tool_result(
            "get_pod_logs",
            {
                "pod": "app-123",
                "line_count": 1,
                "truncated": False,
                "logs": [
                    (
                        "dial tcp: lookup "
                        "database.default.svc.cluster.local "
                        "on 10.100.0.10:53: no such host"
                    )
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The application is healthy.",
            probable_cause=(
                "No infrastructure problem was detected."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "No further investigation is required."
            ),
        ),
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == report.summary
    assert (
        enriched.probable_cause
        == report.probable_cause
    )

    diagnosis = (
        f"{enriched.summary} "
        f"{enriched.probable_cause}"
    ).lower()

    assert "dns" in diagnosis
    assert (
        "database.default.svc.cluster.local"
        in diagnosis
    )
    assert "no such host" in diagnosis

def test_llm_dns_diagnosis_is_accepted_when_evidence_is_preserved(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace.append(
        tool_result(
            "get_pod_logs",
            {
                "pod": "app-123",
                "line_count": 1,
                "truncated": False,
                "logs": [
                    (
                        "dial tcp: lookup "
                        "database.default.svc.cluster.local "
                        "on 10.100.0.10:53: no such host"
                    )
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    expected_summary = (
        "The application has a DNS resolution failure."
    )
    expected_cause = (
        "DNS lookup for "
        "database.default.svc.cluster.local failed with "
        "no such host."
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary=expected_summary,
            probable_cause=expected_cause,
            confidence=Confidence.HIGH,
            recommended_action=(
                "Verify the Kubernetes Service name and "
                "cluster DNS configuration before making "
                "a change."
            ),
        ),
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == expected_summary
    assert enriched.probable_cause == expected_cause
    assert enriched.summary != report.summary
    assert enriched.confidence == Confidence.HIGH
    assert enriched.approval_required is True

def test_dns_failure_collects_service_endpoint_evidence(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["ready_containers"] = 0
    pod["restarts"] = 1
    pod["containers"] = [
        {
            "name": "app",
            "ready": False,
            "restart_count": 1,
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
            "message": "Application dependency check failed.",
            "object_name": "app-123",
        }
    ]

    logs_result = tool_result(
        "get_pod_logs",
        {
            "pod": "app-123",
            "line_count": 1,
            "truncated": False,
            "logs": [
                (
                    "dial tcp: lookup "
                    "database.default.svc.cluster.local "
                    "on 10.100.0.10:53: no such host"
                )
            ],
        },
    )

    service_result = tool_result(
        "get_service_endpoints",
        {
            "service": "aws-platform-app-service",
            "type": "ClusterIP",
            "selector": {
                "app": "aws-platform-app",
            },
            "ports": [
                {
                    "name": "http",
                    "protocol": "TCP",
                    "port": 80,
                    "target_port": "http",
                }
            ],
            "endpoint_slice_count": 0,
            "ready_endpoint_count": 0,
            "not_ready_endpoint_count": 0,
            "ready_addresses": [],
            "not_ready_addresses": [],
        },
    )

    results = iter(
        [
            healthy_trace[0],
            healthy_trace[1],
            healthy_trace[2],
            logs_result,
            service_result,
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
        "enrich_report_with_llm",
        lambda report, trace: report,
    )

    report = (
        kubernetes_investigation
        .run_kubernetes_investigation(
            name="aws-platform-app",
            namespace="dev",
        )
    )

    assert [name for name, _ in calls] == [
        "get_deployment",
        "get_pods",
        "get_events",
        "get_pod_logs",
        "get_service_endpoints",
    ]

    assert calls[4][1] == {
        "service": "aws-platform-app-service",
        "namespace": "dev",
    }

    assert len(report.tool_trace) == 5
    assert report.tool_trace[-1].tool == (
        "get_service_endpoints"
    )

def test_deterministic_report_detects_zero_ready_endpoints(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace.append(
        tool_result(
            "get_service_endpoints",
            {
                "service": (
                    "aws-platform-app-service"
                ),
                "type": "ClusterIP",
                "selector": {
                    "app": "aws-platform-app",
                },
                "ports": [
                    {
                        "name": "http",
                        "protocol": "TCP",
                        "port": 80,
                        "target_port": "http",
                    }
                ],
                "endpoint_slice_count": 0,
                "ready_endpoint_count": 0,
                "not_ready_endpoint_count": 0,
                "ready_addresses": [],
                "not_ready_addresses": [],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = (
        f"{report.summary} "
        f"{report.probable_cause}"
    ).lower()

    assert (
        "aws-platform-app-service"
        in diagnosis
    )
    assert "zero ready endpoints" in diagnosis
    assert report.approval_required is True
    assert report.errors == []

def test_llm_zero_endpoint_mismatch_falls_back(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace.append(
        tool_result(
            "get_service_endpoints",
            {
                "service": (
                    "aws-platform-app-service"
                ),
                "type": "ClusterIP",
                "selector": {
                    "app": "aws-platform-app",
                },
                "ports": [
                    {
                        "name": "http",
                        "protocol": "TCP",
                        "port": 80,
                        "target_port": "http",
                    }
                ],
                "endpoint_slice_count": 0,
                "ready_endpoint_count": 0,
                "not_ready_endpoint_count": 0,
                "ready_addresses": [],
                "not_ready_addresses": [],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary="The application is healthy.",
            probable_cause=(
                "The Service is routing traffic normally."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "No further investigation is required."
            ),
        ),
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == report.summary
    assert (
        enriched.probable_cause
        == report.probable_cause
    )

    diagnosis = (
        f"{enriched.summary} "
        f"{enriched.probable_cause}"
    ).lower()

    assert (
        "aws-platform-app-service"
        in diagnosis
    )
    assert "zero ready endpoints" in diagnosis

def test_llm_zero_endpoint_diagnosis_is_accepted(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace.append(
        tool_result(
            "get_service_endpoints",
            {
                "service": "aws-platform-app-service",
                "type": "ClusterIP",
                "selector": {
                    "app": "aws-platform-app",
                },
                "ports": [
                    {
                        "name": "http",
                        "protocol": "TCP",
                        "port": 80,
                        "target_port": "http",
                    }
                ],
                "endpoint_slice_count": 0,
                "ready_endpoint_count": 0,
                "not_ready_endpoint_count": 0,
                "ready_addresses": [],
                "not_ready_addresses": [],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = LLMDiagnosis(
        summary=(
            "Service aws-platform-app-service "
            "has zero ready endpoints."
        ),
        probable_cause=(
            "The Service selector currently produces "
            "no ready endpoints for traffic."
        ),
        confidence=Confidence.HIGH,
        recommended_action=(
            "Compare the Service selector with the "
            "Deployment pod labels."
        ),
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: diagnosis,
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == diagnosis.summary
    assert (
        enriched.probable_cause
        == diagnosis.probable_cause
    )
    assert enriched.confidence == Confidence.HIGH
    assert enriched.summary != report.summary
    assert (
        enriched.approval_required
        == report.approval_required
    )
    assert enriched.tool_trace == report.tool_trace
    assert enriched.errors == report.errors

def test_deterministic_report_detects_service_selector_mismatch(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace.append(
        tool_result(
            "get_service_endpoints",
            {
                "service": "aws-platform-app-service",
                "type": "ClusterIP",
                "selector": {
                    "app": "wrong-app",
                },
                "ports": [
                    {
                        "name": "http",
                        "protocol": "TCP",
                        "port": 80,
                        "target_port": "http",
                    }
                ],
                "endpoint_slice_count": 0,
                "ready_endpoint_count": 0,
                "not_ready_endpoint_count": 0,
                "ready_addresses": [],
                "not_ready_addresses": [],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = (
        f"{report.summary} "
        f"{report.probable_cause}"
    ).lower()

    assert "selector" in diagnosis
    assert "app=aws-platform-app" in diagnosis
    assert "app=wrong-app" in diagnosis
    assert report.confidence == Confidence.HIGH
    assert report.approval_required is True

def test_llm_selector_mismatch_falls_back(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace.append(
        tool_result(
            "get_service_endpoints",
            {
                "service": "aws-platform-app-service",
                "type": "ClusterIP",
                "selector": {
                    "app": "wrong-app",
                },
                "ports": [
                    {
                        "name": "http",
                        "protocol": "TCP",
                        "port": 80,
                        "target_port": "http",
                    }
                ],
                "endpoint_slice_count": 0,
                "ready_endpoint_count": 0,
                "not_ready_endpoint_count": 0,
                "ready_addresses": [],
                "not_ready_addresses": [],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary=(
                "Service aws-platform-app-service "
                "has zero ready endpoints."
            ),
            probable_cause=(
                "The Service and Deployment selectors "
                "match correctly, so the missing endpoints "
                "are unrelated to selector configuration."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "Investigate an unrelated application issue."
            ),
        ),
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == report.summary
    assert (
        enriched.probable_cause
        == report.probable_cause
    )
    assert enriched.confidence == report.confidence
    assert enriched.tool_trace == report.tool_trace

def test_llm_selector_mismatch_diagnosis_is_accepted(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace.append(
        tool_result(
            "get_service_endpoints",
            {
                "service": "aws-platform-app-service",
                "type": "ClusterIP",
                "selector": {
                    "app": "wrong-app",
                },
                "ports": [
                    {
                        "name": "http",
                        "protocol": "TCP",
                        "port": 80,
                        "target_port": "http",
                    }
                ],
                "endpoint_slice_count": 0,
                "ready_endpoint_count": 0,
                "not_ready_endpoint_count": 0,
                "ready_addresses": [],
                "not_ready_addresses": [],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = LLMDiagnosis(
        summary=(
            "Service aws-platform-app-service has "
            "zero ready endpoints because its selector "
            "does not match the Deployment selector."
        ),
        probable_cause=(
            "Service selector app=wrong-app differs "
            "from Deployment selector "
            "app=aws-platform-app."
        ),
        confidence=Confidence.HIGH,
        recommended_action=(
            "Change the Service selector to "
            "app=aws-platform-app after human review."
        ),
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: diagnosis,
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == diagnosis.summary
    assert (
        enriched.probable_cause
        == diagnosis.probable_cause
    )
    assert (
        enriched.recommended_action
        == diagnosis.recommended_action
    )
    assert enriched.confidence == Confidence.HIGH
    assert enriched.summary != report.summary
    assert (
        enriched.approval_required
        == report.approval_required
    )
    assert enriched.tool_trace == report.tool_trace
    assert enriched.errors == report.errors

def test_dns_failure_with_ready_endpoints_collects_network_policies(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_trace[0].data["ready_replicas"] = 0
    healthy_trace[0].data["unavailable_replicas"] = 1

    pod = healthy_trace[1].data["pods"][0]
    pod["ready_containers"] = 0
    pod["restarts"] = 1
    pod["containers"] = [
        {
            "name": "app",
            "ready": False,
            "restart_count": 1,
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
                "Application dependency check failed."
            ),
            "object_name": "app-123",
        }
    ]

    logs_result = tool_result(
        "get_pod_logs",
        {
            "pod": "app-123",
            "line_count": 1,
            "truncated": False,
            "logs": [
                (
                    "dial tcp: lookup "
                    "database.default.svc.cluster.local "
                    "on 10.100.0.10:53: no such host"
                )
            ],
        },
    )

    service_result = tool_result(
        "get_service_endpoints",
        {
            "service": "aws-platform-app-service",
            "type": "ClusterIP",
            "selector": {
                "app": "aws-platform-app",
            },
            "ports": [
                {
                    "name": "http",
                    "protocol": "TCP",
                    "port": 80,
                    "target_port": "http",
                }
            ],
            "endpoint_slice_count": 1,
            "ready_endpoint_count": 1,
            "not_ready_endpoint_count": 0,
            "ready_addresses": [
                "10.0.11.20",
            ],
            "not_ready_addresses": [],
        },
    )

    policies_result = tool_result(
        "get_network_policies",
        {
            "namespace": "dev",
            "count": 1,
            "returned_policies": 1,
            "truncated": False,
            "policies": [
                {
                    "name": "deny-app-egress",
                    "pod_selector": {
                        "app": "aws-platform-app",
                    },
                    "has_match_expressions": False,
                    "policy_types": [
                        "Egress",
                    ],
                    "ingress_rule_count": 0,
                    "egress_rule_count": 0,
                    "default_deny_ingress": False,
                    "default_deny_egress": True,
                }
            ],
        },
    )

    results = iter(
        [
            healthy_trace[0],
            healthy_trace[1],
            healthy_trace[2],
            logs_result,
            service_result,
            policies_result,
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
        "enrich_report_with_llm",
        lambda report, trace: report,
    )

    report = (
        kubernetes_investigation
        .run_kubernetes_investigation(
            name="aws-platform-app",
            namespace="dev",
        )
    )

    assert [name for name, _ in calls] == [
        "get_deployment",
        "get_pods",
        "get_events",
        "get_pod_logs",
        "get_service_endpoints",
        "get_network_policies",
    ]

    assert calls[5][1] == {
        "namespace": "dev",
    }
    assert report.tool_trace[-1].tool == (
        "get_network_policies"
    )
def test_deterministic_report_detects_default_deny_egress_policy(
    healthy_trace: list[ToolResult],
) -> None:
    pod = healthy_trace[1].data["pods"][0]
    pod["labels"] = {
        "app": "aws-platform-app",
    }

    healthy_trace.append(
        tool_result(
            "get_pod_logs",
            {
                "pod": "app-123",
                "line_count": 1,
                "truncated": False,
                "logs": [
                    (
                        "dial tcp: lookup "
                        "database.default.svc.cluster.local "
                        "on 10.100.0.10:53: no such host"
                    )
                ],
            },
        )
    )

    healthy_trace.append(
        tool_result(
            "get_network_policies",
            {
                "namespace": "dev",
                "count": 1,
                "returned_policies": 1,
                "truncated": False,
                "policies": [
                    {
                        "name": "deny-app-egress",
                        "pod_selector": {
                            "app": "aws-platform-app",
                        },
                        "has_match_expressions": False,
                        "policy_types": [
                            "Egress",
                        ],
                        "ingress_rule_count": 0,
                        "egress_rule_count": 0,
                        "default_deny_ingress": False,
                        "default_deny_egress": True,
                    }
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = (
        f"{report.summary} "
        f"{report.probable_cause}"
    ).lower()

    assert "deny-app-egress" in diagnosis
    assert "app-123" in diagnosis
    assert "default-deny egress" in diagnosis
    assert report.confidence == Confidence.HIGH
    assert report.approval_required is True

def test_llm_default_deny_egress_mismatch_falls_back(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    pod = healthy_trace[1].data["pods"][0]
    pod["labels"] = {
        "app": "aws-platform-app",
    }

    healthy_trace.append(
        tool_result(
            "get_pod_logs",
            {
                "pod": "app-123",
                "line_count": 1,
                "truncated": False,
                "logs": [
                    (
                        "dial tcp: lookup "
                        "database.default.svc.cluster.local "
                        "on 10.100.0.10:53: no such host"
                    )
                ],
            },
        )
    )

    healthy_trace.append(
        tool_result(
            "get_network_policies",
            {
                "namespace": "dev",
                "count": 1,
                "returned_policies": 1,
                "truncated": False,
                "policies": [
                    {
                        "name": "deny-app-egress",
                        "pod_selector": {
                            "app": "aws-platform-app",
                        },
                        "has_match_expressions": False,
                        "policy_types": [
                            "Egress",
                        ],
                        "ingress_rule_count": 0,
                        "egress_rule_count": 0,
                        "default_deny_ingress": False,
                        "default_deny_egress": True,
                    }
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary=(
                "Pod app-123 has a DNS resolution "
                "failure for "
                "database.default.svc.cluster.local."
            ),
            probable_cause=(
                "The lookup returned no such host, "
                "but NetworkPolicy deny-app-egress "
                "allows all egress traffic."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "Investigate an unrelated DNS problem."
            ),
        ),
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == report.summary
    assert (
        enriched.probable_cause
        == report.probable_cause
    )
    assert enriched.confidence == report.confidence
    assert enriched.tool_trace == report.tool_trace

def test_llm_default_deny_egress_diagnosis_is_accepted(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    pod = healthy_trace[1].data["pods"][0]
    pod["labels"] = {
        "app": "aws-platform-app",
    }

    healthy_trace.append(
        tool_result(
            "get_pod_logs",
            {
                "pod": "app-123",
                "line_count": 1,
                "truncated": False,
                "logs": [
                    (
                        "dial tcp: lookup "
                        "database.default.svc.cluster.local "
                        "on 10.100.0.10:53: no such host"
                    )
                ],
            },
        )
    )

    healthy_trace.append(
        tool_result(
            "get_network_policies",
            {
                "namespace": "dev",
                "count": 1,
                "returned_policies": 1,
                "truncated": False,
                "policies": [
                    {
                        "name": "deny-app-egress",
                        "pod_selector": {
                            "app": "aws-platform-app",
                        },
                        "has_match_expressions": False,
                        "policy_types": [
                            "Egress",
                        ],
                        "ingress_rule_count": 0,
                        "egress_rule_count": 0,
                        "default_deny_ingress": False,
                        "default_deny_egress": True,
                    }
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = LLMDiagnosis(
        summary=(
            "NetworkPolicy deny-app-egress applies "
            "default-deny egress to pod app-123."
        ),
        probable_cause=(
            "The blocked egress causes a DNS "
            "resolution failure for "
            "database.default.svc.cluster.local "
            "with no such host."
        ),
        confidence=Confidence.HIGH,
        recommended_action=(
            "Review and approve a narrowly scoped "
            "egress rule for DNS traffic."
        ),
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: diagnosis,
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == diagnosis.summary
    assert (
        enriched.probable_cause
        == diagnosis.probable_cause
    )
    assert (
        enriched.recommended_action
        == diagnosis.recommended_action
    )
    assert enriched.confidence == Confidence.HIGH
    assert enriched.summary != report.summary
    assert (
        enriched.approval_required
        == report.approval_required
    )
    assert enriched.tool_trace == report.tool_trace
    assert enriched.errors == report.errors

def test_hpa_investigation_collects_autoscaler_evidence(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hpa_result = tool_result(
        "get_hpa",
        {
            "name": "aws-platform-app-hpa",
            "target": {
                "kind": "Deployment",
                "name": "aws-platform-app",
            },
            "min_replicas": 2,
            "max_replicas": 5,
            "current_replicas": 2,
            "desired_replicas": 2,
            "target_cpu_utilization": 50,
            "current_cpu_utilization": None,
            "conditions": [
                {
                    "type": "ScalingActive",
                    "status": "False",
                    "reason": (
                        "FailedGetResourceMetric"
                    ),
                    "message": (
                        "No metrics returned from "
                        "resource metrics API."
                    ),
                    "last_transition_time": (
                        "2026-10-26T05:00:00Z"
                    ),
                }
            ],
        },
    )

    results = iter(
        [
            healthy_trace[0],
            healthy_trace[1],
            healthy_trace[2],
            hpa_result,
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
        "enrich_report_with_llm",
        lambda report, trace: report,
    )

    report = (
        kubernetes_investigation
        .run_kubernetes_investigation(
            name="aws-platform-app",
            namespace="dev",
            hpa_name="aws-platform-app-hpa",
        )
    )

    assert [name for name, _ in calls] == [
        "get_deployment",
        "get_pods",
        "get_events",
        "get_hpa",
    ]

    assert calls[3][1] == {
        "name": "aws-platform-app-hpa",
        "namespace": "dev",
    }
    assert report.tool_trace[-1].tool == "get_hpa"

def test_deterministic_report_diagnoses_hpa_metrics_api_failure(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace[0].data["containers"] = [
        {
            "name": "app",
            "image": "example/app:1.0",
            "cpu_request": "250m",
            "memory_request": "256Mi",
            "cpu_limit": "500m",
            "memory_limit": "512Mi",
        }
    ]

    healthy_trace.append(
        tool_result(
            "get_hpa",
            {
                "name": "aws-platform-app-hpa",
                "target": {
                    "kind": "Deployment",
                    "name": "aws-platform-app",
                },
                "min_replicas": 2,
                "max_replicas": 5,
                "current_replicas": 2,
                "desired_replicas": 2,
                "target_cpu_utilization": 50,
                "current_cpu_utilization": None,
                "conditions": [
                    {
                        "type": "ScalingActive",
                        "status": "False",
                        "reason": (
                            "FailedGetResourceMetric"
                        ),
                        "message": (
                            "No metrics returned from "
                            "resource metrics API."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:00:00Z"
                        ),
                    }
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = (
        f"{report.summary} "
        f"{report.probable_cause}"
    ).lower()

    assert "aws-platform-app-hpa" in diagnosis
    assert "failedgetresourcemetric" in diagnosis
    assert "resource metrics api" in diagnosis
    assert "cpu requests are present" in diagnosis
    assert report.confidence == Confidence.HIGH
    assert report.approval_required is True

def test_deterministic_report_detects_missing_cpu_request(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace[0].data["containers"] = [
        {
            "name": "app",
            "image": "example/app:1.0",
            "cpu_request": None,
            "memory_request": "256Mi",
            "cpu_limit": "500m",
            "memory_limit": "512Mi",
        }
    ]

    healthy_trace.append(
        tool_result(
            "get_hpa",
            {
                "name": "aws-platform-app-hpa",
                "target": {
                    "kind": "Deployment",
                    "name": "aws-platform-app",
                },
                "min_replicas": 2,
                "max_replicas": 5,
                "current_replicas": 2,
                "desired_replicas": 2,
                "target_cpu_utilization": 50,
                "current_cpu_utilization": None,
                "conditions": [
                    {
                        "type": "ScalingActive",
                        "status": "False",
                        "reason": (
                            "FailedGetResourceMetric"
                        ),
                        "message": (
                            "Missing request for cpu "
                            "in container app."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:00:00Z"
                        ),
                    }
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = (
        f"{report.summary} "
        f"{report.probable_cause}"
    ).lower()

    assert "aws-platform-app-hpa" in diagnosis
    assert "failedgetresourcemetric" in diagnosis
    assert "missing cpu requests" in diagnosis
    assert "app" in diagnosis
    assert (
        "even though deployment cpu requests "
        "are present"
        not in diagnosis
    )
    assert report.confidence == Confidence.HIGH
    assert report.approval_required is True

def test_deterministic_report_detects_hpa_max_replica_limit(
    healthy_trace: list[ToolResult],
) -> None:
    healthy_trace.append(
        tool_result(
            "get_hpa",
            {
                "name": "aws-platform-app-hpa",
                "target": {
                    "kind": "Deployment",
                    "name": "aws-platform-app",
                },
                "min_replicas": 2,
                "max_replicas": 5,
                "current_replicas": 5,
                "desired_replicas": 5,
                "target_cpu_utilization": 50,
                "current_cpu_utilization": 92,
                "conditions": [
                    {
                        "type": "ScalingActive",
                        "status": "True",
                        "reason": "ValidMetricFound",
                        "message": (
                            "The HPA successfully calculated "
                            "a replica count from CPU metrics."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:00:00Z"
                        ),
                    },
                    {
                        "type": "ScalingLimited",
                        "status": "True",
                        "reason": "TooManyReplicas",
                        "message": (
                            "The desired replica count is "
                            "greater than the maximum "
                            "replica count."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:01:00Z"
                        ),
                    },
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = (
        f"{report.summary} "
        f"{report.probable_cause}"
    ).lower()

    assert "aws-platform-app-hpa" in diagnosis
    assert "toomanyreplicas" in diagnosis
    assert "maximum of 5 replicas" in diagnosis
    assert "92%" in diagnosis
    assert "target 50%" in diagnosis
    assert report.confidence == Confidence.HIGH
    assert report.approval_required is True

def test_llm_hpa_metric_failure_mismatch_falls_back(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["containers"] = [
        {
            "name": "app",
            "image": "example/app:1.0",
            "cpu_request": "250m",
            "memory_request": "256Mi",
            "cpu_limit": "500m",
            "memory_limit": "512Mi",
        }
    ]

    healthy_trace.append(
        tool_result(
            "get_hpa",
            {
                "name": "aws-platform-app-hpa",
                "target": {
                    "kind": "Deployment",
                    "name": "aws-platform-app",
                },
                "min_replicas": 2,
                "max_replicas": 5,
                "current_replicas": 2,
                "desired_replicas": 2,
                "target_cpu_utilization": 50,
                "current_cpu_utilization": None,
                "conditions": [
                    {
                        "type": "ScalingActive",
                        "status": "False",
                        "reason": (
                            "FailedGetResourceMetric"
                        ),
                        "message": (
                            "No metrics returned from "
                            "resource metrics API."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:00:00Z"
                        ),
                    }
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary=(
                "HPA aws-platform-app-hpa is healthy "
                "and scaling normally."
            ),
            probable_cause=(
                "CPU requests are present and the "
                "resource metrics API is available; "
                "no FailedGetResourceMetric condition "
                "exists."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "No further investigation is required."
            ),
        ),
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == report.summary
    assert (
        enriched.probable_cause
        == report.probable_cause
    )
    assert enriched.confidence == report.confidence
    assert enriched.tool_trace == report.tool_trace

def test_llm_hpa_metric_failure_diagnosis_is_accepted(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace[0].data["containers"] = [
        {
            "name": "app",
            "image": "example/app:1.0",
            "cpu_request": "250m",
            "memory_request": "256Mi",
            "cpu_limit": "500m",
            "memory_limit": "512Mi",
        }
    ]

    healthy_trace.append(
        tool_result(
            "get_hpa",
            {
                "name": "aws-platform-app-hpa",
                "target": {
                    "kind": "Deployment",
                    "name": "aws-platform-app",
                },
                "min_replicas": 2,
                "max_replicas": 5,
                "current_replicas": 2,
                "desired_replicas": 2,
                "target_cpu_utilization": 50,
                "current_cpu_utilization": None,
                "conditions": [
                    {
                        "type": "ScalingActive",
                        "status": "False",
                        "reason": (
                            "FailedGetResourceMetric"
                        ),
                        "message": (
                            "No metrics returned from "
                            "resource metrics API."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:00:00Z"
                        ),
                    }
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = LLMDiagnosis(
        summary=(
            "HPA aws-platform-app-hpa reports "
            "FailedGetResourceMetric."
        ),
        probable_cause=(
            "The resource metrics API is unavailable "
            "even though Deployment CPU requests "
            "are present."
        ),
        confidence=Confidence.HIGH,
        recommended_action=(
            "Check Metrics Server availability, logs, "
            "and metrics.k8s.io API registration."
        ),
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: diagnosis,
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == diagnosis.summary
    assert (
        enriched.probable_cause
        == diagnosis.probable_cause
    )
    assert (
        enriched.recommended_action
        == diagnosis.recommended_action
    )
    assert enriched.confidence == Confidence.HIGH
    assert enriched.summary != report.summary
    assert (
        enriched.approval_required
        == report.approval_required
    )
    assert enriched.tool_trace == report.tool_trace
    assert enriched.errors == report.errors

def test_llm_hpa_scaling_limit_mismatch_falls_back(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace.append(
        tool_result(
            "get_hpa",
            {
                "name": "aws-platform-app-hpa",
                "target": {
                    "kind": "Deployment",
                    "name": "aws-platform-app",
                },
                "min_replicas": 2,
                "max_replicas": 5,
                "current_replicas": 5,
                "desired_replicas": 5,
                "target_cpu_utilization": 50,
                "current_cpu_utilization": 92,
                "conditions": [
                    {
                        "type": "ScalingActive",
                        "status": "True",
                        "reason": "ValidMetricFound",
                        "message": (
                            "A replica count was calculated."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:00:00Z"
                        ),
                    },
                    {
                        "type": "ScalingLimited",
                        "status": "True",
                        "reason": "TooManyReplicas",
                        "message": (
                            "The desired replica count is "
                            "greater than the maximum."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:01:00Z"
                        ),
                    },
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: LLMDiagnosis(
            summary=(
                "HPA aws-platform-app-hpa is not "
                "limited and can continue scaling."
            ),
            probable_cause=(
                "TooManyReplicas is not active. The "
                "HPA has not reached its maximum of "
                "5 replicas, and CPU at 92% is below "
                "the target 50%."
            ),
            confidence=Confidence.HIGH,
            recommended_action=(
                "No scaling change is required."
            ),
        ),
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == report.summary
    assert (
        enriched.probable_cause
        == report.probable_cause
    )
    assert enriched.confidence == report.confidence
    assert enriched.tool_trace == report.tool_trace

def test_llm_hpa_scaling_limit_diagnosis_is_accepted(
    healthy_trace: list[ToolResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from platform_agent.contracts import LLMDiagnosis

    healthy_trace.append(
        tool_result(
            "get_hpa",
            {
                "name": "aws-platform-app-hpa",
                "target": {
                    "kind": "Deployment",
                    "name": "aws-platform-app",
                },
                "min_replicas": 2,
                "max_replicas": 5,
                "current_replicas": 5,
                "desired_replicas": 5,
                "target_cpu_utilization": 50,
                "current_cpu_utilization": 92,
                "conditions": [
                    {
                        "type": "ScalingActive",
                        "status": "True",
                        "reason": "ValidMetricFound",
                        "message": (
                            "A replica count was calculated."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:00:00Z"
                        ),
                    },
                    {
                        "type": "ScalingLimited",
                        "status": "True",
                        "reason": "TooManyReplicas",
                        "message": (
                            "The desired replica count is "
                            "greater than the maximum."
                        ),
                        "last_transition_time": (
                            "2026-10-26T05:01:00Z"
                        ),
                    },
                ],
            },
        )
    )

    report = (
        kubernetes_investigation
        .create_kubernetes_report(
            name="aws-platform-app",
            namespace="dev",
            trace=healthy_trace,
        )
    )

    diagnosis = LLMDiagnosis(
        summary=(
            "HPA aws-platform-app-hpa reports "
            "TooManyReplicas and is scaling limited."
        ),
        probable_cause=(
            "The HPA is limited at its maximum of "
            "5 replicas while CPU utilization at "
            "92% is above target 50%."
        ),
        confidence=Confidence.HIGH,
        recommended_action=(
            "Review workload capacity and approve an "
            "increase to maxReplicas if the cluster "
            "has sufficient resources."
        ),
    )

    monkeypatch.setattr(
        kubernetes_investigation,
        "diagnose_tool_trace",
        lambda trace: diagnosis,
    )

    enriched = (
        kubernetes_investigation
        .enrich_report_with_llm(
            report=report,
            trace=healthy_trace,
        )
    )

    assert enriched.summary == diagnosis.summary
    assert (
        enriched.probable_cause
        == diagnosis.probable_cause
    )
    assert (
        enriched.recommended_action
        == diagnosis.recommended_action
    )
    assert enriched.confidence == Confidence.HIGH
    assert enriched.summary != report.summary
    assert (
        enriched.approval_required
        == report.approval_required
    )
    assert enriched.tool_trace == report.tool_trace
    assert enriched.errors == report.errors
