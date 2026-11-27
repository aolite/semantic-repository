# Imagen del backend del repositorio semántico IT&OT.
# Python fijado igual que en backend/.python-version; dependencias desde uv.lock.

FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM python:3.15.2-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.15.2-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# Java para Pellet (consistencia OWL en la ingesta de ontologías, incluido en owlready2).
# JRE headless de Debian 13 (trixie), versión fijada. Java 25 como mínimo: el Jena que
# incluye owlready2 0.51 para Pellet está compilado para Java 25 (class file 69). Añade
# unos 240 MB a la imagen (ver backend/README.md). Si Debian retira esta versión de sus
# réplicas, el build falla: hay que actualizar el número (apt-cache policy
# openjdk-25-jre-headless).
ARG JRE_VERSION=25.0.5.1+2-1~deb13u1
RUN mkdir -p /usr/share/man/man1 \
    && apt-get update \
    && apt-get install -y --no-install-recommends "openjdk-25-jre-headless=${JRE_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && java -version
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /data/distributions \
    && chown app:app /data/distributions
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# pyproject.toml: de ahí sale la versión que publican /health y el OpenAPI (app/__init__.py).
COPY --chown=app:app alembic.ini pyproject.toml ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app docker-entrypoint.sh ./
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
ENTRYPOINT ["./docker-entrypoint.sh"]
