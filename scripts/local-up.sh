#!/usr/bin/env bash

set -Eeuo pipefail

readonly PROJECT_ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
  pwd
)"

readonly NAMESPACE="local"
readonly APP_IMAGE="aws-platform-app:1.2.0-local"
readonly LOCAL_OVERLAY="${PROJECT_ROOT}/kubernetes/overlays/local"
readonly DATABASE_ENV="${LOCAL_OVERLAY}/database.env"

command -v docker >/dev/null ||
{
  echo "ERROR: docker is not installed"
  exit 1
}

command -v minikube >/dev/null ||
{
  echo "ERROR: minikube is not installed"
  exit 1
}

command -v kubectl >/dev/null ||
{
  echo "ERROR: kubectl is not installed"
  exit 1
}

if [[ ! -f "${DATABASE_ENV}" ]]; then
  echo "ERROR: ${DATABASE_ENV} does not exist"
  echo "Create it from database.env.example and configure a local password."
  exit 1
fi

echo "Starting Minikube..."
minikube start

if [[ "$(kubectl config current-context)" != "minikube" ]]; then
  echo "ERROR: kubectl context is not minikube"
  exit 1
fi

echo "Building ${APP_IMAGE}..."
docker build \
  --pull \
  --tag "${APP_IMAGE}" \
  "${PROJECT_ROOT}/application"

echo "Loading the application image into Minikube..."
minikube image load "${APP_IMAGE}"

echo "Validating the local Kustomize overlay..."
kubectl kustomize "${LOCAL_OVERLAY}" \
  >/tmp/aws-platform-local.yaml

echo "Deploying the local platform..."
kubectl apply \
  -k "${LOCAL_OVERLAY}"

echo "Waiting for PostgreSQL..."
kubectl rollout status \
  deployment/postgres \
  --namespace "${NAMESPACE}" \
  --timeout=180s

echo "Restarting the application to use the latest local image..."
kubectl rollout restart \
  deployment/aws-platform-app \
  --namespace "${NAMESPACE}"

echo "Waiting for the application..."
kubectl rollout status \
  deployment/aws-platform-app \
  --namespace "${NAMESPACE}" \
  --timeout=180s

echo "Local platform is ready."
kubectl get deployments,pods,services,pvc \
  --namespace "${NAMESPACE}"
