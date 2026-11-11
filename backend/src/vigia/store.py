"""Persistencia: archivos JSON que el frontend lee directamente.
- aws:   S3 (los sirve CloudFront)
- local: carpeta .local-data/ (la sirve el dev server)

No hay base de datos: los datos cambian una vez por semana, así que un archivo
estático en un CDN es lo más barato y eficiente para leerlos."""

from __future__ import annotations

import json
from typing import Any

from . import config


def _s3():
    import boto3  # incluido en el runtime de Lambda

    return boto3.client("s3", region_name=config.AWS_REGION)


def put_json(key: str, obj: Any, cache_seconds: int = 300) -> None:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    if config.MODE == "local":
        path = config.LOCAL_DATA_DIR / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return
    _s3().put_object(
        Bucket=config.DATA_BUCKET,
        Key=key,
        Body=body,
        ContentType="application/json; charset=utf-8",
        CacheControl=f"public, max-age={cache_seconds}",
    )


def get_json(key: str, default: Any = None) -> Any:
    if config.MODE == "local":
        path = config.LOCAL_DATA_DIR / key
        return json.loads(path.read_text()) if path.exists() else default
    s3 = _s3()
    try:
        obj = s3.get_object(Bucket=config.DATA_BUCKET, Key=key)
    except s3.exceptions.NoSuchKey:
        return default
    return json.loads(obj["Body"].read())
