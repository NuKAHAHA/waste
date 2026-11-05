# Smart Waste Astana — container image for the 5-agent research module.
#
# Stages:
#   base    – Python + project source (no third-party runtime dependencies)
#   test    – base + tests; its default command runs the suite and writes JUnit XML
#   runtime – minimal image that runs as a non-root user (default target)
#
# Build:  docker build -t smart-waste-astana .
# Tests:  docker build --target test -t smart-waste-astana:test . && docker run --rm smart-waste-astana:test
# Demo:   docker run --rm smart-waste-astana
# Serve:  docker run --rm -p 8088:8080 --entrypoint python smart-waste-astana tools/serve.py

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0
WORKDIR /app
COPY pyproject.toml VERSION README.md LICENSE main.py ./
COPY smart_waste/ smart_waste/
COPY data/ data/

FROM base AS test
COPY tests/ tests/
COPY tools/junit_runner.py tools/
RUN python -m compileall -q smart_waste tests && mkdir -p /reports
CMD ["python", "tools/junit_runner.py", "--output", "/reports/junit.xml"]

FROM base AS runtime
ARG VERSION=dev
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="smart-waste-astana" \
      org.opencontainers.image.description="Reproducible 5-agent waste collection planning module (Astana)" \
      org.opencontainers.image.source="https://github.com/NuKAHAHA/waste" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="MIT"
COPY tools/serve.py tools/
RUN useradd --system --uid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin smartwaste \
 && mkdir -p /app/results \
 && chown smartwaste /app/results
USER 10001
EXPOSE 8080
ENTRYPOINT ["python", "main.py"]
CMD ["demo", "--output", "/app/results"]
