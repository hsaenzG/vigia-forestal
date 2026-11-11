"""Bus de eventos. En AWS es EventBridge: desacopla la ingesta del agente
(el agente solo se despierta cuando llegan datos nuevos). En local es una lista
de suscriptores en memoria que registra el dev server."""

from __future__ import annotations

import json
import logging
from typing import Callable

from . import config

log = logging.getLogger(__name__)

DATA_UPDATED = "DataUpdated"

_local_subscribers: list[Callable[[str, dict], None]] = []


def subscribe_local(fn: Callable[[str, dict], None]) -> None:
    _local_subscribers.append(fn)


def publish(detail_type: str, detail: dict) -> None:
    if config.MODE == "local":
        for fn in _local_subscribers:
            try:
                fn(detail_type, detail)
            except Exception:  # un suscriptor roto no tumba a los demás
                log.exception("suscriptor local falló")
        return
    import boto3

    boto3.client("events", region_name=config.AWS_REGION).put_events(
        Entries=[
            {
                "Source": config.EVENT_SOURCE,
                "DetailType": detail_type,
                "Detail": json.dumps(detail, default=str),
                "EventBusName": config.EVENT_BUS_NAME,
            }
        ]
    )
