import json
import os
import socket
import time
from threading import Lock

import boto3
import psycopg
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

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
            <title>{{ app_name }}</title>
            <style>
              body {
                background: #f4f7fb;
                color: #172033;
                font-family: Arial, sans-serif;
                margin: 0;
              }

              main {
                background: white;
                border-radius: 12px;
                box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
                margin: 80px auto;
                max-width: 700px;
                padding: 40px;
              }

              h1 {
                color: #ff9900;
              }

              .status {
                color: #137333;
                font-weight: bold;
              }

              code {
                background: #eef2f7;
                border-radius: 4px;
                padding: 3px 7px;
              }
            </style>
          </head>
          <body>
            <main>
              <h1>{{ app_name }}</h1>
              <p class="status">Application is running successfully.</p>
              <p>Environment: <code>{{ environment }}</code></p>
              <p>Version: <code>{{ version }}</code></p>
              <p>Pod: <code>{{ hostname }}</code></p>
              <p>Platform: Amazon EKS with AWS ALB and ECR</p>
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
        return jsonify(result), 200

    except Exception as error:
        app.logger.error(
            "Database health check failed: %s",
            type(error).__name__,
        )

        return jsonify(
            status="unhealthy",
            database=DB_NAME,
            error="database connection failed",
        ), 503


@app.errorhandler(404)
def not_found(_error):
    return jsonify(error="not found"), 404
