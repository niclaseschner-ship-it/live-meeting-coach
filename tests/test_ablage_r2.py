"""Datenspende im Cloud-Betrieb, je Datei einzeln hochgeladen statt als ein großer Multipart-Körper: eine
kleine Datei geht als ein `PUT .../intern/spende/<name>/<datei>`, eine große in festen Teilen über R2s
Multipart-API (Start → je Teil ein PUT mit Wiederholungen → Abschluss) – beides streamt die Aufnahme von der
Platte statt sie komplett in den Speicher zu lesen, mit nach Größe gestaffeltem Timeout. Ein abschließendes
`POST .../abschluss` fasst das Ergebnis zusammen. Scheitert eine Datei, laufen die übrigen weiter –
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
    def __init__(self, inhalt: bytes = b"{}"):
        self._inhalt = inhalt

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._inhalt


def _aufrufe_sammeln(monkeypatch, verhalten=None, antwort=None):
    """Ersetzt urllib.request.urlopen; `verhalten(anfrage)` kann eine Ausnahme werfen, um einen einzelnen Ruf
    scheitern zu lassen, `antwort(anfrage)` liefert den simulierten Antwortkörper (Standard: `{}`). Liefert die
    Liste der mitgeschnittenen Anfragen."""
    aufrufe: list = []

    def _fake_urlopen(anfrage, timeout=None):
        aufrufe.append(anfrage)
        anfrage._gelesene_laenge = len(anfrage.data.read()) if hasattr(anfrage.data, "read") else len(anfrage.data)
        anfrage._timeout = timeout
        if verhalten is not None:
            verhalten(anfrage)
        return _FakeAntwort(antwort(anfrage) if antwort is not None else b"{}")

    import coach.ablage_r2 as ablage_r2

    monkeypatch.setattr(ablage_r2.urllib.request, "urlopen", _fake_urlopen)
    return aufrufe


def _multipart_worker_antworten(anfrage) -> bytes:
    """Spielt die drei Worker-Unterbefehle nach: Start liefert eine Upload-ID, ein Teil sein Etag, der
    Abschluss nur `ok`."""
    url = anfrage.full_url
    if "teile=start" in url:
        return json.dumps({"uploadId": "upload-1"}).encode("utf-8")
    if "teil=" in url:
        nr = int(url.split("teil=")[1].split("&")[0])
        return json.dumps({"partNumber": nr, "etag": f"etag-{nr}"}).encode("utf-8")
    return json.dumps({"ok": True}).encode("utf-8")


@pytest.fixture
def kleine_teile(monkeypatch):
    """Setzt die Teilgröße/-schwelle für diesen Test herunter, damit eine winzige Testdatei schon mehrteilig
    hochlädt, ohne echte Megabytes zu schreiben oder zu übertragen."""
    import coach.ablage_r2 as ablage_r2

    monkeypatch.setattr(ablage_r2, "_TEIL_GROESSE_BYTES", 10)
    monkeypatch.setattr(ablage_r2, "_TEIL_SCHWELLE_BYTES", 10)


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


# --- Mehrteiliger Upload großer Dateien ---------------------------------------------------------------------

def test_grosse_datei_laedt_in_teilen_start_je_teil_dann_fertig(monkeypatch, worker_zugang, kleine_teile, tmp_path):
    aufnahme = tmp_path / "aufnahme.wav"
    aufnahme.write_bytes(b"0123456789" * 3 + b"AB")  # 32 Byte → bei Teilgröße 10: 10,10,10,2

    aufrufe = _aufrufe_sammeln(monkeypatch, antwort=_multipart_worker_antworten)
    ergebnis = R2Ablage().ablegen("abc12345", [SpendeDatei("aufnahme.wav", pfad=aufnahme)])

    # Start + vier Teile + Fertig + der eine Abschluss-Ruf danach.
    assert [a.get_method() for a in aufrufe] == ["POST", "PUT", "PUT", "PUT", "PUT", "POST", "POST"]
    start, teil1, teil2, teil3, teil4, fertig, abschluss = aufrufe
    basis = f"{_WORKER_URL}/intern/spende/abc12345/aufnahme.wav"
    assert start.full_url == f"{basis}?teile=start"
    assert teil1.full_url == f"{basis}?teil=1&upload=upload-1"
    assert [t._gelesene_laenge for t in (teil1, teil2, teil3, teil4)] == [10, 10, 10, 2]
    assert fertig.full_url == f"{basis}?teile=fertig"
    assert json.loads(fertig.data) == {"uploadId": "upload-1", "teile": [
        {"partNumber": 1, "etag": "etag-1"}, {"partNumber": 2, "etag": "etag-2"},
        {"partNumber": 3, "etag": "etag-3"}, {"partNumber": 4, "etag": "etag-4"},
    ]}
    assert abschluss.full_url.endswith("/abschluss")

    assert ergebnis.vollstaendig is True
    assert ergebnis.teile[0].bytes == 32


def test_ein_scheiternder_teil_wird_wiederholt_bevor_er_endgueltig_zaehlt(monkeypatch, worker_zugang, kleine_teile, tmp_path):
    aufnahme = tmp_path / "aufnahme.wav"
    aufnahme.write_bytes(b"0123456789" * 2)  # 20 Byte → zwei Teile a 10 Byte

    versuche = {"teil2": 0}

    def _teil2_stolpert_einmal(anfrage):
        if "teil=2" in anfrage.full_url:
            versuche["teil2"] += 1
            if versuche["teil2"] == 1:
                raise urllib.error.URLError("kurzer Hänger")

    aufrufe = _aufrufe_sammeln(monkeypatch, verhalten=_teil2_stolpert_einmal, antwort=_multipart_worker_antworten)
    ergebnis = R2Ablage().ablegen("abc12345", [SpendeDatei("aufnahme.wav", pfad=aufnahme)])

    teil2_aufrufe = [a for a in aufrufe if "teil=2" in a.full_url]
    assert len(teil2_aufrufe) == 2  # erster Versuch scheiterte, der zweite zählt
    assert ergebnis.vollstaendig is True
    assert any("teile=fertig" in a.full_url for a in aufrufe)


def test_scheitert_ein_teil_auch_nach_den_wiederholungen_gilt_die_ganze_datei_als_gescheitert(
    monkeypatch, worker_zugang, kleine_teile, tmp_path,
):
    aufnahme = tmp_path / "aufnahme.wav"
    aufnahme.write_bytes(b"0123456789" * 3)  # 30 Byte → drei Teile a 10 Byte

    def _teil2_schlaegt_immer_fehl(anfrage):
        if "teil=2" in anfrage.full_url:
            raise urllib.error.URLError("dauerhaft kaputt")

    aufrufe = _aufrufe_sammeln(monkeypatch, verhalten=_teil2_schlaegt_immer_fehl, antwort=_multipart_worker_antworten)
    ergebnis = R2Ablage().ablegen("abc12345", [SpendeDatei("aufnahme.wav", pfad=aufnahme)])

    teil2_aufrufe = [a for a in aufrufe if "teil=2" in a.full_url]
    assert len(teil2_aufrufe) == 2  # beide Wiederholungen ausgeschöpft, dann abgebrochen
    assert not any("teil=3" in a.full_url for a in aufrufe)  # kein weiterer Teil nach dem endgültigen Fehlschlag
    assert not any("teile=fertig" in a.full_url for a in aufrufe)  # kein Abschließen eines unvollständigen Uploads

    [teil] = ergebnis.teile
    assert teil.ok is False
    assert ergebnis.vollstaendig is False
    # Trotzdem genau ein Abschluss-Ruf (anderer Pfad als "teile=fertig"), der den Fehlschlag meldet.
    [abschluss] = [a for a in aufrufe if a.full_url.endswith("/abschluss")]
    assert json.loads(abschluss.data)["ergebnisse"] == [{"datei": "aufnahme.wav", "bytes": 30, "ok": False}]
