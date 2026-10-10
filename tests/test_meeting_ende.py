"""Ticket #12: Ein Meeting zählt beim Worker (KundenZaehler) erst ab dem echten Start (`/api/start` →
`/intern/meeting-start`), nicht schon beim Ansehen der Startseite. Aktiv beendet (`/api/abschluss/fertig` →
`/intern/meeting-ende`) gibt den Platz sofort frei, stoppt den Container und löscht das Meeting-Cookie.

Der eigentliche Rückruf zum Worker (`coach/api_abschluss.worker_melden`, Muster wie `coach/ablage_r2.py`) wird
hier am Netz gemockt (`urllib.request.urlopen`) geprüft; die Worker-seitige Zähl- und Stopp-Logik hat ihre
eigenen Tests in `cloudflare/src/zaehler.test.ts`.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import time

import pytest
from fastapi.testclient import TestClient

# Isolation (vgl. tests/test_start.py, tests/test_server.py, tests/test_basis.py, tests/test_knopfdruck.py):
# ohne das hier ist /api/start seit #60 ohne Schlüssel 503 – dieser Datei darf das nicht davon abhängen, dass ein
# anderes Testmodul LMC_OFFLINE schon vorher gesetzt hat.
os.environ.setdefault("LMC_OFFLINE", "1")

from coach import api_abschluss, server  # noqa: E402
from coach.anbieter import wahl_fuer  # noqa: E402
from coach.config import EINST  # noqa: E402
from coach.pipeline import Coach  # noqa: E402
from coach.server import app  # noqa: E402

_GEHEIMNIS = "geheim-test-meeting-ende"
_WORKER_URL = "https://nestor.example.workers.dev"


@pytest.fixture(autouse=True)
def start_mit_bereitem_handy(request, monkeypatch):
    if not request.node.name.startswith("test_start_"):
        return
    handy = object()
    monkeypatch.setattr(server, "audio", {"ws": handy, "quelle": "handy", "letzt": time.monotonic()})
    monkeypatch.setattr(server, "lautsprecher", handy)
    monkeypatch.setattr(server, "verbindungen", {handy})
    monkeypatch.setattr(server, "geraet", {handy: "handy"})


@pytest.fixture
def cloud_betrieb():
    """Cloud-Betrieb mit Worker-Zugang (Muster wie tests/test_zugang.py, tests/test_eigener_schluessel.py)."""
    alt = (EINST.betrieb, EINST.worker_geheimnis, EINST.worker_url)
    object.__setattr__(EINST, "betrieb", "cloud")
    object.__setattr__(EINST, "worker_geheimnis", _GEHEIMNIS)
    object.__setattr__(EINST, "worker_url", _WORKER_URL)
    yield {"X-Nestor-Geheimnis": _GEHEIMNIS, "X-Nestor-Kunde": "testkunde"}
    object.__setattr__(EINST, "betrieb", alt[0])
    object.__setattr__(EINST, "worker_geheimnis", alt[1])
    object.__setattr__(EINST, "worker_url", alt[2])


@pytest.fixture
def archiv_pfad(tmp_path):
    alt = EINST.archiv
    object.__setattr__(EINST, "archiv", str(tmp_path))  # Einstellungen sind eingefroren
    yield tmp_path
    object.__setattr__(EINST, "archiv", alt)


def _abgelegtes_meeting() -> Coach:
    """Ein beendetes, endgültig abgelegtes Meeting – wie in tests/test_abschluss.py."""
    async def lauf():
        c = Coach()
        c.stufe_setzen("premium")
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
    c = _abgelegtes_meeting()
    monkeypatch.setattr(server.coach, "archiv", c.archiv)
    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setattr(server.coach, "wahl", wahl_fuer("basis"))  # #60: bestätigte Variante
    monkeypatch.setattr(server.coach, "kosten_stand", lambda: {"meeting": 0.10})
    return c


def _client() -> TestClient:
    return TestClient(app, client=("127.0.0.1", 5000))


# --- worker_melden(): der eigentliche Rückruf an den Worker, Netz gemockt --------------------------------

def test_worker_melden_ruft_die_richtige_url_mit_geheimnis_und_json_koerper(monkeypatch, cloud_betrieb):
    aufruf = {}

    class _FakeAntwort:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"erlaubt": True, "aktive": 1}).encode("utf-8")

    def _fake_urlopen(anfrage, timeout=None):
        aufruf["url"] = anfrage.full_url
        aufruf["geheimnis"] = anfrage.headers.get("X-nestor-geheimnis")  # urllib legt Kopfzeilen capitalize()-t ab
        aufruf["body"] = json.loads(anfrage.data)
        aufruf["timeout"] = timeout
        return _FakeAntwort()

    monkeypatch.setattr(api_abschluss.urllib.request, "urlopen", _fake_urlopen)
    ergebnis = api_abschluss.worker_melden("/intern/meeting-start", {"meetingId": "m1", "kunde": "acme"})
    assert ergebnis == {"erlaubt": True, "aktive": 1}
    assert aufruf["url"] == f"{_WORKER_URL}/intern/meeting-start"
    assert aufruf["geheimnis"] == _GEHEIMNIS
    assert aufruf["body"] == {"meetingId": "m1", "kunde": "acme"}
    assert aufruf["timeout"] == 10


def test_worker_melden_ohne_cloud_betrieb_tut_nichts():
    assert EINST.betrieb == "lokal"
    assert api_abschluss.worker_melden("/intern/meeting-start", {"meetingId": "m1", "kunde": "acme"}) is None


def test_worker_melden_bei_netzfehler_liefert_none_statt_zu_werfen(monkeypatch, cloud_betrieb):
    def _kaputt(anfrage, timeout=None):
        raise urllib.error.URLError("kein Netz")

    monkeypatch.setattr(api_abschluss.urllib.request, "urlopen", _kaputt)
    assert api_abschluss.worker_melden("/intern/meeting-ende", {"meetingId": "m1"}) is None


# --- /api/start meldet den echten Start (Ticket #12: erst hier zählt das Meeting) -------------------------

def test_start_meldet_dem_worker_meeting_id_und_kunde(monkeypatch, cloud_betrieb):
    aufgerufen = {}

    def _fake_melden(pfad, daten):
        aufgerufen["pfad"] = pfad
        aufgerufen["daten"] = daten
        return {"erlaubt": True, "aktive": 1}

    async def _fake_hoeren_starten():
        aufgerufen["gestartet"] = True

    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setattr(server.coach, "wahl", wahl_fuer("basis"))  # #60: bestätigte Variante
    monkeypatch.setattr(server.coach, "hoeren_starten", _fake_hoeren_starten)
    monkeypatch.setattr(api_abschluss, "worker_melden", _fake_melden)

    headers = {**cloud_betrieb, "X-Nestor-Meeting": "meeting-xyz", "X-Nestor-Kunde": "acme"}
    r = _client().post("/api/start", headers=headers)
    assert r.status_code == 200
    assert aufgerufen["pfad"] == "/intern/meeting-start"
    assert aufgerufen["daten"] == {"meetingId": "meeting-xyz", "kunde": "acme", "stufe": "basis", "modus": "live"}
    assert aufgerufen.get("gestartet") is True


def test_start_429_wenn_worker_hoechstzahl_meldet_und_startet_nicht(monkeypatch, cloud_betrieb):
    async def _nicht_aufrufen():
        raise AssertionError("hoeren_starten hätte bei abgewiesenem Start nicht laufen dürfen")

    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setattr(server.coach, "wahl", wahl_fuer("basis"))  # #60: bestätigte Variante
    monkeypatch.setattr(server.coach, "hoeren_starten", _nicht_aufrufen)
    monkeypatch.setattr(api_abschluss, "worker_melden", lambda pfad, daten: {"erlaubt": False, "aktive": 2})

    headers = {**cloud_betrieb, "X-Nestor-Meeting": "meeting-xyz", "X-Nestor-Kunde": "acme"}
    r = _client().post("/api/start", headers=headers)
    assert r.status_code == 429
    assert "öchstzahl" in r.json()["detail"]


def test_start_ohne_worker_antwort_laesst_im_zweifel_zu(monkeypatch, cloud_betrieb):
    """Netzstörung zwischen Container und Worker (worker_melden liefert None) blockiert den Start nicht."""
    aufgerufen = {}

    async def _fake_hoeren_starten():
        aufgerufen["gestartet"] = True

    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setattr(server.coach, "wahl", wahl_fuer("basis"))  # #60: bestätigte Variante
    monkeypatch.setattr(server.coach, "hoeren_starten", _fake_hoeren_starten)
    monkeypatch.setattr(api_abschluss, "worker_melden", lambda pfad, daten: None)

    headers = {**cloud_betrieb, "X-Nestor-Meeting": "meeting-xyz", "X-Nestor-Kunde": "acme"}
    r = _client().post("/api/start", headers=headers)
    assert r.status_code == 200
    assert aufgerufen.get("gestartet") is True


def test_start_lokal_meldet_dem_worker_nichts(monkeypatch):
    """Lokaler Betrieb (Standard): unverändertes Verhalten, keine Zähler-Meldung."""
    aufgerufen = {}

    def _fake_melden(pfad, daten):
        aufgerufen["aufgerufen"] = True
        return {"erlaubt": True}

    async def _fake_hoeren_starten():
        aufgerufen["gestartet"] = True

    assert EINST.betrieb == "lokal"
    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setattr(server.coach, "wahl", wahl_fuer("basis"))  # #60: bestätigte Variante
    monkeypatch.setattr(server.coach, "hoeren_starten", _fake_hoeren_starten)
    monkeypatch.setattr(api_abschluss, "worker_melden", _fake_melden)
    r = _client().post("/api/start")
    assert r.status_code == 200
    assert "aufgerufen" not in aufgerufen
    assert aufgerufen.get("gestartet") is True


# --- /api/abschluss/fertig meldet das Ende (Hintergrund) und löscht das Meeting-Cookie ---------------------

def test_fertig_meldet_dem_worker_das_ende_und_loescht_das_meeting_cookie(
    monkeypatch, cloud_betrieb, beendetes_meeting
):
    aufgerufen = {}

    def _fake_melden(pfad, daten):
        aufgerufen["pfad"] = pfad
        aufgerufen["daten"] = daten
        return {"ok": True}

    monkeypatch.setattr(api_abschluss, "worker_melden", _fake_melden)
    headers = {**cloud_betrieb, "X-Nestor-Meeting": "meeting-xyz", "X-Nestor-Kunde": "acme"}
    r = _client().post("/api/abschluss/fertig", headers=headers)
    assert r.status_code == 200 and r.json() == {"ok": True}
    # erst NACH der Antwort aufgerufen (BackgroundTasks) – hier schon sichtbar, weil TestClient sie vor der
    # Rückgabe von .post() abwartet (Starlette führt sie im selben ASGI-Zyklus aus)
    assert aufgerufen["pfad"] == "/intern/meeting-ende"
    # kostenUsd (Ticket #64): Tagesdeckel je Kunde im Worker – aus coach.kosten_stand() (hier von der Fixture
    # beendetes_meeting auf 0,10 $ gesetzt), vor dem Zurücksetzen des Meetings gelesen.
    assert aufgerufen["daten"] == {"meetingId": "meeting-xyz", "kunde": "acme", "kostenUsd": 0.1}
    gesetztes_cookie = r.headers.get("set-cookie", "")
    assert "nestor_meeting=" in gesetztes_cookie and "Max-Age=0" in gesetztes_cookie


def test_fertig_ohne_meeting_id_meldet_dem_worker_nichts(monkeypatch, cloud_betrieb, beendetes_meeting):
    """Ohne X-Nestor-Meeting (sollte über den Worker nie passieren) kein Rückruf, aber auch kein Absturz."""
    aufgerufen = {}
    monkeypatch.setattr(api_abschluss, "worker_melden", lambda pfad, daten: aufgerufen.setdefault("lief", True))
    r = _client().post("/api/abschluss/fertig", headers=cloud_betrieb)
    assert r.status_code == 200
    assert "lief" not in aufgerufen


def test_fertig_lokal_meldet_dem_worker_nichts_und_setzt_kein_cookie(monkeypatch, beendetes_meeting):
    aufgerufen = {}
    assert EINST.betrieb == "lokal"
    monkeypatch.setattr(api_abschluss, "worker_melden", lambda pfad, daten: aufgerufen.setdefault("lief", True))
    r = _client().post("/api/abschluss/fertig")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert "lief" not in aufgerufen
    assert "set-cookie" not in r.headers
