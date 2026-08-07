FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LINGOVEIL_DEV_MODE=0 \
    XDG_CONFIG_HOME=/app/data \
    XDG_DATA_HOME=/app/data \
    XDG_CACHE_HOME=/app/cache \
    EASYOCR_MODULE_PATH=/app/modelle/ocr/easyocr

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl libgl1 libglib2.0-0 nodejs npm fonts-dejavu-core default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir torch==2.7.0 torchvision==0.22.0 --index-url "${TORCH_INDEX_URL}" \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY src /app/src
COPY web /app/web
COPY config /app/config
COPY resources /app/resources
COPY sidecar/bergamot /app/sidecar/bergamot
RUN cd /app/sidecar/bergamot \
    && npm ci --omit=dev \
    && npm cache clean --force
COPY app/live_server.py /app/live_server.py
COPY app/model_download_worker.py /app/model_download_worker.py
COPY app/sitecustomize.py /app/live_core/sitecustomize.py
COPY app/lingoveil_group_ids.py /app/live_core/lingoveil_group_ids.py
COPY app/live-controls.js /app/web/live-controls.js

RUN useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin lingoveil \
    && mkdir -p /app/data /app/modelle /app/cache \
    && chown -R lingoveil:lingoveil /app
USER lingoveil

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:8765/api/health >/dev/null || exit 1

ENV PYTHONPATH=/app/live_core:/app/src
STOPSIGNAL SIGTERM
CMD ["python", "/app/live_server.py"]
