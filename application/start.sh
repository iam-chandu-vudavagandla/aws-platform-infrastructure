#!/bin/sh

set -eu

readonly metrics_directory="/tmp/prometheus"

rm -rf "${metrics_directory}"
mkdir -p "${metrics_directory}"

export PROMETHEUS_MULTIPROC_DIR="${metrics_directory}"

exec gunicorn \
  --config /app/gunicorn.conf.py \
  app:app
