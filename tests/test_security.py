import pytest
from fastapi.testclient import TestClient

from brujula.security import MAX_BODY, RateLimiter, client_ip
from brujula.server import app

client = TestClient(app)
OK = {"prompt": "quiero aprender sobre agentes de IA"}


def test_rate_limiter_blocks_then_recovers():
    rl = RateLimiter(limit=3, window_s=10)
    assert [rl.allow("a", now=t) for t in (0, 1, 2)] == [True] * 3
    assert rl.allow("a", now=3) is False
    assert rl.allow("b", now=3) is True, "otra IP no se ve afectada"
    assert rl.allow("a", now=11) is True, "la ventana se desliza"


def test_rate_limiter_memory_is_bounded():
    rl = RateLimiter(limit=1, window_s=1, max_keys=100)
    for i in range(1000):
        rl.allow(f"ip{i}", now=i * 2)
    assert len(rl._hits) <= 101


def test_client_ip_ignores_spoofed_prefix():
    assert client_ip("6.6.6.6, 203.0.113.9", "10.0.0.1") == "203.0.113.9"
    assert client_ip(None, "10.0.0.1") == "10.0.0.1"
    assert client_ip("", None) == "unknown"


def test_security_headers_everywhere():
    r = client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "unsafe-eval" not in r.headers["content-security-policy"]
    assert "script-src 'self'" in r.headers["content-security-policy"]


def test_api_is_not_cached_and_docs_are_off():
    assert client.get("/api/status").headers["cache-control"] == "no-store"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


@pytest.mark.parametrize("bad", [
    {"prompt": "x"},                                   # muy corto
    {"prompt": "a" * 1501},                            # muy largo
    {**OK, "days": ["2026-10-12'; DROP TABLE x;--"]},  # inyección en días
    {**OK, "days": ["2027-01-01"]},                    # fuera de rango
    {**OK, "days": ["2026-10-12"] * 8},                # demasiados
    {**OK, "city": "Miraflores' OR '1'='1"},           # SQL en distrito
    {**OK, "city": "Atlantis"},                        # distrito inexistente
    {**OK, "mode": "hibrido"},                         # no está en la lista
    {**OK, "top_n": 99},                               # fuera de rango
    {**OK, "admin": True},                             # campo extra
])
def test_invalid_payloads_are_rejected(bad):
    assert client.post("/api/search", json=bad).status_code == 422


def test_oversized_body_is_rejected_early():
    r = client.post("/api/search", content=b"x" * (MAX_BODY + 1), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_wrong_method_and_path_traversal():
    assert client.get("/api/search").status_code == 405
    assert client.get("/static/../pyproject.toml").status_code == 404
    assert client.get("/static/%2e%2e/pyproject.toml").status_code in (400, 404)
