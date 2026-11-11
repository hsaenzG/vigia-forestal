"""Asignación punto -> país en Python puro (sin shapely, para que la Lambda sea
liviana). Usa Natural Earth 1:110m con prefiltro por bounding box."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_GEOJSON = Path(__file__).parent / "data" / "countries.geojson"


def _ring_contains(ring: list[list[float]], x: float, y: float) -> bool:
    """Ray casting clásico sobre un anillo [[lon, lat], ...]."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _polygon_contains(poly: list[list[list[float]]], x: float, y: float) -> bool:
    if not _ring_contains(poly[0], x, y):
        return False
    return not any(_ring_contains(hole, x, y) for hole in poly[1:])


@lru_cache(maxsize=1)
def countries() -> list[dict]:
    """Lista de {iso3, name, bbox, polygons, centroid}."""
    data = json.loads(_GEOJSON.read_text())
    out = []
    for feat in data["features"]:
        props, geom = feat["properties"], feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        xs = [p[0] for poly in polys for p in poly[0]]
        ys = [p[1] for poly in polys for p in poly[0]]
        # centroide aproximado del polígono más grande (para volar la cámara)
        biggest = max(polys, key=lambda pl: len(pl[0]))[0]
        cx = sum(p[0] for p in biggest) / len(biggest)
        cy = sum(p[1] for p in biggest) / len(biggest)
        out.append(
            {
                "iso3": props["ADM0_A3"],
                "name": props.get("NAME_ES") or props["NAME"],
                "bbox": (min(xs), min(ys), max(xs), max(ys)),
                "polygons": polys,
                "centroid": (round(cy, 2), round(cx, 2)),
            }
        )
    return out


@lru_cache(maxsize=1)
def country_index() -> dict[str, dict]:
    return {c["iso3"]: c for c in countries()}


def locate(lat: float, lon: float) -> str | None:
    """ISO3 del país que contiene el punto, o None (océano / costa no cubierta)."""
    for c in countries():
        x0, y0, x1, y1 = c["bbox"]
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            if any(_polygon_contains(p, lon, lat) for p in c["polygons"]):
                return c["iso3"]
    return None


def country_name(iso3: str | None) -> str:
    if not iso3:
        return "Sin país asignado"
    c = country_index().get(iso3)
    return c["name"] if c else iso3
