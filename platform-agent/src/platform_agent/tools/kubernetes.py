import json
import os
import re
import subprocess
from typing import Any

AWS_PROFILE = "aws-platform-new"
AWS_REGION = "ap-south-1"
KUBERNETES_CONTEXT = "aws-platform-dev-new"
DEFAULT_NAMESPACE = "dev"
COMMAND_TIMEOUT_SECONDS = 20

DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")


def validate_dns_label(value: str, field_name: str) -> str:
    """Validate a Kubernetes DNS-label value."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if not value or len(value) > 63:
        raise ValueError(f"{field_name} must contain between 1 and 63 characters.")

    if DNS_LABEL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a valid Kubernetes DNS label.")

    return value


def run_kubectl(arguments: list[str]) -> dict[str, Any]:
    """Execute a predefined read-only kubectl command."""

    command = [
        "kubectl",
        "--context",
        KUBERNETES_CONTEXT,
        *arguments,
        "--output=json",
        "--request-timeout=15s",
    ]

    environment = os.environ.copy()
    environment["AWS_PROFILE"] = AWS_PROFILE
    environment["AWS_REGION"] = AWS_REGION

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise ValueError("kubectl is not installed or not in PATH.") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("kubectl command timed out.") from error

    if completed.returncode != 0:
        error_message = (
            completed.stderr.strip() or "kubectl returned a non-zero exit code."
        )
        raise ValueError(error_message)

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("kubectl returned invalid JSON.") from error

    if not isinstance(payload, dict):
        raise TypeError("kubectl returned an unexpected response.")

    return payload


def get_pods(namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
    """Return a safe summary of pods in one namespace."""

    namespace = validate_dns_label(namespace, "namespace")

    payload = run_kubectl(
        [
            "get",
            "pods",
            "--namespace",
            namespace,
        ]
    )

    pods = []

    for item in payload.get("items", []):
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})
        container_statuses = status.get("containerStatuses", [])
        pods.append(
            {
                "name": metadata.get("name", "unknown"),
                "phase": status.get("phase", "Unknown"),
                "ready_containers": sum(
                    1
                    for container in container_statuses
                    if container.get("ready") is True
                ),
                "total_containers": len(container_statuses),
                "restarts": sum(
                    container.get("restartCount", 0) for container in container_statuses
                ),
                "node": spec.get("nodeName"),
                "pod_ip": status.get("podIP"),
            }
        )

    return {
        "context": KUBERNETES_CONTEXT,
        "namespace": namespace,
        "count": len(pods),
        "pods": pods,
    }


def get_deployment(
    name: str,
    namespace: str = DEFAULT_NAMESPACE,
) -> dict[str, Any]:
    """Return a safe summary of one Kubernetes deployment."""

    name = validate_dns_label(name, "name")
    namespace = validate_dns_label(namespace, "namespace")

    payload = run_kubectl(
        [
            "get",
            "deployment",
            name,
            "--namespace",
            namespace,
        ]
    )

    metadata = payload.get("metadata", {})
    spec = payload.get("spec", {})
    status = payload.get("status", {})

    containers = [
        {
            "name": container.get("name", "unknown"),
            "image": container.get("image", "unknown"),
        }
        for container in (
            spec.get("template", {}).get("spec", {}).get("containers", [])
        )
    ]

    conditions = [
        {
            "type": condition.get("type"),
            "status": condition.get("status"),
            "reason": condition.get("reason"),
            "message": condition.get("message"),
            "last_transition_time": condition.get("lastTransitionTime"),
        }
        for condition in status.get("conditions", [])
    ]

    return {
        "context": KUBERNETES_CONTEXT,
        "namespace": namespace,
        "name": metadata.get("name", name),
        "generation": metadata.get("generation"),
        "observed_generation": status.get("observedGeneration"),
        "desired_replicas": spec.get("replicas", 0),
        "current_replicas": status.get("replicas", 0),
        "updated_replicas": status.get(
            "updatedReplicas",
            0,
        ),
        "ready_replicas": status.get("readyReplicas", 0),
        "available_replicas": status.get(
            "availableReplicas",
            0,
        ),
        "unavailable_replicas": status.get(
            "unavailableReplicas",
            0,
        ),
        "containers": containers,
        "conditions": conditions,
    }
