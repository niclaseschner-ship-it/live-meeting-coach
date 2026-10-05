"""HTTP/WebSocket-Schnittstelle für Dashboard und Mikrofon."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import regeln
from .config import EINST, WURZEL, schluessel_info, schluessel_speichern
from .pipeline import Coach, hintergrund
from .transkription import als_data_url, wav_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC = WURZEL / "static"
SZENARIEN = WURZEL / "szenarien"
AUFNAHMEN = Path(EINST.aufnahmen)

coach = Coach()
verbindungen: set[WebSocket] = set()


async def _an_alle(text: str) -> None:
    """An alle Dashboards gleichzeitig; wer nicht binnen 2 s abnimmt (z. B. ein vergessener Hintergrund-Tab),
    fliegt raus – sonst blockiert sein voller Puffer die Pipeline (Abspieltest 05.10. mit Sprachausgabe)."""
    async def eins(ws: WebSocket) -> None:
        try:
            await asyncio.wait_for(ws.send_text(text), 2.0)
        except Exception:  # noqa: BLE001
            verbindungen.discard(ws)
            with contextlib.suppress(Exception):
                await ws.close()

    await asyncio.gather(*(eins(ws) for ws in list(verbindungen)))


async def senden() -> None:
    if verbindungen:
        await _an_alle(json.dumps(coach.schnappschuss(), ensure_ascii=False))


coach.beobachter.append(senden)


lautsprecher: WebSocket | None = None  # der Tab, der das Meeting gestartet hat – nur er spielt Nestor ab


async def senden_direkt(nachricht: dict) -> None:
    """Sprachausgabe nur an den Lautsprecher-Tab – mehrere offene Dashboards sprachen sonst doppelt (Test 05.10.)."""
    if lautsprecher in verbindungen:
        try:
            await asyncio.wait_for(lautsprecher.send_text(json.dumps(nachricht, ensure_ascii=False)), 2.0)
        except Exception:  # noqa: BLE001
            verbindungen.discard(lautsprecher)


coach.direkt.append(senden_direkt)


async def taktgeber() -> None:
    """Echte Meetings: jede Sekunde Ampel prüfen und Uhr aktualisieren."""
    while True:
        await asyncio.sleep(1)
        if coach.meeting.laeuft:
            if not coach.simulation_laeuft:  # im Abspielmodus taktet die Wiedergabe selbst
                coach.takt()
            await senden()  # Uhr und Assistent auch in stillen Phasen aktuell halten


@asynccontextmanager
async def lebenszyklus(app: FastAPI):
    task = asyncio.create_task(taktgeber())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Live Meeting Coach", lifespan=lebenszyklus)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def startseite():
    return FileResponse(STATIC / "index.html")


@app.get("/api/zustand")
async def zustand():
    return coach.schnappschuss()


@app.post("/api/assistent/fragen")
async def assistent_fragen():
    """Knopf statt Namen: die nächste Äußerung gilt als Frage an den Assistenten."""
    coach.assistent.knopf()
    await coach.melden()
    return {"ok": True}


@app.post("/api/assistent/stopp")
async def assistent_stopp():
    coach.assistent.stoppen()
    await coach.direkt_senden({"typ": "stimme_stopp"})
    await coach.melden()
    return {"ok": True}


@app.post("/api/assistent/fortsetzen")
async def assistent_fortsetzen():
    """Nach einem Nein oder einer Pause wieder zuhören – nur per Knopf, weil der Coach dann nichts hört."""
    coach.assistent.fortsetzen()
    await coach.melden()
    return {"ok": True}


@app.post("/api/stumm")
async def stumm(daten: dict):
    await coach.stumm_schalten(bool(daten.get("an")))
    return {"ok": True}


@app.post("/api/einstellungen")
async def einstellungen(daten: dict):
    try:
        coach.einstellen(daten)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "Ungültiger Wert") from e
    await coach.melden()
    return coach.einstellungen()


@app.post("/api/schluessel")
async def schluessel(daten: dict, request: Request):
    """Eigenen OpenAI-Schlüssel eintragen (leer = entfernen). Nur vom eigenen Rechner aus; der Schlüssel wird
    vorher mit einem kostenlosen Aufruf geprüft und nie zurückgegeben oder protokolliert."""
    if request.client is None or request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "Den Schlüssel nur am Rechner eintragen, auf dem der Coach läuft.")
    if coach.hoerstrom is not None:
        raise HTTPException(409, "Erst das Meeting beenden, dann den Schlüssel wechseln.")
    neu = str(daten.get("schluessel") or "").strip()
    if neu:
        if not neu.startswith("sk-") or len(neu) < 20 or any(z.isspace() for z in neu):
            raise HTTPException(400, "Das sieht nicht wie ein OpenAI-API-Schlüssel aus (beginnt mit „sk-“).")
        from openai import AsyncOpenAI, AuthenticationError, PermissionDeniedError

        try:
            await AsyncOpenAI(api_key=neu, max_retries=0, timeout=15).models.list()
        except (AuthenticationError, PermissionDeniedError) as e:
            raise HTTPException(400, "OpenAI hat den Schlüssel abgelehnt.") from e
        except Exception as e:  # noqa: BLE001 – nur den Typ nennen, die Meldung kann Kennungen enthalten
            raise HTTPException(502, f"Prüfung nicht möglich ({type(e).__name__}).") from e
    schluessel_speichern(neu or None)
    coach.client_neu()
    coach.fehler = None
    await senden()
    return schluessel_info()


@app.get("/api/regeln")
async def regelkatalog():
    """Gesprächsregeln zur Auswahl, mit Prüfstufe und Umsetzungsstand (docs/gespraechsregeln.md)."""
    return {"katalog": regeln.katalog(), "standard": regeln.STANDARD}


@app.post("/api/einrichten")
async def einrichten(daten: dict):
    coach.einrichten(daten)
    await senden()
    return {"ok": True}


@app.post("/api/referenz")
async def referenz(name: str = Form(...), datei: UploadFile = File(...)):
    if name not in coach.meeting.teilnehmende:
        raise HTTPException(400, "Unbekannte Person – erst einrichten.")
    wav = await datei.read()
    dauer, _ = wav_info(wav)
    if not 2 <= dauer <= 10:
        raise HTTPException(400, f"Referenz muss 2–10 s lang sein, ist {dauer:.1f} s.")
    if name not in coach.referenzen and len(coach.referenzen) >= 4:
        raise HTTPException(400, "Höchstens vier Stimmreferenzen möglich.")
    coach.referenzen[name] = als_data_url(wav)
    await senden()
    return {"ok": True, "referenzen": list(coach.referenzen)}


@app.post("/api/start")
async def start():
    """Version 2: Hörstrom öffnen; das Audio kommt anschließend über /ws/audio."""
    await coach.hoeren_starten()
    return {"ok": True}


@app.post("/api/stopp")
async def stopp():
    await coach.hoeren_beenden()
    coach.meeting.beenden()
    await senden()
    return {"ok": True}


@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket):
    """Mikrofon: PCM 16 bit, 24 kHz, mono als Binärnachrichten."""
    await ws.accept()
    try:
        while True:
            daten = await ws.receive_bytes()
            await coach.hoeren_zufuehren(daten)
    except WebSocketDisconnect:
        pass


@app.get("/api/aufnahmen")
async def aufnahmen():
    return sorted(p.stem for p in AUFNAHMEN.glob("*.wav")) if AUFNAHMEN.is_dir() else []


@app.post("/api/abspielen")
async def abspielen(daten: dict):
    pfad = (AUFNAHMEN / f"{daten.get('name', '')}.wav").resolve()
    if not pfad.is_file() or pfad.parent != AUFNAHMEN.resolve():
        raise HTTPException(404, "Aufnahme nicht gefunden.")
    if coach.hoerstrom:
        raise HTTPException(409, "Es läuft bereits ein Meeting.")
    hintergrund(coach.abspielen(pfad, float(daten.get("tempo", 1)), bool(daten.get("auto_wechsel", False))))
    return {"ok": True}


@app.post("/api/onepager")
async def onepager_neu():
    """Live-Bild auf Knopfdruck neu zeichnen lassen (FR-10)."""
    return {"ok": coach.onepager_starten()}


@app.get("/api/onepager.svg")
async def onepager_svg():
    if not coach.onepager_svg:
        raise HTTPException(404, "Noch kein Live-Bild.")
    return Response(coach.onepager_svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store", "Content-Security-Policy": "script-src 'none'"})


@app.get("/api/onepager.png")
async def onepager_png():
    if not coach.onepager_png:
        raise HTTPException(404, "Noch kein Live-Bild.")
    return Response(coach.onepager_png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/onepager.md")
async def onepager_analyse():
    if not coach.onepager_analyse:
        raise HTTPException(404, "Noch keine Analyse.")
    return Response(coach.onepager_analyse, media_type="text/markdown; charset=utf-8")


@app.post("/api/block")
async def block(start: float = Form(...), datei: UploadFile = File(...)):
    """Version 1 (Blöcke, OpenAI-Diarisierung) – Rückfallweg, vom Dashboard nicht mehr genutzt."""
    wav = await datei.read()
    hintergrund(coach.block_verarbeiten(wav, start))
    return {"ok": True}


@app.post("/api/punkt")
async def punkt(daten: dict):
    coach.punkt_wechseln(int(daten["index"]))
    await senden()
    return {"ok": True}


@app.post("/api/vorschlag/verwerfen")
async def vorschlag_verwerfen():
    coach.meeting.vorschlag = None
    await senden()
    return {"ok": True}


@app.get("/api/szenarien")
async def szenarien():
    return sorted(p.stem for p in SZENARIEN.glob("*.json"))


@app.post("/api/simulation")
async def simulation(daten: dict):
    pfad = SZENARIEN / f"{daten.get('name', '')}.json"
    if not pfad.is_file() or pfad.parent != SZENARIEN:
        raise HTTPException(404, "Szenario nicht gefunden.")
    coach.simulation_starten(pfad, float(daten.get("tempo", 10)))
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpunkt(ws: WebSocket):
    await ws.accept()
    verbindungen.add(ws)
    await ws.send_text(json.dumps(coach.schnappschuss(), ensure_ascii=False))
    try:
        while True:
            nachricht = await ws.receive_text()
            try:
                daten = json.loads(nachricht)
                if daten.get("sprache"):
                    coach.sprache_melden()
                if daten.get("lautsprecher"):
                    global lautsprecher
                    lautsprecher = ws
            except (ValueError, AttributeError):
                pass
    except WebSocketDisconnect:
        verbindungen.discard(ws)
