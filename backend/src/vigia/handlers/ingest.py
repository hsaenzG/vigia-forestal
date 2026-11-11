"""Lambda: EventBridge Scheduler -> ingesta de datos reales."""

from vigia import ingest


def handler(event, _context):
    force = bool((event or {}).get("force"))
    return ingest.run(force=force)
