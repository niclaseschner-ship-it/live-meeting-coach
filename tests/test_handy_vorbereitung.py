"""#53: Aktivierung am QR-Einstieg und aktuelle Bereitschaft vor Meetingstart."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from coach import server

ROOT = Path(__file__).resolve().parents[1]


def test_aktivierung_vor_meetingfunktionen_und_nicht_doppelt():
    html = (ROOT / "static/handy.html").read_text()
    assert html.index('id="mikro-karte"') < html.index('class="h-karte h-nestor"')
    assert html.count('id="btn-mikro"') == 1
    assert "Mikrofon und Ton aktivieren" in html
    js = (ROOT / "static/app.js").read_text()
    assert 'm.quelle !== "handy" ? "Am Handy Mikrofon aktivieren"' in js
    assert '"Warte auf Handy-Audio"' in js
    assert '"Am Handy Ton aktivieren"' in js


def test_vorbereitung_erhaelt_regelmaessige_zustandsmeldungen(monkeypatch):
    gesendet = []
    runden = 0
    async def schlafen(_):
        nonlocal runden
        runden += 1
        if runden > 1:
            raise asyncio.CancelledError
    async def senden():
        gesendet.append(True)
    monkeypatch.setattr(server, "coach", SimpleNamespace(meeting=SimpleNamespace(laeuft=False)))
    monkeypatch.setattr(server, "verbindungen", {object()})
    monkeypatch.setattr(server, "senden", senden)
    monkeypatch.setattr(server.asyncio, "sleep", schlafen)
    async def lauf():
        try:
            await server.taktgeber()
        except asyncio.CancelledError:
            pass
    asyncio.run(lauf())
    assert gesendet == [True]
