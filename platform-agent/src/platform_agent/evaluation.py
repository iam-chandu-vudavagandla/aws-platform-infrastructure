from pathlib import Path

from pydantic import Field

from platform_agent.contracts import (
    Confidence,
    IncidentReport,
    StrictModel,
    ToolResult,
)
from platform_agent.kubernetes_investigation import (
    create_kubernetes_report,
)


class EvaluationExpectation(StrictModel):
    """Expected behavior for one saved incident scenario."""

    confidence: Confidence
    approval_required: bool
    required_diagnosis_terms: list[str] = Field(
        default_factory=list
    )
    forbidden_output_terms: list[str] = Field(
        default_factory=list
    )
    required_evidence_sources: list[str] = Field(
        default_factory=list
    )
    errors: list[str] = Field(default_factory=list)


class EvaluationCase(StrictModel):
    """One offline incident evaluation fixture."""

    name: str = Field(min_length=1)
    deployment: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    trace: list[ToolResult] = Field(min_length=1)
    expected: EvaluationExpectation


class EvaluationResult(StrictModel):
    """Complete result from evaluating one incident fixture."""

    case_name: str = Field(min_length=1)
    passed: bool
    failures: list[str]
    report: IncidentReport


def load_evaluation_case(
    path: str | Path,
) -> EvaluationCase:
    """Load and validate one JSON evaluation fixture."""

    fixture_path = Path(path)
    payload = fixture_path.read_text(encoding="utf-8")

    return EvaluationCase.model_validate_json(payload)


def evaluate_case(
    case: EvaluationCase,
) -> EvaluationResult:
    """Evaluate the deterministic report for one saved trace."""

    report = create_kubernetes_report(
        name=case.deployment,
        namespace=case.namespace,
        trace=case.trace,
    )

    failures: list[str] = []

    if report.confidence != case.expected.confidence:
        failures.append(
            "Expected confidence "
            f"{case.expected.confidence.value!r}, "
            f"received {report.confidence.value!r}."
        )

    if (
        report.approval_required
        != case.expected.approval_required
    ):
        failures.append(
            "Expected approval_required="
            f"{case.expected.approval_required}, "
            "received "
            f"{report.approval_required}."
        )

    if report.errors != case.expected.errors:
        failures.append(
            f"Expected errors {case.expected.errors!r}, "
            f"received {report.errors!r}."
        )

    diagnosis_text = " ".join(
        [
            report.summary,
            report.probable_cause,
        ]
    ).casefold()

    output_text = " ".join(
        [
            report.summary,
            report.probable_cause,
            report.recommended_action,
        ]
    ).casefold()

    for term in case.expected.required_diagnosis_terms:
        if term.casefold() not in diagnosis_text:
            failures.append(
                f"Required diagnosis term {term!r} "
                "was not found."
            )

    for term in case.expected.forbidden_output_terms:
        if term.casefold() in output_text:
            failures.append(
                f"Forbidden output term {term!r} "
                "was found."
            )

    evidence_sources = {
        evidence.source
        for evidence in report.evidence
    }

    for source in case.expected.required_evidence_sources:
        if source not in evidence_sources:
            failures.append(
                f"Required evidence source {source!r} "
                "was not preserved."
            )

    if report.tool_trace != case.trace:
        failures.append(
            "The report did not preserve the complete tool trace."
        )

    return EvaluationResult(
        case_name=case.name,
        passed=not failures,
        failures=failures,
        report=report,
    )

def evaluate_directory(
    path: str | Path,
) -> list[EvaluationResult]:
    """Evaluate every JSON fixture in one directory."""

    fixture_directory = Path(path)

    if not fixture_directory.is_dir():
        raise ValueError(
            "Evaluation fixture directory does not exist: "
            f"{fixture_directory}"
        )

    fixture_paths = sorted(
        fixture_directory.glob("*.json")
    )

    if not fixture_paths:
        raise ValueError(
            "No JSON evaluation fixtures were found in "
            f"{fixture_directory}."
        )

    return [
        evaluate_case(load_evaluation_case(fixture_path))
        for fixture_path in fixture_paths
    ]
