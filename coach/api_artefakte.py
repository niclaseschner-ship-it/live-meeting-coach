"""Artefakt-Endpunkte (Ticket #26): Lücken per Klick schließen, Einträge bearbeiten, Nestors Rückfrage beantworten.

    POST /api/artefakte/bearbeiten  {"id", "was"?, "wer"?, "bis"?, "status"?, "reaktion"?, "typ"?}
    POST /api/artefakte/neu         {"typ", "was", "wer"?, "bis"?}
    POST /api/artefakte/loeschen    {"id"}
    POST /api/artefakte/ablehnen    {"id"}                – „nicht nötig“: Nestor fragt dazu nie wieder
    POST /api/artefakte/antwort     {"antwort": "ja"|"nein"} – Knöpfe der Fünf-Minuten-Frage im Nestor-Feld

Was die Runde hier setzt, gilt als bestätigt und wird von der Erkennung nicht überschrieben. Der `coach` ist die eine
laufende Instanz aus server.py, spät importiert (sonst Ringimport beim Hochfahren).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .artefakte import TYPEN

router = APIRouter()


def _nr(daten: dict) -> int:
    try:
        return int(daten.get("id"))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "Ungültiger Eintrag.") from e


@router.post("/api/artefakte/bearbeiten")
async def bearbeiten(daten: dict) -> dict:
    from .server import coach

    a = coach.artefakte.bearbeiten(_nr(daten), {k: daten[k] for k in ("was", "wer", "bis", "status", "reaktion", "typ",
                                                                      "hoch") if k in daten})
    if a is None:
        raise HTTPException(404, "Eintrag nicht gefunden.")
    coach.protokoll.append({"zeit": coach.meeting.jetzt(), "art": "artefakt_eingetragen", "id": a.id, "durch": "hand"})
    await coach.melden()
    return {"ok": True, "artefakt": a.bild()}


@router.post("/api/artefakte/neu")
async def neu(daten: dict) -> dict:
    from .server import coach

    if daten.get("typ") not in TYPEN or not str(daten.get("was") or "").strip():
        raise HTTPException(400, "Typ und Text fehlen.")
    a, _ = coach.artefakte.eintragen({k: daten.get(k) for k in ("typ", "was", "wer", "bis", "status", "reaktion")},
                                     herkunft="hand")
    if a is None:
        raise HTTPException(400, "Eintrag nicht möglich.")
    await coach.melden()
    return {"ok": True, "artefakt": a.bild()}


@router.post("/api/artefakte/loeschen")
async def loeschen(daten: dict) -> dict:
    from .server import coach

    ok = coach.artefakte.loeschen(_nr(daten))
    await coach.melden()
    return {"ok": ok}


@router.post("/api/artefakte/ablehnen")
async def ablehnen(daten: dict) -> dict:
    from .server import coach

    ok = coach.artefakte.ablehnen(_nr(daten))
    await coach.melden()
    return {"ok": ok}


@router.post("/api/artefakte/antwort")
async def antwort(daten: dict) -> dict:
    """Knopf an Nestors Rückfrage: Ja = zusammenfassen (im Hintergrund, gesprochen und als Karte), Nein = still."""
    from .pipeline import hintergrund
    from .server import coach

    r = coach.artefakte.rueckfrage
    if r is None:
        return {"ok": False}
    if daten.get("antwort") == "ja" and r.art == "fuenf_minuten":
        coach.artefakte.verlauf.append({"zeit": round(coach.meeting.jetzt(), 1), "art": "fuenf_minuten_ja",
                                        "durch": "knopf"})
        hintergrund(coach.artefakte.zusammenfassen())
    else:
        coach.artefakte.verlauf.append({"zeit": round(coach.meeting.jetzt(), 1), "art": f"{r.art}_nein",
                                        "durch": "knopf"})
        coach.artefakte.rueckfrage = None
    await coach.melden()
    return {"ok": True}
