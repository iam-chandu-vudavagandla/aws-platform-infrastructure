from platform_agent.agent import evidence_from_trace
from platform_agent.contracts import Confidence, IncidentReport, ToolResult
from platform_agent.llm import LLMError, diagnose_tool_trace
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

    relevant_object_names = {
        name,
        *(pod.get("name") for pod in pod_items if isinstance(pod.get("name"), str)),
    }

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

    if pods_result is not None:
        pod_names = {
            pod["name"]
            for pod in pods_result.data.get("pods", [])
            if isinstance(pod.get("name"), str)
        }

    relevant_object_names = {
        name,
        *pod_names,
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

    return report.model_copy(
        update={
            "summary": diagnosis.summary,
            "probable_cause": diagnosis.probable_cause,
            "confidence": diagnosis.confidence,
            "recommended_action": diagnosis.recommended_action,
        }
    )


def run_kubernetes_investigation(
    name: str,
    namespace: str = "dev",
    event_limit: int = 20,
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

    if investigation_has_problem and pod_items:
        log_pod = next(
            (
                pod
                for pod in unhealthy_pods
                if isinstance(pod.get("name"), str)
            ),
            None,
        )

        if log_pod is None:
            log_pod = next(
                (
                    pod
                    for pod in pod_items
                    if pod.get("name") in warning_pod_names
                ),
                None,
            )

        if log_pod is None:
            log_pod = next(
                (
                    pod
                    for pod in pod_items
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
