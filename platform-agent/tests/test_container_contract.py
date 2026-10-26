from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"


def test_dockerfile_uses_non_root_cli_runtime() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert content.startswith(
        "FROM python:3.12-alpine\n"
    )
    assert "addgroup" in content
    assert "adduser" in content
    assert "USER 10001:10001" in content
    assert 'ENTRYPOINT ["platform-agent"]' in content
    assert 'CMD ["--help"]' in content
    assert "evals" in content


def test_dockerignore_excludes_local_and_sensitive_files() -> None:
    entries = {
        line.strip()
        for line in DOCKERIGNORE.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
    }

    required_entries = {
        ".venv",
        ".env",
        ".env.*",
        "__pycache__",
        "*.py[cod]",
        "*.pem",
        "*.key",
        "*.tfstate*",
        "tests",
    }

    assert required_entries <= entries
    assert "evals" not in entries
