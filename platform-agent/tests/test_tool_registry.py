from pathlib import Path

import pytest

from platform_agent import tool_registry
from platform_agent.tools import terraform as terraform_tools


@pytest.fixture
def fake_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    module = tmp_path / "modules" / "vpc"
    module.mkdir(parents=True)

    (module / "main.tf").write_text(
        'resource "test_resource" "example" {}\n',
        encoding="utf-8",
    )

    (module / "variables.tf").write_text(
        'variable "name" { type = string }\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        terraform_tools,
        "PROJECT_ROOT",
        tmp_path.resolve(),
    )

    return tmp_path


def test_allowed_tool_lists_terraform_files(
    fake_project: Path,
) -> None:
    result = tool_registry.execute_tool(
        "list_terraform_files",
        {"path": "modules/vpc"},
    )

    assert result.success is True
    assert result.data["count"] == 2
    assert result.data["files"] == [
        "modules/vpc/main.tf",
        "modules/vpc/variables.tf",
    ]


def test_module_check_reports_missing_file(
    fake_project: Path,
) -> None:
    result = tool_registry.execute_tool(
        "check_module_files",
        {"module": "modules/vpc"},
    )

    assert result.success is True
    assert result.data["complete"] is False
    assert result.data["missing"] == ["outputs.tf"]


def test_path_outside_project_is_rejected(
    fake_project: Path,
) -> None:
    result = tool_registry.execute_tool(
        "list_terraform_files",
        {"path": "../../etc"},
    )

    assert result.success is False
    assert result.error == "Path is outside the approved project."


def test_unknown_tool_is_rejected() -> None:
    result = tool_registry.execute_tool(
        "terraform_destroy",
        {},
    )

    assert result.success is False
    assert result.error is not None
    assert "not allowed" in result.error


def test_invalid_arguments_are_reported(
    fake_project: Path,
) -> None:
    result = tool_registry.execute_tool(
        "check_module_files",
        {"unexpected": "value"},
    )

    assert result.success is False
    assert result.error is not None
