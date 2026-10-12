from __future__ import annotations

import argparse
import json

from .config import EVENTS_JSON, QDRANT_DIR


def _ensure(refresh: bool = False, browser: bool = False) -> None:
    from . import index, scrape

    if refresh or not EVENTS_JSON.exists():
        print("→ Descargando eventos de Luma…")
        print(f"  {len(scrape.run(browser=browser))} eventos guardados en {EVENTS_JSON}")
    if refresh or not QDRANT_DIR.exists():
        print("→ Generando vectores y base vectorial Qdrant (la primera vez baja el modelo, ~220 MB)…")
        print(f"  {index.build()} fragmentos indexados en {QDRANT_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="btw", description="Brújula Tech Week")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scrape", help="descarga los eventos de Luma")
    sc.add_argument("--browser", action="store_true", help="usa Crawl4AI con tu perfil de navegador (ver `btw login`)")
    sc.add_argument("--visible", action="store_true", help="con --browser, muestra la ventana")
    sub.add_parser("login", help="abre un navegador para iniciar sesión en Luma (se guarda en data/browser-profile)")
    sub.add_parser("index", help="reconstruye la base vectorial")
    rf = sub.add_parser("refresh", help="scrape + index")
    rf.add_argument("--browser", action="store_true")
    s = sub.add_parser("serve", help="levanta la app web")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    a = sub.add_parser("ask", help="consulta desde la terminal")
    a.add_argument("prompt")
    a.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "scrape":
        from . import scrape

        print(f"{len(scrape.run(browser=args.browser, headless=not args.visible))} eventos guardados en {EVENTS_JSON}")
    elif args.cmd == "login":
        from . import scrape

        scrape.login()
    elif args.cmd == "index":
        from . import index

        print(f"{index.build()} fragmentos indexados en {QDRANT_DIR}")
    elif args.cmd == "refresh":
        _ensure(refresh=True, browser=args.browser)
    elif args.cmd == "serve":
        import uvicorn

        _ensure()
        uvicorn.run("brujula.server:app", host=args.host, port=args.port)
    elif args.cmd == "ask":
        from .search import search

        _ensure()
        print(json.dumps(search(args.prompt, top_n=args.top), ensure_ascii=False, indent=1))
