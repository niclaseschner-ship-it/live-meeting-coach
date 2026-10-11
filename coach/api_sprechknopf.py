"""Live-Teiltext für die Sprechknöpfe: ein kurzer WS-Kanal, der die PCM-Pakete einer Sprechknopf-Aufnahme
(static/basis.js: sprechknopf/mikro/halten, static/agenda.js: agendaAufnahme) in die Live-Text-Klasse der
gewählten Stufe streamt (coach/livetext.py) und den laufenden Teiltext zurückschickt.

Die Anbietertrennung (coach/anbieter.py) gilt unverändert: der Kanal nutzt genau den Anbieter der bestätigten
Wahl (coach.wahl) und denselben Client/dieselbe Hostwache wie jede andere KI-Verbindung des Meetings. Die
Kostenbremse zählt über coach.live_text_kosten mit – wie beim Live-Text eines laufenden Meetings
(coach/hoeren.py).

Der maßgebliche, fertige Text einer Sprechknopf-Aufnahme kommt weiter aus der vorhandenen WAV-Transkription nach
dem Stopp (coach/transkription.py, über /api/agenda/transkript bzw. /api/frage/audio) – dieser Kanal liefert nur
die Vorschau während des Sprechens, deshalb reicht die kommentarlose Vorschau: kein Commit, kein fertiger Satz
nötig. Fehlt Anbieter, Schlüssel oder ist der Kostendeckel erreicht, schließt der Kanal sofort wieder – der
Browser (basis.js: liveTextOeffnen) behandelt das als „kein Teiltext“, nie als Fehler."""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, WebSocket

from .livetext import LiveText, LiveTextMistral

log = logging.getLogger("coach.sprechknopf")
router = APIRouter()


@router.websocket("/ws/sprechknopf")
async def ws_sprechknopf(ws: WebSocket) -> None:
    from .server import coach  # spät geladen wie in api_agenda.py – sonst ein Kreis mit server.py

    await ws.accept()
    wahl = coach.wahl
    if wahl is None or coach._client is None or coach.ki_gesperrt:
        await ws.close(code=4404)
        return

    async def teiltext(text: str) -> None:
        with contextlib.suppress(Exception):  # Browser schon weg: der Kanal schließt gleich ohnehin
            await ws.send_json({"teil": text})

    async def satz(_meta: dict, _text: str) -> None:
        pass  # der maßgebliche Text kommt aus der WAV-Transkription – hier nur die Vorschau

    klasse = LiveTextMistral if wahl.basis else LiveText
    live = klasse(teiltext, satz, "", [], wahl=wahl, bei_verstoss=coach.anbieter_verstoss)
    try:
        await live.verbinden()
    except Exception:  # noqa: BLE001 – ohne Live-Text läuft die Aufnahme weiter, kein Fehler für den Browser
        log.warning("Live-Text für Sprechknopf nicht verfügbar", exc_info=True)
        with contextlib.suppress(Exception):
            await ws.close(code=4503)
        return

    try:
        while True:
            nachricht = await ws.receive()
            if nachricht["type"] == "websocket.disconnect":
                break
            daten = nachricht.get("bytes")
            if daten is not None:
                await live.audio(daten)
    finally:
        coach.live_text_kosten(live.gesendete_sekunden)
        with contextlib.suppress(Exception):
            await live.schliessen(nachlauf=0)
