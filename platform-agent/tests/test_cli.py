import json
from pathlib import Path

import pytest
from platform_agent import cli
from platform_agent.contracts import Confidence, IncidentReport
from platform_agent.tools import terraform as terraform_tools


@pytest.fixture
def project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Create an isolated Terraform repository for CLI tests."""
    module = tmp_path / "modules" / "vpc"
    module.mkdir(parents=True)

    for filename in [
        "main.tf",
        "variables.tf",
        "outputs.tf",
    ]:
        (module / filename).write_text(
            "# test fixture\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        terraform_tools,
        "PROJECT_ROOT",
        tmp_path,
    )

    return tmp_path


def test_inspect_module_returns_json(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(
        [
            "inspect-module",
            "modules/vpc",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["confidence"] == "high"
    assert payload["approval_required"] is False
    assert payload["errors"] == []
    assert len(payload["tool_trace"]) == 2


def test_cli_rejects_path_outside_project(
    project_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(
        [
            "inspect-module",
            "../../etc",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)

    assert exit_code == 2
    assert payload["confidence"] == "low"
    assert payload["errors"]
    assert payload["tool_trace"][0]["success"] is False


def test_cli_rejects_invalid_tool_limit() -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(
            [
                "inspect-module",
                "modules/vpc",
                "--max-tool-calls",
                "0",
            ]
        )

    assert error.value.code == 2


def test_investigate_kubernetes_returns_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = IncidentReport(
        summary="Deployment aws-platform-app is healthy.",
        probable_cause="No health problems were detected.",
        evidence=[],
        confidence=Confidence.HIGH,
        recommended_action="Continue monitoring.",
        approval_required=False,
        tool_trace=[],
        errors=[],
    )

    monkeypatch.setattr(
        cli,
        "run_kubernetes_investigation",
        lambda **kwargs: report,
    )

    exit_code = cli.main(
        [
            "investigate-kubernetes",
            "aws-platform-app",
            "--namespace",
            "dev",
            "--event-limit",
            "10",
        ]
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["confidence"] == "high"
    assert payload["approval_required"] is False
    assert "is healthy" in payload["summary"]


def test_cli_rejects_invalid_event_limit() -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(
            [
                "investigate-kubernetes",
                "aws-platform-app",
                "--event-limit",
                "101",
            ]
        )

    assert error.value.code == 2

def test_investigate_kubernetes_passes_hpa_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = IncidentReport(
        summary="HPA evidence was collected.",
        probable_cause=(
            "The resource metrics API is unavailable."
        ),
        evidence=[],
        confidence=Confidence.HIGH,
        recommended_action=(
            "Review Metrics Server."
        ),
        approval_required=True,
        tool_trace=[],
        errors=[],
    )

    received_arguments: dict[str, object] = {}

    def fake_investigation(
        **kwargs: object,
    ) -> IncidentReport:
        received_arguments.update(kwargs)
        return report

    monkeypatch.setattr(
        cli,
        "run_kubernetes_investigation",
        fake_investigation,
    )

    exit_code = cli.main(
        [
            "investigate-kubernetes",
            "aws-platform-app",
            "--namespace",
            "dev",
            "--event-limit",
            "10",
            "--hpa-name",
            "aws-platform-app-hpa",
        ]
    )

    payload = json.loads(
        capsys.readouterr().out
    )

    assert exit_code == 0
    assert received_arguments == {
        "name": "aws-platform-app",
        "namespace": "dev",
        "event_limit": 10,
        "hpa_name": "aws-platform-app-hpa",
    }
    assert payload["approval_required"] is True

def test_evaluate_fixtures_returns_json_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture_directory = (
        Path(__file__).resolve().parents[1]
        / "evals"
        / "fixtures"
    )

    exit_code = cli.main(
        [
            "evaluate",
            str(fixture_directory),
        ]
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["total"] == 1
    assert payload["passed"] == 1
    assert payload["failed"] == 0
    assert payload["results"][0]["case_name"] == (
        "oomkilled-container"
    )
    assert payload["results"][0]["passed"] is True

def test_evaluate_returns_one_when_a_fixture_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture_directory = (
        Path(__file__).resolve().parents[1]
        / "evals"
        / "fixtures"
    )

    passing_result = cli.evaluate_directory(
        fixture_directory
    )[0]

    failing_result = passing_result.model_copy(
        update={
            "passed": False,
            "failures": [
                "Required diagnosis term was not found.",
            ],
        }
    )

    monkeypatch.setattr(
        cli,
        "evaluate_directory",
        lambda path: [failing_result],
    )

    exit_code = cli.main(
        [
            "evaluate",
            str(fixture_directory),
        ]
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["total"] == 1
    assert payload["passed"] == 0
    assert payload["failed"] == 1
    assert payload["results"][0]["passed"] is False
    assert payload["results"][0]["failures"] == [
        "Required diagnosis term was not found.",
    ]
