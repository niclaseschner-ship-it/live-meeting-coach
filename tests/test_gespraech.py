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


async def _bogen_mit_antwort(c: Coach, g: Gespraech):
    """Ein Bogen in der offenen Sitzung, die Antwort wie in premium_grenz2: Ton bis 299,15 s, response.done bei 292,9."""
    c.meeting.virtuelle_zeit = 291.0
    b = c.assistent.bogen_starten("frage", "Wie viel Zeit haben wir noch?", "stimme", "Person 1")
    await asyncio.sleep(0.01)
    await _antwort(c, g, 291.7, 6.25, 292.9)
    c.meeting.virtuelle_zeit = 300.0  # Wiedergabe zu Ende
    await b.task
    return b


def test_rueckfrage_ohne_namen_zaehlt_ab_ende_der_wiedergabe():
    """Ticket #17, Grenzfall 4: „Und wer kümmert sich darum?“ endete 10,4 s nach Nestors letztem Wort, aber
    16,6 s nach response.done – das Fenster läuft ab dem Ende der Wiedergabe (Ticket #27: Follow-up-Modus)."""
    async def ablauf():
        c, g, ws = _gespraech()
        await _bogen_mit_antwort(c, g)
        ende_wiedergabe = c.assistent.sprechzeiten[-1][1]
        assert ende_wiedergabe == pytest.approx(291.7 + 0.4 + 6.25 + 0.8)
        assert c.assistent.schnappschuss()["hoert_bis"] == pytest.approx(ende_wiedergabe + 15, abs=1.0)
        c.meeting.virtuelle_zeit = 310.9
        vorher = len(ws.gesendet)
        await c.assistent.satz("Und wer kümmert sich darum?", 309.516, "Person 2")
        await asyncio.sleep(0.01)
        return c.assistent.bogen, ws.typen()[vorher:]

    bogen, neu = asyncio.run(ablauf())
    assert neu == ["conversation.item.create", "response.create"]
    assert bogen is not None and bogen.quelle == "nachfrage"


def test_spaete_rueckfrage_bleibt_ohne_antwort():
    """Grenzfall 5: „Und bis wann ungefähr?“ deutlich nach dem Fenster – Nestor schweigt."""
    async def ablauf():
        c, g, ws = _gespraech()
        await _bogen_mit_antwort(c, g)
        c.meeting.virtuelle_zeit = 331.0
        c.assistent.takt()
        vorher = len(ws.gesendet)
        await c.assistent.satz("Und bis wann ungefähr?", 329.0)  # 30 s nach response.done, 20 s nach der Wiedergabe
        return ws.typen()[vorher:]

    assert asyncio.run(ablauf()) == []


def test_reinreden_stoppt_nur_die_stimme_die_antwort_kommt_als_karte():
    """Ticket #27 Nachtrag B: Reinreden während die Antwort noch erzeugt wird – kein Ton mehr, aber die ganze Antwort
    kommt still als Karte; das Modell erfährt am Ende, wie weit sie zu hören war."""
    async def ablauf():
        c, g, ws = _gespraech()
        gesendet = []

        async def senden(n):
            gesendet.append(n)
        c.direkt.append(senden)
        karten = []
        c.antwort_karte = lambda frage, antwort, aktion, quellen, still=False: karten.append((antwort, still))
        m = c.meeting
        m.virtuelle_zeit = 100.0
        g._antwort_laeuft = True
        stueck = base64.b64encode(bytes(int(RATE * 2 * 1.0))).decode()
        await g._ton(stueck, "item_1")
        m.virtuelle_zeit = 100.9
        g._wiedergabe = {"item": "item_1", "beginn": 100.4, "bytes": RATE * 2}
        assert await g._hineinreden()
        n_ton = sum(1 for n in gesendet if n["typ"] == "stimme")
        await g._ton(stueck, "item_1")  # die Antwort läuft weiter, ist aber nicht mehr zu hören
        g._antwort_text = "Ihr habt noch drei Minuten. Danach kommt das Budget."
        await g._antwort_fertig({})
        return gesendet, n_ton, ws, karten

    gesendet, n_ton, ws, karten = asyncio.run(ablauf())
    assert sum(1 for n in gesendet if n["typ"] == "stimme") == n_ton  # kein Ton nach dem Reinreden
    assert any(n["typ"] == "stimme_stopp" for n in gesendet)
    kuerzen = [e for e in ws.gesendet if e["type"] == "conversation.item.truncate"]
    assert kuerzen and kuerzen[0]["audio_end_ms"] == 500
    assert karten == [("Ihr habt noch drei Minuten. Danach kommt das Budget.", True)]


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
