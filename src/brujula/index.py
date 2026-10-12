"""Divide cada evento en fragmentos, los convierte en vectores y los guarda en LanceDB (local)."""

from __future__ import annotations

import json
import re

import lancedb

from .config import DB_DIR, EVENTS_JSON, TABLE
from .embed import embed

CHUNK_WORDS = 70  # el modelo ve ~128 tokens por fragmento


def chunks_of(ev: dict) -> list[tuple[str, str]]:
    head = f"{ev['name']}. {' '.join(ev['hosts'])}".strip()  # sin ciudad: el lugar se evalúa aparte, en la logística
    words = re.sub(r"https?://\S+", " ", ev["description"]).split()
    parts = [" ".join(words[i : i + CHUNK_WORDS]) for i in range(0, len(words), CHUNK_WORDS)] or [""]
    # el nombre va en todos los fragmentos para que cada uno conserve el contexto del evento
    return [(f"{head}. {p}".strip(), p) for p in parts[:8]]


def build() -> int:
    events = json.loads(EVENTS_JSON.read_text(encoding="utf-8"))
    rows, texts = [], []
    for ev in events:
        for n, (text, body) in enumerate(chunks_of(ev)):
            texts.append(text)
            rows.append(
                {
                    "event_id": ev["id"],
                    "chunk_no": n,
                    "text": text,
                    "body": body,
                    "day": ev["start"][:10],
                    "start": ev["start"],
                    "end": ev["end"],
                    "status": ev["status"],
                    "city": ev["city"],
                    "mode": ev["mode"],
                }
            )
    vecs = embed(texts)
    for r, v in zip(rows, vecs, strict=True):
        r["vector"] = v.tolist()
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(DB_DIR))
    db.create_table(TABLE, data=rows, mode="overwrite")
    return len(rows)


def table():
    return lancedb.connect(str(DB_DIR)).open_table(TABLE)
