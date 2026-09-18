#!/usr/bin/env bash

set -Eeuo pipefail

readonly NAMESPACE="local"
readonly SERVICE_URL="http://aws-platform-app-service"
readonly CURL_IMAGE="curlimages/curl:8.12.1"

if [[ "$(kubectl config current-context)" != "minikube" ]]; then
  echo "ERROR: kubectl context is not minikube"
  exit 1
fi

echo "Testing application information endpoint..."
kubectl run "app-api-test-$$" \
  --namespace "${NAMESPACE}" \
  --rm -i \
  --restart=Never \
  --image="${CURL_IMAGE}" \
  -- curl -fsS \
    "${SERVICE_URL}/api/info"

echo
echo "Testing database health endpoint..."
kubectl run "app-db-test-$$" \
  --namespace "${NAMESPACE}" \
  --rm -i \
  --restart=Never \
  --image="${CURL_IMAGE}" \
  -- curl -fsS \
    "${SERVICE_URL}/db/health"

echo
echo "All local smoke tests passed."
