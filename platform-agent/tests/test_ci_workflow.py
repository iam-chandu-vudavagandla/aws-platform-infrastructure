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


def test_python_ci_job_verifies_agent_dependency_lock() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    python_job = workflow.split(
        "  python:\n",
        maxsplit=1,
    )[1].split(
        "\n  docker:\n",
        maxsplit=1,
    )[0]

    marker = (
        "      - name: Verify reliability-agent "
        "dependency lock\n"
    )

    assert marker in python_job

    lock_step = python_job.split(
        marker,
        maxsplit=1,
    )[1].split(
        "\n      - name:",
        maxsplit=1,
    )[0]

    assert "working-directory: platform-agent" in lock_step
    assert "python -m piptools compile" in lock_step
    assert "--all-build-deps" in lock_step
    assert "--allow-unsafe" in lock_step
    assert "--generate-hashes" in lock_step
    assert "--output-file requirements.lock" in lock_step
    assert "git diff --exit-code -- requirements.lock" in lock_step


def test_kubernetes_ci_validates_rendered_manifests() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert (
        "Validate rendered Kubernetes schemas"
        in workflow
    )
    assert (
        "ghcr.io/yannh/kubeconform:v0.8.0-alpine"
        in workflow
    )
    assert "kubernetes/base" in workflow
    assert "kubernetes/overlays/dev" in workflow
    assert "kubernetes/overlays/local" in workflow
    assert (
        "-kubernetes-version 1.35.0"
        in workflow
    )
    assert "-strict" in workflow
    assert "-summary" in workflow



def test_kubernetes_ci_enforces_workload_policies() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    policy_file = (
        REPOSITORY_ROOT
        / "policies"
        / "kubernetes"
        / "workload.rego"
    )

    policy_test_file = (
        REPOSITORY_ROOT
        / "policies"
        / "kubernetes"
        / "workload_test.rego"
    )

    assert policy_file.is_file()
    assert policy_test_file.is_file()

    policy = policy_file.read_text(encoding="utf-8")
    policy_tests = policy_test_file.read_text(
        encoding="utf-8",
    )

    assert "Run Kubernetes policy checks" in workflow
    assert (
        "openpolicyagent/conftest:v0.71.1"
        in workflow
    )
    assert "policies/kubernetes" in workflow

    assert "runAsNonRoot" in policy
    assert "allowPrivilegeEscalation" in policy
    assert "privileged" in policy
    assert "resources" in policy
    assert "readinessProbe" in policy
    assert "livenessProbe" in policy
    assert "@sha256:" in policy
    assert "verify" in workflow
    assert (
        "test_secure_application_workload_is_allowed"
        in policy_tests
    )
    assert (
        "test_privileged_container_is_denied"
        in policy_tests
    )
    assert (
        "test_unpinned_development_image_is_denied"
        in policy_tests
    )
