"""Graba un recorrido del sitio desplegado (1080p, MP4) para usarlo en la charla.

Usa Chrome + CDP screencast (frames JPEG de alta calidad) y ffmpeg para armar un MP4
de 30 fps. Inyecta un cursor visible para que la audiencia siga cada clic.

Uso: python docs/record_demo.py [URL] [salida.mp4]
Requiere: pip install playwright==1.58.0 ; Google Chrome ; ffmpeg
"""

import asyncio
import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://dqj62khtkxqf7.cloudfront.net/"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "demo-vigia-forestal.mp4").resolve()
W, H = 1920, 1080

CURSOR_JS = """
(() => {
  const c = document.createElement('div');
  c.id = '__cursor';
  c.innerHTML = `<svg width="34" height="34" viewBox="0 0 24 24"><path d="M4 2l16 9.5-7 1.5-3.5 6.5z"
     fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
  Object.assign(c.style, {position:'fixed', left:'960px', top:'1200px', zIndex: 99999,
    pointerEvents:'none', transition:'left .9s cubic-bezier(.4,0,.2,1), top .9s cubic-bezier(.4,0,.2,1)',
    filter:'drop-shadow(0 2px 6px rgba(0,0,0,.6))'});
  document.body.appendChild(c);
  const r = document.createElement('style');
  r.textContent = `.__ripple{position:fixed;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;
    border:3px solid #34d399;pointer-events:none;z-index:99998;animation:__rp .6s ease-out forwards}
    @keyframes __rp{from{transform:scale(.3);opacity:1}to{transform:scale(1.4);opacity:0}}`;
  document.head.appendChild(r);
  window.__moveCursor = (x, y) => { c.style.left = x + 'px'; c.style.top = y + 'px'; };
  window.__ripple = (x, y) => { const d = document.createElement('div'); d.className='__ripple';
    d.style.left = x + 'px'; d.style.top = y + 'px'; document.body.appendChild(d); setTimeout(() => d.remove(), 700); };
})();
"""


def encode(frames, frames_dir):
    # frames con duración variable -> MP4 30 fps
    concat = frames_dir / "list.txt"
    with concat.open("w") as f:
        for (t, path), nxt in zip(frames, frames[1:] + [(frames[-1][0] + 1 / 30, None)]):
            f.write(f"file '{path}'\nduration {max(1 / 60, nxt[0] - t):.4f}\n")
        f.write(f"file '{frames[-1][1]}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-vf", f"fps=30,scale={W}:{H}:flags=lanczos,format=yuv420p", "-c:v", "libx264",
                    "-preset", "slow", "-crf", "18", "-movflags", "+faststart", str(OUT)], check=True)
    span = frames[-1][0] - frames[0][0]
    print(f"OK {OUT} · {len(frames)} frames en {span:.1f}s (~{len(frames) / span:.0f} fps capturados)")
    shutil.rmtree(frames_dir)


async def main() -> None:
    frames_dir = Path(tempfile.mkdtemp(prefix="vigia-rec-"))
    frames: list[tuple[float, Path]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True, args=[
            "--ignore-gpu-blocklist", "--enable-gpu-rasterization", "--use-angle=metal",
            f"--window-size={W},{H}"])
        page = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_function("window.vigia && window.vigia.state.loss && window.vigia.state.fires")
        await page.evaluate(CURSOR_JS)
        await page.evaluate("void vigia.globe.pointOfView({lat: 4, lng: -62, altitude: 2.35})")
        await page.wait_for_timeout(2500)

        cdp = await page.context.new_cdp_session(page)

        recording = {"on": True}

        async def on_frame(ev):
            if not recording["on"]:
                return
            path = frames_dir / f"{len(frames):06d}.jpg"
            path.write_bytes(base64.b64decode(ev["data"]))
            frames.append((ev["metadata"]["timestamp"], path))
            await cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})

        cdp.on("Page.screencastFrame", lambda ev: asyncio.ensure_future(on_frame(ev)))
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92,
                                                "maxWidth": W, "maxHeight": H, "everyNthFrame": 1})

        async def click(selector: str, wait: int = 0, dy: int = 0):
            print(f"  · {selector} ({len(frames)} frames)", flush=True)
            box = await page.locator(selector).first.bounding_box(timeout=10000)
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 + dy
            await page.evaluate(f"__moveCursor({x}, {y})")
            await page.wait_for_timeout(1000)
            await page.evaluate(f"__ripple({x}, {y})")
            await page.mouse.click(x, y)
            await page.wait_for_timeout(wait)

        # 1. Globo girando con los datos reales
        await page.wait_for_timeout(3500)
        # 2. El avance de la deforestación 2001 -> 2024
        await click("#playBtn", wait=20500)
        # 3. Focos de calor de la última semana
        await click('#fireWindow button[data-days="7"]', wait=3500)
        await click('.tabs button[data-rank="fires"]', wait=2500)
        # 4. Una alerta del agente: el globo vuela a la zona
        await click("#feed li.alert >> nth=1", wait=3500)
        await click("#closeDetail", wait=800)
        # 5. País bajo demanda + análisis del agente con su huella
        await click('.tabs button[data-rank="loss"]', wait=1200)
        await click('#ranking button[data-iso="BRA"]', wait=2500)
        await click("#analyzeBtn", wait=0)
        await page.wait_for_function("!document.getElementById('analyzeBtn').disabled", timeout=30000)
        await page.evaluate("document.getElementById('agentOut').scrollIntoView({block: 'end'})")
        await page.wait_for_timeout(6500)
        # 6. Vista de día y cierre
        await click("#closeDetail", wait=600)
        await click("#dayTexture", wait=3500)
        await click("#dayTexture", wait=600)
        await page.evaluate("void vigia.globe.pointOfView({lat: 10, lng: -30, altitude: 2.6}, 2500)")
        print("  · cierre", flush=True)
        await page.evaluate("__moveCursor(960, 1200)")
        await page.wait_for_timeout(3500)

        recording["on"] = False
        print(f"  · fin ({len(frames)} frames)", flush=True)
        try:
            await asyncio.wait_for(cdp.send("Page.stopScreencast"), 5)
        except asyncio.TimeoutError:
            pass
        encode(frames, frames_dir)
        # Chrome headless a veces no responde al cerrar con el screencast activo
        try:
            await asyncio.wait_for(browser.close(), 10)
        except Exception:
            pass
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
