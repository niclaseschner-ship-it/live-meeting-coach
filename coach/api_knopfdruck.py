"""Knopf-Endpunkte für den Modus „Auf Knopfdruck“ (Ticket #6, Lastenheft 4.2).

    POST /api/knopf/<art>       art: stand | regeln | protokoll | bild | frage ({"text"})
    POST /api/knopf/verwerfen   {"minuten": 5 | null}
    GET  /api/knopf/protokoll.md

Ein Knopf antwortet sofort; Fortschritt und Ergebnis kommen über die WebSocket (coach/knopfdruck.py). Je Art eine
eigene Route statt /api/knopf/{art}: so findet test_dashboard_endpunkte_existieren jeden Aufruf aus app.js.
Der `coach` ist die eine laufende Instanz aus server.py, spät importiert (sonst Ringimport beim Hochfahren).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
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

        frage = str((daten or {}).get("text") or "").strip()[:500]
        if art == "frage" and not frage:
            raise HTTPException(400, "Keine Frage.")
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
