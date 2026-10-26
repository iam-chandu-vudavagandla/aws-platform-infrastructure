import re
from platform_agent.agent import evidence_from_trace
from platform_agent.contracts import Confidence, IncidentReport, ToolResult
from platform_agent.llm import LLMError, diagnose_tool_trace
from platform_agent.tool_registry import execute_tool
from typing import Any

def _failed_report(
    name: str,
    namespace: str,
    trace: list[ToolResult],
) -> IncidentReport:
    errors = [result.error for result in trace if result.error is not None]

    return IncidentReport(
        summary=(
            f"Kubernetes investigation of deployment {name} "
            f"in namespace {namespace} stopped because a tool failed."
        ),
        probable_cause=(
            "The agent could not collect all required Kubernetes evidence."
        ),
        evidence=evidence_from_trace(trace),
        confidence=Confidence.LOW,
        recommended_action=(
            "Review the reported tool error, restore read access, "
            "and run the investigation again."
        ),
        approval_required=False,
        tool_trace=trace,
        errors=errors,
    )


def _find_result(
    trace: list[ToolResult],
    tool: str,
) -> ToolResult:
    return next(result for result in trace if result.tool == tool)

DNS_LOOKUP_FAILURE_PATTERN = re.compile(
    (
        r"\blookup\s+"
        r"(?P<target>[a-z0-9][a-z0-9._-]*)"
        r".*?\b"
        r"(?P<signal>no such host|nxdomain|servfail)\b"
    ),
    re.IGNORECASE,
)


def _trace_dns_resolution_failure(
    trace: list[ToolResult],
) -> tuple[str, str] | None:
    """Return DNS target and failure signal from pod logs."""

    for result in trace:
        if (
            result.tool != "get_pod_logs"
            or not result.success
        ):
            continue

        for line in result.data.get("logs", []):
            if not isinstance(line, str):
                continue

            match = DNS_LOOKUP_FAILURE_PATTERN.search(
                line
            )

            if match is not None:
                return (
                    match.group("target"),
                    match.group("signal").lower(),
                )

    return None

def _labels_match_selector(
    labels: object,
    selector: object,
) -> bool:
    """Return whether pod labels match a policy selector."""

    if (
        not isinstance(labels, dict)
        or not isinstance(selector, dict)
    ):
        return False

    if not selector:
        # An empty NetworkPolicy podSelector selects
        # every pod in the namespace.
        return True

    return all(
        isinstance(key, str)
        and isinstance(value, str)
        and labels.get(key) == value
        for key, value in selector.items()
    )


def _trace_default_deny_egress_policy(
    trace: list[ToolResult],
) -> tuple[str, str] | None:
    """Return policy and pod affected by denied egress."""

    if _trace_dns_resolution_failure(trace) is None:
        return None

    pods: list[dict[str, Any]] = []

    for result in trace:
        if (
            result.tool != "get_pods"
            or not result.success
        ):
            continue

        result_pods = result.data.get(
            "pods",
            [],
        )

        if isinstance(result_pods, list):
            pods.extend(
                pod
                for pod in result_pods
                if isinstance(pod, dict)
            )

    for result in trace:
        if (
            result.tool != "get_network_policies"
            or not result.success
        ):
            continue

        policies = result.data.get(
            "policies",
            [],
        )

        if not isinstance(policies, list):
            continue

        for policy in policies:
            if (
                not isinstance(policy, dict)
                or policy.get(
                    "default_deny_egress"
                )
                is not True
                or policy.get(
                    "has_match_expressions"
                )
                is True
            ):
                continue

            policy_name = policy.get("name")
            selector = policy.get(
                "pod_selector"
            )

            if (
                not isinstance(policy_name, str)
                or not policy_name
            ):
                continue

            for pod in pods:
                pod_name = pod.get("name")
                pod_labels = pod.get("labels")

                if (
                    isinstance(pod_name, str)
                    and pod_name
                    and _labels_match_selector(
                        pod_labels,
                        selector,
                    )
                ):
                    return (
                        policy_name,
                        pod_name,
                    )

    return None

def _diagnosis_preserves_default_deny_egress(
    policy_name: str,
    pod_name: str,
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves denied egress."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    deny_signal_preserved = any(
        phrase in diagnosis_text
        for phrase in (
            "default-deny egress",
            "default deny egress",
            "denies all egress",
            "blocks all egress",
            "egress is denied",
            "egress traffic is denied",
            "egress is blocked",
        )
    )

    contradictory_allow_claim = any(
        phrase in diagnosis_text
        for phrase in (
            "allows all egress",
            "allows egress traffic",
            "egress is allowed",
            "does not block egress",
            "does not deny egress",
        )
    )

    return (
        policy_name.lower() in diagnosis_text
        and pod_name.lower() in diagnosis_text
        and deny_signal_preserved
        and not contradictory_allow_claim
    )

def _diagnosis_preserves_dns_resolution_failure(
    dns_target: str,
    dns_signal: str,
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether the diagnosis preserves DNS evidence."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    preserves_dns_context = (
        "dns" in diagnosis_text
        or "name resolution" in diagnosis_text
        or "lookup" in diagnosis_text
    )

    return (
        preserves_dns_context
        and dns_target.lower() in diagnosis_text
        and dns_signal.lower() in diagnosis_text
    )

def _trace_service_without_ready_endpoints(
    trace: list[ToolResult],
) -> str | None:
    """Return the Service with zero ready endpoints."""

    for result in trace:
        if (
            result.tool
            != "get_service_endpoints"
            or not result.success
        ):
            continue

        ready_count = result.data.get(
            "ready_endpoint_count"
        )
        service = result.data.get("service")

        if (
            isinstance(ready_count, int)
            and not isinstance(ready_count, bool)
            and ready_count == 0
            and isinstance(service, str)
            and service
        ):
            return service

    return None

def _selector_to_text(
    selector: object,
) -> str | None:
    """Return a canonical selector string."""

    if isinstance(selector, str):
        labels = [
            label.strip()
            for label in selector.split(",")
            if label.strip()
        ]

        if not labels:
            return None

        return ",".join(sorted(labels))

    if isinstance(selector, dict):
        labels = []

        for key, value in selector.items():
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value
            ):
                return None

            labels.append(f"{key}={value}")

        if not labels:
            return None

        return ",".join(sorted(labels))

    return None


def _trace_service_selector_mismatch(
    trace: list[ToolResult],
) -> tuple[str, str, str] | None:
    """Return mismatched Deployment and Service selectors."""

    deployment_selector = None

    for result in trace:
        if (
            result.tool == "get_deployment"
            and result.success
        ):
            deployment_selector = _selector_to_text(
                result.data.get("selector")
            )
            break

    if deployment_selector is None:
        return None

    for result in trace:
        if (
            result.tool != "get_service_endpoints"
            or not result.success
        ):
            continue

        service = result.data.get("service")
        service_selector = _selector_to_text(
            result.data.get("selector")
        )

        if (
            isinstance(service, str)
            and service
            and service_selector is not None
            and service_selector
            != deployment_selector
        ):
            return (
                service,
                deployment_selector,
                service_selector,
            )

    return None

def _diagnosis_preserves_service_selector_mismatch(
    service: str,
    deployment_selector: str,
    service_selector: str,
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves selector mismatch."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    mismatch_signal_preserved = any(
        phrase in diagnosis_text
        for phrase in (
            "selector mismatch",
            "selectors do not match",
            "selector does not match",
            "selectors differ",
            "different selector",
            "mismatched selector",
        )
    )

    return (
        service.lower() in diagnosis_text
        and deployment_selector.lower()
        in diagnosis_text
        and service_selector.lower()
        in diagnosis_text
        and mismatch_signal_preserved
    )

def _selector_to_text(
    selector: object,
) -> str | None:
    """Return a canonical selector string."""

    if isinstance(selector, str):
        labels = [
            label.strip()
            for label in selector.split(",")
            if label.strip()
        ]

        if not labels:
            return None

        return ",".join(sorted(labels))

    if isinstance(selector, dict):
        labels = []

        for key, value in selector.items():
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value
            ):
                return None

            labels.append(f"{key}={value}")

        if not labels:
            return None

        return ",".join(sorted(labels))

    return None


def _trace_service_selector_mismatch(
    trace: list[ToolResult],
) -> tuple[str, str, str] | None:
    """Return mismatched Deployment and Service selectors."""

    deployment_selector = None

    for result in trace:
        if (
            result.tool == "get_deployment"
            and result.success
        ):
            deployment_selector = _selector_to_text(
                result.data.get("selector")
            )
            break

    if deployment_selector is None:
        return None

    for result in trace:
        if (
            result.tool != "get_service_endpoints"
            or not result.success
        ):
            continue

        service = result.data.get("service")
        service_selector = _selector_to_text(
            result.data.get("selector")
        )

        if (
            isinstance(service, str)
            and service
            and service_selector is not None
            and service_selector
            != deployment_selector
        ):
            return (
                service,
                deployment_selector,
                service_selector,
            )

    return None

def _diagnosis_preserves_zero_endpoint_evidence(
    service: str,
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves zero endpoints."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    endpoint_signal_preserved = any(
        phrase in diagnosis_text
        for phrase in (
            "zero ready endpoints",
            "no ready endpoints",
            "has no endpoints",
            "does not have ready endpoints",
        )
    )

    return (
        service.lower() in diagnosis_text
        and endpoint_signal_preserved
    )

def create_kubernetes_report(
    name: str,
    namespace: str,
    trace: list[ToolResult],
) -> IncidentReport:
    """Correlate deployment, pod, and event evidence."""

    if any(not result.success for result in trace):
        return _failed_report(name, namespace, trace)

    deployment = _find_result(trace, "get_deployment").data
    pods = _find_result(trace, "get_pods").data
    events = _find_result(trace, "get_events").data

    findings: list[str] = []

    generation = deployment.get("generation")
    observed_generation = deployment.get("observed_generation")

    if (
        isinstance(generation, int)
        and isinstance(observed_generation, int)
        and observed_generation < generation
    ):
        findings.append(
            "The deployment controller has not observed the latest generation."
        )

    desired = deployment.get("desired_replicas", 0)
    ready = deployment.get("ready_replicas", 0)
    unavailable = deployment.get("unavailable_replicas", 0)

    if ready < desired:
        findings.append(f"Only {ready} of {desired} desired replicas are ready.")

    if unavailable > 0:
        findings.append(f"The deployment reports {unavailable} unavailable replicas.")

    pod_items = pods.get("pods", [])

    if not pod_items:
        findings.append("No pods were found for the investigation.")

    for pod in pod_items:
        pod_name = pod.get("name", "unknown")

        if pod.get("phase") != "Running":
            findings.append(
                f"Pod {pod_name} is in phase {pod.get('phase', 'Unknown')}."
            )

        if pod.get("ready_containers", 0) < pod.get(
            "total_containers",
            0,
        ):
            findings.append(f"Pod {pod_name} has containers that are not ready.")

        if pod.get("restarts", 0) > 0:
            findings.append(
                f"Pod {pod_name} reports {pod['restarts']} container restarts."
            )

        for container in pod.get("containers", []):
            if container.get("last_reason") == "OOMKilled":
                container_name = container.get("name", "unknown")
                exit_code = container.get("last_exit_code")

                findings.append(
                    f"Container {container_name} in pod {pod_name} "
                    f"was OOMKilled with exit code {exit_code}."
                )

    dns_failure = _trace_dns_resolution_failure(
        trace
    )
    default_deny_egress = (
        _trace_default_deny_egress_policy(
            trace
        )
    )

    if default_deny_egress is not None:
        policy_name, pod_name = (
            default_deny_egress
        )

        findings.append(
            f"NetworkPolicy {policy_name} selects "
            f"pod {pod_name} and applies "
            "default-deny egress during a DNS "
            "resolution failure."
        )

    if dns_failure is not None:
        dns_target, dns_signal = dns_failure

        findings.append(
            "Pod logs report a DNS resolution failure "
            f"for {dns_target}: {dns_signal}."
        )

    service_without_endpoints = (
        _trace_service_without_ready_endpoints(
            trace
        )
    )

    if service_without_endpoints is not None:
        findings.append(
            f"Service {service_without_endpoints} "
            "has zero ready endpoints."
        )
    selector_mismatch = (
        _trace_service_selector_mismatch(
            trace
        )
    )

    if selector_mismatch is not None:
        (
            service,
            deployment_selector,
            service_selector,
        ) = selector_mismatch

        findings.append(
            f"Service {service} selector "
            f"{service_selector} does not match "
            f"Deployment selector "
            f"{deployment_selector}."
        )

    relevant_object_names = {
        name,
        *(
            pod.get("name")
            for pod in pod_items
            if isinstance(pod.get("name"), str)
        ),
        *(
            pod.get("node")
            for pod in pod_items
            if isinstance(pod.get("node"), str)
        ),
    }

    hpa_metric_failure = (
        _trace_hpa_metric_failure(
            trace
        )
    )

    if hpa_metric_failure is not None:
        (
            hpa_name,
            reason,
            message,
            cpu_request_state,
            missing_cpu_requests,
        ) = hpa_metric_failure

        if cpu_request_state == "present":
            findings.append(
                f"HPA {hpa_name} reports {reason}: "
                f"{message} The resource metrics API "
                "did not provide CPU utilization even "
                "though Deployment CPU requests are "
                "present."
            )
        elif cpu_request_state == "missing":
            missing_text = ", ".join(
                missing_cpu_requests
            )

            findings.append(
                f"HPA {hpa_name} reports {reason}: "
                "Deployment containers are missing "
                f"CPU requests: {missing_text}."
            )
        else:
            findings.append(
                f"HPA {hpa_name} reports {reason}: "
                f"{message} Deployment CPU request "
                "evidence is unavailable."
            )

    hpa_scaling_limit = (
        _trace_hpa_scaling_limit(
            trace
        )
    )

    if hpa_scaling_limit is not None:
        (
            hpa_name,
            reason,
            max_replicas,
            current_cpu,
            target_cpu,
        ) = hpa_scaling_limit

        findings.append(
            f"HPA {hpa_name} reports {reason} "
            f"and is limited at its maximum of "
            f"{max_replicas} replicas while current "
            f"CPU utilization is {current_cpu}% "
            f"above target {target_cpu}%."
        )

    warning_events = [
        event
        for event in events.get("events", [])
        if (
            event.get("type") == "Warning"
            and event.get("object_name") in relevant_object_names
        )
    ]
    for event in warning_events:
        findings.append(
            "Warning event "
            f"{event.get('reason', 'Unknown')}: "
            f"{event.get('message', 'No message')}"
        )

    evidence = evidence_from_trace(trace)

    if not findings:
        return IncidentReport(
            summary=(f"Deployment {name} in namespace {namespace} is healthy."),
            probable_cause=(
                "No deployment, pod, or warning-event problems were detected."
            ),
            evidence=evidence,
            confidence=Confidence.HIGH,
            recommended_action=("No remediation is required. Continue monitoring."),
            approval_required=False,
            tool_trace=trace,
            errors=[],
        )

    return IncidentReport(
        summary=(
            f"Deployment {name} in namespace {namespace} "
            "has one or more health indicators."
        ),
        probable_cause=" ".join(findings),
        evidence=evidence,
        confidence=Confidence.HIGH,
        recommended_action=(
            "Review the correlated evidence before approving "
            "any Kubernetes configuration or workload change."
        ),
        approval_required=True,
        tool_trace=trace,
        errors=[],
    )

def _incident_scoped_trace(
    name: str,
    trace: list[ToolResult],
) -> list[ToolResult]:
    """Return an LLM trace containing only incident-relevant events."""

    pods_result = next(
        (
            result
            for result in trace
            if result.tool == "get_pods" and result.success
        ),
        None,
    )

    pod_names: set[str] = set()
    node_names: set[str] = set()

    if pods_result is not None:
        pod_names = {
            pod["name"]
            for pod in pods_result.data.get("pods", [])
            if isinstance(pod.get("name"), str)
        }

        node_names = {
            pod["node"]
            for pod in pods_result.data.get("pods", [])
            if isinstance(pod.get("node"), str)
        }

    relevant_object_names = {
        name,
        *pod_names,
        *node_names,
    }

    scoped_trace: list[ToolResult] = []

    for result in trace:
        if result.tool != "get_events" or not result.success:
            scoped_trace.append(result)
            continue

        relevant_events = [
            event
            for event in result.data.get("events", [])
            if event.get("object_name") in relevant_object_names
        ]

        scoped_data = {
            **result.data,
            "events": relevant_events,
            "returned_events": len(relevant_events),
        }

        scoped_trace.append(
            result.model_copy(
                update={"data": scoped_data},
            )
        )

    return scoped_trace


def _trace_has_readiness_probe_failure(
    trace: list[ToolResult],
) -> bool:
    """Return whether Kubernetes explicitly reported a readiness failure."""

    for result in trace:
        if result.tool != "get_events" or not result.success:
            continue

        for event in result.data.get("events", []):
            message = str(
                event.get("message", "")
            ).lower()

            if "readiness probe failed" in message:
                return True

    return False


def _diagnosis_mentions_readiness(
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves the readiness failure mode."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    return "readiness" in diagnosis_text


def _trace_has_missing_secret(
    trace: list[ToolResult],
) -> bool:
    """Return whether Kubernetes explicitly reported a missing Secret."""

    for result in trace:
        if result.tool != "get_events" or not result.success:
            continue

        for event in result.data.get("events", []):
            message = str(
                event.get("message", "")
            ).lower()

            if (
                "secret" in message
                and "not found" in message
            ):
                return True

    return False


def _diagnosis_mentions_missing_secret(
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves the missing-Secret failure."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    return (
        "secret" in diagnosis_text
        and "not found" in diagnosis_text
    )


def _trace_has_liveness_probe_failure(
    trace: list[ToolResult],
) -> bool:
    """Return whether Kubernetes explicitly reported a liveness failure."""

    for result in trace:
        if result.tool != "get_events" or not result.success:
            continue

        for event in result.data.get("events", []):
            message = str(
                event.get("message", "")
            ).lower()

            if "liveness probe failed" in message:
                return True

    return False


def _diagnosis_mentions_liveness(
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves the liveness failure mode."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    return "liveness" in diagnosis_text


def _trace_has_failed_scheduling(
    trace: list[ToolResult],
) -> bool:
    """Return whether Kubernetes explicitly reported FailedScheduling."""

    for result in trace:
        if result.tool != "get_events" or not result.success:
            continue

        for event in result.data.get("events", []):
            reason = str(
                event.get("reason", "")
            ).lower()

            if reason == "failedscheduling":
                return True

    return False


def _diagnosis_preserves_failed_scheduling(
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves the scheduling failure signal."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    compact_text = diagnosis_text.replace(" ", "")

    return (
        "failedscheduling" in compact_text
        or "failed scheduling" in diagnosis_text
        or "insufficient cpu" in diagnosis_text
        or "insufficient memory" in diagnosis_text
    )


def _trace_has_oomkilled(
    trace: list[ToolResult],
) -> bool:
    """Return whether Kubernetes reported an OOMKilled container."""

    for result in trace:
        if result.tool != "get_pods" or not result.success:
            continue

        for pod in result.data.get("pods", []):
            for container in pod.get("containers", []):
                if container.get("last_reason") == "OOMKilled":
                    return True

    return False


def _diagnosis_preserves_oomkilled(
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves the OOM failure signal."""

    diagnosis_text = f"{summary} {probable_cause}".lower()

    return (
        "oomkilled" in diagnosis_text
        or "oom killed" in diagnosis_text
        or "out of memory" in diagnosis_text
        or "exit code 137" in diagnosis_text
    )


def _trace_has_eviction(
    trace: list[ToolResult],
) -> bool:
    """Return whether Kubernetes explicitly reported pod eviction."""

    for result in trace:
        if not result.success:
            continue

        if result.tool == "get_events":
            for event in result.data.get("events", []):
                reason = str(
                    event.get("reason", "")
                ).lower()

                if reason == "evicted":
                    return True

        if result.tool == "get_pods":
            for pod in result.data.get("pods", []):
                reason = str(
                    pod.get("reason", "")
                ).lower()

                if reason == "evicted":
                    return True

    return False


def _diagnosis_preserves_eviction(
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves the eviction failure signal."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    return (
        "evicted" in diagnosis_text
        or "eviction" in diagnosis_text
        or (
            "ephemeral" in diagnosis_text
            and "storage" in diagnosis_text
        )
    )


def _trace_has_node_not_ready(
    trace: list[ToolResult],
) -> bool:
    """Return whether Kubernetes explicitly reported NodeNotReady."""

    for result in trace:
        if result.tool != "get_events" or not result.success:
            continue

        for event in result.data.get("events", []):
            reason = str(
                event.get("reason", "")
            ).lower()

            message = str(
                event.get("message", "")
            ).lower()

            if (
                reason == "nodenotready"
                or "node is not ready" in message
                or "node not ready" in message
            ):
                return True

    return False


def _diagnosis_preserves_node_not_ready(
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves the node-not-ready signal."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    compact_text = diagnosis_text.replace(" ", "")

    return (
        "nodenotready" in compact_text
        or "node not ready" in diagnosis_text
        or "node is not ready" in diagnosis_text
        or "worker node is not ready" in diagnosis_text
    )

def _trace_hpa_metric_failure(
    trace: list[ToolResult],
) -> tuple[str, str, str, str, list[str]] | None:
    """Return HPA metric failure and CPU request state."""

    containers: list[dict[str, Any]] = []

    for result in trace:
        if (
            result.tool != "get_deployment"
            or not result.success
        ):
            continue

        raw_containers = result.data.get(
            "containers",
            [],
        )

        if isinstance(raw_containers, list):
            containers = [
                container
                for container in raw_containers
                if isinstance(container, dict)
            ]

        break

    missing_cpu_requests = []

    for container in containers:
        cpu_request = container.get(
            "cpu_request"
        )

        if (
            not isinstance(cpu_request, str)
            or not cpu_request
        ):
            container_name = container.get(
                "name",
                "unknown",
            )

            if not isinstance(container_name, str):
                container_name = "unknown"

            missing_cpu_requests.append(
                container_name
            )

    if not containers:
        cpu_request_state = "unknown"
    elif missing_cpu_requests:
        cpu_request_state = "missing"
    else:
        cpu_request_state = "present"

    for result in trace:
        if (
            result.tool != "get_hpa"
            or not result.success
        ):
            continue

        hpa_name = result.data.get("name")
        conditions = result.data.get(
            "conditions",
            [],
        )

        if (
            not isinstance(hpa_name, str)
            or not hpa_name
            or not isinstance(conditions, list)
        ):
            continue

        for condition in conditions:
            if not isinstance(condition, dict):
                continue

            if (
                condition.get("type")
                != "ScalingActive"
                or condition.get("status")
                != "False"
                or condition.get("reason")
                != "FailedGetResourceMetric"
            ):
                continue

            reason = condition.get("reason")
            message = condition.get("message")

            if not isinstance(reason, str):
                reason = (
                    "FailedGetResourceMetric"
                )

            if not isinstance(message, str):
                message = (
                    "CPU resource metrics are "
                    "unavailable."
                )

            return (
                hpa_name,
                reason,
                message,
                cpu_request_state,
                missing_cpu_requests,
            )

    return None

def _diagnosis_preserves_hpa_metric_failure(
    hpa_name: str,
    reason: str,
    cpu_request_state: str,
    missing_cpu_requests: list[str],
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves HPA evidence."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    contradictory_claim = any(
        phrase in diagnosis_text
        for phrase in (
            "hpa is healthy",
            "scaling normally",
            "no failedgetresourcemetric",
            "metrics api is available",
            "resource metrics api is available",
            "metrics are available",
            "cpu metrics are available",
        )
    )

    if contradictory_claim:
        return False

    common_evidence_preserved = (
        hpa_name.lower() in diagnosis_text
        and reason.lower() in diagnosis_text
    )

    if not common_evidence_preserved:
        return False

    if cpu_request_state == "present":
        metrics_failure_preserved = (
            "resource metrics api"
            in diagnosis_text
            and any(
                phrase in diagnosis_text
                for phrase in (
                    "unavailable",
                    "no metrics",
                    "did not provide",
                    "failed to provide",
                    "returned no",
                )
            )
        )

        requests_preserved = any(
            phrase in diagnosis_text
            for phrase in (
                "cpu requests are present",
                "cpu requests exist",
                "defines cpu requests",
                "has cpu requests",
            )
        )

        return (
            metrics_failure_preserved
            and requests_preserved
        )

    if cpu_request_state == "missing":
        if "missing cpu request" not in diagnosis_text:
            return False

        return all(
            container.lower() in diagnosis_text
            for container in missing_cpu_requests
        )

    return any(
        phrase in diagnosis_text
        for phrase in (
            "cpu request evidence is unavailable",
            "cpu requests could not be verified",
            "cpu request state is unknown",
        )
    )

def _trace_hpa_scaling_limit(
    trace: list[ToolResult],
) -> tuple[str, str, int, int, int] | None:
    """Return an HPA constrained at maximum replicas."""

    for result in trace:
        if (
            result.tool != "get_hpa"
            or not result.success
        ):
            continue

        hpa_name = result.data.get("name")
        max_replicas = result.data.get(
            "max_replicas"
        )
        current_replicas = result.data.get(
            "current_replicas"
        )
        current_cpu = result.data.get(
            "current_cpu_utilization"
        )
        target_cpu = result.data.get(
            "target_cpu_utilization"
        )
        conditions = result.data.get(
            "conditions",
            [],
        )

        integer_values = (
            max_replicas,
            current_replicas,
            current_cpu,
            target_cpu,
        )

        if (
            not isinstance(hpa_name, str)
            or not hpa_name
            or not isinstance(conditions, list)
            or not all(
                isinstance(value, int)
                and not isinstance(value, bool)
                for value in integer_values
            )
            or current_replicas != max_replicas
            or current_cpu <= target_cpu
        ):
            continue

        for condition in conditions:
            if (
                not isinstance(condition, dict)
                or condition.get("type")
                != "ScalingLimited"
                or condition.get("status")
                != "True"
            ):
                continue

            reason = condition.get("reason")

            if not isinstance(reason, str) or not reason:
                reason = "ScalingLimited"

            return (
                hpa_name,
                reason,
                max_replicas,
                current_cpu,
                target_cpu,
            )

    return None

def _diagnosis_preserves_hpa_scaling_limit(
    hpa_name: str,
    reason: str,
    max_replicas: int,
    current_cpu: int,
    target_cpu: int,
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves HPA limit."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    contradictory_claim = any(
        phrase in diagnosis_text
        for phrase in (
            "is not limited",
            "not scaling limited",
            "can continue scaling",
            "has not reached",
            "below the target",
            "below target",
            f"{reason.lower()} is not active",
        )
    )

    if contradictory_claim:
        return False

    limit_signal_preserved = any(
        phrase in diagnosis_text
        for phrase in (
            "limited at",
            "reached its maximum",
            "at the maximum",
            "maximum replica limit",
            "scalinglimited=true",
            "scaling limited",
        )
    )

    maximum_preserved = any(
        phrase in diagnosis_text
        for phrase in (
            f"maximum of {max_replicas} replicas",
            f"maximum {max_replicas} replicas",
            f"maxreplicas {max_replicas}",
            f"limit of {max_replicas} replicas",
        )
    )

    utilization_preserved = (
        f"{current_cpu}%" in diagnosis_text
        and f"{target_cpu}%" in diagnosis_text
        and any(
            phrase in diagnosis_text
            for phrase in (
                "above target",
                "above the target",
                "exceeds target",
                "exceeds the target",
                "higher than target",
            )
        )
    )

    return (
        hpa_name.lower() in diagnosis_text
        and reason.lower() in diagnosis_text
        and limit_signal_preserved
        and maximum_preserved
        and utilization_preserved
    )

def _trace_node_pressure_reason(
    trace: list[ToolResult],
) -> str | None:
    """Return the node pressure reason reported by Kubernetes."""

    pressure_reasons = {
        "memorypressure": "MemoryPressure",
        "nodehasinsufficientmemory": "MemoryPressure",
        "diskpressure": "DiskPressure",
        "nodehasdiskpressure": "DiskPressure",
        "pidpressure": "PIDPressure",
        "nodehasinsufficientpid": "PIDPressure",
    }

    for result in trace:
        if result.tool != "get_events" or not result.success:
            continue

        for event in result.data.get("events", []):
            reason = str(
                event.get("reason", "")
            ).lower()

            if reason in pressure_reasons:
                return pressure_reasons[reason]

    return None


def _diagnosis_preserves_node_pressure(
    pressure_reason: str,
    summary: str,
    probable_cause: str,
) -> bool:
    """Return whether diagnosis preserves the specific pressure signal."""

    diagnosis_text = (
        f"{summary} {probable_cause}"
    ).lower()

    compact_text = diagnosis_text.replace(" ", "")

    return pressure_reason.lower() in compact_text


def enrich_report_with_llm(
    report: IncidentReport,
    trace: list[ToolResult],
) -> IncidentReport:
    """Enrich an unhealthy report with optional LLM reasoning."""

    if report.errors or not report.approval_required:
        return report

    try:
        diagnosis = diagnose_tool_trace(trace)
    except LLMError:
        return report

    if (
        _trace_has_readiness_probe_failure(trace)
        and not _diagnosis_mentions_readiness(
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    if (
        _trace_has_missing_secret(trace)
        and not _diagnosis_mentions_missing_secret(
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    if (
        _trace_has_liveness_probe_failure(trace)
        and not _diagnosis_mentions_liveness(
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    if (
        _trace_has_failed_scheduling(trace)
        and not _diagnosis_preserves_failed_scheduling(
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    if (
        _trace_has_oomkilled(trace)
        and not _diagnosis_preserves_oomkilled(
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    if (
        _trace_has_eviction(trace)
        and not _diagnosis_preserves_eviction(
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    if (
        _trace_has_node_not_ready(trace)
        and not _diagnosis_preserves_node_not_ready(
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    node_pressure_reason = _trace_node_pressure_reason(trace)

    if (
        node_pressure_reason is not None
        and not _diagnosis_preserves_node_pressure(
            node_pressure_reason,
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    dns_failure = _trace_dns_resolution_failure(
        trace
    )

    if dns_failure is not None:
        dns_target, dns_signal = dns_failure

        if not (
            _diagnosis_preserves_dns_resolution_failure(
                dns_target,
                dns_signal,
                diagnosis.summary,
                diagnosis.probable_cause,
            )
        ):
            return report

    service_without_endpoints = (
        _trace_service_without_ready_endpoints(
            trace
        )
    )

    if (
        service_without_endpoints is not None
        and not _diagnosis_preserves_zero_endpoint_evidence(
            service_without_endpoints,
            diagnosis.summary,
            diagnosis.probable_cause,
        )
    ):
        return report

    selector_mismatch = (
        _trace_service_selector_mismatch(
            trace
        )
    )

    if selector_mismatch is not None:
        (
            service,
            deployment_selector,
            service_selector,
        ) = selector_mismatch

        if not (
            _diagnosis_preserves_service_selector_mismatch(
                service=service,
                deployment_selector=deployment_selector,
                service_selector=service_selector,
                summary=diagnosis.summary,
                probable_cause=diagnosis.probable_cause,
            )
        ):
            return report

    default_deny_egress = (
        _trace_default_deny_egress_policy(
            trace
        )
    )

    if default_deny_egress is not None:
        policy_name, pod_name = (
            default_deny_egress
        )

        if not (
            _diagnosis_preserves_default_deny_egress(
                policy_name=policy_name,
                pod_name=pod_name,
                summary=diagnosis.summary,
                probable_cause=diagnosis.probable_cause,
            )
        ):
            return report

    hpa_metric_failure = (
        _trace_hpa_metric_failure(
            trace
        )
    )

    if hpa_metric_failure is not None:
        (
            hpa_name,
            reason,
            _message,
            cpu_request_state,
            missing_cpu_requests,
        ) = hpa_metric_failure

        if not (
            _diagnosis_preserves_hpa_metric_failure(
                hpa_name=hpa_name,
                reason=reason,
                cpu_request_state=(
                    cpu_request_state
                ),
                missing_cpu_requests=(
                    missing_cpu_requests
                ),
                summary=diagnosis.summary,
                probable_cause=(
                    diagnosis.probable_cause
                ),
            )
        ):
            return report

    hpa_scaling_limit = (
        _trace_hpa_scaling_limit(
            trace
        )
    )

    if hpa_scaling_limit is not None:
        (
            hpa_name,
            reason,
            max_replicas,
            current_cpu,
            target_cpu,
        ) = hpa_scaling_limit

        if not (
            _diagnosis_preserves_hpa_scaling_limit(
                hpa_name=hpa_name,
                reason=reason,
                max_replicas=max_replicas,
                current_cpu=current_cpu,
                target_cpu=target_cpu,
                summary=diagnosis.summary,
                probable_cause=(
                    diagnosis.probable_cause
                ),
            )
        ):
            return report

    return report.model_copy(
        update={
            "summary": diagnosis.summary,
            "probable_cause": diagnosis.probable_cause,
            "confidence": diagnosis.confidence,
            "recommended_action": diagnosis.recommended_action,
        }
    )

def _pod_has_loggable_container(
    pod: dict,
) -> bool:
    """Return whether pod container state indicates logs may exist."""

    containers = pod.get("containers", [])

    for container in containers:
        if container.get("state") == "running":
            return True

        if (
            container.get("last_state") == "terminated"
            and container.get("last_reason")
            not in {
                None,
                "ContainerStatusUnknown",
            }
        ):
            return True

    return False

def run_kubernetes_investigation(
    name: str,
    namespace: str = "dev",
    event_limit: int = 20,
    hpa_name: str | None = None
) -> IncidentReport:
    """Run a bounded, read-only Kubernetes investigation."""

    trace: list[ToolResult] = []

    deployment_result = execute_tool(
        "get_deployment",
        {
            "name": name,
            "namespace": namespace,
        },
    )
    trace.append(deployment_result)

    if not deployment_result.success:
        return create_kubernetes_report(
            name=name,
            namespace=namespace,
            trace=trace,
        )

    selector = deployment_result.data.get("selector", "")

    pods_result = execute_tool(
        "get_pods",
        {
            "namespace": namespace,
            "selector": selector,
        },
    )
    trace.append(pods_result)

    if not pods_result.success:
        return create_kubernetes_report(
            name=name,
            namespace=namespace,
            trace=trace,
        )

    events_result = execute_tool(
        "get_events",
        {
            "namespace": namespace,
            "limit": event_limit,
        },
    )
    trace.append(events_result)

    if not events_result.success:
        return create_kubernetes_report(
            name=name,
            namespace=namespace,
            trace=trace,
        )

    deployment = deployment_result.data
    pod_items = pods_result.data.get("pods", [])
    event_items = events_result.data.get("events", [])

    desired = deployment.get("desired_replicas", 0)
    ready = deployment.get("ready_replicas", 0)
    unavailable = deployment.get("unavailable_replicas", 0)

    unhealthy_pods = [
        pod
        for pod in pod_items
        if (
            pod.get("phase") != "Running"
            or pod.get("ready_containers", 0)
            < pod.get("total_containers", 0)
            or pod.get("restarts", 0) > 0
        )
    ]

    pod_names = {
        pod.get("name")
        for pod in pod_items
        if isinstance(pod.get("name"), str)
    }

    warning_pod_names = {
        event.get("object_name")
        for event in event_items
        if (
            event.get("type") == "Warning"
            and event.get("object_name") in pod_names
        )
    }

    investigation_has_problem = (
        ready < desired
        or unavailable > 0
        or bool(unhealthy_pods)
        or bool(warning_pod_names)
    )

    loggable_warning_pods = [
        pod
        for pod in unhealthy_pods
        if (
            pod.get("name") in warning_pod_names
            and _pod_has_loggable_container(pod)
        )
    ]

    if investigation_has_problem and loggable_warning_pods:
        log_pod = next(
            (
                pod
                for pod in loggable_warning_pods
                if isinstance(pod.get("name"), str)
            ),
            None,
        )

        if log_pod is not None:
            log_arguments = {
                "pod": log_pod["name"],
                "namespace": namespace,
                "tail_lines": 100,
                "since_seconds": 600,
            }

            containers = deployment.get("containers", [])

            if containers:
                container_name = containers[0].get("name")

                if isinstance(container_name, str) and container_name:
                    log_arguments["container"] = container_name

            logs_result = execute_tool(
                "get_pod_logs",
                log_arguments,
            )
            trace.append(logs_result)

    dns_failure = _trace_dns_resolution_failure(
        trace
    )

    if dns_failure is not None:
        service_result = execute_tool(
            "get_service_endpoints",
            {
                "service": f"{name}-service",
                "namespace": namespace,
            },
        )
        trace.append(service_result)
        ready_endpoint_count = (
            service_result.data.get(
                "ready_endpoint_count"
            )
        )

        service_has_ready_endpoints = (
            service_result.success
            and isinstance(
                ready_endpoint_count,
                int,
            )
            and not isinstance(
                ready_endpoint_count,
                bool,
            )
            and ready_endpoint_count > 0
        )

        if service_has_ready_endpoints:
            policies_result = execute_tool(
                "get_network_policies",
                {
                    "namespace": namespace,
                },
            )
            trace.append(policies_result)

    if hpa_name is not None:
        hpa_result = execute_tool(
            "get_hpa",
            {
                "name": hpa_name,
                "namespace": namespace,
            },
        )
        trace.append(hpa_result)

    report = create_kubernetes_report(
        name=name,
        namespace=namespace,
        trace=trace,
    )

    llm_trace = _incident_scoped_trace(
        name=name,
        trace=trace,
    )

    return enrich_report_with_llm(
        report=report,
        trace=llm_trace,
    )
