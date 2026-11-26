ARG PYTHON_BASE=python:3.12-alpine
FROM ${PYTHON_BASE}

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt ./
RUN if command -v apt-get >/dev/null; then \
        apt-get update \
        && apt-get upgrade -y --no-install-recommends \
        && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null; then \
        apk upgrade --no-cache; \
    else \
        echo "Unsupported base image package manager" >&2; exit 1; \
    fi \
    && pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && pip check \
    && if command -v groupadd >/dev/null; then \
        groupadd --gid 10001 macket \
        && useradd --uid 10001 --gid 10001 --no-create-home macket; \
    else \
        addgroup -g 10001 -S macket \
        && adduser -S -D -H -u 10001 -G macket macket; \
    fi

COPY *.py stage2_extraction_prompt.txt ./
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "45"]
