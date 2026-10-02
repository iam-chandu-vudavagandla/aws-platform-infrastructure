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
LABEL_SELECTOR_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9./_-]*="
    r"[A-Za-z0-9][A-Za-z0-9._-]*"
    r"(?:,[A-Za-z0-9][A-Za-z0-9./_-]*="
    r"[A-Za-z0-9][A-Za-z0-9._-]*)*$"
)


def validate_dns_label(value: str, field_name: str) -> str:
    """Validate a Kubernetes DNS-label value."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")

    if not value or len(value) > 63:
        raise ValueError(f"{field_name} must contain between 1 and 63 characters.")

    if DNS_LABEL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a valid Kubernetes DNS label.")

    return value


def validate_label_selector(selector: str) -> str:
    """Validate a restricted equality-based label selector."""

    if not isinstance(selector, str):
        raise TypeError("selector must be a string.")

    if not selector:
        raise ValueError("selector must not be empty.")

    if len(selector) > 253:
        raise ValueError("selector must not exceed 253 characters.")

    if LABEL_SELECTOR_PATTERN.fullmatch(selector) is None:
        raise ValueError("selector must contain comma-separated key=value labels.")

    return selector


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


def get_pods(
    namespace: str = DEFAULT_NAMESPACE,
    selector: str | None = None,
) -> dict[str, Any]:
    """Return a safe summary of pods in one namespace."""

    namespace = validate_dns_label(namespace, "namespace")

    arguments = [
        "get",
        "pods",
        "--namespace",
        namespace,
    ]

    if selector is not None:
        selector = validate_label_selector(selector)
        arguments.extend(
            [
                "--selector",
                selector,
            ]
        )

    payload = run_kubectl(arguments)
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
        "selector": selector,
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
    match_labels = spec.get("selector", {}).get(
        "matchLabels",
        {},
    )

    selector = ",".join(
        f"{key}={value}"
        for key, value in sorted(match_labels.items())
        if isinstance(key, str) and isinstance(value, str)
    )

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
        "selector": selector,
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


def get_events(
    namespace: str = DEFAULT_NAMESPACE,
    limit: int = 20,
) -> dict[str, Any]:
    """Return the most recent Kubernetes events in a namespace."""

    namespace = validate_dns_label(namespace, "namespace")

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer.")

    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100.")

    payload = run_kubectl(
        [
            "get",
            "events",
            "--namespace",
            namespace,
        ]
    )

    def last_event_time(event: dict[str, Any]) -> str:
        metadata = event.get("metadata", {})
        series = event.get("series") or {}

        return (
            event.get("eventTime")
            or series.get("lastObservedTime")
            or event.get("lastTimestamp")
            or metadata.get("creationTimestamp")
            or ""
        )

    sorted_events = sorted(
        payload.get("items", []),
        key=last_event_time,
        reverse=True,
    )

    events = []

    for event in sorted_events[:limit]:
        metadata = event.get("metadata", {})
        involved_object = event.get("involvedObject", {})
        series = event.get("series") or {}

        events.append(
            {
                "type": event.get("type", "Unknown"),
                "reason": event.get("reason", "Unknown"),
                "message": event.get("message", ""),
                "count": (series.get("count") or event.get("count") or 1),
                "object_kind": involved_object.get("kind"),
                "object_name": involved_object.get("name"),
                "first_timestamp": (
                    event.get("firstTimestamp") or metadata.get("creationTimestamp")
                ),
                "last_timestamp": last_event_time(event),
            }
        )

    return {
        "context": KUBERNETES_CONTEXT,
        "namespace": namespace,
        "total_events": len(payload.get("items", [])),
        "returned_events": len(events),
        "limit": limit,
        "events": events,
    }


def run_kubectl_text(arguments: list[str]) -> str:
    """Execute a predefined read-only kubectl command returning text."""

    command = [
        "kubectl",
        "--context",
        KUBERNETES_CONTEXT,
        *arguments,
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

    return completed.stdout


def get_pod_logs(
    pod: str,
    namespace: str = DEFAULT_NAMESPACE,
    container: str | None = None,
    tail_lines: int = 100,
    since_seconds: int = 600,
) -> dict[str, Any]:
    """Return bounded recent logs from one Kubernetes pod."""

    pod = validate_dns_label(pod, "pod")
    namespace = validate_dns_label(namespace, "namespace")

    if container is not None:
        container = validate_dns_label(container, "container")

    if isinstance(tail_lines, bool) or not isinstance(tail_lines, int):
        raise TypeError("tail_lines must be an integer.")

    if tail_lines < 1 or tail_lines > 500:
        raise ValueError("tail_lines must be between 1 and 500.")

    if isinstance(since_seconds, bool) or not isinstance(since_seconds, int):
        raise TypeError("since_seconds must be an integer.")

    if since_seconds < 1 or since_seconds > 86400:
        raise ValueError("since_seconds must be between 1 and 86400.")

    arguments = [
        "logs",
        pod,
        "--namespace",
        namespace,
        f"--tail={tail_lines}",
        f"--since={since_seconds}s",
        "--timestamps=true",
    ]

    if container is not None:
        arguments.extend(
            [
                "--container",
                container,
            ]
        )

    output = run_kubectl_text(arguments)
    maximum_characters = 50000
    truncated = len(output) > maximum_characters

    if truncated:
        output = output[-maximum_characters:]

    lines = output.splitlines()

    return {
        "context": KUBERNETES_CONTEXT,
        "namespace": namespace,
        "pod": pod,
        "container": container,
        "tail_lines": tail_lines,
        "since_seconds": since_seconds,
        "line_count": len(lines),
        "truncated": truncated,
        "logs": lines,
    }
