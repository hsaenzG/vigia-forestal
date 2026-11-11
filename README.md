# 🌳 Vigía Forestal

Demo de la charla **"IA que no cuesta el planeta"** (ESCOM-IPN 2026): un globo 3D con la
deforestación global hecho con **datos satelitales reales**, un **agente Strands con Amazon Nova Lite**
y una arquitectura **100% serverless** que solo consume cuando hay trabajo.

![captura](docs/captura.png)

## Datos (reales, públicos, sin API key)

| Capa | Fuente | Frecuencia |
|---|---|---|
| Pérdida de cobertura arbórea por país, 2001–2024 | Hansen/UMD/Google/USGS/NASA vía Global Forest Watch, procesado por Our World in Data | anual |
| Focos de calor (últimos 7 días) | NASA FIRMS · VIIRS NOAA-20 | se ingiere semanalmente |
| Fronteras | Natural Earth 1:110m | — |

> Pérdida de cobertura arbórea ≠ solo deforestación: incluye incendios, tala y agricultura.
> Un foco de calor tampoco es prueba de deforestación; el agente lo trata como señal.

## Arquitectura

```
EventBridge Scheduler (cada 7 días)
   └─► Lambda Ingesta ── HEAD + ETag: si nada cambió, termina en ms
          ├─► S3  data/loss.json · data/fires.json
          └─► EventBridge "DataUpdated"
                 └─► Lambda Agente (Strands + Nova Lite)
                        ├─ compuerta: sin repuntes en países con bosque → 0 tokens
                        └─► S3  data/alerts.json (reporte semanal)

Navegador ◄── CloudFront ◄── S3 (sitio + data/*.json)
Navegador ──► HTTP API  POST /analyze ──► Lambda Agente (análisis bajo demanda)
```

Decisiones de "cómputo suficiente" que se pueden contar en la charla:

- **Sin servidores encendidos**: Lambda arm64 (Graviton), sin base de datos. Los datos son archivos JSON en un CDN.
- **No se procesa lo que no cambió**: HEAD + ETag antes de descargar 40 MB.
- **El modelo solo despierta si hay señal**: una compuerta en Python puro filtra repuntes de fuego en países con historial de pérdida forestal (≥ 20 000 ha/año). Fuego en pastizal no es deforestación.
- **Modelo correcto, no el más grande**: Nova Lite. El sitio muestra la huella de cada respuesta (tokens, llamadas al modelo, segundos).
- **El modelo decide, los datos ponen las cifras**: las herramientas entregan pico, promedio y totales ya calculados, y las alertas escriben las cifras desde los datos. Así se evitan números inventados.

Mediciones reales del despliegue: ingesta ~5–7 s con 134 MB de RAM; agente ~3–7 s con ~3–9 k tokens por ejecución.

## Uso

```bash
make setup                                   # venv local (Python 3.13, uv)
make local                                   # http://localhost:8000, el mismo código que las Lambdas
make deploy AWS_PROFILE=<tu-perfil>        # SAM + sitio + primera ingesta
make ingest                                  # fuerza una ingesta en la nube
make logs                                    # logs del agente
make destroy                                 # borra todo
```

Requisitos: `uv`, AWS SAM CLI y acceso a Amazon Nova en Bedrock. El modelo se cambia con el parámetro `ModelId`.

## Estructura

```
backend/src/vigia/   config · sources (FIRMS/OWID) · geo (punto→país) · ingest · analysis · agent · handlers/
backend/layer/       capa Strands (wheels Linux arm64, se compila con uv)
frontend/            index.html · app.js (globe.gl/three.js) · vendor/ (librería y texturas sin depender de un CDN)
local/dev_server.py  imita Scheduler, EventBridge, S3 y la API en una sola terminal
template.yaml        infraestructura SAM
```
