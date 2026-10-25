import json
import subprocess

import pytest
from platform_agent.tools import kubernetes
from platform_agent.tool_registry import execute_tool

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
            "name": "aws-platform-app",
            "ready": True,
            "restartCount": 0,
            "state": {
                "running": {
                    "startedAt": "2026-09-25T17:45:00Z",
                }
             },
                 "lastState": {},
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
    assert result["returned_pods"] == 1
    assert result["truncated"] is False
    assert result["pods"][0]["phase"] == "Running"
    assert result["pods"][0]["ready_containers"] == 1
    assert result["pods"][0]["restarts"] == 0
    container = result["pods"][0]["containers"][0]

    assert container["name"] == "aws-platform-app"
    assert container["ready"] is True
    assert container["restart_count"] == 0
    assert container["state"] == "running"
    assert container["state_reason"] is None
    assert container["last_state"] is None
    assert container["last_reason"] is None
    assert container["last_exit_code"] is None
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


def test_get_pod_logs_returns_bounded_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_arguments: list[str] = []

    def fake_run_kubectl_text(arguments: list[str]) -> str:
        captured_arguments.extend(arguments)
        return (
            "2026-09-30T01:00:00Z application started\n"
            "2026-09-30T01:00:01Z health check passed\n"
        )

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl_text",
        fake_run_kubectl_text,
    )

    result = kubernetes.get_pod_logs(
        pod="aws-platform-app-abc123",
        namespace="dev",
        container="aws-platform-app",
        tail_lines=50,
        since_seconds=300,
    )

    assert captured_arguments == [
        "logs",
        "aws-platform-app-abc123",
        "--namespace",
        "dev",
        "--tail=50",
        "--since=300s",
        "--timestamps=true",
        "--container",
        "aws-platform-app",
    ]
    assert result["pod"] == "aws-platform-app-abc123"
    assert result["container"] == "aws-platform-app"
    assert result["line_count"] == 2
    assert result["truncated"] is False
    assert result["logs"] == [
        "2026-09-30T01:00:00Z application started",
        "2026-09-30T01:00:01Z health check passed",
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tail_lines", 0, "tail_lines must be between"),
        ("tail_lines", 501, "tail_lines must be between"),
        ("tail_lines", True, "tail_lines must be an integer"),
        ("since_seconds", 0, "since_seconds must be between"),
        ("since_seconds", 86401, "since_seconds must be between"),
        ("since_seconds", True, "since_seconds must be an integer"),
    ],
)
def test_get_pod_logs_rejects_invalid_bounds(
    field: str,
    value: int,
    message: str,
) -> None:
    arguments = {
        "pod": "aws-platform-app-abc123",
        field: value,
    }

    with pytest.raises(
        (TypeError, ValueError),
        match=message,
    ):
        kubernetes.get_pod_logs(**arguments)


def test_get_pod_logs_rejects_unsafe_pod_name() -> None:
    with pytest.raises(
        ValueError,
        match="valid Kubernetes DNS label",
    ):
        kubernetes.get_pod_logs(
            pod="pod;delete-all",
            namespace="dev",
        )


def test_get_pods_reports_container_failure_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "items": [
            {
                "metadata": {
                    "name": "crashloop-demo-abc123",
                },
                "spec": {
                    "nodeName": "worker-node-1",
                },
                "status": {
                    "phase": "Running",
                    "podIP": "10.0.11.50",
                    "containerStatuses": [
                        {
                            "name": "busybox",
                            "ready": False,
                            "restartCount": 12,
                            "state": {
                                "waiting": {
                                    "reason": "CrashLoopBackOff",
                                    "message": "back-off restarting failed container",
                                }
                            },
                            "lastState": {
                                "terminated": {
                                    "reason": "Error",
                                    "exitCode": 1,
                                }
                            },
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

    result = kubernetes.get_pods(
        "dev",
        selector="app=crashloop-demo",
    )

    pod = result["pods"][0]
    container = pod["containers"][0]

    assert pod["phase"] == "Running"
    assert pod["ready_containers"] == 0
    assert pod["restarts"] == 12

    assert container["name"] == "busybox"
    assert container["ready"] is False
    assert container["restart_count"] == 12
    assert container["state"] == "waiting"
    assert container["state_reason"] == "CrashLoopBackOff"
    assert container["last_state"] == "terminated"
    assert container["last_reason"] == "Error"
    assert container["last_exit_code"] == 1


def test_get_pods_bounds_large_pod_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = []

    for index in range(120):
        items.append(
            {
                "metadata": {
                    "name": f"eviction-demo-{index:03d}",
                    "creationTimestamp": (
                        f"2026-10-14T"
                        f"{index // 60:02d}:"
                        f"{index % 60:02d}:00Z"
                    ),
                },
                "spec": {
                    "nodeName": "worker-node-1",
                },
                "status": {
                    "phase": "Failed",
                    "containerStatuses": [],
                },
            }
        )

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        lambda arguments: {"items": items},
    )

    result = kubernetes.get_pods(
        namespace="dev",
        selector="app=eviction-demo",
    )

    assert result["count"] == 120
    assert result["returned_pods"] == 50
    assert result["truncated"] is True
    assert len(result["pods"]) == 50

    assert result["pods"][0]["name"] == "eviction-demo-119"
    assert result["pods"][-1]["name"] == "eviction-demo-070"


def test_get_pods_preserves_pod_failure_reason_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "items": [
            {
                "metadata": {
                    "name": "eviction-demo-pod",
                },
                "spec": {
                    "nodeName": "worker-node-1",
                },
                "status": {
                    "phase": "Failed",
                    "reason": "Evicted",
                    "message": (
                        "Pod ephemeral local storage usage exceeds "
                        "the total limit of containers 32Mi."
                    ),
                    "containerStatuses": [],
                },
            }
        ]
    }

    monkeypatch.setattr(
        kubernetes.subprocess,
        "run",
        lambda *args, **kwargs: successful_result(payload),
    )

    result = kubernetes.get_pods(
        "dev",
        selector="app=eviction-demo",
    )

    pod = result["pods"][0]

    assert pod["phase"] == "Failed"
    assert pod["reason"] == "Evicted"
    assert (
        pod["message"]
        == (
            "Pod ephemeral local storage usage exceeds "
            "the total limit of containers 32Mi."
        )
    )

def test_get_service_endpoints_returns_sanitized_network_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_payload = {
        "metadata": {
            "name": "aws-platform-app-service",
        },
        "spec": {
            "type": "ClusterIP",
            "selector": {
                "app": "aws-platform-app",
            },
            "ports": [
                {
                    "name": "http",
                    "protocol": "TCP",
                    "port": 80,
                    "targetPort": "http",
                }
            ],
        },
    }

    endpoint_slice_payload = {
        "items": [
            {
                "metadata": {
                    "name": (
                        "aws-platform-app-service-abc12"
                    ),
                },
                "addressType": "IPv4",
                "ports": [
                    {
                        "name": "http",
                        "protocol": "TCP",
                        "port": 8080,
                    }
                ],
                "endpoints": [
                    {
                        "addresses": [
                            "10.0.11.20",
                        ],
                        "conditions": {
                            "ready": True,
                        },
                    },
                    {
                        "addresses": [
                            "10.0.12.30",
                        ],
                        "conditions": {
                            "ready": False,
                        },
                    },
                ],
            }
        ]
    }

    payloads = iter(
        [
            service_payload,
            endpoint_slice_payload,
        ]
    )
    calls: list[list[str]] = []

    def fake_run_kubectl(
        arguments: list[str],
    ) -> dict:
        calls.append(arguments)
        return next(payloads)

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        fake_run_kubectl,
    )

    result = kubernetes.get_service_endpoints(
        service="aws-platform-app-service",
        namespace="dev",
    )

    assert calls == [
        [
            "get",
            "service",
            "aws-platform-app-service",
            "--namespace",
            "dev",
        ],
        [
            "get",
            "endpointslices",
            "--namespace",
            "dev",
            "--selector",
            (
                "kubernetes.io/service-name="
                "aws-platform-app-service"
            ),
        ],
    ]

    assert result["service"] == (
        "aws-platform-app-service"
    )
    assert result["type"] == "ClusterIP"
    assert result["selector"] == {
        "app": "aws-platform-app",
    }
    assert result["ports"] == [
        {
            "name": "http",
            "protocol": "TCP",
            "port": 80,
            "target_port": "http",
        }
    ]
    assert result["endpoint_slice_count"] == 1
    assert result["ready_endpoint_count"] == 1
    assert result["not_ready_endpoint_count"] == 1
    assert result["ready_addresses"] == [
        "10.0.11.20",
    ]
    assert result["not_ready_addresses"] == [
        "10.0.12.30",
    ]

def test_get_service_endpoints_rejects_unsafe_name() -> None:
    with pytest.raises(
        ValueError,
        match="valid Kubernetes DNS label",
    ):
        kubernetes.get_service_endpoints(
            service="../production",
            namespace="dev",
        )


def test_registry_allows_get_service_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = iter(
        [
            {
                "metadata": {
                    "name": "aws-platform-app-service",
                },
                "spec": {
                    "type": "ClusterIP",
                    "selector": {
                        "app": "aws-platform-app",
                    },
                    "ports": [
                        {
                            "name": "http",
                            "protocol": "TCP",
                            "port": 80,
                            "targetPort": "http",
                        }
                    ],
                },
            },
            {
                "items": [],
            },
        ]
    )

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        lambda arguments: next(payloads),
    )

    result = execute_tool(
        "get_service_endpoints",
        {
            "service": (
                "aws-platform-app-service"
            ),
            "namespace": "dev",
        },
    )

    assert result.success is True
    assert result.data["service"] == (
        "aws-platform-app-service"
    )
    assert result.data[
        "ready_endpoint_count"
    ] == 0

def test_get_pods_returns_sanitized_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "items": [
            {
                "metadata": {
                    "name": "app-123",
                    "labels": {
                        "app": "aws-platform-app",
                        "environment": "dev",
                    },
                },
                "spec": {
                    "nodeName": "worker-1",
                },
                "status": {
                    "phase": "Running",
                    "podIP": "10.0.11.20",
                    "containerStatuses": [],
                },
            }
        ]
    }

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        lambda arguments: payload,
    )

    result = kubernetes.get_pods(
        namespace="dev",
        selector="app=aws-platform-app",
    )

    assert result["pods"][0]["labels"] == {
        "app": "aws-platform-app",
        "environment": "dev",
    }

def test_get_network_policies_returns_sanitized_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "items": [
            {
                "metadata": {
                    "name": "deny-app-egress",
                },
                "spec": {
                    "podSelector": {
                        "matchLabels": {
                            "app": "aws-platform-app",
                        },
                    },
                    "policyTypes": [
                        "Egress",
                    ],
                    "egress": [],
                },
            }
        ]
    }

    captured_arguments: list[str] = []

    def fake_run_kubectl(
        arguments: list[str],
    ) -> dict:
        captured_arguments.extend(arguments)
        return payload

    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        fake_run_kubectl,
    )

    result = kubernetes.get_network_policies(
        namespace="dev",
    )

    assert captured_arguments == [
        "get",
        "networkpolicies",
        "--namespace",
        "dev",
    ]
    assert result["namespace"] == "dev"
    assert result["count"] == 1
    assert result["returned_policies"] == 1
    assert result["truncated"] is False
    assert result["policies"] == [
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
    ]

def test_get_network_policies_rejects_unsafe_namespace() -> None:
    with pytest.raises(
        ValueError,
        match="valid Kubernetes DNS label",
    ):
        kubernetes.get_network_policies(
            namespace="--all-namespaces",
        )

def test_registry_allows_get_network_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        kubernetes,
        "run_kubectl",
        lambda arguments: {
            "items": [],
        },
    )

    result = execute_tool(
        "get_network_policies",
        {
            "namespace": "dev",
        },
    )

    assert result.success is True
    assert result.error is None
    assert result.data["namespace"] == "dev"
    assert result.data["count"] == 0
    assert result.data["policies"] == []
