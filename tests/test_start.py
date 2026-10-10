"""Startseite, Richtwerte und Stufenwahl (Ticket #1, Lastenheft Abschnitt 2/3/6)."""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LMC_OFFLINE", "1")

from coach.config import EINST  # noqa: E402
from coach.server import app, coach  # noqa: E402


@pytest.fixture
def lokal():
    # TestClient meldet sich als „testclient“, nicht als 127.0.0.1 – ungekoppelt gar kein Zugang (test_zugang.py)
    return TestClient(app, client=("127.0.0.1", 5000))


def test_startseite_und_dashboard_getrennt(lokal):
    start = lokal.get("/")
    assert start.status_code == 200 and "Wie soll Nestor" in start.text
    meeting = lokal.get("/meeting")
    assert meeting.status_code == 200 and 'id="titel-anzeige"' in meeting.text
    assert lokal.get("/handy").status_code == 200  # unverändert


def test_startseite_und_meeting_bleiben_ohne_kopplung_verschlossen():
    fremd = TestClient(app)  # weder lokal noch gekoppelt
    assert fremd.get("/").status_code == 401
    assert fremd.get("/meeting").status_code == 401


def test_api_start_liefert_richtwerte_und_leere_pflichtangaben(lokal):
    r = lokal.get("/api/start")
    assert r.status_code == 200
    d = r.json()
    assert d["richtwert_basis_eur"] == EINST.richtwert_basis_eur
    assert d["richtwert_premium_eur"] == EINST.richtwert_premium_eur
    assert d["paypal_aktiv"] is False  # kein LMC_PAYPAL_ME gesetzt
    assert d["impressum_name"] is None and d["impressum_anschrift"] is None and d["impressum_mail"] is None


def test_api_start_kennt_keinen_modus_mehr(lokal):
    """Ticket #71: der Modus „Nur auf Knopfdruck“ ist vollständig ausgebaut – kein Modus-Feld, kein Schalter."""
    assert "modus" not in lokal.get("/api/start").json()
    try:
        coach.stufe_setzen("basis")
        assert "modus" not in lokal.get("/api/zustand").json()
        assert lokal.post("/api/modus", json={"modus": "knopfdruck"}).status_code == 404
    finally:
        coach.stufe_setzen("premium")
