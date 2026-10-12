from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("BTW_DATA_DIR", ROOT / "data"))
EVENTS_JSON = DATA_DIR / "events.json"
QDRANT_DIR = DATA_DIR / "qdrant"
COLLECTION = "event_chunks"

CALENDAR_SLUG = os.environ.get("BTW_CALENDAR", "Perutechweek2026")
MODEL = os.environ.get("BTW_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
MODEL_CACHE = DATA_DIR / "models"

LIMA_UTC_OFFSET_HOURS = -5
