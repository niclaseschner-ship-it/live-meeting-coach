"""HTTP/WebSocket-Schnittstelle für Dashboard und Mikrofon."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import api_abschluss, api_agenda, api_start, regeln, zugang
from .config import EINST, WURZEL, schluessel_info, schluessel_speichern
from .pipeline import Coach, hintergrund
from .transkription import als_data_url, wav_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC = WURZEL / "static"
SZENARIEN = WURZEL / "szenarien"
AUFNAHMEN = Path(EINST.aufnahmen)

coach = Coach()
coach.archiv_aktiv = True  # echte Meetings ablegen (meetings/), Testskripte nicht


def ereignis(art: str, **daten) -> None:
    """Debug-Ereignis ins laufende Meeting (Mikrofon, Lautsprecher, Start/Stopp und woher)."""
    if coach.archiv and not coach.archiv.fertig:
        coach.archiv.ereignis(art, **daten)
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


# Mikrofon: genau eine Quelle (Laptop oder Handy). Merkt sich, wann zuletzt Ton kam – ein gesperrtes Handy liefert
# nichts mehr, und das ist etwas anderes als Stille im Raum (Teachbuddy, 14.09.).
audio: dict = {"ws": None, "quelle": None, "letzt": 0.0}
LUECKE = 3.0  # s ohne Audiopaket = Mikrofon weg (Pakete kommen alle 100 ms, auch bei Stille)


PEGEL_TAKT = 0.2  # s – so oft geht der Pegel an die Laptop-Seiten


def pegel(pcm: bytes) -> float:
    """Lautstärke eines Pakets als 0..1 (−60 dBFS … 0 dBFS, Effektivwert) für die Anzeige."""
    import numpy as np

    a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
    if not len(a):
        return 0.0
    db = 20 * np.log10(max(float(np.sqrt(np.mean(a * a))), 1e-6))
    return round(min(1.0, max(0.0, (db + 60) / 60)), 2)


def pegel_senden(wert: float, quelle: str) -> None:
    """Ohne zu warten an die Laptop-Seiten – der Audiostrom darf nie auf eine langsame Seite warten."""
    text = json.dumps({"typ": "pegel", "wert": wert, "quelle": quelle})
    for w, g in list(geraet.items()):
        if g == "laptop" and w in verbindungen:
            asyncio.ensure_future(_leise_senden(w, text))


async def _leise_senden(ws: WebSocket, text: str) -> None:
    with contextlib.suppress(Exception):
        await asyncio.wait_for(ws.send_text(text), 1.0)


def mikro_stand() -> dict:
    luecke = round(time.monotonic() - audio["letzt"], 1) if audio["ws"] is not None else None
    weg = coach.hoerstrom is not None and not coach.simulation_laeuft and (luecke is None or luecke > LUECKE)
    return {"quelle": audio["quelle"], "luecke": luecke, "weg": weg}


def stand() -> dict:
    ton = geraet.get(lautsprecher) if lautsprecher in verbindungen else None
    handys = sum(1 for w, g in geraet.items() if g == "handy" and w in verbindungen)
    return {**coach.schnappschuss(), "mikro": mikro_stand(), "lautsprecher": ton, "handys": handys}


async def senden() -> None:
    if verbindungen:
        await _an_alle(json.dumps(stand(), ensure_ascii=False))


coach.beobachter.append(senden)


lautsprecher: WebSocket | None = None  # der Tab, der das Meeting gestartet hat – nur er spielt Nestor ab
geraet: dict[WebSocket, str] = {}       # Verbindung -> "laptop" | "handy", damit alle Seiten sehen, wo Nestor spricht


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
app.add_middleware(zugang.Zugangsschutz)


@app.middleware("http")
async def immer_nachfragen(request: Request, call_next):
    """Seiten und Skripte: der Browser fragt jedes Mal nach (meist 304). Sonst mischt ein Handy alte und neue
    Fassungen – Teachbuddy 14.09., und im eigenen Test 06.10. kam das alte CSS."""
    antwort = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in ("/", "/meeting", "/handy"):
        antwort.headers["Cache-Control"] = "no-cache"
    return antwort
app.mount("/static", StaticFiles(directory=STATIC), name="static")
# Router der Einzelmodule (api_*.py). Nicht include_router(): FastAPI 0.142 legt dafür einen Platzhalter ohne .path
# in app.routes ab, test_dashboard_endpunkte_existieren braucht flache Routen. Neue Module hier in die Liste.
for _modul in (api_start, api_agenda, api_abschluss):
    app.router.routes.extend(_modul.router.routes)


@app.get("/")
async def startseite():
    """Moduswahl, Kostenhinweis, Links auf Impressum und Datenschutz (Lastenheft Abschnitt 2)."""
    return FileResponse(STATIC / "start.html")


@app.get("/meeting")
async def meeting_seite():
    """Das bisherige Dashboard – zog von „/“ hierher, als die Startseite dazukam (Ticket #1)."""
    return FileResponse(STATIC / "index.html")


@app.get("/abschluss")
async def abschlussseite():
    return FileResponse(STATIC / "abschluss.html")


@app.get("/handy")
async def handy(k: str | None = None):
    """Handy-Fernbedienung. Mit ?k=<Code> (aus dem QR-Code) wird das Handy gekoppelt und der Code aus der Adresse
    genommen; ein falscher Code landet auf der Seite mit Code-Eingabe."""
    if k is not None:
        antwort = RedirectResponse("/handy" + ("" if zugang.code_passt(k) else "?falsch=1"), status_code=303)
        if zugang.code_passt(k):
            antwort.set_cookie(zugang.COOKIE, zugang.normalisieren(k), max_age=400 * 24 * 3600, httponly=True,
                               samesite="strict", secure=True)
        return antwort
    return FileResponse(STATIC / "handy.html", headers={"Cache-Control": "no-cache"})


@app.get("/handy.webmanifest")
async def handy_manifest():
    return FileResponse(STATIC / "handy.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    # aus der Wurzel, damit er /handy steuern darf; nie zwischenspeichern, sonst hängt ein altes Handy fest
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/api/kopplung")
async def kopplung(request: Request):
    """QR-Code und Code zum Koppeln – nur am Laptop selbst abrufbar."""
    if not zugang.lokal(request.scope):
        raise HTTPException(403, "Nur am Laptop.")
    import segno

    basis = zugang.adresse()
    url = f"{basis}/handy?k={zugang.code()}" if basis else None
    svg = segno.make(url, error="m").svg_inline(scale=5, dark="#1E1B4B", border=2) if url else None
    # Tailscale erlaubt HTTPS nur auf 443, 8443 und 10000 – also höchstens drei Coaches auf einem Laptop
    https = {8000: 443, 8001: 8443}.get(EINST.port, 10000)
    befehl = f"tailscale serve --bg {EINST.port}" if https == 443 else f"tailscale serve --bg --https={https} {EINST.port}"
    return {"code": zugang.code(), "adresse": f"{basis}/handy" if basis else None, "qr": svg, "befehl": befehl}


@app.post("/api/ablage/oeffnen")
async def ablage_oeffnen(request: Request):
    """Meeting-Ordner im Explorer öffnen – nur am Laptop selbst."""
    if not zugang.lokal(request.scope):
        raise HTTPException(403, "Nur am Laptop.")
    if coach.archiv is None:
        raise HTTPException(404, "Noch kein Meeting abgelegt.")
    import os
    import subprocess
    import sys

    ordner = str(coach.archiv.ordner)
    if sys.platform == "win32":
        os.startfile(ordner)  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", ordner])
    return {"ok": True}


@app.get("/api/zustand")
async def zustand():
    return stand()


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
    if not zugang.lokal(request.scope):
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
    if coach.hoerstrom is not None:
        raise HTTPException(409, "Während des Meetings nicht umstellbar.")
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


def _herkunft(request: Request) -> str:
    return "laptop" if zugang.lokal(request.scope) else "handy"


@app.post("/api/start")
async def start(request: Request):
    """Version 2: Hörstrom öffnen; das Audio kommt anschließend über /ws/audio. Ein Meeting zur Zeit – ein zweiter
    Start (zweiter Tab, Handy) würde den laufenden Hörstrom samt Live-Text-Verbindung verwaisen lassen."""
    if coach.hoerstrom is not None:
        ereignis("start_abgewiesen", von=_herkunft(request))
        raise HTTPException(409, "Das Meeting läuft schon – auf allen Seiten derselbe Stand.")
    await coach.hoeren_starten()
    ereignis("start_von", von=_herkunft(request), mikro=audio["quelle"])
    return {"ok": True}


@app.post("/api/stopp")
async def stopp(request: Request):
    ereignis("stopp_von", von=_herkunft(request))
    await coach.hoeren_beenden()
    coach.meeting.beenden()
    await senden()
    return {"ok": True}


@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket, quelle: str = "laptop"):
    """Mikrofon: PCM 16 bit, 24 kHz, mono als Binärnachrichten. Eine neue Quelle löst die alte ab (Code 4001) –
    zwei Mikrofone zugleich ergäben einen zerhackten Strom."""
    await ws.accept()
    alt = audio["ws"]
    audio.update(ws=ws, quelle="handy" if quelle == "handy" else "laptop", letzt=time.monotonic())
    ereignis("mikro_an", quelle=audio["quelle"], abgeloest=alt is not None)
    if alt is not None:
        with contextlib.suppress(Exception):
            await alt.close(code=4001)
    await senden()
    zuletzt_pegel, spitze = 0.0, 0.0
    try:
        while True:
            daten = await ws.receive_bytes()
            if audio["ws"] is not ws:
                break
            audio["letzt"] = time.monotonic()
            spitze = max(spitze, pegel(daten))  # lauteste Stelle seit der letzten Anzeige
            if audio["letzt"] - zuletzt_pegel >= PEGEL_TAKT:
                pegel_senden(spitze, audio["quelle"])
                zuletzt_pegel, spitze = audio["letzt"], 0.0
            await coach.hoeren_zufuehren(daten)
    except WebSocketDisconnect:
        pass
    finally:
        if audio["ws"] is ws:
            ereignis("mikro_weg", quelle=audio["quelle"], still_s=round(time.monotonic() - audio["letzt"], 1))
            audio.update(ws=None, quelle=None)
            await senden()


DEMO = WURZEL / "demo"


def _aufnahmen() -> dict[str, Path]:
    """Name -> WAV: die Demo aus dem Repo zuerst, dann die lokale Testbibliothek."""
    gefunden: dict[str, Path] = {}
    for ordner in (DEMO, AUFNAHMEN):
        if ordner.is_dir():
            for p in sorted(ordner.glob("*.wav")):
                gefunden.setdefault(p.stem, p.resolve())
    return gefunden


@app.get("/api/aufnahmen")
async def aufnahmen():
    return list(_aufnahmen())


@app.post("/api/abspielen")
async def abspielen(daten: dict):
    pfad = _aufnahmen().get(str(daten.get("name", "")))
    if pfad is None:
        raise HTTPException(404, "Aufnahme nicht gefunden.")
    if coach.hoerstrom:
        raise HTTPException(409, "Es läuft bereits ein Meeting.")
    hintergrund(coach.abspielen(pfad, float(daten.get("tempo", 1)), bool(daten.get("auto_wechsel", False))))
    return {"ok": True}


@app.post("/api/onepager")
async def onepager_neu():
    """Live-Bild auf Knopfdruck neu zeichnen lassen (FR-10)."""
    return {"ok": coach.onepager_starten()}


@app.post("/api/folie")
async def folie_neu():
    """Letzte Recherche mit Quellen als Folie (Knopf im Dashboard; per Zuruf macht es Nestor)."""
    return {"ok": coach.folie_starten()}


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
async def ws_endpunkt(ws: WebSocket, geraet_art: str = Query("laptop", alias="geraet")):
    global lautsprecher
    await ws.accept()
    verbindungen.add(ws)
    geraet[ws] = "handy" if geraet_art == "handy" else "laptop"
    if geraet[ws] == "handy":
        await senden()  # alle Seiten sehen sofort: Handy verbunden
    await ws.send_text(json.dumps(stand(), ensure_ascii=False))
    try:
        while True:
            nachricht = await ws.receive_text()
            try:
                daten = json.loads(nachricht)
                if daten.get("sprache"):
                    coach.sprache_melden()
                if "ping" in daten:  # Laufzeitmessung vom Handy: sofort und nur an diesen Client zurück
                    await ws.send_text(json.dumps({"typ": "pong", "t": daten["ping"]}))
                    if isinstance(daten.get("laufzeit"), (int, float)) and coach.archiv and not coach.archiv.fertig:
                        coach.archiv.laufzeit(daten["laufzeit"])
                # Ein gemeldetes Handy trägt den Ton; ein Laptop-Tab nimmt ihn nur auf ausdrücklichen Klick
                handy_spricht = lautsprecher in verbindungen and geraet.get(lautsprecher) == "handy"
                if (daten.get("lautsprecher") and lautsprecher is not ws
                        and (not handy_spricht or geraet[ws] == "handy" or daten.get("erzwingen"))):
                    lautsprecher = ws
                    ereignis("ton_an", geraet=geraet[ws], erzwungen=bool(daten.get("erzwingen")))
                    await senden()
                elif daten.get("lautsprecher") is False and lautsprecher is ws:
                    lautsprecher = None  # Handy gibt die Stimme ab; der nächste Klick am Laptop holt sie
                    await senden()
            except (ValueError, AttributeError, TypeError):
                pass
    except WebSocketDisconnect:
        verbindungen.discard(ws)
    finally:
        if geraet.pop(ws, None) == "handy":
            await senden()
        if lautsprecher is ws:
            ereignis("ton_weg", geraet="?")
            await senden()  # alle Seiten zeigen: Nestor hat gerade keinen Lautsprecher
