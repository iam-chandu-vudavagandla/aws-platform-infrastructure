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
