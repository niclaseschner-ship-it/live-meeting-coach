"""Ticket #82: Datenspende im Cloud-Betrieb, je Datei einzeln gestreamt statt als ein großer Multipart-Körper.

Befund aus dem Pilot vom 10.10.: der alte Weg baute EINEN Multipart-Körper für alle Dateien und schickte ihn
per `urllib` mit `timeout=30`; im Worker verdoppelte `formData()`/`arrayBuffer()` eine 45-MB-Aufnahme auf
90–135 MB, nahe der 128-MB-Isolate-Grenze. Jetzt: `PUT .../intern/spende/<name>/<datei>` je Datei, die Aufnahme
von der Platte gestreamt statt komplett in den Speicher gelesen, Timeout nach Größe gestaffelt, ein
abschließendes `POST .../abschluss` mit der Zusammenfassung. Scheitert eine Datei, laufen die übrigen weiter –
`SpendeErgebnis.vollstaendig` wird dann `False`, es fliegt keine Ausnahme.

Das Netz wird wie in tests/test_meeting_ende.py gemockt (`urllib.request.urlopen`), ohne echten Worker.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from coach.abschluss import SpendeDatei
from coach.ablage_r2 import AblageFehler, R2Ablage, _timeout_fuer
from coach.config import EINST

_GEHEIMNIS = "geheim-test-ablage-r2"
_WORKER_URL = "https://nestor.example.workers.dev"


@pytest.fixture
def worker_zugang():
    alt = (EINST.worker_url, EINST.worker_geheimnis)
    object.__setattr__(EINST, "worker_url", _WORKER_URL)
    object.__setattr__(EINST, "worker_geheimnis", _GEHEIMNIS)
    yield
    object.__setattr__(EINST, "worker_url", alt[0])
    object.__setattr__(EINST, "worker_geheimnis", alt[1])


class _FakeAntwort:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def _aufrufe_sammeln(monkeypatch, verhalten=None):
    """Ersetzt urllib.request.urlopen; `verhalten(anfrage)` kann eine Ausnahme werfen, um einen einzelnen Ruf
    scheitern zu lassen. Liefert die Liste der mitgeschnittenen Anfragen."""
    aufrufe: list = []

    def _fake_urlopen(anfrage, timeout=None):
        aufrufe.append(anfrage)
        anfrage._gelesene_laenge = len(anfrage.data.read()) if hasattr(anfrage.data, "read") else len(anfrage.data)
        anfrage._timeout = timeout
        if verhalten is not None:
            verhalten(anfrage)
        return _FakeAntwort()

    import coach.ablage_r2 as ablage_r2

    monkeypatch.setattr(ablage_r2.urllib.request, "urlopen", _fake_urlopen)
    return aufrufe


def test_timeout_wird_nach_dateigroesse_gestaffelt_und_oben_begrenzt():
    assert _timeout_fuer(0) == pytest.approx(20.0)
    assert _timeout_fuer(5 * 1024 * 1024) == pytest.approx(30.0)  # 20 + 2*5
    assert _timeout_fuer(290 * 1024 * 1024) == 300.0  # 20 + 2*290 = 600, auf 300 gekappt


def test_ohne_worker_zugang_kein_netz_sondern_ablagefehler():
    assert not EINST.worker_url or not EINST.worker_geheimnis or True  # Vorbedingung dieses Tests egal zum Stand
    alt = (EINST.worker_url, EINST.worker_geheimnis)
    object.__setattr__(EINST, "worker_url", "")
    object.__setattr__(EINST, "worker_geheimnis", "")
    try:
        with pytest.raises(AblageFehler):
            R2Ablage().ablegen("abc12345", [SpendeDatei("feedback.txt", inhalt=b"x")])
    finally:
        object.__setattr__(EINST, "worker_url", alt[0])
        object.__setattr__(EINST, "worker_geheimnis", alt[1])


def test_ohne_dateien_wird_kein_netzaufruf_gemacht(monkeypatch, worker_zugang):
    aufrufe = _aufrufe_sammeln(monkeypatch)
    ergebnis = R2Ablage().ablegen("abc12345", [])
    assert ergebnis.teile == []
    assert aufrufe == []


def test_jede_datei_geht_einzeln_per_put_mit_content_length_und_geheimnis_dann_ein_abschluss(monkeypatch, worker_zugang):
    aufrufe = _aufrufe_sammeln(monkeypatch)
    dateien = [
        SpendeDatei("transkript.md", inhalt=b"**[00:00] A:** Hallo\n"),
        SpendeDatei("feedback.txt", inhalt=b"Gut gemacht"),
    ]
    ergebnis = R2Ablage().ablegen("abc12345", dateien)

    assert len(aufrufe) == 3  # zwei PUTs + ein Abschluss-POST
    put1, put2, abschluss = aufrufe
    assert put1.full_url == f"{_WORKER_URL}/intern/spende/abc12345/transkript.md"
    assert put1.get_method() == "PUT"
    assert put1.headers.get("Content-length") == "21"
    assert put1.headers.get("X-nestor-geheimnis") == _GEHEIMNIS
    assert put1._gelesene_laenge == 21

    assert put2.full_url == f"{_WORKER_URL}/intern/spende/abc12345/feedback.txt"
    assert put2.headers.get("Content-length") == "11"

    assert abschluss.full_url == f"{_WORKER_URL}/intern/spende/abc12345/abschluss"
    assert abschluss.get_method() == "POST"
    koerper = json.loads(abschluss.data)
    assert koerper["ergebnisse"] == [
        {"datei": "transkript.md", "bytes": 21, "ok": True},
        {"datei": "feedback.txt", "bytes": 11, "ok": True},
    ]
    assert koerper["dauerMs"] >= 0

    assert ergebnis.vollstaendig is True
    assert [t.datei for t in ergebnis.teile] == ["transkript.md", "feedback.txt"]


def test_grosse_datei_wird_von_der_platte_gestreamt_nie_komplett_eingelesen(monkeypatch, worker_zugang, tmp_path):
    """Kernpunkt des Tickets: `urllib.Request.data` ist für die Aufnahme ein offenes Dateiobjekt, kein
    `bytes`-Block – `http.client` liest es blockweise (Standardverhalten für Objekte mit `.read()`), die
    Aufnahme wird also nie als Ganzes im Speicher gehalten."""
    aufnahme = tmp_path / "aufnahme.wav"
    inhalt = b"RIFF" + b"\0" * 4096
    aufnahme.write_bytes(inhalt)

    aufrufe = _aufrufe_sammeln(monkeypatch)
    datei = SpendeDatei("aufnahme.wav", pfad=aufnahme)
    ergebnis = R2Ablage().ablegen("abc12345", [datei])

    [put, _abschluss] = aufrufe
    assert hasattr(put.data, "read")  # Dateiobjekt, kein im Speicher gehaltener bytes-Block
    assert put.data.closed  # nach dem (simulierten) Versand wieder geschlossen
    assert put.headers.get("Content-length") == str(len(inhalt))
    assert put._gelesene_laenge == len(inhalt)
    assert ergebnis.teile[0].bytes == len(inhalt)
    assert ergebnis.vollstaendig is True


def test_scheitert_nur_die_aufnahme_bleiben_die_texte_ok_und_die_spende_gilt_als_teilweise(monkeypatch, worker_zugang):
    def _aufnahme_schlaegt_fehl(anfrage):
        if anfrage.full_url.endswith("/aufnahme.wav"):
            raise urllib.error.URLError("Zeitüberschreitung")

    aufrufe = _aufrufe_sammeln(monkeypatch, verhalten=_aufnahme_schlaegt_fehl)
    dateien = [
        SpendeDatei("transkript.md", inhalt=b"Text"),
        SpendeDatei("aufnahme.wav", inhalt=b"\0" * 10),  # bytes reichen hier, die Fehlerstelle ist der Netzruf
    ]
    ergebnis = R2Ablage().ablegen("abc12345", dateien)

    assert ergebnis.vollstaendig is False
    [text, aufnahme] = ergebnis.teile
    assert text.ok is True and text.bytes == 4
    assert aufnahme.ok is False and aufnahme.bytes == 10

    # Trotzdem genau ein Abschluss-Ruf, der beide Ergebnisse (auch das fehlgeschlagene) meldet.
    abschluss = aufrufe[-1]
    assert abschluss.full_url.endswith("/abschluss")
    koerper = json.loads(abschluss.data)
    assert koerper["ergebnisse"] == [
        {"datei": "transkript.md", "bytes": 4, "ok": True},
        {"datei": "aufnahme.wav", "bytes": 10, "ok": False},
    ]


def test_abschluss_meldung_scheitert_am_netz_ohne_die_ablage_selbst_scheitern_zu_lassen(monkeypatch, worker_zugang):
    def _abschluss_schlaegt_fehl(anfrage):
        if anfrage.full_url.endswith("/abschluss"):
            raise urllib.error.URLError("kein Netz mehr")

    _aufrufe_sammeln(monkeypatch, verhalten=_abschluss_schlaegt_fehl)
    ergebnis = R2Ablage().ablegen("abc12345", [SpendeDatei("feedback.txt", inhalt=b"Danke")])
    assert ergebnis.vollstaendig is True  # die Datei selbst kam an, nur die Meldung hinterher nicht
