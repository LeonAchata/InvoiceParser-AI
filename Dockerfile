FROM python:3.12-slim

LABEL org.opencontainers.image.title="InvoiceParser AI" \
      org.opencontainers.image.source="https://github.com/LeonAchata/InvoiceParser-AI"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_PATH=/app/data/invoices.db \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --create-home --uid 1000 appuser && mkdir -p /app/data && chown appuser:appuser /app/data
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser frontend ./frontend
COPY --chown=appuser:appuser samples ./samples
USER appuser

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/api/health')" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
