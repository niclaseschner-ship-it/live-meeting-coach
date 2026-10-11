import asyncio
import types

from coach import bestaetigung as B
from coach.pipeline import Coach
from coach.config import EINST
import pytest


@pytest.fixture(autouse=True)
def text_modus():
    alt = EINST.assistent_modus
    object.__setattr__(EINST, "assistent_modus", "text")
    yield
    object.__setattr__(EINST, "assistent_modus", alt)


def _coach():
    c = Coach()
    c.stufe_setzen("premium")
    c._einrichten({"titel": "T", "agenda": [{"titel": "A"}], "regel_ids": []})
    c._client = object()   # damit der Assistent aktiv ist; es wird kein Modell gerufen
    return c


@pytest.mark.parametrize("text", [
    "stopp",
    "Warte mal.",
    "warte, warte",
    "Moment bitte!",
    "halt stopp",
    "Einen Moment.",
    "eine Sekunde",
    "Stopp!",
])
def test_halt_wunsch_wahr(text):
    assert B.halt_wunsch(text)


@pytest.mark.parametrize("text", [
    "",
    "stopp die Recherche",
    "warte mit der Folie",
    "fass zusammen",
    "Moment, was haben wir beschlossen?",
    "warte, was war Punkt zwei?",
])
def test_halt_wunsch_falsch(text):
    assert not B.halt_wunsch(text)


def test_bogen_wird_abgeloest():
    async def lauf():
        c = _coach()
        a = c.assistent
        a.aktiv = True
        abgeloest = []

        def abloesen():
            abgeloest.append(1)
            return None

        a._bogen_abloesen = abloesen
        ja = []

        async def ja_sagen():
            ja.append(1)

        a._ja_sagen = ja_sagen
        fut = asyncio.get_running_loop().create_future()
        a.bogen = types.SimpleNamespace(task=fut, art="frage")
        jetzt = c.meeting.jetzt()
        await a.satz("Nestor, Nestor, warte mal.", jetzt)
        assert len(abgeloest) == 1
        assert ja == []
        assert a._angesprochen_bis > c.meeting.jetzt()
        assert any(e.get("art") == "halt" for e in c.protokoll)
        fut.cancel()

    asyncio.run(lauf())


def test_ohne_bogen_kein_ja():
    async def lauf():
        c = _coach()
        a = c.assistent
        a.aktiv = True
        ja = []

        async def ja_sagen():
            ja.append(1)

        a._ja_sagen = ja_sagen
        await a.satz("Nestor, stopp!", c.meeting.jetzt())
        assert ja == []
        assert a.bogen is None

    asyncio.run(lauf())


def test_kein_halt_bei_inhalt():
    async def lauf():
        c = _coach()
        a = c.assistent
        a.aktiv = True
        halte = []
        ja = []
        angenommen = []

        async def halt():
            halte.append(1)

        a._halt = halt

        async def ja_sagen():
            ja.append(1)

        a._ja_sagen = ja_sagen

        def annehmen(frage, quelle, sprecher=None):
            angenommen.append((frage, quelle))

        a.annehmen = annehmen
        await a.satz("Nestor, fass zusammen", c.meeting.jetzt())
        assert halte == []
        assert ja == []
        assert len(angenommen) == 1

    asyncio.run(lauf())
