import json
import os
import socket
import time
from threading import Lock

import boto3
import psycopg
from flask import Flask, jsonify, render_template_string
from observability import (
    configure_logging,
    metrics_response,
    record_database_check,
    request_finished,
    request_started,
)

app = Flask(__name__)

configure_logging(app)
app.before_request(request_started)


@app.after_request
def observe_request(response):
    return request_finished(app, response)

APP_NAME = os.getenv("APP_NAME", "AWS Platform Application")
APP_ENV = os.getenv("APP_ENV", "local")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
DB_SECRET_ARN = os.getenv("DB_SECRET_ARN", "")
DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "appdb")
DB_USERNAME = os.getenv("DB_USERNAME", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "5"))
SECRET_CACHE_SECONDS = 300

_secret_cache = None
_secret_cached_at = 0
_secret_lock = Lock()


def get_database_credentials():
    global _secret_cache
    global _secret_cached_at

    if not DB_SECRET_ARN:
        if not DB_USERNAME or not DB_PASSWORD:
            raise RuntimeError(
                "DB_USERNAME and DB_PASSWORD are not configured"
            )

        return {
            "username": DB_USERNAME,
            "password": DB_PASSWORD,
        }

    with _secret_lock:
        cache_age = time.monotonic() - _secret_cached_at

        if _secret_cache and cache_age < SECRET_CACHE_SECONDS:
            return _secret_cache

        secrets_client = boto3.client(
            "secretsmanager",
            region_name=AWS_REGION,
        )

        response = secrets_client.get_secret_value(
            SecretId=DB_SECRET_ARN,
        )

        credentials = json.loads(response["SecretString"])

        required_fields = {
            "username",
            "password",
        }

        missing_fields = required_fields.difference(credentials)

        if missing_fields:
            raise RuntimeError(
                "Database secret is missing required fields"
            )

        _secret_cache = credentials
        _secret_cached_at = time.monotonic()

        return credentials

def check_database():
    if not DB_HOST:
        raise RuntimeError("DB_HOST is not configured")

    credentials = get_database_credentials()

    with psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=credentials["username"],
        password=credentials["password"],
        connect_timeout=DB_CONNECT_TIMEOUT,
        sslmode=DB_SSLMODE,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database(),
                    current_user,
                    current_setting('server_version')
                """
            )

            database, database_user, postgres_version = cursor.fetchone()

    return {
        "status": "healthy",
        "database": database,
        "database_user": database_user,
        "postgres_version": postgres_version,
    }


@app.get("/")
def index():
    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
          <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <meta
              name="description"
              content="DevOps and Platform Engineering portfolio project built with AWS, Terraform, Kubernetes, Amazon EKS, CI/CD, observability, and Agentic AI."
            >
            <title>Chandu | DevOps & Platform Engineering</title>

            <style>
              * {
                box-sizing: border-box;
              }

              body {
                background: #f4f7fb;
                color: #172033;
                font-family: Arial, sans-serif;
                line-height: 1.6;
                margin: 0;
              }

              main {
                margin: 0 auto;
                max-width: 1050px;
                padding: 60px 24px;
              }

              .hero,
              .section {
                background: white;
                border-radius: 14px;
                box-shadow: 0 8px 30px rgba(0, 0, 0, 0.07);
                margin-bottom: 24px;
                padding: 36px;
              }

              .eyebrow {
                color: #526173;
                font-size: 14px;
                font-weight: bold;
                letter-spacing: 1px;
                text-transform: uppercase;
              }

              h1 {
                color: #172033;
                font-size: 42px;
                line-height: 1.15;
                margin: 8px 0 16px;
              }

              h2 {
                color: #172033;
                margin-top: 0;
              }

              .accent {
                color: #ff9900;
              }

              .lead {
                font-size: 18px;
                max-width: 800px;
              }

              .status {
                color: #137333;
                font-weight: bold;
              }

              .grid {
                display: grid;
                gap: 16px;
                grid-template-columns: repeat(
                  auto-fit,
                  minmax(220px, 1fr)
                );
              }

              .card {
                background: #f8fafc;
                border: 1px solid #e5eaf0;
                border-radius: 10px;
                padding: 20px;
              }

              .card h3 {
                margin-top: 0;
              }

              .stack {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
              }

              .tag {
                background: #eef2f7;
                border-radius: 20px;
                font-size: 14px;
                padding: 7px 12px;
              }

              code {
                background: #eef2f7;
                border-radius: 4px;
                padding: 3px 7px;
              }

              a {
                color: #0969da;
                font-weight: bold;
              }

              footer {
                color: #667085;
                padding: 12px 4px 40px;
                text-align: center;
              }

              @media (max-width: 600px) {
                h1 {
                  font-size: 32px;
                }

                .hero,
                .section {
                  padding: 24px;
                }
              }
            </style>
          </head>

          <body>
            <main>
              <section class="hero">
                <div class="eyebrow">
                  DevOps • Platform Engineering • Cloud Infrastructure
                </div>

                <h1>
                  Chandu's
                  <span class="accent">AWS Platform Engineering</span>
                  Project
                </h1>

                <p class="lead">
                  A hands-on software engineering portfolio project demonstrating
                  production-style cloud infrastructure, Kubernetes operations,
                  CI/CD automation, observability, reliability engineering, and
                  Agentic AI for DevOps.
                </p>

                <p class="status">
                  Platform application is running successfully on Amazon EKS.
                </p>

                <p>
                  Environment: <code>{{ environment }}</code>
                  &nbsp; Version: <code>{{ version }}</code>
                  &nbsp; Pod: <code>{{ hostname }}</code>
                </p>
              </section>

              <section class="section">
                <h2>Project Architecture</h2>

                <div class="grid">
                  <div class="card">
                    <h3>Infrastructure as Code</h3>
                    <p>
                      AWS infrastructure is provisioned and managed with
                      Terraform, including networking, IAM, EKS, ECR, RDS,
                      security groups, and supporting cloud services.
                    </p>
                  </div>

                  <div class="card">
                    <h3>Kubernetes Platform</h3>
                    <p>
                      The application runs on Amazon EKS with Kubernetes
                      deployments, health probes, autoscaling, disruption
                      protection, scheduling controls, and AWS ALB ingress.
                    </p>
                  </div>

                  <div class="card">
                    <h3>CI/CD Engineering</h3>
                    <p>
                      GitHub-based automation builds, tests, scans, publishes
                      container images to Amazon ECR, and deploys workloads to
                      the Kubernetes platform.
                    </p>
                  </div>

                  <div class="card">
                    <h3>Data & Security</h3>
                    <p>
                      PostgreSQL runs on Amazon RDS with application credentials
                      stored in AWS Secrets Manager and accessed using
                      least-privilege IAM integration.
                    </p>
                  </div>

                  <div class="card">
                    <h3>Observability</h3>
                    <p>
                      The application exposes health, readiness, metrics, and
                      structured operational signals for monitoring and
                      reliability investigation.
                    </p>
                  </div>

                  <div class="card">
                    <h3>Agentic AI Reliability</h3>
                    <p>
                      A read-only reliability agent collects Kubernetes
                      deployment, pod, event, and bounded log evidence, then
                      produces structured incident reports with deterministic
                      checks and optional local LLM reasoning.
                    </p>
                  </div>
                </div>
              </section>

              <section class="section">
                <h2>Technology Stack</h2>

                <div class="stack">
                  <span class="tag">AWS</span>
                  <span class="tag">Terraform</span>
                  <span class="tag">Amazon EKS</span>
                  <span class="tag">Kubernetes</span>
                  <span class="tag">Docker</span>
                  <span class="tag">Amazon ECR</span>
                  <span class="tag">AWS ALB</span>
                  <span class="tag">Amazon RDS PostgreSQL</span>
                  <span class="tag">AWS Secrets Manager</span>
                  <span class="tag">GitHub Actions</span>
                  <span class="tag">Python</span>
                  <span class="tag">Flask</span>
                  <span class="tag">Pydantic</span>
                  <span class="tag">Ollama</span>
                  <span class="tag">Agentic AI</span>
                  <span class="tag">AIOps</span>
                </div>
              </section>

              <section class="section">
                <h2>Engineering Goal</h2>

                <p>
                  This project is built as a practical DevOps and Platform
                  Engineering portfolio to demonstrate cloud-native software
                  delivery, infrastructure automation, Kubernetes reliability,
                  secure application deployment, and AI-assisted operational
                  investigation.
                </p>

                <p>
                  Source code:
                  <a
                    href="https://github.com/iam-chandu-vudavagandla/aws-platform-infrastructure"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    github.com/iam-chandu-vudavagandla/aws-platform-infrastructure
                  </a>
                </p>
              </section>

              <footer>
                {{ app_name }} • DevOps & Platform Engineering Portfolio
              </footer>
            </main>
          </body>
        </html>
        """,
        app_name=APP_NAME,
        environment=APP_ENV,
        version=APP_VERSION,
        hostname=socket.gethostname(),
    )


@app.get("/health")
def health():
    return jsonify(status="healthy"), 200


@app.get("/ready")
def ready():
    return jsonify(status="ready"), 200

@app.get("/metrics")
def metrics():
    return metrics_response()

@app.get("/api/info")
def info():
    return jsonify(
        application=APP_NAME,
        environment=APP_ENV,
        version=APP_VERSION,
        hostname=socket.gethostname(),
    )


@app.get("/db/health")
def database_health():
    try:
        result = check_database()
        record_database_check("success")
        return jsonify(result), 200
    except Exception as error:
        record_database_check("failure")
        app.logger.error(
            "Database health check failed",
            extra={
                "error_type": type(error).__name__,
            },
            exc_info=True,
        )

        return jsonify(
            status="unhealthy",
            database=DB_NAME,
            error="database connection failed",
        ), 503


@app.errorhandler(404)
def not_found(_error):
    return jsonify(error="not found"), 404
