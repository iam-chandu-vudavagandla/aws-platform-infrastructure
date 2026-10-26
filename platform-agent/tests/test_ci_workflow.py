from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = (
    REPOSITORY_ROOT
    / ".github"
    / "workflows"
    / "ci.yaml"
)


def test_python_ci_job_runs_offline_agent_quality_gate() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    python_job = workflow.split(
        "  python:\n",
        maxsplit=1,
    )[1].split(
        "\n  docker:\n",
        maxsplit=1,
    )[0]

    assert "python -m pytest" in python_job
    assert "python -m pip check" in python_job
    assert (
        "platform-agent evaluate evals/fixtures"
        in python_job
    )

    assert "AWS_ACCESS_KEY_ID" not in python_job
    assert "AWS_SECRET_ACCESS_KEY" not in python_job
    assert "configure-aws-credentials" not in python_job

def test_docker_ci_job_builds_and_evaluates_agent_image() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    docker_job = workflow.split(
        "  docker:\n",
        maxsplit=1,
    )[1].split(
        "\n  secrets:\n",
        maxsplit=1,
    )[0]

    assert "context: platform-agent" in docker_job
    assert "load: true" in docker_job
    assert "tags: platform-agent:ci" in docker_job
    assert "docker run" in docker_job
    assert "platform-agent:ci" in docker_job
    assert "evaluate evals/fixtures" in docker_job
