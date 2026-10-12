from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import MODEL
from .search import load_events, now_lima, search
from .security import HEADERS, MAX_BODY, RateLimiter, client_ip

log = logging.getLogger("brujula")
STATIC = Path(__file__).parent / "static"
DAY_RX = re.compile(r"^2026-10-1[2-8]$")
limiter = RateLimiter(limit=20, window_s=60)



@asynccontextmanager
async def lifespan(_: FastAPI):
    """Carga el modelo y abre el índice ANTES de aceptar tráfico: sin esto, la primera búsqueda de cada instancia nueva espera ~4 s."""
    try:
        search("calentamiento del modelo", top_n=1)
    except Exception:  # un índice ausente no debe impedir arrancar; /healthz sigue respondiendo
        log.exception("no se pudo calentar el modelo")
    yield


# Sin /docs, /redoc ni /openapi.json: no hay motivo para publicar el esquema de la API.
app = FastAPI(title="Brújula Tech Week", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos = 422, no se ignoran en silencio

    prompt: str = Field(min_length=3, max_length=1500)
    days: list[str] = Field(default_factory=list, max_length=7)
    city: str | None = Field(default=None, max_length=60)
    mode: Literal["presencial", "virtual"] | None = None
    include_soldout: bool = True
    hide_ended: bool = True
    top_n: int | None = Field(default=None, ge=1, le=12)

    @field_validator("prompt")
    @classmethod
    def _prompt(cls, v: str) -> str:
        v = "".join(c for c in v if c == "\n" or c.isprintable()).strip()
        if len(v) < 3:
            raise ValueError("prompt demasiado corto")
        return v

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[str]) -> list[str]:
        if not all(DAY_RX.match(d) for d in v):
            raise ValueError("día fuera del rango del evento")
        return v

    @field_validator("city")
    @classmethod
    def _city(cls, v: str | None) -> str | None:
        # lista blanca: solo se aceptan distritos que existen (defensa en profundidad; el filtro de Qdrant ya es tipado)
        if v and v not in {e["city"] for e in load_events().values()}:
            raise ValueError("distrito desconocido")
        return v or None


@app.middleware("http")
async def guard(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY:
        resp = JSONResponse({"detail": "Solicitud demasiado grande"}, status_code=413)
    elif request.method == "POST" and request.url.path == "/api/search" and not limiter.allow(
        client_ip(request.headers.get("x-forwarded-for"), request.client.host if request.client else None)
    ):
        resp = JSONResponse({"detail": "Demasiadas solicitudes, espera un minuto"}, status_code=429, headers={"Retry-After": "30"})
    else:
        try:
            resp = await call_next(request)
        except Exception:  # nunca devolver trazas al cliente
            log.exception("error no controlado en %s", request.url.path)
            resp = JSONResponse({"detail": "Error interno"}, status_code=500)
    for k, v in HEADERS.items():
        resp.headers.setdefault(k, v)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/status")
def status():
    ev = load_events().values()
    return {"events": len(ev), "model": MODEL, "db": "Qdrant (local)", "now": now_lima(),
            "cities": sorted({e["city"] for e in ev if e["city"]})}


@app.get("/api/events")
def events():
    return list(load_events().values())


@app.post("/api/search")
def do_search(q: Query):
    return search(q.prompt, q.days, q.city, q.mode, q.include_soldout, q.hide_ended, q.top_n)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
