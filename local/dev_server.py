"""Servidor local que imita la arquitectura serverless en una sola terminal.

    EventBridge Scheduler  ->  una ingesta al arrancar (+ POST /admin/ingest)
    EventBridge (bus)      ->  events.subscribe_local  (DataUpdated -> agente)
    S3 + CloudFront        ->  .local-data/ servido como /data
    HTTP API + Lambda      ->  POST /analyze llama al MISMO handler de Lambda

Uso:  make local   (o)   python local/dev_server.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
os.environ.setdefault("VIGIA_MODE", "local")
os.environ.setdefault("VIGIA_LOCAL_DATA_DIR", str(ROOT / ".local-data"))

from aiohttp import web  # noqa: E402

from vigia import agent, config, events, ingest  # noqa: E402
from vigia.handlers import analyst as analyst_handler  # noqa: E402

FRONTEND = ROOT / "frontend"
log = logging.getLogger("dev_server")


def run_watch() -> None:
    r = agent.watch()
    log.info("agente: modo=%s señales=%s alertas=%s tokens=%s", r["mode"], r["signals"],
             len(r["alerts"]), r.get("usage", {}).get("total_tokens", 0))


def on_event(detail_type: str, _detail: dict) -> None:
    if detail_type == events.DATA_UPDATED:  # regla de EventBridge: DataUpdated -> agente
        run_watch()


# ------------------------------------------------------------------ rutas
async def index(_req):
    return web.FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-store"})


async def config_js(_req):
    cfg = {"apiUrl": "", "dataUrl": "/data", "mode": "local", "model": config.MODEL_ID}
    return web.Response(text=f"window.VIGIA_CONFIG = {json.dumps(cfg)};", content_type="application/javascript",
                        headers={"Cache-Control": "no-store"})


async def data_file(req):
    name = req.match_info["name"]
    for base in (config.LOCAL_DATA_DIR / "data", FRONTEND / "data"):
        path = (base / name).resolve()
        if path.is_file() and path.parent == base.resolve():
            return web.FileResponse(path, headers={"Cache-Control": "no-cache"})
    raise web.HTTPNotFound()


async def analyze(req):
    event = {"routeKey": "POST /analyze", "body": await req.text()}
    resp = await asyncio.to_thread(analyst_handler.handler, event, None)
    return web.Response(status=resp["statusCode"], body=resp["body"], headers=resp.get("headers", {}))


async def force_ingest(_req):
    return web.json_response(await asyncio.to_thread(ingest.run, True))


async def on_startup(app):
    events.subscribe_local(on_event)
    app["boot"] = asyncio.get_running_loop().run_in_executor(None, ingest.run)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("VIGIA_PORT", "8000")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/config.js", config_js)
    app.router.add_get("/data/{name}", data_file)
    app.router.add_post("/analyze", analyze)
    app.router.add_post("/admin/ingest", force_ingest)  # solo local: forzar una ingesta
    app.router.add_static("/", FRONTEND)
    app.on_startup.append(on_startup)
    print(f"\n  Vigía Forestal local -> http://localhost:{args.port}\n")
    web.run_app(app, host="127.0.0.1", port=args.port, print=None)


if __name__ == "__main__":
    main()
