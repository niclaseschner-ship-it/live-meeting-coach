"""Endpunkte für die Agenda per Prompt (Lastenheft 4.1): Vorschlag aus Text, Vorschlag aus Sprache."""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import transkription
from .agenda_prompt import agenda_vorschlagen
from .config import EINST

router = APIRouter()


def _bereit():
    """Der laufende Coach – erst hier importiert, sonst entsteht ein Kreis mit server.py."""
    from .server import coach

    if coach.hoerstrom is not None:
        raise HTTPException(409, "Während des Meetings nicht möglich.")
    if coach._client is None:
        raise HTTPException(409, "Ohne eingerichtete KI-Verbindung nicht möglich.")
    return coach


def _fehler(e: Exception) -> HTTPException:
    # Nur der Typ, nicht die Meldung – die kann Kennungen der API enthalten (wie coach/pipeline.py:fehlertext)
    return HTTPException(502, f"KI nicht erreichbar ({type(e).__name__}).")


@router.post("/api/agenda/vorschlag")
async def agenda_vorschlag(daten: dict):
    coach = _bereit()
    eingabe = str(daten.get("eingabe", "")).strip()
    if not eingabe:
        raise HTTPException(400, "Eingabe fehlt.")
    try:
        return await agenda_vorschlagen(coach._client, coach.wahl.analyse_modell, eingabe,
                                       daten.get("bisher"), daten.get("verlauf"))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise _fehler(e) from e


@router.post("/api/agenda/sprache")
async def agenda_sprache(bisher: str = Form("null"), verlauf: str = Form("[]"), datei: UploadFile = File(...)):
    coach = _bereit()
    try:
        bisher_dict = json.loads(bisher)
    except json.JSONDecodeError:
        bisher_dict = None
    try:
        dialog = json.loads(verlauf)
    except json.JSONDecodeError:
        dialog = []
    wav = await datei.read()
    try:
        eingabe = await transkription.text(coach._client, coach.wahl.text_modell, wav, EINST.sprache, "")
    except Exception as e:  # noqa: BLE001
        raise _fehler(e) from e
    if not eingabe.strip():
        raise HTTPException(400, "Darin war nichts zu verstehen.")
    try:
        ergebnis = await agenda_vorschlagen(coach._client, coach.wahl.analyse_modell, eingabe, bisher_dict, dialog)
    except Exception as e:  # noqa: BLE001
        raise _fehler(e) from e
    return {**ergebnis, "eingabe": eingabe}
