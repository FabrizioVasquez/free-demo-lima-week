FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app

# dependencias primero para aprovechar la caché de capas
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev

# el índice vectorial y el modelo se generan al construir la imagen: el arranque no descarga nada
COPY data/events.json data/events.json
RUN uv run --no-sync btw index

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uv run --no-sync uvicorn brujula.server:app --host 0.0.0.0 --port ${PORT}"]
