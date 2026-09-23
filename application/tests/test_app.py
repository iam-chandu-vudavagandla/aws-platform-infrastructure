import json
import logging
from unittest.mock import patch

import pytest
from app import app
from observability import JsonFormatter


@pytest.fixture
def client():
    app.config.update(TESTING=True)

    with app.test_client() as test_client:
        yield test_client


def test_health_endpoint_returns_request_id(client):
    response = client.get(
        "/health",
        headers={
            "X-Request-ID": "test-request-id",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "healthy",
    }
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_metrics_endpoint_exposes_request_metrics(client):
    client.get("/health")

    response = client.get("/metrics")
    metrics = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.content_type.startswith("text/plain")
    assert "aws_platform_http_requests_total" in metrics
    assert 'method="GET"' in metrics
    assert 'route="/health"' in metrics
    assert 'status="200"' in metrics
    assert "aws_platform_http_request_duration_seconds" in metrics


def test_database_failure_returns_safe_response_and_metric(client):
    with patch(
        "app.check_database",
        side_effect=RuntimeError("simulated database failure"),
    ):
        response = client.get("/db/health")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "unhealthy",
        "database": "appdb",
        "error": "database connection failed",
    }

    metrics = client.get("/metrics").get_data(as_text=True)

    assert "aws_platform_database_health_checks_total" in metrics
    assert 'result="failure"' in metrics


def test_json_formatter_produces_structured_event():
    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="HTTP request completed",
        args=(),
        exc_info=None,
    )

    record.request_id = "structured-log-test"
    record.http_method = "GET"
    record.http_route = "/api/info"
    record.http_status = 200
    record.duration_ms = 1.25

    event = json.loads(JsonFormatter().format(record))

    assert event["message"] == "HTTP request completed"
    assert event["request_id"] == "structured-log-test"
    assert event["http_method"] == "GET"
    assert event["http_route"] == "/api/info"
    assert event["http_status"] == 200
    assert event["duration_ms"] == 1.25
    assert event["service"] == "AWS Platform Application"
    assert event["environment"] == "local"
    assert event["version"] == "1.0.0"
    assert event["timestamp"]
