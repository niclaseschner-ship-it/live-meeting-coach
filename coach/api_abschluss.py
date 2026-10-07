"""Abschluss-Endpunkte: Paket, Unterstützung (PayPal/QR), Datenspende und Feedback.

Eigenes Modul mit APIRouter (s. Hinweis im Ticket), in coach/server.py mit einer Zeile eingebunden. Der `coach`
dort ist die eine laufende Instanz; er wird erst bei Gebrauch importiert, damit es beim Hochfahren keinen
Ringimport zwischen server.py und diesem Modul gibt.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from .abschluss import OrdnerAblage, paket, spenden_dateien, stufen
from .ablage_r2 import AblageFehler, R2Ablage
from .config import EINST

router = APIRouter()
_ablage = R2Ablage() if EINST.betrieb == "cloud" else OrdnerAblage()


async def _ablegen(dateien: dict[str, bytes]) -> None:
    """Im Thread: der R2-Weg lädt über das Netz hoch und soll die Ereignisschleife nicht aufhalten."""
    try:
        await asyncio.to_thread(_ablage.ablegen, _kurz_id(), dateien)
    except AblageFehler as e:
        raise HTTPException(502, "Die Spende ließ sich gerade nicht ablegen – bitte später noch einmal.") from e


def _kurz_id() -> str:
    return uuid.uuid4().hex[:8]


def _nach_ende():
    """Der gemeinsame Coach, nur wenn ein Meeting beendet (und damit abgelegt) ist – sonst 409."""
    from .server import coach

    if coach.hoerstrom is not None or coach.archiv is None:
        raise HTTPException(409, "Kein beendetes Meeting vorhanden.")
    return coach


@router.get("/api/abschluss")
async def abschluss():
    coach = _nach_ende()
    kosten_usd = coach.kosten_stand()["meeting"]
    liste = stufen(kosten_usd)
    name = EINST.paypal_me or None
    return {
        "dauer_sekunden": round(coach.meeting.jetzt(), 1),
        "kosten_usd": round(kosten_usd, 4),
        "kosten_eur": round(kosten_usd * EINST.eur_je_usd, 2),
        "stufen": liste,
        "paypal": ([{**s, "link": f"https://paypal.me/{name}/{s['betrag']}EUR"} for s in liste]
                   if name else None),
        "ablage_fertig": coach.archiv.fertig,
    }


@router.get("/api/abschluss/qr.svg")
async def abschluss_qr(betrag: float = Query(...)):
    _nach_ende()
    if not EINST.paypal_me:
        raise HTTPException(404, "Keine PayPal-Adresse hinterlegt.")
    import segno

    link = f"https://paypal.me/{EINST.paypal_me}/{betrag:g}EUR"
    svg = segno.make(link, error="m").svg_inline(scale=5, dark="#1E1B4B", border=2)
    from fastapi.responses import Response

    return Response(svg, media_type="image/svg+xml",
                     headers={"Cache-Control": "no-store", "Content-Security-Policy": "script-src 'none'"})


@router.get("/api/abschluss/paket.zip")
async def abschluss_paket(aufnahme: int = Query(0)):
    coach = _nach_ende()
    try:
        daten = paket(coach.archiv.ordner, bool(aufnahme))
    except OSError as e:
        raise HTTPException(404, "Ablage noch nicht da – bitte kurz warten.") from e
    from fastapi.responses import Response

    return Response(daten, media_type="application/zip",
                     headers={"Content-Disposition": 'attachment; filename="nestor-paket.zip"'})


@router.post("/api/abschluss/spende")
async def abschluss_spende(daten: dict):
    coach = _nach_ende()
    if daten.get("einverstanden") is not True:
        raise HTTPException(400, "Ohne das Häkchen „alle einverstanden“ keine Datenspende.")
    try:
        dateien = spenden_dateien(coach.archiv.ordner, str(daten.get("feedback") or ""), bool(daten.get("aufnahme")))
    except OSError as e:
        raise HTTPException(404, "Ablage noch nicht da – bitte kurz warten.") from e
    await _ablegen(dateien)
    return {"ok": True}


@router.post("/api/abschluss/feedback")
async def abschluss_feedback(daten: dict):
    _nach_ende()
    text = str(daten.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Kein Feedback-Text.")
    await _ablegen({"feedback.txt": text.encode("utf-8")})
    return {"ok": True}


@router.post("/api/abschluss/fertig")
async def abschluss_fertig():
    coach = _nach_ende()
    ordner = coach.archiv.ordner
    coach.einrichten({})  # auf ein leeres Meeting zurücksetzen (wie eine neue Einrichtung)
    coach.archiv = None
    if not EINST.ablage_behalten:
        import shutil

        shutil.rmtree(ordner, ignore_errors=True)
    await coach.melden()
    return {"ok": True}
