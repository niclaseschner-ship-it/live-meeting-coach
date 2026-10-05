r"""Bildschirmfoto des laufenden Dashboards in voller Auflösung (Edge kopflos über das DevTools-Protokoll).

    .venv\Scripts\python scripts\dashboard_foto.py demo\dashboard_live.png [--breite 1600 --hoehe 900 --warten 3]

Der Coach muss laufen (http://127.0.0.1:8000). Das Foto zeigt den aktuellen Stand, also z. B. während eine
Aufnahme abgespielt wird. Die Seite schaltet den Lautsprecher nicht frei, es ist also nichts zu hören.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import websockets

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PORT = 9333


async def foto(ziel: Path, url: str, breite: int, hoehe: int, warten: float) -> None:
    profil = tempfile.mkdtemp(prefix="lmc-foto-")
    edge = subprocess.Popen([str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             f"--remote-debugging-port={PORT}", f"--user-data-dir={profil}",
                             f"--window-size={breite},{hoehe}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                ziele = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                seite = next(z for z in ziele if z["type"] == "page")
                break
            except Exception:  # noqa: BLE001 – Edge startet noch
                await asyncio.sleep(0.2)
        async with websockets.connect(seite["webSocketDebuggerUrl"], max_size=None) as ws:
            n = 0

            async def cdp(methode: str, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": methode, "params": params}))
                while True:
                    a = json.loads(await ws.recv())
                    if a.get("id") == n:
                        return a.get("result", {})

            await cdp("Emulation.setDeviceMetricsOverride", width=breite, height=hoehe, deviceScaleFactor=1, mobile=False)
            await cdp("Page.navigate", url=url)
            await asyncio.sleep(warten)  # WebSocket verbinden, ersten Zustand und Live-Bild laden
            bild = await cdp("Page.captureScreenshot", format="png")
        ziel.write_bytes(base64.b64decode(bild["data"]))
        print(f"{ziel}: {breite}×{hoehe}")
    finally:
        edge.terminate()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ziel", type=Path)
    ap.add_argument("--url", default="http://127.0.0.1:8000/")
    ap.add_argument("--breite", type=int, default=1600)
    ap.add_argument("--hoehe", type=int, default=900)
    ap.add_argument("--warten", type=float, default=3.0)
    a = ap.parse_args()
    asyncio.run(foto(a.ziel, a.url, a.breite, a.hoehe, a.warten))


if __name__ == "__main__":
    main()
