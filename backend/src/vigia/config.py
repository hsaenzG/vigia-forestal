"""Configuración central. Todo sale de variables de entorno para que el mismo
código corra en Lambda (MODE=aws) y en la laptop (MODE=local)."""

import os
from pathlib import Path

MODE = os.environ.get("VIGIA_MODE", "aws")  # "aws" | "local"

# --- AWS ---
DATA_BUCKET = os.environ.get("DATA_BUCKET", "")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "default")
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

# --- Local ---
LOCAL_DATA_DIR = Path(os.environ.get("VIGIA_LOCAL_DATA_DIR", Path.cwd() / ".local-data"))

# --- Modelo: el correcto, no el más grande ---
MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-lite-v1:0")

# --- Fuentes de datos reales (públicas, sin API key) ---
# NASA FIRMS — VIIRS a bordo de NOAA-20. Se toma el archivo de los últimos 7 días:
# con una ingesta semanal basta para tener la semana completa.
FIRMS_FEED_7D = (
    "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_7d.csv"
)
# Hansen/UMD/GFW — pérdida anual de cobertura arbórea por país, vía Our World in Data.
OWID_LOSS_CSV = (
    "https://ourworldindata.org/grapher/tree-cover-loss.csv"
    "?v=1&csvType=full&useColumnShortNames=true"
)

# Tamaño de celda (grados) para agregar detecciones de fuego.
GRID_DEG = float(os.environ.get("GRID_DEG", "0.5"))
# Días de historia de fuegos que se conservan.
FIRE_HISTORY_DAYS = int(os.environ.get("FIRE_HISTORY_DAYS", "7"))

# --- "Cómputo suficiente": umbrales para decidir si vale la pena llamar al modelo ---
MIN_FIRES_FOR_SIGNAL = int(os.environ.get("MIN_FIRES_FOR_SIGNAL", "150"))
MIN_SURGE_RATIO = float(os.environ.get("MIN_SURGE_RATIO", "1.3"))
# Pérdida forestal promedio anual (últimos 10 años) mínima para considerar un país.
MIN_ANNUAL_LOSS_HA = int(os.environ.get("MIN_ANNUAL_LOSS_HA", "20000"))
MAX_ALERTS_PER_RUN = int(os.environ.get("MAX_ALERTS_PER_RUN", "3"))

EVENT_SOURCE = "vigia.forestal"
