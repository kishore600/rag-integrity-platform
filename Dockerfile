FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Unprivileged user; /data holds the SQLite ledger when no Postgres/Supabase URL is configured.
RUN useradd --create-home --uid 10001 ragi && mkdir /data && chown ragi /data

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY examples ./examples
COPY scripts ./scripts
COPY supabase ./supabase

USER ragi
ENV RAGI_DATABASE_URL=sqlite:////data/ragi.db
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# Demo mode out of the box. Set RAGI_MODE=live (and the S3 / manifest / Qdrant variables) for real infrastructure.
CMD ["ragi", "serve", "--host", "0.0.0.0", "--port", "8000"]
