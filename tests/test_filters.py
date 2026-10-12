"""Prueba los filtros de Qdrant con datos sintéticos en memoria: no necesita el modelo ni el índice real."""
from qdrant_client import QdrantClient, models

from brujula.index import to_ts
from brujula.search import build_filter

NOW = "2026-10-13 12:00"


def make():
    c = QdrantClient(":memory:")
    c.create_collection("t", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
    ev = [  # id, estado, distrito, formato, inicio, fin
        (1, "abierto", "Miraflores", "presencial", "2026-10-12 09:00", "2026-10-12 11:00"),   # ya terminó
        (2, "abierto", "Miraflores", "presencial", "2026-10-13 18:00", "2026-10-13 20:00"),
        (3, "agotado", "Barranco", "presencial", "2026-10-14 18:00", "2026-10-14 20:00"),
        (4, "abierto", "Barranco", "virtual", "2026-10-14 10:00", "2026-10-14 11:00"),
        (5, "abierto", "Miraflores", "presencial", "2026-10-13 20:00", "2026-10-15 09:00"),    # cruza varios días
    ]
    c.upsert("t", points=[models.PointStruct(id=i, vector=[1.0, 0.1 * i], payload={
        "status": st, "city": ci, "mode": mo, "start_ts": to_ts(a), "end_ts": to_ts(b)}) for i, st, ci, mo, a, b in ev])
    return c


def ids(flt):
    return sorted(p.id for p in make().query_points("t", query=[1.0, 0.0], query_filter=flt, limit=50).points)


def test_no_filters_returns_all():
    assert build_filter(NOW, [], True, False, None, None) is None
    assert ids(None) == [1, 2, 3, 4, 5]


def test_hide_ended():
    assert ids(build_filter(NOW, [], True, True, None, None)) == [2, 3, 4, 5]


def test_day_overlap_includes_multi_day_events():
    assert ids(build_filter(NOW, ["2026-10-14"], True, True, None, None)) == [3, 4, 5]
    assert ids(build_filter(NOW, ["2026-10-13", "2026-10-15"], True, True, None, None)) == [2, 5]


def test_status_mode_city():
    assert ids(build_filter(NOW, [], False, True, None, None)) == [2, 4, 5]
    assert ids(build_filter(NOW, [], True, True, "virtual", None)) == [4]
    assert ids(build_filter(NOW, [], True, True, None, "Barranco")) == [3, 4]


def test_filter_values_are_data_not_query_text():
    # un valor "malicioso" solo puede ser un valor que no coincide con nada; no cambia la lógica del filtro
    assert ids(build_filter(NOW, [], True, True, None, "Miraflores' OR '1'='1")) == []


def test_to_ts_uses_lima_time():
    assert to_ts("2026-10-12 19:00") - to_ts("2026-10-12 18:00") == 3600
    assert to_ts("1970-01-01 00:00") == 5 * 3600  # Lima = UTC-5
