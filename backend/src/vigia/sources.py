"""Descarga y normaliza los datos reales.

- NASA FIRMS (VIIRS NOAA-20): detecciones de fuego activas, casi tiempo real.
- Hansen/UMD/GFW vía Our World in Data: pérdida anual de cobertura arbórea por país.

Solo usa la librería estándar (urllib + csv) para no inflar el paquete de Lambda.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import urllib.error
import urllib.request
from collections import defaultdict

from . import config, geo

log = logging.getLogger(__name__)
_UA = {"User-Agent": "vigia-forestal-demo/1.0 (+https://github.com/hsaenzG)"}


def _open(url: str, etag: str | None = None, last_modified: str | None = None):
    """Descarga solo si el archivo cambió. Devuelve (respuesta | None, etag, last_modified).

    FIRMS ignora If-None-Match (siempre responde 200), así que primero se hace un
    HEAD de pocos bytes y se compara el ETag/Last-Modified guardado."""
    if etag or last_modified:
        head = urllib.request.Request(url, headers=_UA, method="HEAD")
        with urllib.request.urlopen(head, timeout=30) as h:
            new_etag, new_lm = h.headers.get("ETag"), h.headers.get("Last-Modified")
        if (etag and new_etag == etag) or (not new_etag and last_modified and new_lm == last_modified):
            return None, etag, last_modified
    headers = dict(_UA)
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as err:
        if err.code == 304:
            return None, etag, last_modified
        raise
    return resp, resp.headers.get("ETag"), resp.headers.get("Last-Modified")


# ----------------------------------------------------------------- FIRMS
def fetch_fires(url: str, etag: str | None = None, last_modified: str | None = None):
    """Descarga un feed FIRMS y lo agrega en celdas de GRID_DEG grados.

    Devuelve (cells | None si no cambió, etag, last_modified, n_detecciones).
    cells = {"lat_lon": {"lat", "lon", "d": {fecha: conteo}, "frp": float}}
    """
    resp, etag, last_modified = _open(url, etag, last_modified)
    if resp is None:
        return None, etag, last_modified, 0

    g = config.GRID_DEG
    cells: dict[str, dict] = {}
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    n = 0
    with resp:
        reader = csv.DictReader(io.TextIOWrapper(resp, encoding="utf-8"))
        for row in reader:
            # VIIRS: low | nominal | high. Descartamos "low" (ruido, reflejos).
            if row.get("confidence") == "low":
                continue
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
                frp = float(row.get("frp") or 0)
            except (KeyError, ValueError):
                continue
            key = f"{math.floor(lat / g)}_{math.floor(lon / g)}"
            cell = cells.get(key)
            if cell is None:
                cell = cells[key] = {"d": defaultdict(int), "frp": 0.0}
            date = row["acq_date"]
            cell["d"][date] += 1
            cell["frp"] += frp
            s = sums[key]
            s[0] += lat
            s[1] += lon
            s[2] += 1
            n += 1

    for key, cell in cells.items():
        s = sums[key]
        cell["lat"] = round(s[0] / s[2], 3)  # posición = centro de masa de las detecciones
        cell["lon"] = round(s[1] / s[2], 3)
        cell["d"] = dict(cell["d"])
        cell["frp"] = round(cell["frp"], 1)
    log.info("FIRMS: %s detecciones -> %s celdas", n, len(cells))
    return cells, etag, last_modified, n


def merge_fire_cells(old: dict, new: dict, keep_dates: list[str]) -> dict:
    """Combina celdas. Para cada (celda, fecha) se queda con el máximo: el feed de
    24 h es una ventana deslizante, así que un día que 'sale' de la ventana trae
    conteos parciales que no deben pisar a los completos."""
    keep = set(keep_dates)
    merged: dict[str, dict] = {}
    for key in set(old) | set(new):
        o, n = old.get(key), new.get(key)
        base = dict(n or o)
        days = {}
        for src in (o, n):
            if not src:
                continue
            for date, cnt in src["d"].items():
                if date in keep:
                    days[date] = max(days.get(date, 0), cnt)
        if not days:
            continue
        base["d"] = days
        base["frp"] = max((o or {}).get("frp", 0), (n or {}).get("frp", 0))
        if o and "iso3" in o:  # país ya calculado en una corrida anterior
            base["iso3"] = o["iso3"]
        if o:  # posición estable: no se mueve la celda en cada corrida
            base["lat"], base["lon"] = o["lat"], o["lon"]
        merged[key] = base
    return merged


def assign_countries(cells: dict) -> int:
    """Asigna ISO3 solo a celdas nuevas (las conocidas ya lo traen)."""
    done = 0
    for cell in cells.values():
        if "iso3" not in cell:
            cell["iso3"] = geo.locate(cell["lat"], cell["lon"])
            done += 1
    return done


# ----------------------------------------------------------------- OWID / GFW
def fetch_tree_cover_loss() -> dict:
    """{"years": [...], "world": [...], "countries": {iso3: {"name", "loss": [...]}}}"""
    resp, *_ = _open(config.OWID_LOSS_CSV)
    with resp:
        rows = list(csv.DictReader(io.TextIOWrapper(resp, encoding="utf-8")))
    value_col = next(c for c in rows[0] if c not in ("entity", "code", "year"))
    years = sorted({int(r["year"]) for r in rows})
    idx = {y: i for i, y in enumerate(years)}
    countries: dict[str, dict] = {}
    world = [0.0] * len(years)
    for r in rows:
        code, val = r["code"], r[value_col]
        if not val:
            continue
        v = round(float(val))
        if code == "OWID_WRL":
            world[idx[int(r["year"])]] = v
            continue
        if not code or code.startswith("OWID_"):
            if code != "OWID_KOS":  # agregados regionales: fuera
                continue
            code = "KOS"
        entry = countries.setdefault(code, {"name": r["entity"], "loss": [0] * len(years)})
        entry["loss"][idx[int(r["year"])]] = v
    return {
        "years": years,
        "world": world,
        "countries": countries,
        "unit": "ha",
        "source": "Hansen/UMD/Google/USGS/NASA vía Global Forest Watch · procesado por Our World in Data",
    }
