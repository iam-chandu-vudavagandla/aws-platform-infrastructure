FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup \
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

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install \
    --no-cache-dir \
    .

COPY --chown=appuser:appgroup \
    evals \
    ./evals

USER 10001:10001

ENTRYPOINT ["platform-agent"]
CMD ["--help"]
