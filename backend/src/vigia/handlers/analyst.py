"""Lambda del agente.
- EventBridge (DataUpdated) -> modo vigía.
- HTTP API  POST /analyze   -> análisis bajo demanda de un país."""

import json
import re

from vigia import agent

_ISO3 = re.compile(r"^[A-Za-z]{3}$")
_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


def _http(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": _HEADERS, "body": json.dumps(body, ensure_ascii=False)}


def handler(event, _context):
    if event.get("detail-type"):  # viene de EventBridge
        return agent.watch()

    try:
        body = json.loads(event.get("body") or "{}")
        iso3 = str(body.get("iso3", ""))
        from_year = int(body.get("from_year", 2001))
        to_year = int(body.get("to_year", 2024))
    except (ValueError, TypeError):
        return _http(400, {"error": "JSON inválido"})
    if not _ISO3.match(iso3) or not (2001 <= from_year <= to_year <= 2100):
        return _http(400, {"error": "Parámetros inválidos: iso3 (3 letras), from_year <= to_year"})
    return _http(200, agent.analyze_country(iso3, from_year, to_year))
