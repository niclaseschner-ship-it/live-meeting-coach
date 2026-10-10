"""Startseite (Ticket #1, Lastenheft Abschnitt 2/3/6): Richtwerte, Pflichtangaben, Wahl der Stufe.

Seit Ticket #13 wählt die Startseite die Stufe – Nestor Basis (nur Mistral, EU) oder Nestor Premium (OpenAI).
Es gibt keine Vorgabe-Stufe: bis zur Wahl meldet der Server `stufe: null`.

Eigenes Modul mit APIRouter, damit sich parallele Tickets in server.py nicht in die Quere kommen.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import anbieter
from .config import EINST

router = APIRouter()


def _coach():
    from .server import coach  # spät importiert: server.py bindet diesen Router ein, ein Import oben wäre ein Kreis

    return coach


@router.get("/api/start")
async def start_daten() -> dict:
    """Für Startseite, Impressum und Datenschutz: Kostenrichtwerte und Pflichtangaben.

    Leere Angaben kommen als None – die Seiten zeigen dann „[wird ergänzt]“.
    """
    return {
        "richtwert_basis_eur": EINST.richtwert_basis_eur,
        "richtwert_premium_eur": EINST.richtwert_premium_eur,
        "stufe": _coach().stufe,  # None, solange keine Variante bestätigt ist (Ticket #60)
        # ob die Stufe überhaupt nutzbar ist (Schlüssel vorhanden) – nie der Schlüssel selbst
        # Ohne KI (LMC_OFFLINE=1, Tests) sind beide Stufen wählbar – es geht ohnehin kein Aufruf hinaus
        "basis_bereit": anbieter.bereit("basis"),
        "premium_bereit": anbieter.bereit("premium"),
        "paypal_aktiv": bool(EINST.paypal_me),
        "impressum_name": EINST.impressum_name or None,
        "impressum_anschrift": EINST.impressum_anschrift or None,
        "impressum_mail": EINST.impressum_mail or None,
    }


@router.post("/api/stufe")
async def stufe_setzen(daten: dict) -> dict:
    """Stufe für das nächste Meeting: {"stufe": "basis"|"premium"}."""
    stufe = daten.get("stufe")
    if stufe not in anbieter.STUFEN:
        raise HTTPException(400, "Unbekannte Stufe.")
    from .pipeline import WahlGesperrt

    coach = _coach()
    if coach.wahl_gesperrt:
        raise HTTPException(409, "Während des Meetings nicht wechselbar.")
    if not anbieter.bereit(stufe):
        raise HTTPException(503, "Die gewählte Variante ist auf dem Server nicht eingerichtet; es wird nicht auf eine andere gewechselt.")
    try:
        coach.stufe_setzen(stufe)
    except WahlGesperrt as e:
        raise HTTPException(409, str(e)) from e
    except anbieter.AnbieterFehler as e:
        raise HTTPException(503, str(e)) from e
    await coach.melden()
    return {"ok": True, "stufe": coach.stufe}
