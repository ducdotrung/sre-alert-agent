FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

WORKDIR ${APP_HOME}

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt \
    && npm install -g --ignore-scripts @earendil-works/pi-coding-agent \
    && useradd --create-home --shell /bin/bash appuser

COPY . ${APP_HOME}

RUN mkdir -p ${APP_HOME}/output \
    && chown -R appuser:appuser ${APP_HOME}

USER appuser

EXPOSE 8088

CMD ["python3", "scripts/review_web.py", "--host", "0.0.0.0", "--port", "8088"]
