from pathlib import Path

from platform_agent.contracts import Confidence
from platform_agent.evaluation import (
    evaluate_case,
    evaluate_directory,
    load_evaluation_case,
)


FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "fixtures"
)


def test_oomkilled_fixture_passes_evaluation() -> None:
    case = load_evaluation_case(
        FIXTURE_DIRECTORY / "oomkilled.json"
    )

    result = evaluate_case(case)

    assert case.name == "oomkilled-container"
    assert case.expected.confidence == Confidence.HIGH
    assert result.passed is True, result.failures
    assert result.failures == []
    assert result.report.tool_trace == case.trace

def test_evaluator_reports_all_expectation_failures() -> None:
    case = load_evaluation_case(
        FIXTURE_DIRECTORY / "oomkilled.json"
    )

    incorrect_expectation = case.expected.model_copy(
        update={
            "confidence": Confidence.LOW,
            "approval_required": False,
            "required_diagnosis_terms": [
                "database connection timeout",
            ],
            "forbidden_output_terms": [
                "oomkilled",
            ],
            "required_evidence_sources": [
                "get_hpa",
            ],
            "errors": [
                "Expected evaluation error.",
            ],
        }
    )

    incorrect_case = case.model_copy(
        update={
            "expected": incorrect_expectation,
        }
    )

    result = evaluate_case(incorrect_case)

    assert result.passed is False
    assert len(result.failures) == 6

    failures = " ".join(result.failures).lower()

    assert "confidence" in failures
    assert "approval_required" in failures
    assert "errors" in failures
    assert "required diagnosis term" in failures
    assert "forbidden output term" in failures
    assert "required evidence source" in failures

def test_evaluate_directory_runs_all_fixtures() -> None:
    results = evaluate_directory(FIXTURE_DIRECTORY)

    assert len(results) == 1
    assert [result.case_name for result in results] == [
        "oomkilled-container",
    ]
    assert all(result.passed for result in results)
