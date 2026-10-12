# syntax=docker/dockerfile:1

# ── Etapa 1: construir. Aquí se instalan las dependencias, se descarga el modelo y se genera el índice vectorial.
FROM python:3.14-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_PREFERENCE=only-system HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY data/events.json data/events.json
RUN .venv/bin/btw index
# adelgazar: carpetas de pruebas de las librerías y el cliente de descargas Xet (la app corre sin red, no se usa)
RUN find .venv -type d \( -name tests -o -name test \) -prune -exec rm -rf {} + \
 && rm -rf .venv/lib/python3.12/site-packages/hf_xet*

# ── Etapa 2: ejecutar. Sin uv, sin compiladores, sin caché de apt, sin root.
FROM python:3.14-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
# herramientas de empaquetado e IDLE/Tk que la app no usa: menos peso y menos superficie de ataque
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip* /usr/local/lib/python3.12/site-packages/setuptools* \
           /usr/local/lib/python3.12/site-packages/wheel* /usr/local/lib/python3.12/site-packages/_distutils_hack \
           /usr/local/lib/python3.12/ensurepip /usr/local/lib/python3.12/idlelib /usr/local/lib/python3.12/turtledemo \
           /usr/local/lib/python3.12/lib2to3 /usr/local/lib/python3.12/tkinter /usr/local/bin/pip* /usr/local/bin/idle*
WORKDIR /app
# el código y el índice quedan de SOLO LECTURA para el usuario de la app (propietario: root)
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 PORT=8080
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s CMD ["python", "-c", "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz',timeout=2)"]
CMD ["sh", "-c", "exec uvicorn brujula.server:app --host 0.0.0.0 --port ${PORT} --no-server-header"]
