from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import MODEL
from .search import load_events, now_lima, search

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Brújula Tech Week")


class Query(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    days: list[str] = []
    city: str | None = None
    mode: str | None = None
    include_soldout: bool = True
    hide_ended: bool = True
    top_n: int | None = Field(default=None, ge=1, le=12)


@app.get("/api/status")
def status():
    ev = load_events().values()
    return {
        "events": len(ev),
        "model": MODEL,
        "db": "LanceDB (local)",
        "now": now_lima(),
        "cities": sorted({e["city"] for e in ev if e["city"]}),
    }


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
