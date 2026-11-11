"""Ingesta: trae datos reales, los compacta y avisa por el bus SOLO si cambiaron.

Principio de 'cómputo suficiente': corre una vez por semana y, antes de descargar,
un HEAD compara el ETag del archivo; si no cambió, termina en milisegundos.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from . import analysis, config, events, sources, store

log = logging.getLogger(__name__)
STATE_KEY = "state/ingest.json"


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _refresh_loss(state: dict, force: bool) -> bool:
    """La pérdida anual cambia una vez al año: se revisa como máximo una vez al día."""
    if not force and state.get("loss_checked_on") == _today() and store.get_json(analysis.LOSS_KEY):
        return False
    loss = sources.fetch_tree_cover_loss()
    store.put_json(analysis.LOSS_KEY, loss, cache_seconds=86400)
    state["loss_checked_on"] = _today()
    log.info("Pérdida de cobertura: %s países, %s-%s", len(loss["countries"]), loss["years"][0], loss["years"][-1])
    return True


def _refresh_fires(state: dict, force: bool) -> dict | None:
    current = store.get_json(analysis.FIRES_KEY)
    bootstrap = current is None or not current.get("cells")
    url = config.FIRMS_FEED_7D
    etag = None if (bootstrap or force) else state.get("firms_etag")
    last_mod = None if (bootstrap or force) else state.get("firms_last_modified")

    new_cells, etag, last_mod, n = sources.fetch_fires(url, etag, last_mod)
    if new_cells is None:
        log.info("FIRMS sin cambios (mismo ETag). No se descarga ni procesa nada.")
        return None
    state["firms_etag"], state["firms_last_modified"] = etag, last_mod

    old_cells = {}
    if current:
        for key, lat, lon, iso3, counts, frp in current["cells"]:
            old_cells[key] = {"lat": lat, "lon": lon, "iso3": iso3, "frp": frp,
                              "d": {d: c for d, c in zip(current["dates"], counts) if c}}

    all_dates = sorted({d for c in list(old_cells.values()) + list(new_cells.values()) for d in c["d"]})
    keep_dates = all_dates[-config.FIRE_HISTORY_DAYS:]
    merged = sources.merge_fire_cells(old_cells, new_cells, keep_dates)
    located = sources.assign_countries(merged)

    cells = [
        [k, c["lat"], c["lon"], c.get("iso3"), [c["d"].get(d, 0) for d in keep_dates], c["frp"]]
        for k, c in merged.items()
    ]
    total = sum(sum(c[4]) for c in cells)
    previous_total = sum(sum(c[4]) for c in current["cells"]) if current else 0
    if current and current["dates"] == keep_dates and sorted(cells) == sorted(current["cells"]):
        log.info("Feed nuevo pero sin detecciones nuevas: no se publica nada.")
        return None
    fires = {
        "updated_at": int(time.time()),
        "source_updated": last_mod,
        "dates": keep_dates,
        "cells": cells,
        "total": total,
        "source": "NASA FIRMS · VIIRS NOAA-20 · últimos 7 días · confianza nominal/alta",
        "grid_deg": config.GRID_DEG,
    }
    store.put_json(analysis.FIRES_KEY, fires, cache_seconds=3600)
    log.info("Fuegos: %s celdas (%s nuevas localizadas), %s detecciones", len(cells), located, total)
    return {"total": total, "new_detections": max(0, total - previous_total), "feed_rows": n,
            "cells": len(cells), "dates": keep_dates, "bootstrap": bootstrap}


def run(force: bool = False) -> dict:
    t0 = time.time()
    state = store.get_json(STATE_KEY, {})
    loss_changed = _refresh_loss(state, force)
    fire_info = _refresh_fires(state, force)
    store.put_json(STATE_KEY, state)

    changed = loss_changed or fire_info is not None
    result = {
        "changed": changed,
        "loss_refreshed": loss_changed,
        "fires": fire_info,
        "updated_at": int(time.time()),
        "duration_ms": int((time.time() - t0) * 1000),
    }
    if changed:
        events.publish(events.DATA_UPDATED, result)
    log.info("Ingesta terminada: %s", result)
    return result
