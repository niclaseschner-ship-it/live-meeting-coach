"""Die Knöpfe (Ticket #6, Lastenheft 4.2; seit Ticket #13 in beiden Stufen gleich): fünf Kernaktionen plus Bild,
Regelprüfung und freie Frage. Ein Doppelklick wird abgewiesen, Protokoll erkennt die Artefakte aus dem Transkript
(Ticket #26)."""

import asyncio
import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("LMC_OFFLINE", "1")

from coach import knopfdruck  # noqa: E402
from coach.config import EINST  # noqa: E402
from coach.hoeren import wav_aus  # noqa: E402
from coach.pipeline import Coach  # noqa: E402


@pytest.fixture(autouse=True)
def ohne_protokolldateien(monkeypatch):
    """Keine Einträge in logs/nutzung.jsonl und logs/nestor.jsonl aus Tests."""
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)
    monkeypatch.setattr("coach.pipeline._zeit_loggen", lambda e: None)


class Attrappe:
    """Transkription: Text je WAV, die frühen Äußerungen antworten am langsamsten; Chat: feste Karte."""

    def __init__(self, texte: dict[bytes, str]) -> None:
        self.texte = texte
        self.transkribiert: list[str] = []
        self.gleichzeitig = self.hoechstens = 0
        self.chat_aufrufe = 0

        async def transkribieren(*, file, **kw):
            text = self.texte[file[1]]
            self.gleichzeitig += 1
            self.hoechstens = max(self.hoechstens, self.gleichzeitig)
            await asyncio.sleep(0.01 * (10 - int(text.split()[-1])))  # Nr. 1 kommt zuletzt zurück
            self.gleichzeitig -= 1
            self.transkribiert.append(text)
            return SimpleNamespace(text=text)

        async def chat(**kw):
            self.chat_aufrufe += 1
            inhalt = {"titel": "Budget offen", "punkte": ["Ihr seid bei Punkt eins.", "Vorschlag: zum Budget."],
                      "naechster_punkt": 2}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(inhalt)))],
                                   usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))

        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=transkribieren))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=chat))


def _proben(nr: int, sekunden: float = 1.0) -> np.ndarray:
    return np.full(int(16000 * sekunden), 0.001 * nr, dtype=np.float32)


async def _knopf_meeting(texte: dict[bytes, str], archiv: bool = False) -> Coach:
    c = Coach()
    c.stufe_setzen("premium")
    c._client = Attrappe(texte)
    c.archiv_aktiv = archiv
    c.einrichten({"titel": "Knopf", "agenda": [{"titel": "Termin", "minuten": 5}, {"titel": "Budget", "minuten": 5}],
                  "regel_ids": ["thema", "ton", "kurz"]})
    await c.hoeren_starten()
    # Stimmanalyse ohne Modell: eine Person je Äußerung
    c.hoerstrom.stimmen.analysieren = lambda p: {"person": 0, "abschnitte": [(0.0, len(p) / 16000, 0)],
                                                 "mischung": [], "ueberlappung": []}
    return c


# Ticket #80: Die Karte-plus-Vorschlag-Probe für „Wo stehen wir?“ und die Doppelklick-Sperre laufen inzwischen
# über den echten Weg (coach.assistent.bogen_starten) – siehe tests/test_bogen.py
# (test_bogen_stand_schlaegt_naechsten_punkt_vor, test_bogen_sperre_knopf_wird_abgewiesen_zuruf_unterbricht_nur_die_stimme).

# --- Weitere Knöpfe und Endpunkte ------------------------------------------------------

def test_regeln_und_protokoll_knopf(monkeypatch):
    """„Regeln eingehalten?“ fasst live nur die Ampeln zusammen, ohne eigenen KI-Aufruf; „Protokoll“ erkennt die
    Artefakte aus dem Transkript (Ticket #26)."""
    texte = {wav_aus(_proben(nr, 12.0)): f"Satz Nummer {nr}" for nr in range(1, 4)}
    alt = EINST.live_art
    object.__setattr__(EINST, "live_art", "sparsam")  # Text je Äußerung statt Live-Streaming (hier ohne echte Verbindung)

    async def lauf():
        c = await _knopf_meeting(texte)
        c.meeting.regel_ids = ["thema", "ton", "kurz", "ergebnisse"]

        async def chat(**kw):
            inhalt = {"artefakte": [{"typ": "entscheidung", "was": "Termin im April", "status": "endgueltig",
                                     "wer": "die Runde", "zeit": "0:01", "konfidenz": 0.9},
                                    {"typ": "aufgabe", "was": "Stand buchen", "wer": "Lea", "zeit": "0:14",
                                     "konfidenz": 0.9}]}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(inhalt)))],
                                   usage=None)
        c._client.chat = SimpleNamespace(completions=SimpleNamespace(create=chat))
        for nr in (1, 2, 3):
            c.hoerstrom.sekunden = c.meeting.virtuelle_zeit = nr * 13.0
            await c.hoerstrom._aeusserung(nr * 13.0 - 12.5, nr * 13.0 - 0.5, _proben(nr, 12.0))
            await asyncio.gather(*c.hoerstrom._analysen)
        regeln = await knopfdruck._regeln(c, "")
        await knopfdruck._protokoll(c, "")
        return c, regeln

    try:
        c, regeln = asyncio.run(lauf())
    finally:
        object.__setattr__(EINST, "live_art", alt)
    assert regeln["art"] == "regeln" and len(regeln["punkte"]) == 4  # eine Zeile je gewählter Regel, ohne KI-Aufruf
    protokoll = c.karten[-1]
    assert protokoll["art"] == "protokoll" and protokoll["punkte"][0] == "1. Termin: Termin im April"
    assert "- Stand buchen · wer: Lea · bis: offen – **fehlt: bis wann**" in c.knopf.protokoll
    assert c.meeting.ergebnisse[0]["ergebnis"] == "Termin im April"


def test_knopf_endpunkte():
    from fastapi.testclient import TestClient

    from coach.server import app

    web = TestClient(app, client=("127.0.0.1", 5000))
    assert web.post("/api/knopf/stand", json={}).status_code == 409  # kein Meeting
    assert web.post("/api/knopf/frage", json={}).status_code == 400  # keine Frage
    assert web.get("/api/knopf/protokoll.md").status_code == 404
