from pathlib import Path

import pytest

from platform_agent.agent import (
    run_terraform_module_investigation,
)
from platform_agent.contracts import Confidence
from platform_agent.tools import terraform as terraform_tools


@pytest.fixture
def fake_complete_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    module = tmp_path / "modules" / "vpc"
    module.mkdir(parents=True)

    for filename in (
        "main.tf",
        "variables.tf",
        "outputs.tf",
    ):
        (module / filename).write_text(
            f"# {filename}\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        terraform_tools,
        "PROJECT_ROOT",
        tmp_path.resolve(),
    )

    return module


def test_complete_module_produces_high_confidence_report(
    fake_complete_module: Path,
) -> None:
    report = run_terraform_module_investigation(
        "modules/vpc"
    )

    assert report.confidence == Confidence.HIGH
    assert report.approval_required is False
    assert report.errors == []
    assert len(report.tool_trace) == 2
    assert report.tool_trace[0].tool == (
        "list_terraform_files"
    )
    assert report.tool_trace[0].arguments == {
        "path": "modules/vpc"
    }
    assert report.tool_trace[1].tool == (
        "check_module_files"
    )


def test_missing_file_requires_human_approved_change(
    fake_complete_module: Path,
) -> None:
    (fake_complete_module / "outputs.tf").unlink()

    report = run_terraform_module_investigation(
        "modules/vpc"
    )

    assert report.confidence == Confidence.HIGH
    assert report.approval_required is True
    assert "outputs.tf" in report.probable_cause


def test_unsafe_path_stops_after_failed_tool(
    fake_complete_module: Path,
) -> None:
    report = run_terraform_module_investigation(
        "../../etc"
    )

    assert report.confidence == Confidence.LOW
    assert len(report.tool_trace) == 1
    assert report.tool_trace[0].success is False
    assert report.errors == [
        "Path is outside the approved project."
    ]


def test_maximum_tool_call_limit_stops_loop(
    fake_complete_module: Path,
) -> None:
    report = run_terraform_module_investigation(
        "modules/vpc",
        max_tool_calls=1,
    )

    assert report.confidence == Confidence.LOW
    assert len(report.tool_trace) == 1
    assert report.errors == [
        "Maximum tool-call limit reached before "
        "the investigation completed."
    ]
