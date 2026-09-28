import json
import subprocess

import pytest
from platform_agent.tools import kubernetes


def successful_result(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["kubectl"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_get_pods_returns_safe_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "items": [
            {
                "metadata": {
                    "name": "aws-platform-app-abc123",
                },
                "spec": {
                    "nodeName": "worker-node-1",
                },
                "status": {
                    "phase": "Running",
                    "podIP": "10.0.11.25",
                    "containerStatuses": [
                        {
                            "ready": True,
                            "restartCount": 0,
                        }
                    ],
                },
            }
        ]
    }

    monkeypatch.setattr(
        kubernetes.subprocess,
        "run",
        lambda *args, **kwargs: successful_result(payload),
    )

    result = kubernetes.get_pods("dev")

    assert result["namespace"] == "dev"
    assert result["count"] == 1
    assert result["pods"][0]["phase"] == "Running"
    assert result["pods"][0]["ready_containers"] == 1
    assert result["pods"][0]["restarts"] == 0
    assert result["pods"][0]["node"] == "worker-node-1"


def test_invalid_namespace_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="valid Kubernetes DNS label",
    ):
        kubernetes.get_pods("--all-namespaces")


def test_kubectl_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = subprocess.CompletedProcess(
        args=["kubectl"],
        returncode=1,
        stdout="",
        stderr="Unable to connect to the server",
    )

    monkeypatch.setattr(
        kubernetes.subprocess,
        "run",
        lambda *args, **kwargs: failure,
    )

    with pytest.raises(
        ValueError,
        match="Unable to connect",
    ):
        kubernetes.get_pods("dev")


def test_kubectl_timeout_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["kubectl"],
            timeout=20,
        )

    monkeypatch.setattr(
        kubernetes.subprocess,
        "run",
        raise_timeout,
    )

    with pytest.raises(
        ValueError,
        match="timed out",
    ):
        kubernetes.get_pods("dev")


def test_get_deployment_returns_health_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "metadata": {
            "name": "aws-platform-app",
            "generation": 4,
        },
        "spec": {
            "replicas": 2,
            "selector": {
                "matchLabels": {
                    "app": "aws-platform-app",
                }
            },
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "aws-platform-app",
                            "image": "example/app@sha256:test",
                        }
                    ]
                }
            },
        },
        "status": {
            "observedGeneration": 4,
            "replicas": 2,
            "updatedReplicas": 2,
            "readyReplicas": 2,
            "availableReplicas": 2,
            "conditions": [
                {
                    "type": "Available",
                    "status": "True",
                    "reason": "MinimumReplicasAvailable",
                    "message": "Deployment has minimum availability.",
                    "lastTransitionTime": "2026-09-25T17:45:00Z",
                }
            ],
        },
    }

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        lambda arguments: payload,
    )

    result = kubernetes.get_deployment(
        "aws-platform-app",
        "dev",
    )

    assert result["name"] == "aws-platform-app"
    assert result["desired_replicas"] == 2
    assert result["updated_replicas"] == 2
    assert result["ready_replicas"] == 2
    assert result["available_replicas"] == 2
    assert result["unavailable_replicas"] == 0
    assert result["containers"][0]["name"] == ("aws-platform-app")
    assert result["conditions"][0]["status"] == "True"
    assert result["selector"] == "app=aws-platform-app"


def test_get_deployment_rejects_unsafe_name() -> None:
    with pytest.raises(
        ValueError,
        match="valid Kubernetes DNS label",
    ):
        kubernetes.get_deployment(
            "--all-namespaces",
            "dev",
        )


def test_get_events_returns_newest_events_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "items": [
            {
                "metadata": {
                    "creationTimestamp": "2026-09-25T10:00:00Z",
                },
                "type": "Normal",
                "reason": "Scheduled",
                "message": "Pod scheduled successfully.",
                "count": 1,
                "lastTimestamp": "2026-09-25T10:01:00Z",
                "involvedObject": {
                    "kind": "Pod",
                    "name": "older-pod",
                },
            },
            {
                "metadata": {
                    "creationTimestamp": "2026-09-25T11:00:00Z",
                },
                "type": "Warning",
                "reason": "Unhealthy",
                "message": "Startup probe failed.",
                "count": 2,
                "lastTimestamp": "2026-09-25T11:02:00Z",
                "involvedObject": {
                    "kind": "Pod",
                    "name": "newer-pod",
                },
            },
        ]
    }

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        lambda arguments: payload,
    )

    result = kubernetes.get_events(
        namespace="dev",
        limit=1,
    )

    assert result["total_events"] == 2
    assert result["returned_events"] == 1
    assert result["events"][0]["reason"] == "Unhealthy"
    assert result["events"][0]["object_name"] == "newer-pod"
    assert result["events"][0]["count"] == 2


@pytest.mark.parametrize("limit", [0, 101])
def test_get_events_rejects_limit_outside_range(
    limit: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="between 1 and 100",
    ):
        kubernetes.get_events(
            namespace="dev",
            limit=limit,
        )


def test_get_events_rejects_non_integer_limit() -> None:
    with pytest.raises(
        TypeError,
        match="must be an integer",
    ):
        kubernetes.get_events(
            namespace="dev",
            limit=True,
        )


def test_get_pods_uses_validated_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_arguments: list[str] = []

    def fake_run_kubectl(
        arguments: list[str],
    ) -> dict:
        captured_arguments.extend(arguments)
        return {"items": []}

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        fake_run_kubectl,
    )

    result = kubernetes.get_pods(
        namespace="dev",
        selector="app=aws-platform-app",
    )

    assert captured_arguments == [
        "get",
        "pods",
        "--namespace",
        "dev",
        "--selector",
        "app=aws-platform-app",
    ]
    assert result["selector"] == "app=aws-platform-app"


@pytest.mark.parametrize(
    "selector",
    [
        "",
        "--all-namespaces",
        "app in (one,two)",
        "app=valid;delete=pods",
    ],
)
def test_get_pods_rejects_unsafe_selector(
    selector: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="selector",
    ):
        kubernetes.get_pods(
            namespace="dev",
            selector=selector,
        )
