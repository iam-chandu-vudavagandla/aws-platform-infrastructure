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

COPY --chown=appuser:appgroup \
    app.py \
    observability.py \
    gunicorn.conf.py \
    start.sh \
    ./

USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()"

CMD ["/app/start.sh"]
