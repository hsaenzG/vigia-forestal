"""Cálculos determinísticos sobre los datos. Son baratos (Python puro) y se usan
para dos cosas: (1) como herramientas del agente y (2) como 'compuerta' que
decide si vale la pena despertar al modelo."""

from __future__ import annotations

from collections import defaultdict

from . import config, geo, store

FIRES_KEY = "data/fires.json"
LOSS_KEY = "data/loss.json"


def load_fires() -> dict:
    return store.get_json(FIRES_KEY, {"dates": [], "cells": []})


def load_loss() -> dict:
    return store.get_json(LOSS_KEY, {"years": [], "world": [], "countries": {}})


# ------------------------------------------------------------------ fuegos
def fires_by_country(fires: dict) -> dict[str, list[int]]:
    """iso3 -> conteo por fecha (alineado con fires['dates'])."""
    out: dict[str, list[int]] = defaultdict(lambda: [0] * len(fires["dates"]))
    for _key, _lat, _lon, iso3, counts, _frp in fires["cells"]:
        if not iso3:
            continue
        row = out[iso3]
        for i, c in enumerate(counts):
            row[i] += c
    return dict(out)


def fire_signals(fires: dict, loss: dict | None = None) -> list[dict]:
    """Países con un repunte de focos de calor EN ZONAS CON BOSQUE.

    El último día del feed suele estar incompleto (UTC en curso), así que el día
    'reciente' es el penúltimo y la línea base es el promedio de los 3 anteriores.
    Si se pasa `loss`, se descartan países con poca pérdida forestal histórica
    (p. ej. quemas de pastizal en el Sahel): fuego sin bosque no es deforestación.
    """
    dates = fires["dates"]
    if len(dates) < 3:
        return []
    recent_i = len(dates) - 2
    base_idx = list(range(max(0, recent_i - 3), recent_i))
    years = loss["years"] if loss else []
    last10 = slice(max(0, len(years) - 10), len(years))
    signals = []
    for iso3, row in fires_by_country(fires).items():
        recent = row[recent_i]
        baseline = sum(row[i] for i in base_idx) / len(base_idx)
        ratio = recent / baseline if baseline else float("inf")
        if recent < config.MIN_FIRES_FOR_SIGNAL or ratio < config.MIN_SURGE_RATIO:
            continue
        avg_loss = None
        if loss:
            serie = loss["countries"].get(iso3, {}).get("loss", [])[last10]
            avg_loss = round(sum(serie) / len(serie)) if serie else 0
            if avg_loss < config.MIN_ANNUAL_LOSS_HA:
                continue
        signals.append(
            {
                "iso3": iso3,
                "pais": geo.country_name(iso3),
                "fecha": dates[recent_i],
                "focos_dia": recent,
                "promedio_previo": round(baseline, 1),
                "repunte": round(ratio, 2) if baseline else None,
                "focos_hoy_parcial": row[-1],
                "perdida_promedio_anual_ha_10a": avg_loss,
            }
        )
    signals.sort(key=lambda s: s["focos_dia"], reverse=True)
    return signals


def fire_ranking(fires: dict, days: int = 1, limit: int = 10) -> list[dict]:
    dates = fires["dates"]
    days = max(1, min(days, len(dates)))
    by_country = fires_by_country(fires)
    ranking = [
        {"iso3": iso3, "pais": geo.country_name(iso3), "focos": sum(row[-days:])}
        for iso3, row in by_country.items()
    ]
    ranking.sort(key=lambda r: r["focos"], reverse=True)
    return ranking[:limit]


def country_fire_trend(fires: dict, iso3: str) -> dict:
    """Serie diaria + hechos ya calculados: el modelo no debe hacer aritmética."""
    dates = fires["dates"]
    row = fires_by_country(fires).get(iso3.upper(), [0] * len(dates))
    complete = row[:-1] or row  # el último día UTC está en curso
    peak_i = max(range(len(complete)), key=lambda i: complete[i]) if complete else 0
    return {
        "iso3": iso3.upper(),
        "pais": geo.country_name(iso3.upper()),
        "pico": {"fecha": dates[peak_i] if dates else None, "focos": complete[peak_i] if complete else 0},
        "ultimo_dia_completo": {"fecha": dates[-2] if len(dates) > 1 else None,
                                "focos": row[-2] if len(row) > 1 else 0},
        "total_dias_completos": sum(complete),
        "promedio_diario": round(sum(complete) / len(complete)) if complete else 0,
        "focos_por_dia": dict(zip(dates, row)),
        "nota": f"El {dates[-1] if dates else ''} está incompleto (día UTC en curso); no se usa para pico ni promedio.",
    }


def hottest_cell(fires: dict, iso3: str) -> tuple[float, float] | None:
    best, pos = -1, None
    for _key, lat, lon, cell_iso, counts, _frp in fires["cells"]:
        if cell_iso == iso3 and sum(counts[-3:]) > best:
            best, pos = sum(counts[-3:]), (lat, lon)
    return pos


# ------------------------------------------------------------------ pérdida
def country_loss(loss: dict, iso3: str, from_year: int, to_year: int) -> dict:
    iso3 = iso3.upper()
    years = loss["years"]
    entry = loss["countries"].get(iso3)
    if not entry or not years:
        return {"iso3": iso3, "error": "Sin datos de pérdida de cobertura para este país."}
    from_year = max(from_year, years[0])
    to_year = min(to_year, years[-1])
    i0, i1 = years.index(from_year), years.index(to_year) + 1
    serie = entry["loss"][i0:i1]
    total = sum(serie)
    world_total = sum(loss["world"][i0:i1]) or 1
    peak_i = max(range(len(serie)), key=lambda i: serie[i]) if serie else 0
    k = max(1, min(5, len(serie) // 2))
    first, last = sum(serie[:k]) / k, sum(serie[-k:]) / k
    totals = sorted(
        ((sum(c["loss"][i0:i1]), code) for code, c in loss["countries"].items()), reverse=True
    )
    rank = next((i + 1 for i, (_, code) in enumerate(totals) if code == iso3), None)
    return {
        "iso3": iso3,
        "pais": entry["name"],
        "periodo": f"{from_year}-{to_year}",
        "perdida_total_ha": total,
        "porcentaje_del_mundo": round(100 * total / world_total, 2),
        "ranking_mundial": rank,
        "anio_pico": years[i0 + peak_i],
        "perdida_anio_pico_ha": serie[peak_i] if serie else 0,
        "tendencia": "al alza" if last > first * 1.1 else "a la baja" if last < first * 0.9 else "estable",
        "promedio_primeros_anios_ha": round(first),
        "promedio_ultimos_anios_ha": round(last),
        "serie_ha": dict(zip(years[i0:i1], serie)),
        "unidad": "hectáreas de cobertura arbórea perdida (incluye incendios, tala y agricultura)",
    }


def global_loss(loss: dict, from_year: int, to_year: int, limit: int = 10) -> dict:
    years = loss["years"]
    from_year, to_year = max(from_year, years[0]), min(to_year, years[-1])
    i0, i1 = years.index(from_year), years.index(to_year) + 1
    total = sum(loss["world"][i0:i1])
    top = sorted(
        ({"iso3": k, "pais": v["name"], "perdida_ha": sum(v["loss"][i0:i1])} for k, v in loss["countries"].items()),
        key=lambda r: r["perdida_ha"],
        reverse=True,
    )[:limit]
    return {"periodo": f"{from_year}-{to_year}", "perdida_mundial_ha": total, "top_paises": top}
