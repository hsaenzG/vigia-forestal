"""Agente vigía (Strands Agents SDK + Amazon Nova Lite en Bedrock).

Dos modos:
- watch(): se dispara con cada DataUpdated. Primero una compuerta determinística
  decide si hay señales; solo entonces se invoca el modelo, que decide qué
  señales merecen una alerta.
- analyze_country(): análisis bajo demanda desde el sitio web.
"""

from __future__ import annotations

import json
import logging
import re
import time

from . import analysis, config, geo, store

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres Vigía Forestal, un analista ambiental que vigila la deforestación
global con datos satelitales reales. Respondes SIEMPRE en español neutro, claro y breve.

Datos a tu disposición (vía herramientas):
- Focos de calor activos de NASA FIRMS (satélite VIIRS NOAA-20), por país y día. Un foco
  de calor no siempre es deforestación, pero en zonas tropicales los incendios son una de
  las principales herramientas de desmonte.
- Pérdida anual de cobertura arbórea 2001-2024 (Hansen/UMD/Global Forest Watch).

Reglas:
- Usa SOLO cifras que obtengas de las herramientas, copiándolas tal cual. Nunca inventes
  ni recalcules números: si una herramienta ya trae pico, total o promedio, usa ese valor.
- Cita el periodo y la fuente de cada cifra.
- Sé honesto con la incertidumbre: un repunte de fuego es una señal para revisar, no una prueba.
- No llames herramientas que no necesitas: cada llamada consume energía."""


def _model():
    from strands.models import BedrockModel

    return BedrockModel(model_id=config.MODEL_ID, region_name=config.AWS_REGION,
                        temperature=0.2, max_tokens=900)


def _text(result) -> str:
    """Texto final sin los bloques <thinking> que a veces emite Nova."""
    return re.sub(r"<thinking>.*?</thinking>", "", str(result), flags=re.S).strip()


def _usage(result) -> dict:
    u = getattr(result.metrics, "accumulated_usage", {}) or {}
    return {"input_tokens": u.get("inputTokens", 0), "output_tokens": u.get("outputTokens", 0),
            "total_tokens": u.get("totalTokens", 0), "model_calls": result.metrics.cycle_count}


# ---------------------------------------------------------------- herramientas
def _data_tools(fires: dict, loss: dict) -> list:
    from strands import tool

    @tool
    def ranking_focos_de_calor(dias: int = 1, limite: int = 10) -> str:
        """Países con más focos de calor activos (NASA FIRMS) en los últimos `dias` días."""
        return json.dumps(analysis.fire_ranking(fires, dias, limite), ensure_ascii=False)

    @tool
    def tendencia_focos_pais(iso3: str) -> str:
        """Focos de calor por día (últimos 7 días) de un país. `iso3` es el código ISO de 3 letras, p. ej. BRA."""
        return json.dumps(analysis.country_fire_trend(fires, iso3), ensure_ascii=False)

    @tool
    def perdida_cobertura_pais(iso3: str, desde: int = 2001, hasta: int = 2024) -> str:
        """Pérdida anual de cobertura arbórea (hectáreas) de un país entre dos años, con tendencia y ranking mundial."""
        return json.dumps(analysis.country_loss(loss, iso3, desde, hasta), ensure_ascii=False)

    @tool
    def perdida_cobertura_mundial(desde: int = 2001, hasta: int = 2024) -> str:
        """Pérdida mundial de cobertura arbórea y los 10 países con más pérdida en el periodo."""
        return json.dumps(analysis.global_loss(loss, desde, hasta), ensure_ascii=False)

    return [ranking_focos_de_calor, tendencia_focos_pais, perdida_cobertura_pais, perdida_cobertura_mundial]


# ---------------------------------------------------------------- modo vigía
ALERTS_KEY = "data/alerts.json"


def _alert(fires: dict, iso3: str, nivel: str, titulo: str, motivo: str, fuente: str, signal: dict | None) -> dict:
    pos = analysis.hottest_cell(fires, iso3) or geo.country_index().get(iso3, {}).get("centroid")
    return {
        "iso3": iso3, "pais": geo.country_name(iso3), "nivel": nivel, "titulo": titulo,
        "motivo": motivo, "fuente": fuente, "lat": pos[0] if pos else None,
        "lon": pos[1] if pos else None, "senal": signal or {},
    }


def watch() -> dict:
    """Revisa la semana de datos y guarda el reporte en data/alerts.json."""
    t0 = time.time()
    fires, loss = analysis.load_fires(), analysis.load_loss()
    signals = analysis.fire_signals(fires, loss)[: config.MAX_ALERTS_PER_RUN * 2]
    created: list[dict] = []
    summary, usage, mode = "", {}, "compuerta"

    if not signals:
        # Compuerta: sin señales, el modelo NO se invoca. Cero tokens.
        log.info("Sin señales: el modelo no se invoca.")
        summary = "Sin repuntes relevantes de focos de calor: el modelo no se invocó (0 tokens)."
    else:
        by_iso = {s["iso3"]: s for s in signals}
        from strands import Agent, tool

        @tool
        def emitir_alerta(iso3: str, nivel: str, razon: str) -> str:
            """Publica una alerta en el mapa para un país candidato. nivel: 'alta' | 'media'.
            razon: UNA frase corta y cualitativa de por qué importa, SIN cifras (las cifras
            las agrega el sistema directamente desde los datos)."""
            iso3 = iso3.upper()
            if iso3 not in by_iso:
                return "Rechazada: ese país no está en la lista de señales candidatas."
            if len(created) >= config.MAX_ALERTS_PER_RUN:
                return "Rechazada: ya se alcanzó el máximo de alertas por ciclo."
            s = by_iso[iso3]
            cl = analysis.country_loss(loss, iso3, 2015, 2024)
            cifras = (f"{s['focos_dia']:,} focos de calor el {s['fecha']} "
                      f"({s['repunte']}× el promedio previo de {s['promedio_previo']:,.0f}). "
                      f"Pérdida de cobertura arbórea 2015-2024: {cl.get('perdida_total_ha', 0):,} ha.")
            created.append(_alert(fires, iso3, nivel if nivel in ("alta", "media") else "media",
                                  f"Repunte de focos de calor en {s['pais']}",
                                  f"{cifras} {razon.strip()}", f"agente · {config.MODEL_ID}", s))
            return "Alerta publicada."

        prompt = (
            "La compuerta automática detectó estos repuntes de focos de calor (NASA FIRMS):\n"
            f"{json.dumps(signals, ensure_ascii=False)}\n\n"
            f"Decide cuáles merecen alerta (máximo {config.MAX_ALERTS_PER_RUN}). Prioriza países con "
            "historial alto de pérdida de cobertura arbórea: consulta `perdida_cobertura_pais` "
            "(2015-2024) solo para los candidatos que lo ameriten. Usa `emitir_alerta` para cada una "
            "y al final responde con una sola frase de resumen."
        )
        try:
            agent = Agent(model=_model(), system_prompt=SYSTEM_PROMPT, callback_handler=None,
                          tools=[*_data_tools(fires, loss), emitir_alerta])
            result = agent(prompt)
            summary, usage, mode = _text(result), _usage(result), "agente"
        except Exception as err:  # respaldo: reglas determinísticas
            log.exception("El modelo falló; uso reglas de respaldo")
            for s in signals[: config.MAX_ALERTS_PER_RUN - len(created)]:
                created.append(_alert(
                    fires, s["iso3"], "alta" if (s["repunte"] or 9) >= 2 else "media",
                    f"Repunte de focos de calor en {s['pais']}",
                    f"{s['focos_dia']} focos el {s['fecha']} vs. {s['promedio_previo']} de promedio previo.",
                    "reglas (respaldo sin modelo)", s))
            summary, mode = f"Respaldo sin modelo: {err.__class__.__name__}", "respaldo"

    report = {
        "generated_at": int(time.time()), "mode": mode, "model": config.MODEL_ID if mode == "agente" else None,
        "model_invoked": mode == "agente", "signals": len(signals), "alerts": created,
        "summary": summary, "usage": usage, "duration_ms": int((time.time() - t0) * 1000),
    }
    store.put_json(ALERTS_KEY, report, cache_seconds=3600)
    return report


# ---------------------------------------------------------------- bajo demanda
def analyze_country(iso3: str, from_year: int = 2001, to_year: int = 2024) -> dict:
    t0 = time.time()
    iso3 = iso3.upper()
    fires, loss = analysis.load_fires(), analysis.load_loss()
    prompt = (
        f"Analiza {geo.country_name(iso3)} (ISO3 {iso3}). Periodo de pérdida de cobertura: "
        f"{from_year}-{to_year}. Usa `perdida_cobertura_pais` y `tendencia_focos_pais`. "
        "Responde en máximo 120 palabras con: 1) cuánto perdió y cómo va la tendencia, "
        "2) qué dicen los focos de calor de esta semana, 3) un nivel de alerta (baja/media/alta) con su porqué."
    )
    try:
        from strands import Agent

        agent = Agent(model=_model(), system_prompt=SYSTEM_PROMPT, callback_handler=None,
                      tools=_data_tools(fires, loss))
        result = agent(prompt)
        return {"iso3": iso3, "mode": "agente", "model": config.MODEL_ID, "analysis": _text(result),
                "usage": _usage(result), "duration_ms": int((time.time() - t0) * 1000)}
    except Exception as err:
        log.exception("El modelo falló; respondo con datos crudos")
        cl = analysis.country_loss(loss, iso3, from_year, to_year)
        tr = analysis.country_fire_trend(fires, iso3)
        if "error" in cl:
            text = cl["error"]
        else:
            text = (f"{cl['pais']} perdió {cl['perdida_total_ha']:,} ha de cobertura arbórea en "
                    f"{cl['periodo']} ({cl['porcentaje_del_mundo']}% del total mundial, puesto "
                    f"#{cl['ranking_mundial']}). Año pico: {cl['anio_pico']}. Tendencia: {cl['tendencia']}. "
                    f"Focos de calor por día: {tr['focos_por_dia']}.")
        return {"iso3": iso3, "mode": "respaldo", "model": None, "analysis": text,
                "error": f"{err.__class__.__name__}: {err}"[:300], "usage": {},
                "duration_ms": int((time.time() - t0) * 1000)}
