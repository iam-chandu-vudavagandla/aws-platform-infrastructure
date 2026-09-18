from pathlib import Path
from typing import Any


# terraform.py is located at:
# platform-agent/src/platform_agent/tools/terraform.py
#
# parents[4] resolves to:
# aws-platform-infrastructure
PROJECT_ROOT = Path(__file__).resolve().parents[4]


def safe_project_path(relative_path: str) -> Path:
    """Resolve a path while preventing access outside the project."""

    if not isinstance(relative_path, str):
        raise ValueError("Path must be a string.")

    if not relative_path.strip():
        raise ValueError("Path cannot be empty.")

    requested_path = Path(relative_path)

    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    target = (PROJECT_ROOT / requested_path).resolve()

    try:
        target.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise ValueError(
            "Path is outside the approved project."
        ) from error

    return target


def list_terraform_files(path: str = ".") -> dict[str, Any]:
    """List Terraform files under an approved project directory."""

    target = safe_project_path(path)

    if not target.exists():
        raise ValueError("Requested path does not exist.")

    if not target.is_dir():
        raise ValueError("Requested path is not a directory.")

    files = sorted(
        str(terraform_file.relative_to(PROJECT_ROOT))
        for terraform_file in target.rglob("*.tf")
        if terraform_file.is_file()
    )

    return {
        "path": path,
        "files": files,
        "count": len(files),
    }


def check_module_files(module: str) -> dict[str, Any]:
    """Check whether a Terraform module has its standard files."""

    target = safe_project_path(module)

    if not target.exists():
        raise ValueError("Requested module does not exist.")

    if not target.is_dir():
        raise ValueError("Requested module is not a directory.")

    expected = (
        "main.tf",
        "variables.tf",
        "outputs.tf",
    )

    present = [
        filename
        for filename in expected
        if (target / filename).is_file()
    ]

    missing = [
        filename
        for filename in expected
        if filename not in present
    ]

    return {
        "module": module,
        "expected": list(expected),
        "present": present,
        "missing": missing,
        "complete": len(missing) == 0,
    }
