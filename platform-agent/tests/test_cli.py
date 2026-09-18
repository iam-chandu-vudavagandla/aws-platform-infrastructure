import json
from pathlib import Path

import pytest

from platform_agent import cli
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
