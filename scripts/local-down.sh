#!/usr/bin/env bash

set -Eeuo pipefail

echo "Stopping Minikube while preserving cluster data..."
minikube stop

echo "Minikube stopped. PostgreSQL persistent data was preserved."
