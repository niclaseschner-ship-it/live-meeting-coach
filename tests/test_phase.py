"""Ticket #66: Der Server führt die Phase explizit im Schnappschuss – abgeleitet, kein zweiter Zustand."""

from pathlib import Path

from coach.pipeline import Coach

ROOT = Path(__file__).resolve().parents[1]


def test_phase_folgt_dem_meeting():
    c = Coach()
    assert c.schnappschuss()["phase"] == "vorbereitung"
    c.meeting.starten()
    assert c.schnappschuss()["phase"] == "live"
    c.meeting.beenden()
    assert c.schnappschuss()["phase"] == "abschluss"
    c.einrichten({"titel": "Neu", "agenda": []})  # neues Meeting angelegt → wieder Vorbereitung
    assert c.schnappschuss()["phase"] == "vorbereitung"


def test_wiedergabe_zaehlt_als_live():
    c = Coach()
    c.simulation_laeuft = True
    assert c.phase() == "live"


def test_beide_seiten_schalten_ueber_phase_js():
    """Keine eigene Phasen-Herleitung mehr in app.js/handy.js – beide nutzen phaseAnzeigen()."""
    for skript, seite in (("app.js", "index.html"), ("handy.js", "handy.html")):
        js = (ROOT / "static" / skript).read_text(encoding="utf-8")
        html = (ROOT / "static" / seite).read_text(encoding="utf-8")
        assert "phaseAnzeigen(" in js, skript
        assert "segmente.length > 0 || z.zeit > 0" not in js, skript
        assert html.index("/static/phase.js") < html.index(f"/static/{skript}"), seite
