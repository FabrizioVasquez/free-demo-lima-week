"""Fragmenta cada evento por tokens, lo convierte en vectores y lo guarda en LanceDB (local)."""
from __future__ import annotations

import json
import re

import lancedb

from .config import DB_DIR, EVENTS_JSON, TABLE
from .embed import embed, tokenizer

# El modelo (paraphrase-multilingual-MiniLM-L12-v2) se entrenó con 128 tokens: lo que pase de ahí se descarta en silencio.
BUDGET = 120  # 128 menos margen para tokens especiales
OVERLAP = 16  # tokens compartidos entre fragmentos vecinos, para no cortar una idea por la mitad
MAX_CHUNKS = 12
MAX_HEAD_TOKENS = 48


def chunks_of(ev: dict, tok) -> list[tuple[str, str]]:
    """Devuelve [(texto_a_vectorizar, cuerpo)]. Cada texto = cabecera (nombre y organizadores) + una ventana de la descripción.

    `tok` solo necesita `encode(text, add_special_tokens=False)` con `.ids` y `.offsets` (así se puede probar sin el modelo).
    """
    head = f"{ev['name']}. {' '.join(ev['hosts'])}".strip()
    head_tokens = len(tok.encode(head, add_special_tokens=False).ids)
    while head_tokens > MAX_HEAD_TOKENS:  # nombres larguísimos no pueden comerse el presupuesto
        head = head[: int(len(head) * 0.8)]
        head_tokens = len(tok.encode(head, add_special_tokens=False).ids)

    desc = re.sub(r"\s+", " ", re.sub(r"https?://\S+", " ", ev["description"])).strip()
    if not desc:
        return [(head, "")]
    room = BUDGET - head_tokens - 2
    step = max(8, room - OVERLAP)
    enc = tok.encode(desc, add_special_tokens=False)
    n, i, out = len(enc.ids), 0, []
    while i < n and len(out) < MAX_CHUNKS:
        j = min(n, i + room)
        body = desc[enc.offsets[i][0]: enc.offsets[j - 1][1]].strip()
        out.append((f"{head}. {body}", body))
        if j >= n:
            break
        i += step
    return out


def build() -> int:
    events = json.loads(EVENTS_JSON.read_text(encoding="utf-8"))
    tok = tokenizer()
    rows, texts = [], []
    for ev in events:
        for n, (text, body) in enumerate(chunks_of(ev, tok)):
            texts.append(text)
            rows.append({
                "event_id": ev["id"], "chunk_no": n, "text": text, "body": body,
                "day": ev["start"][:10], "start": ev["start"], "end": ev["end"],
                "status": ev["status"], "city": ev["city"], "mode": ev["mode"],
            })
    vecs = embed(texts)
    for r, v in zip(rows, vecs, strict=True):
        r["vector"] = v.tolist()
    DB_DIR.mkdir(parents=True, exist_ok=True)
    lancedb.connect(str(DB_DIR)).create_table(TABLE, data=rows, mode="overwrite")
    return len(rows)


def table():
    return lancedb.connect(str(DB_DIR)).open_table(TABLE)
