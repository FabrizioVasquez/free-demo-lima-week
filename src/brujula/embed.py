from __future__ import annotations

from functools import lru_cache

import numpy as np

from .config import MODEL, MODEL_CACHE


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=MODEL, cache_dir=str(MODEL_CACHE))


def embed(texts: list[str]) -> np.ndarray:
    vecs = np.array(list(_model().embed(texts)), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-9, None)
