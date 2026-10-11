"""Der kurze WS-Kanal für den Sprechknopf-Teiltext (coach/api_sprechknopf.py).

Keine echten Anbieter: `LiveText`/`LiveTextMistral` werden durch eine Attrappe ersetzt (wie die vorhandenen
Fakes in tests/test_kostenbremse.py, tests/test_hoeren_teilen.py). Geprüft wird nur das Vertrag: PCM rein, Teiltext
zurück, Anbietertrennung/Kostenbremse/Kostenlogging unverändert, best effort ohne Fehler, wenn nichts verfügbar
ist."""

from __future__ import annotations

import os

os.environ.setdefault("LMC_OFFLINE", "1")

import pytest
from fastapi.testclient import TestClient

from coach import api_sprechknopf
from coach.anbieter import wahl_fuer
from coach.server import app, coach


class FakeLiveText:
    """Attrappe mit der Schnittstelle von coach/livetext.py: verbinden/audio/schliessen, kein Netzwerk."""

    letzte: "FakeLiveText | None" = None

    def __init__(self, bei_teiltext, bei_satz, prompt, stichwoerter, *, wahl, bei_verstoss=None) -> None:
        self.bei_teiltext = bei_teiltext
        self.bei_satz = bei_satz
        self.wahl = wahl
        self.audio_stuecke: list[bytes] = []
        self.gesendete_sekunden = 0.0
        self.verbunden = False
        self.geschlossen = False
        FakeLiveText.letzte = self

    async def verbinden(self) -> None:
        self.verbunden = True

    async def audio(self, pcm24k: bytes) -> None:
        self.audio_stuecke.append(pcm24k)
        self.gesendete_sekunden += len(pcm24k) / 2 / 24000
        await self.bei_teiltext(f"Teiltext {len(self.audio_stuecke)}")

    async def schliessen(self, nachlauf: float = 0) -> None:
        self.geschlossen = True


class PlatzendeLiveText(FakeLiveText):
    """Verbinden schlägt fehl – wie ein nicht erreichbarer Anbieter oder ein API-Fehler."""

    async def verbinden(self) -> None:
        raise RuntimeError("Anbieter nicht erreichbar")


@pytest.fixture
def lokal():
    return TestClient(app, client=("127.0.0.1", 5000))


@pytest.fixture
def verbunden(monkeypatch):
    """coach.wahl/._client wie nach einer bestätigten Variante – ohne echten Netzwerkclient."""
    monkeypatch.setattr(coach, "wahl", wahl_fuer("premium"))
    monkeypatch.setattr(coach, "_client", object())
    monkeypatch.setattr(coach, "_kosten_gedeckelt", False)
    monkeypatch.setattr(api_sprechknopf, "LiveText", FakeLiveText)
    kosten_aufrufe: list[float] = []
    monkeypatch.setattr(coach, "live_text_kosten", lambda sekunden: kosten_aufrufe.append(sekunden))
    return kosten_aufrufe


def test_pcm_geht_rein_teiltext_kommt_zurueck(lokal, verbunden):
    with lokal.websocket_connect("/ws/sprechknopf") as ws:
        ws.send_bytes(b"\x00\x01" * 1200)
        d = ws.receive_json()
        assert d == {"teil": "Teiltext 1"}
        ws.send_bytes(b"\x02\x03" * 1200)
        d2 = ws.receive_json()
        assert d2 == {"teil": "Teiltext 2"}
    fake = FakeLiveText.letzte
    assert fake.verbunden and fake.geschlossen
    assert len(fake.audio_stuecke) == 2
    assert verbunden and verbunden[0] > 0  # coach.live_text_kosten wurde mit den gesendeten Sekunden aufgerufen


def test_nutzt_den_anbieter_der_gewaehlten_stufe(lokal, verbunden, monkeypatch):
    """Anbietertrennung: Premium nimmt LiveText (OpenAI), Basis LiveTextMistral – nie das andere."""
    aufrufe = []

    class Markierung(FakeLiveText):
        def __init__(self, *a, **k):
            aufrufe.append("mistral")
            super().__init__(*a, **k)

    monkeypatch.setattr(api_sprechknopf, "LiveTextMistral", Markierung)
    monkeypatch.setattr(coach, "wahl", wahl_fuer("basis"))
    with lokal.websocket_connect("/ws/sprechknopf"):
        pass
    assert aufrufe == ["mistral"]


def test_ohne_bestaetigte_wahl_schliesst_der_kanal_sofort_kein_fehler(lokal, monkeypatch):
    """accept() kommt noch (sonst wäre es ein Login-/Kopplungsfehler wie in test_zugang.py) – erst danach lehnt
    der Kanal mangels Wahl ab. Der Browser sieht das erst beim nächsten Empfang als Disconnect mit Code."""
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setattr(coach, "wahl", None)
    with lokal.websocket_connect("/ws/sprechknopf") as ws, pytest.raises(WebSocketDisconnect) as e:
        ws.receive_text()
    assert e.value.code == 4404


def test_nach_kostendeckel_schliesst_der_kanal_sofort(lokal, verbunden, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setattr(coach, "_kosten_gedeckelt", True)
    with lokal.websocket_connect("/ws/sprechknopf") as ws, pytest.raises(WebSocketDisconnect) as e:
        ws.receive_text()
    assert e.value.code == 4404


def test_anbieter_nicht_erreichbar_schliesst_ohne_die_aufnahme_zu_stoeren(lokal, verbunden, monkeypatch):
    """Best effort: schlägt verbinden() fehl, bekommt der Browser nur einen Close-Code, keinen Fehlertext –
    basis.js (liveTextOeffnen) behandelt das als „kein Teiltext“, die Aufnahme läuft weiter."""
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setattr(api_sprechknopf, "LiveText", PlatzendeLiveText)
    with lokal.websocket_connect("/ws/sprechknopf") as ws, pytest.raises(WebSocketDisconnect) as e:
        ws.receive_text()
    assert e.value.code == 4503
