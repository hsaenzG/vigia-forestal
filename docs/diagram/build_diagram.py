"""Genera el diagrama de arquitectura REAL de Vigía Forestal con los iconos oficiales
de AWS (incrustados como data URI, el SVG funciona en cualquier lado).

Uso: python docs/diagram/build_diagram.py <carpeta-Asset-Package-AWS>
Salida: docs/arquitectura.svg y docs/arquitectura.png (requiere rsvg-convert)
"""

import base64
import subprocess
import sys
from pathlib import Path

PKG = Path(sys.argv[1])
OUT = Path(__file__).resolve().parents[1]
ARCH = PKG / "Architecture-Service-Icons_07312025"
RES = PKG / "Resource-Icons_07312025"

ICONS = {
    "amplify": ARCH / "Arch_Front-End-Web-Mobile/64/Arch_AWS-Amplify_64.svg",
    "cloudfront": ARCH / "Arch_Networking-Content-Delivery/64/Arch_Amazon-CloudFront_64.svg",
    "apigw": ARCH / "Arch_Networking-Content-Delivery/64/Arch_Amazon-API-Gateway_64.svg",
    "eventbridge": ARCH / "Arch_App-Integration/64/Arch_Amazon-EventBridge_64.svg",
    "lambda": ARCH / "Arch_Compute/64/Arch_AWS-Lambda_64.svg",
    "s3": ARCH / "Arch_Storage/64/Arch_Amazon-Simple-Storage-Service_64.svg",
    "bedrock": ARCH / "Arch_Artificial-Intelligence/64/Arch_Amazon-Bedrock_64.svg",
    "scheduler": RES / "Res_Application-Integration/Res_Amazon-EventBridge_Scheduler_48.svg",
    "users": RES / "Res_General-Icons/Res_48_Light/Res_Users_48_Light.svg",
    "internet": RES / "Res_General-Icons/Res_48_Light/Res_Internet_48_Light.svg",
    "code": RES / "Res_General-Icons/Res_48_Light/Res_Source-Code_48_Light.svg",
    "cloud": PKG / "Architecture-Group-Icons_07312025/AWS-Cloud-logo_32.svg",
}

INK, GRAY, GREEN, RED = "#232F3E", "#5F6B7A", "#037F0C", "#D91515"
W, H, S = 1700, 1240, 72  # lienzo y tamaño de icono
FONT = "font-family='Arial, Helvetica, sans-serif'"


def uri(path: Path) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()


parts: list[str] = []


def icon(key, cx, cy, title, sub=None, size=S):
    parts.append(f"<image href='{uri(ICONS[key])}' x='{cx - size / 2}' y='{cy - size / 2}' width='{size}' height='{size}'/>")
    parts.append(f"<text x='{cx}' y='{cy + size / 2 + 22}' {FONT} font-size='17' font-weight='bold' fill='{INK}' text-anchor='middle'>{title}</text>")
    if sub:
        parts.append(f"<text x='{cx}' y='{cy + size / 2 + 42}' {FONT} font-size='14' fill='{GRAY}' text-anchor='middle'>{sub}</text>")


def line(points, color=INK, both=False, dash=False, label=None, lx=None, ly=None):
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    extra = " stroke-dasharray='7 5'" if dash else ""
    start = " marker-start='url(#a-start)'" if both else ""
    mk = "a-end-red" if color == RED else "a-end-green" if color == GREEN else "a-end"
    parts.append(f"<path d='{d}' fill='none' stroke='{color}' stroke-width='2.2'{extra}{start} marker-end='url(#{mk})'/>")
    if label:
        parts.append(f"<text x='{lx}' y='{ly}' {FONT} font-size='13' fill='{GRAY}' text-anchor='middle' "
                     f"font-style='italic'>{label}</text>")


# columnas / filas
C1, C2, C3, C4, C5 = 450, 730, 1010, 1270, 1500
R1, R2, R3 = 280, 500, 720
h = S / 2 + 6

# contenedor AWS Cloud
parts.append(f"<rect x='310' y='150' width='1340' height='770' fill='none' stroke='{INK}' stroke-width='1.5'/>")
parts.append(f"<image href='{uri(ICONS['cloud'])}' x='310' y='150' width='40' height='40'/>")
parts.append(f"<text x='358' y='176' {FONT} font-size='15' fill='{INK}'>AWS Cloud · us-east-2</text>")

# externos
icon("internet", C2, 62, "NASA FIRMS · Global Forest Watch", "datos satelitales abiertos", size=52)
icon("users", 140, 610, "Personas", "navegador / celular", size=60)

# servicios
icon("scheduler", C1, R1, "EventBridge Scheduler", "cada semana")
icon("lambda", C2, R1, "AWS Lambda", "Ingesta (Python)")
icon("eventbridge", C3, R1, "Amazon EventBridge", "evento DataUpdated")
icon("lambda", C4, R1, "AWS Lambda", "Agente Strands")
icon("bedrock", C5, R1, "Amazon Bedrock", "Amazon Nova Lite")
icon("s3", C2, R2, "Amazon S3", "SOLO datos: loss · fires · alerts .json")
icon("cloudfront", C1, R2, "Amazon CloudFront", "CDN de los datos .json")
icon("amplify", C1, R3, "AWS Amplify Hosting", "aloja el sitio (HTML · JS · globo 3D)")
icon("code", C1, 1050, "Archivos del sitio", "make site → deploy directo a Amplify", size=56)
icon("apigw", C4, R3, "Amazon API Gateway", "POST /analyze")

# flujo semanal
line([(C2, 62 + 26 + 46), (C2, R1 - h)], label="HEAD + ETag: si no cambió, termina", lx=C2 + 150, ly=R1 - h - 18)
line([(C1 + h, R1), (C2 - h, R1)])
line([(C2, R1 + h + 46), (C2, R2 - h)], label="escribe datos", lx=C2 + 62, ly=R2 - h - 14)
line([(C2 + h, R1), (C3 - h, R1)])
line([(C3 + h, R1), (C4 - h, R1)], label="despierta al agente", lx=(C3 + C4) / 2, ly=R1 - 18)
line([(C4 + h, R1), (C5 - h, R1)], color=GREEN, both=True, label="solo si hay señal", lx=(C4 + C5) / 2, ly=R1 - 18)
line([(C4 - 20, R1 + h + 48), (C2 + h + 4, R2 - 10)], label="alerts.json", lx=1000, ly=R2 - 40)
line([(C2 - h, R2), (C1 + h, R2)])

# lectura desde el navegador
line([(140 + 34, 625), (C1 - h, R3 - 6)], label="abre el sitio", lx=392, ly=676)
line([(C1, R3 - h), (C1, R2 + h + 50)], label="proxy solo de /datos/*.json", lx=C1 + 112, ly=(R2 + R3) / 2 + 30)
line([(C1, 1050 - 34), (C1, R3 + h + 50)], color=GREEN, label="despliegue del sitio", lx=C1 + 95, ly=960)
line([(140, 610 + 30 + 48), (140, 1170), (C4, 1170), (C4, R3 + h + 50)], label="pide un análisis", lx=820, ly=1160)
line([(C4, R3 - h), (C4, R1 + h + 50)], color=GREEN)

# leyenda
parts.append(f"<text x='{(310 + 1650) / 2}' y='1222' {FONT} font-size='18' font-weight='bold' fill='{GREEN}' "
             f"text-anchor='middle'>Nada encendido esperando: todo escala a cero</text>")

defs = "".join(
    f"<marker id='{mid}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
    f"<path d='M0 0 L10 5 L0 10 z' fill='{col}'/></marker>"
    for mid, col in (("a-end", INK), ("a-end-green", GREEN), ("a-end-red", RED), ("a-start", GREEN)))
svg = (f"<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' width='{W}' height='{H}' "
       f"viewBox='0 0 {W} {H}'><title>Arquitectura de Vigía Forestal</title><defs>{defs}</defs>"
       f"<rect width='100%' height='100%' fill='#FFFFFF'/>{''.join(parts)}</svg>")
(OUT / "arquitectura.svg").write_text(svg)
subprocess.run(["rsvg-convert", "-w", str(W * 2), str(OUT / "arquitectura.svg"), "-o", str(OUT / "arquitectura.png")], check=True)
print("OK", OUT / "arquitectura.svg", OUT / "arquitectura.png")
