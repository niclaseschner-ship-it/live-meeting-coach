"""Knopf-Endpunkte (Ticket #6, Lastenheft 4.2; seit Ticket #13 in beiden Stufen gleich).

    POST /api/knopf/<art>       art: stand | regeln | ueberblick | protokoll | bild | frage ({"text"})
    GET  /api/knopf/protokoll.md
    POST /api/frage/halten      {"an": true|false}             – „Nestor fragen“ am Handy wird gehalten/losgelassen
    POST /api/frage/audio       WAV (24 kHz mono) im Körper     – die gehaltene Frage: transkribieren, dann antworten

Jeder Knopf ist ein Antwortbogen (Ticket #27, coach/assistent.py): Bestätigung, Karte im Verlauf, ein bis zwei
Sätze; während ein Bogen läuft, sind die Knöpfe gesperrt (409). Je Art eine eigene Route statt /api/knopf/{art}:
so findet test_dashboard_endpunkte_existieren jeden Aufruf aus app.js.
Der `coach` ist die eine laufende Instanz aus server.py, spät importiert (sonst Ringimport beim Hochfahren).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import knopfdruck
from .knopfdruck import ARTEN

router = APIRouter()


def _knopf(art: str):
    async def knopf(daten: dict | None = None) -> dict:
        from .server import coach

        from .assistent import BogenBelegt
        from .bogen import NAMEN as BOGEN_NAMEN

        frage = str((daten or {}).get("text") or "").strip()[:500]
        if art == "frage" and not frage:
            raise HTTPException(400, "Keine Frage.")
        if coach.hoerstrom is None or coach._client is None:
            raise HTTPException(409, "Es läuft kein Meeting." if coach.hoerstrom is None else "Kein KI-Schlüssel.")
        try:
            await coach.hoerstrom.text_abwarten()
        except TimeoutError as e:
            raise HTTPException(409, str(e)) from e
        if art == "frage":
            coach.assistent.frage_beantworten(frage, "getippt")
            return {"ok": True}
        ziel = knopfdruck.BOGEN[art]
        if (daten or {}).get("band"):  # Band-Knopf gedrückt: der Hinweis ist erledigt – auf allen Seiten weg
            jetzt = coach.meeting.jetzt()
            for h in coach.meeting.hinweise:
                if (h.aktion or {}).get("bogen") == art and jetzt - h.zeit < h.dauer:
                    h.dauer = max(0.0, jetzt - h.zeit)
        if ziel == "bild" and coach.bild_als_text:
            ziel = "ueberblick"  # Basis: kein Bildmodell
        try:
            coach.assistent.bogen_starten(ziel, BOGEN_NAMEN.get(ziel, ziel), "band" if (daten or {}).get("band")
                                          else "knopf", fokus="aktueller Agendapunkt" if
                                          art == "ueberblick" and (daten or {}).get("umfang", "aktuell") == "aktuell"
                                          else "gesamtes Meeting" if art == "ueberblick" else "")
        except BogenBelegt as e:
            raise HTTPException(409, str(e)) from e
        await coach.melden()
        return {"ok": True}

    knopf.__name__ = f"knopf_{art}"
    return knopf


for _art in ARTEN:
    router.add_api_route(f"/api/knopf/{_art}", _knopf(_art), methods=["POST"])


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
    (Stimme + Karte)."""
    from .config import EINST
    from .pipeline import fehlertext, nutzung_loggen
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
            model=coach.wahl.text_modell, file=("frage.wav", wav, "audio/wav"), language=EINST.sprache,
            prompt=f"Frage an den Moderationsassistenten {EINST.assistent_name}.")
    except Exception as e:  # noqa: BLE001
        coach.assistent.halten_abbrechen()
        raise HTTPException(502, f"Transkription fehlgeschlagen ({fehlertext(e)}).") from e
    nutzung_loggen({"art": "text", "modell": coach.wahl.text_modell, "sekunden_audio": round(sekunden, 1), "knopf": "halten"})
    from .assistent import frage_aus

    frage = frage_aus((getattr(antwort, "text", "") or "").strip())
    if len(frage.split()) < 2:
        coach.assistent.halten_abbrechen()
        await coach.melden()
        return {"ok": False, "frage": frage, "grund": "Nichts verstanden – bitte noch einmal halten und fragen."}
    coach.assistent.frage_beantworten(frage, "taste")
    return {"ok": True, "frage": frage}
