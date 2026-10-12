"""Embeddings locales con fastembed (ONNX, cuantizado): sin API keys, sin GPU, sin que tu texto salga del servidor."""
from __future__ import annotations

import threading
from functools import lru_cache

import numpy as np

from .config import MODEL, MODEL_CACHE

_lock = threading.Lock()  # el modelo se comparte entre hilos de FastAPI: serializamos la inferencia (~4 ms)


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=MODEL, cache_dir=str(MODEL_CACHE))


@lru_cache(maxsize=1)
def tokenizer():
    """Copia del tokenizador del modelo SIN truncar, para medir fragmentos con exactitud."""
    from tokenizers import Tokenizer

    t = Tokenizer.from_str(_model().model.tokenizer.to_str())
    t.no_truncation()
    return t


def embed(texts: list[str]) -> np.ndarray:
    with _lock:
        vecs = np.array(list(_model().embed(texts)), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-9, None)
