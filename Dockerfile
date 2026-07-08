FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    NODE_VERSION=24.15.0

WORKDIR ${APP_HOME}

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*

# pi CLI 0.79.x requires Node >=22.19.0.
RUN arch="$(dpkg --print-architecture)" \
    && case "${arch}" in \
        amd64) node_arch='x64' ;; \
        arm64) node_arch='arm64' ;; \
        *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" -o /tmp/node.tar.xz \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --no-same-owner \
    && rm -f /tmp/node.tar.xz

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt \
    && node --version \
    && npm --version \
    && npm install -g --ignore-scripts @earendil-works/pi-coding-agent \
    && useradd --create-home --shell /bin/bash appuser

COPY . ${APP_HOME}

RUN mkdir -p ${APP_HOME}/output \
    && chown -R appuser:appuser ${APP_HOME}

USER appuser

EXPOSE 8088

CMD ["python3", "scripts/review_web.py", "--host", "0.0.0.0", "--port", "8088"]
