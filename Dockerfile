# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Litestream (continuous SQLite backup to S3/R2). Only runs when LITESTREAM_* is configured.
FROM python:3.12-slim AS litestream
ARG TARGETARCH
ARG LITESTREAM_VERSION=0.3.13
RUN case "${TARGETARCH:-amd64}" in \
      amd64) SUM=eb75a3de5cab03875cdae9f5f539e6aedadd66607003d9b1e7a9077948818ba0 ;; \
      arm64) SUM=9585f5a508516bd66af2b2376bab4de256a5ef8e2b73ec760559e679628f2d59 ;; \
      *) echo "unsupported arch ${TARGETARCH}" && exit 1 ;; \
    esac \
 && python -c "import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/ls.tgz')" \
      "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-${TARGETARCH:-amd64}.tar.gz" \
 && echo "${SUM}  /tmp/ls.tgz" | sha256sum -c - \
 && tar -xzf /tmp/ls.tgz -C /usr/local/bin litestream

FROM python:3.12-slim AS runner

WORKDIR /app

# Security: non-root user
RUN groupadd -r keyflint && useradd -r -g keyflint -d /app -s /sbin/nologin keyflint

# Copy Python packages from builder
COPY --from=builder /root/.local /home/keyflint/.local
ENV PYTHONUSERBASE=/home/keyflint/.local
ENV PATH=/home/keyflint/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY --from=litestream /usr/local/bin/litestream /usr/local/bin/litestream

# Copy project files
COPY app ./app
COPY pyproject.toml .
COPY README.md .

# Create persistent data directory with permissions
RUN mkdir -p /app/data && chown -R keyflint:keyflint /app

# The entrypoint starts as root only to chown platform-mounted volumes (Render/Railway/Fly
# mount them root-owned), then drops to the unprivileged keyflint user before anything runs.
VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % (os.environ.get('PORT') or '8000'))" || exit 1

# No args: generates missing secrets into /app/data/secrets.env on first boot, then serves on $PORT.
# Any args are passed to the CLI as before, e.g. `docker run IMAGE issue ...`.
ENTRYPOINT ["python", "-m", "app.bootstrap"]
CMD []
