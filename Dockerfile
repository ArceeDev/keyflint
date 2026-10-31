# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim AS runner

WORKDIR /app

# Security: non-root user
RUN groupadd -r keyforge && useradd -r -g keyforge -d /app -s /sbin/nologin keyforge

# Copy Python packages from builder
COPY --from=builder /root/.local /home/keyforge/.local
ENV PATH=/home/keyforge/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy project files
COPY app ./app
COPY pyproject.toml .
COPY README.md .

# Create persistent data directory with permissions
RUN mkdir -p /app/data && chown -R keyforge:keyforge /app

USER keyforge

VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

ENTRYPOINT ["python", "-m", "app.cli"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
