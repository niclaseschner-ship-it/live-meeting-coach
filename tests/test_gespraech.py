"""Realtime-Gespräch ohne Netz: Rückfrage-Fenster und Sprechzeiten mit einer Attrappe der Verbindung."""

import asyncio
import base64
import json

import pytest

from coach.config import EINST
from coach.gespraech import RATE, Gespraech
from coach.pipeline import Coach


@pytest.fixture(autouse=True)
def premium_fenster():
    alt = EINST.nachfrage_sekunden
    object.__setattr__(EINST, "nachfrage_sekunden", 15.0)
    yield
    object.__setattr__(EINST, "nachfrage_sekunden", alt)


class Verbindung:
    def __init__(self, ereignisse=()):
        self.gesendet: list[dict] = []
        self._ereignisse = list(ereignisse)

    async def send(self, roh: str) -> None:
        self.gesendet.append(json.loads(roh))

    async def close(self) -> None:
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._ereignisse:
            raise StopAsyncIteration
        return json.dumps(self._ereignisse.pop(0))

    def typen(self) -> list[str]:
        return [e["type"] for e in self.gesendet]


def _gespraech(ereignisse=()) -> tuple[Coach, Gespraech, Verbindung]:
    c = Coach()
    g = Gespraech(c.assistent)
    g._ws = Verbindung(ereignisse)
    g.offen = True
    c.assistent.gespraech = g
    return c, g, g._ws


async def _antwort(c: Coach, g: Gespraech, beginn: float, sekunden: float, fertig: float) -> None:
    """Wie im Cloud-Lauf 08.10. (premium_grenz2): erster Ton bei `beginn`, das Modell liefert `sekunden` Ton
    schneller als Echtzeit, response.done kommt bei `fertig` – lange bevor die Wiedergabe endet."""
    m = c.meeting
    m.virtuelle_zeit = beginn
    g._antwort_laeuft = True
    stueck = base64.b64encode(bytes(int(RATE * 2 * 0.25))).decode()  # 0,25 s PCM16
    for _ in range(int(sekunden / 0.25)):
        await g._ton(stueck)
    g._antwort_text = "Ihr seid noch bei Punkt 2, aber die Zeit ist um."
    m.virtuelle_zeit = fertig
    await g._antwort_fertig({})


def test_rueckfrage_ohne_namen_zaehlt_ab_ende_der_wiedergabe():
    """Ticket #17, Grenzfall 4: „Und wer kümmert sich darum?“ endete 10,4 s nach Nestors letztem Wort, aber
    16,6 s nach response.done. Das Fenster lief ab response.done (Sprechzeit dort abgeschnitten) – keine Antwort."""
    async def ablauf():
        c, g, ws = _gespraech()
        await _antwort(c, g, 291.7, 6.25, 292.9)
        ende_wiedergabe = c.assistent.sprechzeiten[-1][1]
        assert ende_wiedergabe == pytest.approx(291.7 + 0.4 + 6.25 + 0.8)
        c.meeting.virtuelle_zeit = 310.9
        g._letztes_commit = 309.6
        vorher = len(ws.gesendet)
        await g.satz("Und wer kümmert sich darum?", 309.516)
        return c, ws.typen()[vorher:]

    c, neu = asyncio.run(ablauf())
    assert neu == ["response.create"]
    assert c.assistent.zustand == "denkt"


def test_rueckfrage_wartet_auf_commit_des_modells():
    """premium_grenz2: Der Satz kam 3 s vor dem Turn-Ende des Modells – geantwortet wird nach dem Commit."""
    async def ablauf():
        c, g, ws = _gespraech()
        await _antwort(c, g, 291.7, 6.25, 292.9)
        c.meeting.virtuelle_zeit = 310.9
        g._letztes_commit = 285.0
        await g.satz("Und wer kümmert sich darum?", 309.516)
        assert ws.typen() == [] and g._wartet_auf_commit
        c.meeting.virtuelle_zeit = 313.9
        ws._ereignisse.append({"type": "input_audio_buffer.committed"})
        await g._empfangen()
        return ws.typen()

    assert asyncio.run(ablauf()) == ["response.create"]


def test_spaete_rueckfrage_bleibt_ohne_antwort():
    """Grenzfall 5: „Und bis wann ungefähr?“ deutlich nach dem Fenster – Nestor schweigt."""
    async def ablauf():
        c, g, ws = _gespraech()
        await _antwort(c, g, 291.7, 6.25, 292.9)
        c.meeting.virtuelle_zeit = 331.0
        g._letztes_commit = 330.5
        vorher = len(ws.gesendet)
        await g.satz("Und bis wann ungefähr?", 329.0)  # 30 s nach response.done, 20 s nach der Wiedergabe
        await g.satz("Das sehe ich auch so.", 300.0)  # kein Fragezeichen: auch im Fenster keine Antwort
        return ws.typen()[vorher:]

    assert asyncio.run(ablauf()) == []


def test_ins_wort_fallen_kuerzt_die_sprechzeit():
    """Beim Abbruch endet Nestors Sprechzeit sofort (Echo-Filter, Rückfrage-Fenster)."""
    async def ablauf():
        c, g, ws = _gespraech([{"type": "input_audio_buffer.speech_started"}])
        c.meeting.virtuelle_zeit = 291.7
        g._antwort_laeuft = True
        stueck = base64.b64encode(bytes(RATE * 2 * 6)).decode()  # 6 s Ton auf einmal
        await g._ton(stueck)
        c.meeting.virtuelle_zeit = 293.0
        await g._empfangen()
        return c

    c = asyncio.run(ablauf())
    assert c.assistent.sprechzeiten[-1][1] == pytest.approx(293.5)


def test_echo_filter_kennt_den_text_der_antwort():
    """Die Sprechzeit reicht bis zum Ende der Wiedergabe; wer Nestor dort ins Wort fällt, bleibt im Transkript."""
    async def ablauf():
        c, g, ws = _gespraech()
        await _antwort(c, g, 291.7, 6.25, 292.9)
        return c.assistent

    a = asyncio.run(ablauf())
    assert a.eigene_sprache(296.0, 298.0, "Ihr seid noch bei Punkt 2.")  # Nestor selbst über den Lautsprecher
    assert not a.eigene_sprache(296.0, 298.0, "Moment, warte, ich hab noch was.")
