"""Knopf-Endpunkte (Ticket #6, Lastenheft 4.2; seit Ticket #13 in beiden Stufen, mit und ohne „Nur auf Knopfdruck“).

    POST /api/knopf/<art>       art: stand | regeln | ueberblick | protokoll | bild | frage ({"text"})
    POST /api/knopf/verwerfen   {"minuten": 5 | null}          – nur bei „Nur auf Knopfdruck“
    GET  /api/knopf/protokoll.md
    POST /api/frage/halten      {"an": true|false}             – „Nestor fragen“ am Handy wird gehalten/losgelassen
    POST /api/frage/audio       WAV (24 kHz mono) im Körper     – die gehaltene Frage: transkribieren, dann antworten

Ohne „Nur auf Knopfdruck“ ist jeder Knopf ein Antwortbogen (Ticket #27, coach/assistent.py): Bestätigung, Karte im
Verlauf, ein bis zwei Sätze; während ein Bogen läuft, sind die Knöpfe gesperrt (409). Mit „Nur auf Knopfdruck“
antwortet ein Knopf sofort; Fortschritt und Ergebnis kommen über die WebSocket (coach/knopfdruck.py). Je Art eine
eigene Route statt /api/knopf/{art}: so findet test_dashboard_endpunkte_existieren jeden Aufruf aus app.js.
Der `coach` ist die eine laufende Instanz aus server.py, spät importiert (sonst Ringimport beim Hochfahren).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import knopfdruck
from .knopfdruck import ARTEN, KnopfFehler

router = APIRouter()


async def _an_alle(nachricht: dict) -> None:
    from .server import _an_alle

    await _an_alle(json.dumps(nachricht, ensure_ascii=False))


def _knopf(art: str):
    async def knopf(daten: dict | None = None) -> dict:
        from .pipeline import hintergrund
        from .server import coach

        from .assistent import BogenBelegt
        from .bogen import NAMEN as BOGEN_NAMEN
        from .config import EINST

        frage = str((daten or {}).get("text") or "").strip()[:500]
        if art == "frage" and not frage:
            raise HTTPException(400, "Keine Frage.")
        if not coach.knopfdruck:
            # Live (Ticket #27): jeder Knopf ist ein Antwortbogen, die getippte Frage wie eine gesprochene
            if coach.hoerstrom is None or coach._client is None:
                raise HTTPException(409, "Es läuft kein Meeting." if coach.hoerstrom is None else "Kein KI-Schlüssel.")
            if art == "frage":
                coach.assistent.frage_beantworten(frage, "getippt")
                return {"ok": True}
            ziel = knopfdruck.BOGEN[art]
            if ziel == "bild" and EINST.bild_anbieter == "text":
                ziel = "ueberblick"  # Basis: kein Bildmodell
            try:
                coach.assistent.bogen_starten(ziel, BOGEN_NAMEN.get(ziel, ziel), "band" if (daten or {}).get("band")
                                              else "knopf")
            except BogenBelegt as e:
                raise HTTPException(409, str(e)) from e
            await coach.melden()
            return {"ok": True}
        try:
            knopfdruck.reservieren(coach, art)
        except KnopfFehler as e:
            raise HTTPException(409, str(e)) from e
        hintergrund(knopfdruck.ausfuehren(coach, art, frage, _an_alle))
        return {"ok": True}

    knopf.__name__ = f"knopf_{art}"
    return knopf


for _art in ARTEN:
    router.add_api_route(f"/api/knopf/{_art}", _knopf(_art), methods=["POST"])


@router.post("/api/knopf/verwerfen")
async def knopf_verwerfen(daten: dict) -> dict:
    from .server import coach

    if not coach.knopfdruck:
        raise HTTPException(409, "Verwerfen gibt es nur im Modus „Auf Knopfdruck“.")
    if coach.hoerstrom is None:
        raise HTTPException(409, "Es läuft kein Meeting.")
    minuten = daten.get("minuten")
    if minuten is not None:
        try:
            minuten = float(minuten)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, "Ungültige Minutenzahl.") from e
        if not 0 < minuten <= 600:
            raise HTTPException(400, "Ungültige Minutenzahl.")
    return await knopfdruck.verwerfen(coach, minuten)


@router.get("/api/knopf/protokoll.md")
async def knopf_protokoll():
    from .server import coach

    if not coach.knopf.protokoll:
        raise HTTPException(404, "Noch kein Protokoll – Knopf „Protokoll“ drücken.")
    return Response(coach.knopf.protokoll, media_type="text/markdown; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


# --- „Nestor fragen“ halten (Handy, Ticket #13) -----------------------------------------------------------------------
MAX_FRAGE_BYTES = 24000 * 2 * 30 + 44  # höchstens 30 s Ton


@router.post("/api/frage/halten")
async def frage_halten(daten: dict) -> dict:
    from .server import coach

    if coach.hoerstrom is None:
        raise HTTPException(409, "Es läuft kein Meeting.")
    if daten.get("an"):
        coach.assistent.halten_start()
    else:  # losgelassen ohne Aufnahme (zu kurz): wieder zuhören
        coach.assistent.halten_ende()
        coach.assistent.halten_abbrechen()
    await coach.melden()
    return {"ok": True}


@router.post("/api/frage/audio")
async def frage_audio(request: Request) -> dict:
    """Die gehaltene Frage als WAV: mit dem Transkriptionsmodell der Stufe in Text, dann wie eine gesprochene Frage
    (Live: Stimme + Karte) bzw. wie der Knopf „Nestor fragen“ (Nur auf Knopfdruck: Karte)."""
    from .config import EINST
    from .pipeline import fehlertext, hintergrund, nutzung_loggen
    from .server import coach

    if coach.hoerstrom is None:
        raise HTTPException(409, "Es läuft kein Meeting.")
    if coach._client is None:
        raise HTTPException(409, "Kein KI-Schlüssel.")
    wav = await request.body()
    coach.assistent.halten_ende()
    if not 44 < len(wav) <= MAX_FRAGE_BYTES:
        coach.assistent.halten_abbrechen()
        raise HTTPException(400, "Keine oder zu lange Aufnahme.")
    sekunden = (len(wav) - 44) / 2 / 24000
    try:
        antwort = await coach._client.audio.transcriptions.create(
            model=EINST.text_modell, file=("frage.wav", wav, "audio/wav"), language=EINST.sprache,
            prompt=f"Frage an den Moderationsassistenten {EINST.assistent_name}.")
    except Exception as e:  # noqa: BLE001
        coach.assistent.halten_abbrechen()
        raise HTTPException(502, f"Transkription fehlgeschlagen ({fehlertext(e)}).") from e
    nutzung_loggen({"art": "text", "modell": EINST.text_modell, "sekunden_audio": round(sekunden, 1), "knopf": "halten"})
    from .assistent import frage_aus

    frage = frage_aus((getattr(antwort, "text", "") or "").strip())
    if len(frage.split()) < 2:
        coach.assistent.halten_abbrechen()
        await coach.melden()
        return {"ok": False, "frage": frage, "grund": "Nichts verstanden – bitte noch einmal halten und fragen."}
    if coach.knopfdruck:
        try:
            knopfdruck.reservieren(coach, "frage")
        except KnopfFehler as e:
            raise HTTPException(409, str(e)) from e
        hintergrund(knopfdruck.ausfuehren(coach, "frage", frage, _an_alle))
    else:
        coach.assistent.frage_beantworten(frage, "taste")
    return {"ok": True, "frage": frage}
