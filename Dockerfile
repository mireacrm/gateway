FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY pyproject.toml /srv/
COPY app /srv/app

# Обвяз приезжает из своего репозитория по версии из pyproject.toml,
# поэтому сборке нужен git. В готовом образе он не остаётся.
# Берётся только ядро обвяза: базы, брокера и gRPC у шлюза нет.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && pip install . \
 && apt-get purge -y --auto-remove git \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 1001 gateway && chown -R gateway /srv
USER gateway

EXPOSE 8000
CMD ["python", "-m", "app"]
