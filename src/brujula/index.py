"""Fragmenta cada evento por tokens, lo convierte en vectores y lo guarda en Qdrant (modo local, en disco)."""
from __future__ import annotations

import atexit
import json
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient, models

from .config import COLLECTION, EVENTS_JSON, QDRANT_DIR
from .embed import embed, tokenizer

# El modelo (paraphrase-multilingual-MiniLM-L12-v2) se entrenó con 128 tokens: lo que pase de ahí se descarta en silencio.
BUDGET = 120  # 128 menos margen para tokens especiales
OVERLAP = 16  # tokens compartidos entre fragmentos vecinos, para no cortar una idea por la mitad
MAX_CHUNKS = 12
MAX_HEAD_TOKENS = 48
LIMA = timezone(timedelta(hours=-5))


def to_ts(s: str) -> int:
    """'2026-10-15 18:30' (hora de Lima) -> segundos Unix. Qdrant filtra rangos con números, no con texto."""
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=LIMA).timestamp())


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
    payloads, texts = [], []
    for ev in events:
        for n, (text, body) in enumerate(chunks_of(ev, tok)):
            texts.append(text)
            payloads.append({
                "event_id": ev["id"], "chunk_no": n, "body": body,
                "status": ev["status"], "city": ev["city"], "mode": ev["mode"],
                "start_ts": to_ts(ev["start"]), "end_ts": to_ts(ev["end"]),
            })
    vecs = embed(texts)
    if QDRANT_DIR.exists():
        shutil.rmtree(QDRANT_DIR)
    QDRANT_DIR.parent.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(QDRANT_DIR))
    try:
        client.create_collection(COLLECTION, vectors_config=models.VectorParams(size=int(vecs.shape[1]), distance=models.Distance.COSINE))
        client.upload_points(COLLECTION, points=[
            models.PointStruct(id=i, vector=v.tolist(), payload=p) for i, (v, p) in enumerate(zip(vecs, payloads, strict=True))
        ])
    finally:
        client.close()
    return len(payloads)


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    """Abre el índice desde una COPIA en un directorio temporal (~1 MB).

    El modo local de Qdrant necesita escribir un archivo `.lock`; así la imagen puede ser de solo lectura
    y tampoco hay choque si `btw index` reconstruye el índice mientras el servidor corre.
    """
    if not QDRANT_DIR.exists():
        raise FileNotFoundError("No hay índice: ejecuta `uv run btw index`")
    tmp = Path(tempfile.mkdtemp(prefix="btw-qdrant-"))
    shutil.copytree(QDRANT_DIR, tmp / "db")
    atexit.register(shutil.rmtree, tmp, True)  # atexit corre al revés: primero se cierra el cliente, luego se borra la copia
    client = QdrantClient(path=str(tmp / "db"))
    atexit.register(client.close)
    return client


def query(vector, flt: models.Filter | None = None, limit: int = 2000):
    """Búsqueda por similitud coseno con filtro tipado opcional. Devuelve puntos con `.score` (similitud) y `.payload`."""
    return get_client().query_points(COLLECTION, query=list(map(float, vector)), query_filter=flt, limit=limit, with_payload=True).points
