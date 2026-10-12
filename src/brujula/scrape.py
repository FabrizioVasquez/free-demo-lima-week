"""Descarga todos los eventos del calendario de Luma y guarda data/events.json.

Dos modos:
  * httpx (por defecto): rápido, sin navegador.
  * navegador (--browser): Crawl4AI con un perfil persistente propio (data/browser-profile).
    Con `btw login` inicias sesión en Luma una vez y la sesión se reutiliza.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from urllib.parse import urlencode

import httpx

from .config import CALENDAR_SLUG, DATA_DIR, EVENTS_JSON

UA = {"User-Agent": "Mozilla/5.0"}
API = "https://api.lu.ma/calendar/get-items"
MODE = {"offline": "presencial", "meet": "virtual", "zoom": "virtual"}
PROFILE_DIR = DATA_DIR / "browser-profile"
Fetch = Callable[[str], Awaitable[str]]


def _next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("No encontré __NEXT_DATA__ en la página de Luma")
    return json.loads(m.group(1))["props"]["pageProps"]["initialData"]["data"]


def _json_from(text: str) -> dict:
    try:
        return json.loads(text)
    except ValueError:  # el navegador envuelve el JSON en <pre>
        return json.loads(re.sub(r"<[^>]+>", "", text).strip())


def _text(node) -> str:
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return " ".join(_text(c) for c in node.get("content", []))
    return ""


def _lima(iso: str) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-5)))
    return t.strftime("%Y-%m-%d %H:%M")


def _normalize(entry: dict, description: str) -> dict:
    ev, ti = entry["event"], entry.get("ticket_info") or {}
    ra = entry.get("registration_availability")
    status = "agotado" if ti.get("is_sold_out") else "abierto"
    if entry.get("waitlist_active") or ra == "waitlist":
        status = "lista de espera"
    geo = ev.get("geo_address_info") or {}
    hosts = [h.get("name") for h in entry.get("hosts", []) if h.get("name") and h.get("name") != "Peru Tech Week"]
    return {
        "id": ev["url"],
        "name": ev["name"],
        "start": _lima(ev["start_at"]),
        "end": _lima(ev["end_at"]),
        "city": (geo.get("city_state") or "").replace(", Peru", ""),
        "mode": MODE.get(ev.get("location_type"), "por confirmar"),
        "hosts": hosts[:4],
        "guests": entry.get("guest_count") or 0,
        "status": status,
        "approval": bool(ti.get("require_approval")),
        "spots": ti.get("spots_remaining"),
        "description": description,
        "url": f"https://luma.com/{ev['url']}",
    }


async def _collect(fetch: Fetch, slug: str, pause: float) -> list[dict]:
    """Lógica común: lista paginada del calendario + descripción de cada evento."""
    data = _next_data(await fetch(f"https://luma.com/{slug}"))
    cal_id = data["calendar"]["api_id"]
    entries = list(data["upcoming"]["entries"])
    more, cursor = data["upcoming"]["has_more"], data["upcoming"]["next_cursor"]
    while more:
        qs = urlencode({"calendar_api_id": cal_id, "period": "future", "pagination_limit": 50, "pagination_cursor": cursor})
        j = _json_from(await fetch(f"{API}?{qs}"))
        entries += j["entries"]
        more, cursor = j.get("has_more"), j.get("next_cursor")
        await asyncio.sleep(pause)

    old = {e["id"]: e["description"] for e in json.loads(EVENTS_JSON.read_text("utf-8"))} if EVENTS_JSON.exists() else {}
    events = []
    for n, entry in enumerate(entries, 1):
        slug_ev = entry["event"]["url"]
        try:
            d = _next_data(await fetch(f"https://luma.com/{slug_ev}"))
            desc = re.sub(r"\s+", " ", _text(d.get("description_mirror") or {})).strip()
        except Exception as exc:  # conserva lo que ya teníamos si Luma falla
            print(f"  ! {slug_ev}: {exc}; conservo la descripción anterior")
            desc = old.get(slug_ev, "")
        events.append(_normalize(entry, desc or old.get(slug_ev, "")))
        if n % 20 == 0:
            print(f"  {n}/{len(entries)} eventos")
        await asyncio.sleep(pause)
    events.sort(key=lambda e: e["start"])
    return events


async def _scrape_httpx(slug: str) -> list[dict]:
    async with httpx.AsyncClient(headers=UA, follow_redirects=True, timeout=30) as client:

        async def fetch(url: str) -> str:
            """GET que respeta el 429 de Luma: espera y reintenta."""
            for attempt in range(8):
                r = await client.get(url)
                if r.status_code != 429:
                    return r.text
                wait = float(r.headers.get("retry-after", 0)) or 6 * (attempt + 1)
                print(f"  … Luma pidió esperar (429), reintento en {wait:.0f}s")
                await asyncio.sleep(wait)
            raise RuntimeError(f"Luma sigue respondiendo 429 en {url}; reintenta en unos minutos")

        return await _collect(fetch, slug, pause=0.4)


def _browser_config(headless: bool):
    from crawl4ai import BrowserConfig

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return BrowserConfig(headless=headless, use_persistent_context=True, user_data_dir=str(PROFILE_DIR), verbose=False)


async def _scrape_browser(slug: str, headless: bool) -> list[dict]:
    from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig

    run = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, wait_until="domcontentloaded", delay_before_return_html=1.0)
    async with AsyncWebCrawler(config=_browser_config(headless)) as crawler:

        async def fetch(url: str) -> str:
            for attempt in range(6):
                res = await crawler.arun(url=url, config=run)
                if res.success and res.status_code != 429:
                    return res.html
                await asyncio.sleep(6 * (attempt + 1))
            raise RuntimeError(f"No pude cargar {url} con el navegador")

        return await _collect(fetch, slug, pause=1.0)


async def _login() -> None:
    from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig

    async with AsyncWebCrawler(config=_browser_config(headless=False)) as crawler:
        await crawler.arun(url="https://luma.com/signin", config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS))
        print("Se abrió una ventana de navegador. Inicia sesión en Luma y vuelve aquí.")
        await asyncio.get_running_loop().run_in_executor(None, input, "Presiona Enter cuando hayas terminado… ")


def login() -> None:
    asyncio.run(_login())


def run(slug: str = CALENDAR_SLUG, browser: bool = False, headless: bool = True) -> list[dict]:
    events = asyncio.run(_scrape_browser(slug, headless) if browser else _scrape_httpx(slug))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_JSON.write_text(json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")
    return events
