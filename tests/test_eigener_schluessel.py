"""Eigener OpenAI-Schlüssel als Angebot (eigener Schlüssel): Startseiten-Flow, Abschluss, Löschen im
Cloud-Betrieb und die Zusicherung, dass der Schlüssel nirgends (Bericht, Paket, Spende, Log) auftaucht.

Lastenheft: Abschnitte 2, 4.5, 5, 6. Baut auf dem vorhandenen Weg auf (coach/config.py: schluessel_speichern,
schluessel_info; POST /api/schluessel in coach/server.py) – hier wird nur das Neue getestet.
"""

from __future__ import annotations

import asyncio
import json

import openai
import pytest
from fastapi.testclient import TestClient

from coach import config
from coach.abschluss import OrdnerAblage, paket, spenden_dateien
from coach.config import EINST
from coach.pipeline import Coach
from coach.server import app

# Sieht wie ein echter Schlüssel aus (besteht die Formatprüfung in server.py), ist aber nur ein Testwert –
# nie an OpenAI geschickt, weil der Prüfweg in jedem Test gemockt ist.
_TEST_SCHLUESSEL = "sk-test-eigener-schluessel-998877"


def _lokal() -> TestClient:
    return TestClient(app, client=("127.0.0.1", 5000))


@pytest.fixture
def archiv_pfad(tmp_path):
    alt = EINST.archiv
    object.__setattr__(EINST, "archiv", str(tmp_path))  # Einstellungen sind eingefroren
    yield tmp_path
    object.__setattr__(EINST, "archiv", alt)


def _abgelegtes_meeting() -> Coach:
    """Ein beendetes, endgültig abgelegtes Meeting – wie in test_abschluss.py."""
    async def lauf():
        c = Coach()
        c._client = None
        c.archiv_aktiv = True
        c.einrichten({"titel": "Team Runde", "agenda": [{"titel": "Start", "minuten": 5}]})
        await c.hoeren_starten()
        await c.hoeren_zufuehren(bytes(24000 * 2))  # 1 s Stille
        await c.hoeren_beenden()
        c.archiv.schreiben(endgueltig=True)
        return c
    return asyncio.run(lauf())


@pytest.fixture
def beendetes_meeting(monkeypatch, archiv_pfad):
    """server.coach auf ein beendetes, abgelegtes Meeting setzen (ohne den echten Server laufen zu lassen)."""
    from coach import server

    c = _abgelegtes_meeting()
    monkeypatch.setattr(server.coach, "archiv", c.archiv)
    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setattr(server.coach, "kosten_stand", lambda: {"meeting": 0.80})
    return c


@pytest.fixture
def eigener_schluessel():
    """Trägt für den Test einen Dashboard-Schlüssel ein (ohne echten OpenAI-Aufruf) und räumt danach auf –
    unabhängig davon, was vorher in der Datei stand (frischer Zustand pro Test, s. conftest.py)."""
    config.schluessel_speichern(_TEST_SCHLUESSEL)
    try:
        yield _TEST_SCHLUESSEL
    finally:
        config.schluessel_speichern(None)


_CLOUD_GEHEIMNIS = "geheim-test-fuer-eigener-schluessel"


@pytest.fixture
def cloud_betrieb():
    """Cloud-Betrieb mit Worker-Geheimnis (wie test_zugang.py) – ohne passende Kopfzeile ist in der Cloud alles
    403, auch die sonst offenen Wege; darum braucht jede Anfrage in diesen Tests die Kopfzeile."""
    alt_betrieb, alt_geheimnis = EINST.betrieb, EINST.worker_geheimnis
    object.__setattr__(EINST, "betrieb", "cloud")
    object.__setattr__(EINST, "worker_geheimnis", _CLOUD_GEHEIMNIS)
    yield {"X-Nestor-Geheimnis": _CLOUD_GEHEIMNIS}
    object.__setattr__(EINST, "betrieb", alt_betrieb)
    object.__setattr__(EINST, "worker_geheimnis", alt_geheimnis)


# --- Startseiten-Flow: /api/schluessel mit gemocktem Prüfweg, kein echter OpenAI-Aufruf -----------------------

def test_schluessel_endpunkt_speichert_nach_gemocktem_pruefweg_ohne_netzaufruf(monkeypatch, caplog):
    from coach import server

    monkeypatch.setattr(server.coach, "hoerstrom", None)
    aufgerufen = {}

    class _FakeModels:
        async def list(self):
            aufgerufen["geprueft"] = True  # steht hier für den (gemockten) Aufruf bei OpenAI

    class _FakeClient:
        def __init__(self, **kwargs):
            aufgerufen["kwargs"] = kwargs
            self.models = _FakeModels()

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)
    try:
        with caplog.at_level("DEBUG"):
            r = _lokal().post("/api/schluessel", json={"schluessel": _TEST_SCHLUESSEL})
        assert r.status_code == 200
        d = r.json()
        assert d["vorhanden"] is True
        assert d["quelle"] == "dashboard"
        assert d["ende"] == _TEST_SCHLUESSEL[-4:]
        assert aufgerufen.get("geprueft") is True  # der Prüfweg lief, aber gemockt – kein echtes Netz
        assert _TEST_SCHLUESSEL not in json.dumps(d)  # der Server gibt den Schlüssel nie zurück
        assert _TEST_SCHLUESSEL not in caplog.text  # und protokolliert ihn auch nicht
    finally:
        config.schluessel_speichern(None)


def test_startseite_zeigt_die_aufklappbare_schluessel_zeile():
    lokal = _lokal()
    text = lokal.get("/").text
    assert "Eigenen OpenAI-Schlüssel verwenden" in text
    assert 'id="sk-eingabe"' in text and 'id="sk-pruefen"' in text


# --- Abschluss: mit/ohne eigenen Schlüssel ---------------------------------------------------------------------

def test_abschluss_ohne_eigenen_schluessel_zeigt_stufen_wie_bisher(beendetes_meeting):
    alt = EINST.paypal_me
    object.__setattr__(EINST, "paypal_me", "niclaseschner")
    try:
        z = _lokal().get("/api/abschluss").json()
        assert z["eigener_schluessel"] is False
        assert [s["betrag"] for s in z["stufen"]] == [2, 3, 6]
        assert z["paypal"][0]["link"] == "https://paypal.me/niclaseschner/2EUR"
        assert z["paypal_allgemein"] == "https://paypal.me/niclaseschner"
    finally:
        object.__setattr__(EINST, "paypal_me", alt)


def test_abschluss_mit_eigenem_schluessel_meldet_es_und_versteckt_stufen(beendetes_meeting, eigener_schluessel):
    alt = EINST.paypal_me
    object.__setattr__(EINST, "paypal_me", "niclaseschner")
    try:
        z = _lokal().get("/api/abschluss").json()
        assert z["eigener_schluessel"] is True
        assert z["paypal"] is None  # kein Kostenausgleich-Block mit Stufen
        assert z["paypal_allgemein"] == "https://paypal.me/niclaseschner"  # nur der allgemeine Link, ohne Betrag
        assert z["kosten_eur"] >= 0  # fließt in den Satz „… liefen über Ihren eigenen Schlüssel“ (Frontend)
    finally:
        object.__setattr__(EINST, "paypal_me", alt)


def test_abschluss_mit_eigenem_schluessel_ohne_paypal_me_zeigt_keine_unterstuetzung(beendetes_meeting, eigener_schluessel):
    alt = EINST.paypal_me
    object.__setattr__(EINST, "paypal_me", "")
    try:
        z = _lokal().get("/api/abschluss").json()
        assert z["eigener_schluessel"] is True
        assert z["paypal"] is None and z["paypal_allgemein"] is None
    finally:
        object.__setattr__(EINST, "paypal_me", alt)


# --- Löschen am Ende: nur im Cloud-Betrieb ----------------------------------------------------------------------

def test_fertig_entfernt_dashboard_schluessel_nur_im_cloud_betrieb(beendetes_meeting, eigener_schluessel, cloud_betrieb):
    from coach import server

    assert config.schluessel_info()["quelle"] == "dashboard"
    r = _lokal().post("/api/abschluss/fertig", headers=cloud_betrieb)
    assert r.status_code == 200
    assert config.schluessel_info()["quelle"] != "dashboard"  # entfernt – galt nur für dieses eine Meeting
    assert server.coach._client is None  # client_neu() nach dem Entfernen neu aufgesetzt


def test_fertig_behaelt_dashboard_schluessel_im_lokalen_betrieb(beendetes_meeting, eigener_schluessel):
    assert EINST.betrieb == "lokal"
    r = _lokal().post("/api/abschluss/fertig")
    assert r.status_code == 200
    assert config.schluessel_info()["quelle"] == "dashboard"  # lokal bleibt er wie heute gespeichert


def test_fertig_ohne_eigenen_schluessel_aendert_nichts_am_schluessel_cloud(beendetes_meeting, cloud_betrieb):
    assert config.schluessel_info()["quelle"] != "dashboard"
    r = _lokal().post("/api/abschluss/fertig", headers=cloud_betrieb)
    assert r.status_code == 200
    assert config.schluessel_info()["quelle"] != "dashboard"


# --- Der Schlüssel darf nie in Bericht, Paket, Spende oder Log auftauchen ---------------------------------------

def test_schluessel_taucht_nicht_in_bericht_paket_spende_oder_log_auf(archiv_pfad, eigener_schluessel, caplog):
    with caplog.at_level("DEBUG"):
        c = _abgelegtes_meeting()
        bericht_text = (c.archiv.ordner / "bericht.json").read_text(encoding="utf-8")
        assert _TEST_SCHLUESSEL not in bericht_text

        daten = paket(c.archiv.ordner, mit_aufnahme=False)
        assert _TEST_SCHLUESSEL.encode("utf-8") not in daten

        dateien = spenden_dateien(c.archiv.ordner, "Testfeedback", mit_aufnahme=False)
        assert all(_TEST_SCHLUESSEL.encode("utf-8") not in inhalt for inhalt in dateien.values())

    assert _TEST_SCHLUESSEL not in caplog.text


def test_schluessel_info_gibt_nie_den_rohen_schluessel_zurueck(eigener_schluessel):
    info = config.schluessel_info()
    assert info["quelle"] == "dashboard"
    assert _TEST_SCHLUESSEL not in json.dumps(info)
    assert info["ende"] == _TEST_SCHLUESSEL[-4:]
