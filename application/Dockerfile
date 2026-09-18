FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

RUN apk upgrade --no-cache \
    && addgroup \
        --system \
        --gid 10001 \
        appgroup \
    && adduser \
        --system \
        --disabled-password \
        --no-create-home \
        --uid 10001 \
        --ingroup appgroup \
        appuser

COPY requirements.txt .

RUN pip install \
    --no-cache-dir \
    --requirement requirements.txt

COPY --chown=appuser:appgroup app.py .

USER 10001:10001

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "2", "--timeout", "30", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
