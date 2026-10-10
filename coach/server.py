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

from . import anbieter, api_abschluss, api_agenda, api_artefakte, api_knopfdruck, api_start, regeln, zugang
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
handy_kennungen: dict[WebSocket, str] = {}  # anonyme Browserkennung, keine Registrierung


def handy_verbindung():
    return next((w for w in verbindungen if geraet.get(w) == "handy"), None)


async def senden_direkt(nachricht: dict) -> None:
    """Sprachausgabe nur an den Lautsprecher-Tab – mehrere offene Dashboards sprachen sonst doppelt (Test 05.10.).
    Was Nestor sagt (Text) und das Verstummen gehen an alle: der Beamer zeigt den Text auch, wenn das Handy spricht
    (Ticket #21)."""
    if nachricht.get("typ") in ("nestor_text", "stimme_stopp"):
        await _an_alle(json.dumps(nachricht, ensure_ascii=False))
        return
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
        if verbindungen:
            await senden()  # auch Vorbereitung: Handy-Audio und Startbereitschaft aktuell halten (#53)


@asynccontextmanager
async def lebenszyklus(app: FastAPI):
    task = asyncio.create_task(taktgeber())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Live Meeting Coach", lifespan=lebenszyklus)
app.add_middleware(zugang.Zugangsschutz)
_variantenwahl_wiederhergestellt = False


@app.middleware("http")
async def immer_nachfragen(request: Request, call_next):
    """Seiten und Skripte: der Browser fragt jedes Mal nach (meist 304). Sonst mischt ein Handy alte und neue
    Fassungen – Teachbuddy 14.09., und im eigenen Test 06.10. kam das alte CSS."""
    # #54: Der Worker hält die bestätigte Auswahl außerhalb des flüchtigen Containers (cloudflare/src/variantenwahl.ts).
    # Fremde Header sind keine Autorität; laufende Meetings bleiben unverändert. #60: Ein frisch gestarteter Container
    # hat keine Vorgabe-Stufe – ohne gespeicherte Wahl bleibt er unbestimmt, und /api/start weist ab.
    global _variantenwahl_wiederhergestellt
    if not _variantenwahl_wiederhergestellt and EINST.betrieb == "cloud" and zugang.worker_geheimnis_passt(request.scope):
        stufe = request.headers.get("X-Nestor-Stufe")
        modus = request.headers.get("X-Nestor-Modus")
        if not coach.wahl_gesperrt and stufe in anbieter.STUFEN and modus in anbieter.MODI:
            if coach.stufe != stufe or coach.modus != modus:
                try:
                    coach.stufe_setzen(stufe, nur_knopfdruck=modus == "knopfdruck")
                except (ValueError, anbieter.AnbieterFehler) as e:
                    logging.getLogger("coach").error("Gespeicherte Variante nicht übernommen: %s", type(e).__name__)
            _variantenwahl_wiederhergestellt = True
    antwort = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in ("/", "/meeting", "/handy"):
        antwort.headers["Cache-Control"] = "no-cache"
    return antwort
app.mount("/static", StaticFiles(directory=STATIC), name="static")
# Router der Einzelmodule (api_*.py). Nicht include_router(): FastAPI 0.142 legt dafür einen Platzhalter ohne .path
# in app.routes ab, test_dashboard_endpunkte_existieren braucht flache Routen. Neue Module hier in die Liste.
for _modul in (api_start, api_agenda, api_abschluss, api_knopfdruck, api_artefakte):
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
    """QR-Code und Code zum Koppeln – nur mit Laptop-Rechten abrufbar (am Laptop selbst, oder im Cloud-Betrieb
    über den Worker, der das Kundenpasswort schon geprüft hat)."""
    if not zugang.lokal(request.scope):
        raise HTTPException(403, "Nur am Laptop.")
    import segno

    if EINST.betrieb == "cloud":
        # Die Handy-Adresse kommt aus der Anfrage (Host), nicht aus tailscale; die Meeting-Kennung des Worker
        # (Cookie `nestor_meeting`, hier als Kopfzeile) muss mit in die URL, damit das gescannte Handy im
        # selben Meeting-Container landet wie das Dashboard (der Worker wählt den Container über `?meeting=`).
        # Ticket #63: Die nackte Meeting-ID gehört nicht mehr in den QR-Code – der Worker signiert dafür ein
        # kurzlebiges Kopplungstoken (`/intern/kopplungstoken`, gleiches Vertrauensverhältnis wie bei
        # `/intern/meeting-start`); ohne gültige Signatur startet der Worker später keinen Container. Der
        # Coach selbst kennt das Signier-Geheimnis nicht und kann das Token darum nicht selbst bauen.
        host = request.headers.get("host")
        basis = zugang.adresse_aus_host(host) if host else None
        meeting = zugang.meeting_id(request.scope)
        token = None
        if meeting:
            antwort_token = api_abschluss.worker_melden(
                "/intern/kopplungstoken", {"meetingId": meeting, "kunde": zugang.kunde(request.scope)},
            )
            token = antwort_token.get("token") if antwort_token else None
        url = f"{basis}/handy?k={zugang.code()}&meeting={token}" if basis and token else None
        befehl = None
    else:
        basis = zugang.adresse()
        url = f"{basis}/handy?k={zugang.code()}" if basis else None
        # Tailscale erlaubt HTTPS nur auf 443, 8443 und 10000 – also höchstens drei Coaches auf einem Laptop
        https = {8000: 443, 8001: 8443}.get(EINST.port, 10000)
        befehl = f"tailscale serve --bg {EINST.port}" if https == 443 else f"tailscale serve --bg --https={https} {EINST.port}"
    svg = segno.make(url, error="m").svg_inline(scale=5, dark="#1E1B4B", border=2) if url else None
    return {"code": zugang.code(), "adresse": url, "qr": svg, "befehl": befehl}


@app.post("/api/ablage/oeffnen")
async def ablage_oeffnen(request: Request):
    """Meeting-Ordner im Explorer öffnen – nur am Laptop selbst, und nur lokal: im Container gibt es keinen
    Explorer, und niemand soll aus der Ferne einen Dateimanager auf dem Server öffnen."""
    if EINST.betrieb == "cloud":
        raise HTTPException(404, "In der Cloud nicht verfügbar.")
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


@app.post("/api/assistent/abbrechen")
async def assistent_abbrechen(daten: dict):
    """✕ an einem Auftrag in der Warteschlange (Ticket #21): Recherche, Bild, Folie oder Überblick abbrechen."""
    try:
        nr = int(daten.get("id"))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "Ungültiger Auftrag") from e
    ok = coach.assistent.auftrag_abbrechen(nr)
    await coach.melden()
    return {"ok": ok}


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
        from openai import AuthenticationError, PermissionDeniedError

        try:
            await anbieter.openai_schluessel_pruefen(neu)
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
    if coach.hoerstrom is not None or coach.startet:
        ereignis("start_abgewiesen", von=_herkunft(request))
        raise HTTPException(409, "Das Meeting läuft schon – auf allen Seiten derselbe Stand.")
    # Ticket #60: ohne bestätigte Variante kein Start – es gibt keine Vorgabe-Stufe, auf die still ausgewichen würde
    wahl = coach.wahl
    if wahl is None:
        raise HTTPException(409, "Bitte Variante wählen: Basis oder Premium auf der Startseite.")
    erwartet = request.headers.get("X-Nestor-Erwartete-Stufe")
    if erwartet and erwartet != wahl.stufe:
        raise HTTPException(409, "Die gewählte Variante stimmt nicht mit dem Server überein. Bitte auf der Startseite erneut wählen.")
    if (audio["ws"] is None or audio["quelle"] != "handy"
            or time.monotonic() - audio["letzt"] > LUECKE
            or lautsprecher not in verbindungen or geraet.get(lautsprecher) != "handy"):
        raise HTTPException(409, "Erst den QR-Code scannen und am Handy Mikrofon und Ton einschalten. Dann Meeting starten.")
    # Ab hier ist die Wahl gesperrt (/api/stufe, /api/modus → 409), auch während der Worker-Meldung im Thread.
    coach.startet = True
    try:
        if EINST.betrieb == "cloud":
            # Ticket #12: Ein Meeting zählt beim Worker (KundenZaehler) erst ab hier, nicht schon beim Ansehen der
            # Startseite. Kein Netzkontakt zum Worker möglich (None) lässt den Start im Zweifel zu, statt an einer
            # Netzstörung zu scheitern – wie bei der Datenspende (coach/ablage_r2.py) ist das keine harte Grenze.
            # #60: im Thread, damit die Ereignisschleife (Audio, Takt) nicht bis zu 10 s steht; mit Stufe für die
            # Startmeldung.
            meeting_id = zugang.meeting_id(request.scope)
            if meeting_id:
                rueckmeldung = await asyncio.to_thread(
                    api_abschluss.worker_melden, "/intern/meeting-start",
                    {"meetingId": meeting_id, "kunde": zugang.kunde(request.scope), "stufe": wahl.stufe,
                     "modus": wahl.modus},
                )
                if rueckmeldung is not None and not rueckmeldung.get("erlaubt", True):
                    raise HTTPException(
                        429,
                        "Höchstzahl gleichzeitiger Meetings für diesen Zugang erreicht – bitte ein laufendes "
                        "Meeting beenden oder kurz warten.",
                    )
        if coach.wahl is not wahl:  # kann wegen der Sperre nicht passieren – wenn doch, lieber nicht starten
            raise HTTPException(409, "Die Variante hat sich während des Starts geändert. Bitte erneut starten.")
        await coach.hoeren_starten()
    finally:
        coach.startet = False
    ereignis("start_von", von=_herkunft(request), mikro=audio["quelle"], stufe=wahl.stufe)
    return {"ok": True}


@app.post("/api/stopp")
async def stopp(request: Request):
    ereignis("stopp_von", von=_herkunft(request))
    await coach.hoeren_beenden()
    coach.meeting.beenden()
    await senden()
    return {"ok": True}


@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket, quelle: str = "laptop", handy_id: str = ""):
    """Mikrofon: PCM 16 bit, 24 kHz, mono als Binärnachrichten. Eine neue Quelle löst die alte ab (Code 4001) –
    zwei Mikrofone zugleich ergäben einen zerhackten Strom."""
    await ws.accept()
    if quelle == "handy":
        handy = handy_verbindung()
        if handy is None or not handy_id or handy_kennungen.get(handy) != handy_id:
            await ws.close(code=4409)
            return
    alt = audio["ws"]
    audio.update(ws=ws, quelle="handy" if quelle == "handy" else "laptop", letzt=time.monotonic())
    ereignis("mikro_an", quelle=audio["quelle"], abgeloest=alt is not None)
    if alt is not None:
        with contextlib.suppress(Exception):
            await alt.close(code=4001)
    await senden()
    zuletzt_pegel, spitze = 0.0, 0.0
    beginn = letzter_empfang = time.monotonic()
    pakete = bytezahl = luecken = 0
    try:
        while True:
            daten = await ws.receive_bytes()
            if audio["ws"] is not ws:
                break
            jetzt = time.monotonic()
            if pakete and jetzt - letzter_empfang > 0.25:
                luecken += 1
            letzter_empfang = jetzt
            pakete += 1
            bytezahl += len(daten)
            audio["letzt"] = jetzt
            spitze = max(spitze, pegel(daten))  # lauteste Stelle seit der letzten Anzeige
            if audio["letzt"] - zuletzt_pegel >= PEGEL_TAKT:
                pegel_senden(spitze, audio["quelle"])
                zuletzt_pegel, spitze = audio["letzt"], 0.0
            await coach.hoeren_zufuehren(daten)
    except WebSocketDisconnect:
        pass
    finally:
        if audio["ws"] is ws:
            ende = time.monotonic()
            audio_s = bytezahl / (24_000 * 2)
            wand_s = max(0.0, ende - beginn)
            ereignis("mikro_weg", quelle=audio["quelle"], still_s=round(ende - audio["letzt"], 1),
                     pakete=pakete, audio_s=round(audio_s, 2), wand_s=round(wand_s, 2),
                     drift_s=round(audio_s - wand_s, 2), luecken=luecken)
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
    """Live-Bild auf Knopfdruck (ohne laufendes Meeting, z. B. nach dem Abspielen) neu zeichnen lassen (FR-10).
    Im Meeting ist „Bild“ ein langer Auftrag über /api/knopf/bild (Ticket #27)."""
    return {"ok": coach.onepager_starten()}


@app.post("/api/folie")
async def folie_neu():
    """Letzte Recherche mit Quellen als Folie – im Meeting als Bogen („Hier ist die Folie“, Ticket #27)."""
    from .assistent import BogenBelegt

    if coach.hoerstrom is None or coach.knopfdruck:
        return {"ok": coach.folie_starten()}
    try:
        coach.assistent.bogen_starten("folie", "Folie", "knopf")
    except BogenBelegt as e:
        raise HTTPException(409, str(e)) from e
    await coach.melden()
    return {"ok": True}


def _bild(v: int | None, art: type):
    """Das Bild einer Version (Bild-Karten im Verlauf, Ticket #27), sonst das neueste."""
    b = coach.bilder.get(v) if v is not None else None
    if b is None:
        b = coach.onepager_png if art is bytes else coach.onepager_svg
    return b if isinstance(b, art) else None


@app.get("/api/onepager.svg")
async def onepager_svg(v: int | None = None):
    svg = _bild(v, str)
    if not svg:
        raise HTTPException(404, "Noch kein Live-Bild.")
    return Response(svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store", "Content-Security-Policy": "script-src 'none'"})


@app.get("/api/onepager.png")
async def onepager_png(v: int | None = None):
    png = _bild(v, bytes)
    if not png:
        raise HTTPException(404, "Noch kein Live-Bild.")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/onepager.md")
async def onepager_analyse():
    if not coach.onepager_analyse:
        raise HTTPException(404, "Noch keine Analyse.")
    return Response(coach.onepager_analyse, media_type="text/markdown; charset=utf-8")


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
async def ws_endpunkt(ws: WebSocket, geraet_art: str = Query("laptop", alias="geraet"), handy_id: str = ""):
    global lautsprecher
    await ws.accept()
    alt = None
    if geraet_art == "handy":
        alt = handy_verbindung()
        if not handy_id or len(handy_id) > 100 or (alt is not None and handy_kennungen.get(alt) != handy_id):
            await ws.close(code=4409)
            return
        if alt is not None:
            verbindungen.discard(alt)  # Neuladen desselben Handys übernimmt den einzigen Platz
        handy_kennungen[ws] = handy_id
    verbindungen.add(ws)
    geraet[ws] = "handy" if geraet_art == "handy" else "laptop"
    if alt is not None:
        with contextlib.suppress(Exception):
            await alt.close(code=4001)
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
        verbindungen.discard(ws)
        handy_kennungen.pop(ws, None)
        war_handy = geraet.pop(ws, None) == "handy"
        if lautsprecher is ws:
            lautsprecher = None
            ereignis("ton_weg", geraet="?")
        if war_handy:
            # Beim Schließen der Handyseite auch ihren Audiostrom freigeben.
            if handy_verbindung() is None and audio["quelle"] == "handy" and audio["ws"] is not None:
                with contextlib.suppress(Exception):
                    await audio["ws"].close(code=1012)  # Netzabriss darf nach Rückkehr erneut verbinden
        await senden()
