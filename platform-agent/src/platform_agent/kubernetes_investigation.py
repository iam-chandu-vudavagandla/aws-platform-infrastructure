from typing import Any

from platform_agent.agent import evidence_from_trace
from platform_agent.contracts import Confidence, IncidentReport, ToolResult
from platform_agent.tool_registry import execute_tool


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

    warning_events = [
        event for event in events.get("events", []) if event.get("type") == "Warning"
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


def run_kubernetes_investigation(
    name: str,
    namespace: str = "dev",
    event_limit: int = 20,
) -> IncidentReport:
    """Run a bounded, read-only Kubernetes investigation."""

    tool_plan: tuple[tuple[str, dict[str, Any]], ...] = (
        (
            "get_deployment",
            {
                "name": name,
                "namespace": namespace,
            },
        ),
        (
            "get_pods",
            {
                "namespace": namespace,
            },
        ),
        (
            "get_events",
            {
                "namespace": namespace,
                "limit": event_limit,
            },
        ),
    )

    trace: list[ToolResult] = []

    for tool_name, arguments in tool_plan:
        result = execute_tool(tool_name, arguments)
        trace.append(result)

        if not result.success:
            break

    return create_kubernetes_report(
        name=name,
        namespace=namespace,
        trace=trace,
    )
