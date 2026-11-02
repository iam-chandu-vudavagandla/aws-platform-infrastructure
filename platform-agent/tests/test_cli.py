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
    expected_total = len(
        list(fixture_directory.glob("*.json"))
    )

    assert payload["total"] == expected_total
    assert payload["passed"] == expected_total
    assert payload["failed"] == 0

    case_names = {
        result["case_name"]
        for result in payload["results"]
    }

    assert "oomkilled-container" in case_names
    assert all(
        result["passed"]
        for result in payload["results"]
    )
    assert payload.get("errors", []) == []

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

def test_evaluate_missing_directory_returns_structured_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_directory = (
        tmp_path
        / "missing-evaluation-fixtures"
    )

    exit_code = cli.main(
        [
            "evaluate",
            str(missing_directory),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 2
    assert payload == {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "results": [],
        "errors": [
            (
                "Evaluation fixture directory "
                "does not exist: "
                f"{missing_directory}"
            )
        ],
    }
    events = [
        json.loads(line)
        for line in captured.err.splitlines()
        if line.strip()
    ]

    assert [
        event["event"]
        for event in events
    ] == [
        "command_started",
        "command_completed",
    ]

    assert events[0]["command"] == "evaluate"
    assert events[0]["level"] == "info"
    assert events[1]["command"] == "evaluate"
    assert events[1]["level"] == "error"
    assert events[1]["exit_code"] == 2
    assert events[1]["success"] is False
    assert events[1]["duration_seconds"] >= 0

def test_evaluate_malformed_fixture_returns_structured_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture_path = tmp_path / "malformed.json"

    fixture_path.write_text(
        '{"name":',
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "evaluate",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 2
    assert payload["total"] == 0
    assert payload["passed"] == 0
    assert payload["failed"] == 0
    assert payload["results"] == []
    assert len(payload["errors"]) == 1
    assert "Invalid JSON" in payload["errors"][0]
    events = [
        json.loads(line)
        for line in captured.err.splitlines()
        if line.strip()
    ]

    assert [
        event["event"]
        for event in events
    ] == [
        "command_started",
        "command_completed",
    ]

    assert events[0]["command"] == "evaluate"
    assert events[0]["level"] == "info"

    assert events[1]["command"] == "evaluate"
    assert events[1]["level"] == "error"
    assert events[1]["exit_code"] == 2
    assert events[1]["success"] is False
    assert events[1]["duration_seconds"] >= 0

def test_cli_emits_structured_lifecycle_events(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = IncidentReport(
        summary="Deployment is healthy.",
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
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    events = [
        json.loads(line)
        for line in captured.err.splitlines()
        if line.strip()
    ]

    assert exit_code == 0
    assert payload["summary"] == "Deployment is healthy."
    assert [
        event["event"]
        for event in events
    ] == [
        "command_started",
        "command_completed",
    ]

    started, completed = events

    assert started["level"] == "info"
    assert started["command"] == "investigate-kubernetes"
    assert isinstance(started["timestamp"], str)

    assert completed["level"] == "info"
    assert completed["command"] == "investigate-kubernetes"
    assert completed["exit_code"] == 0
    assert completed["success"] is True
    assert completed["duration_seconds"] >= 0

def test_cli_writes_prometheus_command_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = IncidentReport(
        summary="Deployment is healthy.",
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

    metrics_file = tmp_path / "platform-agent.prom"

    exit_code = cli.main(
        [
            "--metrics-file",
            str(metrics_file),
            "investigate-kubernetes",
            "aws-platform-app",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["summary"] == "Deployment is healthy."
    assert metrics_file.is_file()

    metrics = metrics_file.read_text(encoding="utf-8")

    assert (
        "platform_agent_commands_total"
        '{command="investigate-kubernetes",status="success"} '
        "1.0"
        in metrics
    )
    assert (
        "platform_agent_command_duration_seconds_count"
        '{command="investigate-kubernetes"} 1.0'
        in metrics
    )


def test_cli_writes_prometheus_tool_metrics(
    project_root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    metrics_file = tmp_path / "platform-agent.prom"

    exit_code = cli.main(
        [
            "--metrics-file",
            str(metrics_file),
            "inspect-module",
            "modules/vpc",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["errors"] == []

    metrics = metrics_file.read_text(encoding="utf-8")

    assert (
        "platform_agent_tool_calls_total"
        '{status="success",tool="list_terraform_files"} '
        "1.0"
        in metrics
    )
    assert (
        "platform_agent_tool_calls_total"
        '{status="success",tool="check_module_files"} '
        "1.0"
        in metrics
    )
    assert (
        "platform_agent_tool_duration_seconds_count"
        '{tool="list_terraform_files"} 1.0'
        in metrics
    )

    events = [
        json.loads(line)
        for line in captured.err.splitlines()
        if line.strip()
    ]
    completed_tools = [
        event
        for event in events
        if event["event"] == "tool_completed"
    ]

    assert [
        event["tool"]
        for event in completed_tools
    ] == [
        "list_terraform_files",
        "check_module_files",
    ]
    assert all(
        event["success"] is True
        for event in completed_tools
    )
    assert all(
        event["duration_seconds"] >= 0
        for event in completed_tools
    )
