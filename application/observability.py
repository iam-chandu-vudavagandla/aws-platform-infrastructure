import json
import logging
import os
import socket
import time
import uuid
from datetime import UTC, datetime

from flask import Response, g, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

SERVICE_NAME = os.getenv("APP_NAME", "AWS Platform Application")
SERVICE_ENVIRONMENT = os.getenv("APP_ENV", "local")
SERVICE_VERSION = os.getenv("APP_VERSION", "1.0.0")

REQUESTS = Counter(
    "aws_platform_http_requests_total",
    "Total HTTP requests processed by the application",
    ["method", "route", "status"],
)

REQUEST_DURATION = Histogram(
    "aws_platform_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
)

DATABASE_CHECKS = Counter(
    "aws_platform_database_health_checks_total",
    "Database health checks grouped by result",
    ["result"],
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": SERVICE_NAME,
            "environment": SERVICE_ENVIRONMENT,
            "version": SERVICE_VERSION,
            "hostname": socket.gethostname(),
        }

        for field in (
            "request_id",
            "http_method",
            "http_route",
            "http_status",
            "duration_ms",
            "error_type",
        ):
            value = getattr(record, field, None)

            if value is not None:
                event[field] = value

        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)

        return json.dumps(
            event,
            separators=(",", ":"),
            ensure_ascii=False,
        )


def configure_logging(app):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False


def request_started():
    supplied_request_id = request.headers.get("X-Request-ID", "").strip()

    if supplied_request_id:
        g.request_id = supplied_request_id[:128]
    else:
        g.request_id = str(uuid.uuid4())

    g.request_started_at = time.monotonic()


def request_finished(app, response):
    route = (
        request.url_rule.rule
        if request.url_rule is not None
        else "unmatched"
    )

    duration_seconds = (
        time.monotonic()
        - getattr(g, "request_started_at", time.monotonic())
    )

    if route != "/metrics":
        REQUESTS.labels(
            method=request.method,
            route=route,
            status=str(response.status_code),
        ).inc()

        REQUEST_DURATION.labels(
            method=request.method,
            route=route,
        ).observe(duration_seconds)

    response.headers["X-Request-ID"] = getattr(
        g,
        "request_id",
        str(uuid.uuid4()),
    )

    app.logger.info(
        "HTTP request completed",
        extra={
            "request_id": response.headers["X-Request-ID"],
            "http_method": request.method,
            "http_route": route,
            "http_status": response.status_code,
            "duration_ms": round(duration_seconds * 1000, 3),
        },
    )

    return response


def record_database_check(result):
    DATABASE_CHECKS.labels(result=result).inc()


def metrics_response():
    multiprocess_directory = os.getenv("PROMETHEUS_MULTIPROC_DIR")

    if multiprocess_directory:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = REGISTRY

    return Response(
        generate_latest(registry),
        status=200,
        content_type=CONTENT_TYPE_LATEST,
    )
