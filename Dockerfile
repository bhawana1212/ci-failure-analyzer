FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    DATABASE_URL=sqlite:////data/ci-analyzer.db

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
COPY ci_analyzer ./ci_analyzer
RUN uv sync --frozen --no-dev \
    && useradd --uid 10001 --create-home analyzer \
    && mkdir /data \
    && chown analyzer:analyzer /data

USER analyzer
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["/app/.venv/bin/uvicorn", "ci_analyzer.main:app", "--host", "0.0.0.0", "--port", "8000"]