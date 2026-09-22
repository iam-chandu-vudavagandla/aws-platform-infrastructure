#!/usr/bin/env bash

set -Eeuo pipefail

readonly PROJECT_ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
  pwd
)"

readonly OUTPUT_FILE="${1:-}"

if [[ -z "${OUTPUT_FILE}" ]]; then
  echo "Usage: $0 OUTPUT_FILE" >&2
  exit 1
fi

required_variables=(
  ECR_REPOSITORY_URI
  IMAGE_DIGEST
  APPLICATION_ROLE_ARN
  DB_SECRET_ARN
  DB_HOST
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "ERROR: ${variable_name} is required" >&2
    exit 1
  fi
done

render_root="$(mktemp -d)"
trap 'rm -rf "${render_root}"' EXIT

cp -R \
  "${PROJECT_ROOT}/kubernetes" \
  "${render_root}/kubernetes"

export DEV_OVERLAY="${render_root}/kubernetes/overlays/dev"

python3 <<'PY'
import os
from pathlib import Path

overlay = Path(os.environ["DEV_OVERLAY"])

replacements = {
    overlay / "kustomization.yaml": {
        "000000000000.dkr.ecr.ap-south-1.amazonaws.com/aws-platform-dev-app":
            os.environ["ECR_REPOSITORY_URI"],
        "sha256:0000000000000000000000000000000000000000000000000000000000000000":
            os.environ["IMAGE_DIGEST"],
    },
    overlay / "app-serviceaccount-patch.yaml": {
        "arn:aws:iam::000000000000:role/REPLACE_WITH_APPLICATION_ROLE":
            os.environ["APPLICATION_ROLE_ARN"],
    },
    overlay / "app-configmap-patch.yaml": {
        "replace-with-rds-endpoint.invalid":
            os.environ["DB_HOST"],
        "arn:aws:secretsmanager:ap-south-1:000000000000:secret:REPLACE_WITH_APPLICATION_DATABASE_SECRET":
            os.environ["DB_SECRET_ARN"],
    },
}

for path, file_replacements in replacements.items():
    content = path.read_text(encoding="utf-8")

    for placeholder, value in file_replacements.items():
        if placeholder not in content:
            raise SystemExit(
                f"Expected placeholder not found in {path}: {placeholder}"
            )

        content = content.replace(placeholder, value)

    path.write_text(content, encoding="utf-8")
PY

kubectl kustomize \
  "${DEV_OVERLAY}" \
  >"${OUTPUT_FILE}"

if grep -Eq \
  '000000000000|REPLACE_WITH_|replace-with-.*\.invalid|sha256:0{64}' \
  "${OUTPUT_FILE}"; then
  echo "ERROR: unresolved deployment placeholder detected" >&2
  exit 1
fi

echo "Rendered development manifests to ${OUTPUT_FILE}" >&2
