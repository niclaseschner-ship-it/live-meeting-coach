"""Startseite (Ticket #1, Lastenheft Abschnitt 2/3/6): Richtwerte, Pflichtangaben, Moduswahl.

Eigenes Modul mit APIRouter, damit sich parallele Tickets in server.py nicht in die Quere kommen.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .config import EINST

router = APIRouter()

MODI = ("live", "knopfdruck")


@router.get("/api/start")
async def start_daten() -> dict:
    """Für Startseite, Impressum und Datenschutz: Kostenrichtwerte und Pflichtangaben.

    Leere Angaben kommen als None – die Seiten zeigen dann „[wird ergänzt]“.
    """
    return {
        "richtwert_live_eur": EINST.richtwert_live_eur,
        "richtwert_knopfdruck_eur": EINST.richtwert_knopfdruck_eur,
        "paypal_aktiv": bool(EINST.paypal_me),
        "impressum_name": EINST.impressum_name or None,
        "impressum_anschrift": EINST.impressum_anschrift or None,
        "impressum_mail": EINST.impressum_mail or None,
    }


@router.post("/api/modus")
async def modus_setzen(daten: dict) -> dict:
    """Modus für das nächste Meeting festlegen (Startseite). Während ein Meeting läuft, bleibt er fest."""
    modus = daten.get("modus")
    if modus not in MODI:
        raise HTTPException(400, "Unbekannter Modus.")
    from .server import coach  # spät importiert: server.py bindet diesen Router ein, ein Import oben wäre ein Kreis

    if coach.hoerstrom is not None:
        raise HTTPException(409, "Während des Meetings nicht wechselbar.")
    coach.modus = modus
    await coach.melden()
    return {"ok": True, "modus": modus}
