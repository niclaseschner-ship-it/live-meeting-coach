"""Startseite (Ticket #1, Lastenheft Abschnitt 2/3/6): Richtwerte, Pflichtangaben, Wahl der Stufe.

Seit Ticket #13 wählt die Startseite die Stufe – Nestor Basis (nur Mistral, EU) oder Nestor Premium (OpenAI) – und in
Basis den Schalter „Nur auf Knopfdruck“ (der frühere Modus). /api/modus bleibt für ältere Aufrufer erhalten.

Eigenes Modul mit APIRouter, damit sich parallele Tickets in server.py nicht in die Quere kommen.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from .config import EINST, STUFEN, mistral_schluessel, openai_schluessel

router = APIRouter()

MODI = ("live", "knopfdruck")


def _modus() -> str:
    from .server import coach  # spät importiert: server.py bindet diesen Router ein

    return coach.modus


@router.get("/api/start")
async def start_daten() -> dict:
    """Für Startseite, Impressum und Datenschutz: Kostenrichtwerte und Pflichtangaben.

    Leere Angaben kommen als None – die Seiten zeigen dann „[wird ergänzt]“.
    """
    return {
        "richtwert_live_eur": EINST.richtwert_live_eur,
        "richtwert_knopfdruck_eur": EINST.richtwert_knopfdruck_eur,
        "richtwert_basis_eur": EINST.richtwert_basis_eur,
        "richtwert_premium_eur": EINST.richtwert_premium_eur,
        "stufe": EINST.stufe,
        "modus": _modus(),
        # ob die Stufe überhaupt nutzbar ist (Schlüssel vorhanden) – nie der Schlüssel selbst
        # Ohne KI (LMC_OFFLINE=1, Tests) sind beide Stufen wählbar – es geht ohnehin kein Aufruf hinaus
        "basis_bereit": bool(mistral_schluessel()) or os.getenv("LMC_OFFLINE") == "1",
        "premium_bereit": bool(openai_schluessel()) or os.getenv("LMC_OFFLINE") == "1",
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
    if modus == "knopfdruck":  # „Nur auf Knopfdruck“ gibt es nur in Basis (Ticket #13)
        coach.stufe_setzen("basis", nur_knopfdruck=True)
    coach.modus = modus
    await coach.melden()
    return {"ok": True, "modus": modus}


@router.post("/api/stufe")
async def stufe_setzen(daten: dict) -> dict:
    """Stufe für das nächste Meeting: {"stufe": "basis"|"premium", "nur_knopfdruck": bool (nur Basis)}."""
    stufe = daten.get("stufe")
    if stufe not in STUFEN:
        raise HTTPException(400, "Unbekannte Stufe.")
    from .server import coach

    if coach.hoerstrom is not None:
        raise HTTPException(409, "Während des Meetings nicht wechselbar.")
    coach.stufe_setzen(stufe, nur_knopfdruck=bool(daten.get("nur_knopfdruck")))
    await coach.melden()
    return {"ok": True, "stufe": coach.stufe, "modus": coach.modus}
