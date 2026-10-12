"""Defensas de la capa web: límite de tasa por IP, cabeceras de seguridad y extracción de la IP del cliente."""
from __future__ import annotations

import threading
import time
from collections import deque

# CSP estricta: solo scripts propios; sin eval, sin iframes, sin <base>, sin formularios externos.
# `style-src-attr 'unsafe-inline'` permite los style="" que usa la UI (barras de peso); un atributo style no ejecuta código.
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; style-src-attr 'unsafe-inline'; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'; object-src 'none'"
)
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
MAX_BODY = 8 * 1024  # un prompt de 1500 caracteres con filtros pesa ~2 KB


class RateLimiter:
    """Ventana deslizante en memoria. Es por instancia de Cloud Run: junto con --max-instances acota el gasto, no es un WAF."""

    def __init__(self, limit: int = 20, window_s: float = 60.0, max_keys: int = 10_000):
        self.limit, self.window, self.max_keys = limit, window_s, max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > self.max_keys:  # evita crecer sin límite si alguien rota IPs
                self._hits = {k: q for k, q in self._hits.items() if q and now - q[-1] < self.window}
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def client_ip(forwarded_for: str | None, peer: str | None) -> str:
    """En Cloud Run el front de Google AÑADE la IP real al final de X-Forwarded-For; lo que el cliente escriba va antes
    y es falsificable. Por eso se toma la entrada de más a la derecha, nunca la primera."""
    if forwarded_for:
        last = forwarded_for.split(",")[-1].strip()
        if last:
            return last[:64]
    return (peer or "unknown")[:64]
