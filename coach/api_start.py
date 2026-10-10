"""Startseite (Ticket #1, Lastenheft Abschnitt 2/3/6): Richtwerte, Pflichtangaben, Wahl der Stufe.

Seit Ticket #13 wählt die Startseite die Stufe – Nestor Basis (nur Mistral, EU) oder Nestor Premium (OpenAI) – und in
Basis den Schalter „Nur auf Knopfdruck“ (der frühere Modus). /api/modus bleibt für ältere Aufrufer erhalten, setzt aber
nie eine Stufe (Ticket #60). Es gibt keine Vorgabe-Stufe: bis zur Wahl meldet der Server `stufe: null`.

Eigenes Modul mit APIRouter, damit sich parallele Tickets in server.py nicht in die Quere kommen.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import anbieter
from .config import EINST

router = APIRouter()

MODI = ("live", "knopfdruck")


def _coach():
    from .server import coach  # spät importiert: server.py bindet diesen Router ein, ein Import oben wäre ein Kreis

    return coach


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
        "stufe": _coach().stufe,  # None, solange keine Variante bestätigt ist (Ticket #60)
        "modus": _coach().modus,
        # ob die Stufe überhaupt nutzbar ist (Schlüssel vorhanden) – nie der Schlüssel selbst
        # Ohne KI (LMC_OFFLINE=1, Tests) sind beide Stufen wählbar – es geht ohnehin kein Aufruf hinaus
        "basis_bereit": anbieter.bereit("basis"),
        "premium_bereit": anbieter.bereit("premium"),
        "paypal_aktiv": bool(EINST.paypal_me),
        "impressum_name": EINST.impressum_name or None,
        "impressum_anschrift": EINST.impressum_anschrift or None,
        "impressum_mail": EINST.impressum_mail or None,
    }


@router.post("/api/modus")
async def modus_setzen(daten: dict) -> dict:
    """Modus für das nächste Meeting festlegen. Während ein Meeting läuft, bleibt er fest. Die Stufe ändert er nie
    (Ticket #60): „Nur auf Knopfdruck“ gibt es nur in einer bestätigten Basis-Wahl (Ticket #13)."""
    modus = daten.get("modus")
    if modus not in MODI:
        raise HTTPException(400, "Unbekannter Modus.")
    coach = _coach()
    if coach.wahl_gesperrt:
        raise HTTPException(409, "Während des Meetings nicht wechselbar.")
    if modus == "knopfdruck" and coach.stufe != "basis":
        raise HTTPException(409, "„Nur auf Knopfdruck“ gibt es nur in Nestor Basis – bitte zuerst Basis wählen.")
    if coach.wahl is not None:
        coach.stufe_setzen(coach.stufe, nur_knopfdruck=modus == "knopfdruck")
    else:
        coach.modus = modus
    await coach.melden()
    return {"ok": True, "modus": modus}


@router.post("/api/stufe")
async def stufe_setzen(daten: dict) -> dict:
    """Stufe für das nächste Meeting: {"stufe": "basis"|"premium", "nur_knopfdruck": bool (nur Basis)}."""
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
        coach.stufe_setzen(stufe, nur_knopfdruck=bool(daten.get("nur_knopfdruck")))
    except WahlGesperrt as e:
        raise HTTPException(409, str(e)) from e
    except anbieter.AnbieterFehler as e:
        raise HTTPException(503, str(e)) from e
    await coach.melden()
    return {"ok": True, "stufe": coach.stufe, "modus": coach.modus}
