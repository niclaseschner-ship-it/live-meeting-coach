"""Sprachassistent ohne Netzwerk: Ansprache, Aktionen, Einwand, eigene Sprache, Ablauf mit Attrappen."""

import asyncio
from types import SimpleNamespace

from coach import assistent as a
from coach.pipeline import Coach
from coach.config import EINST
from coach.zustand import Agendapunkt, Segment

import pytest


@pytest.fixture(autouse=True)
def text_modus():
    """Diese Tests prüfen den Text-Weg (Sprachmodell + Sprachausgabe); das Realtime-Gespräch braucht Netz."""
    alt = EINST.assistent_modus
    object.__setattr__(EINST, "assistent_modus", "text")
    yield
    object.__setattr__(EINST, "assistent_modus", alt)


def test_name_erkennen_auch_in_typischen_schreibweisen():
    assert a.angesprochen("Nestor, wo stehen wir?")
    assert a.angesprochen("Hey Nester, fass das mal zusammen")
    assert a.angesprochen("Kannst du uns das zeigen, Nestor?")
    assert not a.angesprochen("Wir brauchen ein Nest für die Daten")


def test_frage_ohne_namen_und_anrede():
    assert a.frage_aus("Hey Nestor, wo stehen wir gerade?") == "wo stehen wir gerade?"
    assert a.frage_aus("Was kommt als Nächstes, Nestor?") == "Was kommt als Nächstes?"


def test_aktionszeile_lesen():
    assert a.aktion_lesen("AKTION: keine") is None
    assert a.aktion_lesen("AKTION: bild was noch ansteht") == {"typ": "bild", "fokus": "was noch ansteht"}
    assert a.aktion_lesen("AKTION: weiter 3") == {"typ": "weiter", "ziel": "3"}
    assert a.aktion_lesen("Wir sind bei Punkt zwei.") is None


def test_saetze_teilen_laesst_unfertigen_rest_stehen():
    fertig, rest = a.saetze_teilen("Ihr seid bei Punkt zwei. Entschieden ist noch nich")
    assert fertig == ["Ihr seid bei Punkt zwei."] and rest == "Entschieden ist noch nich"


def test_einwand_erkennen():
    assert a.einwand("Nein.") and a.einwand("Das möchte ich nicht") and a.einwand("Ich bin nicht einverstanden")
    assert not a.einwand("Ja, passt.") and not a.einwand("Keine Einwände")


def test_begruessung_nennt_regeln_und_ersten_punkt():
    c = Coach()
    c._einrichten({"titel": "T", "agenda": [{"titel": "Budget"}], "regel_ids": ["ausreden", "zeit"]})
    gruss, start = a.begruessungstext(c.meeting)
    assert "Ausreden lassen und Zeit einhalten" in gruss and "Nein" in gruss
    assert "Punkt eins: Budget" in start and "Nestor" in start


def test_eigene_sprache_wird_nur_live_herausgefiltert():
    c = Coach()
    c.assistent.sprechzeiten = [(10.0, 15.0)]
    assert c.assistent.eigene_sprache(10.5, 14.0)
    assert not c.assistent.eigene_sprache(20, 25)
    c.simulation_laeuft = True  # Abspielmodus: die Aufnahme enthält den Coach nicht
    assert not c.assistent.eigene_sprache(10.5, 14.0)


class _Strom:
    def __init__(self, teile):
        self.teile = teile

    def __aiter__(self):
        async def gen():
            for t in self.teile:
                yield SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=t))])
        return gen()


class _Ton:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *x):
        return False

    async def iter_bytes(self, n):
        yield bytes(24000 * 2)  # 1 s Stille


def _attrappe(antwort_teile):
    async def create(**kw):
        return _Strom(antwort_teile)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=lambda **kw: _Ton()))),
    )


def test_frage_antwort_mit_aktion_und_sprachausgabe(monkeypatch):
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)

    async def ablauf():
        c = Coach()
        c._client = _attrappe(["AKTION: weiter 2\nGut, dann geht es weiter mit Punkt zwei. ", "Punkt eins ist abgeschlossen."])
        c.meeting.agenda = [Agendapunkt("Start"), Agendapunkt("Budget")]
        c.meeting.regel_ids = []
        c.meeting.starten(virtuell=True)
        gesendet = []

        async def senden(n):
            gesendet.append(n)
        c.direkt.append(senden)
        await c.satz(Segment("Person 1", "Nestor, wir sind durch, bitte weiter zum nächsten Punkt.", 1, 4))
        await c.assistent._aufgabe
        return c, gesendet

    c, gesendet = asyncio.run(ablauf())
    assert c.meeting.aktiver_punkt == 1
    assert c.assistent.letzte["antwort"] == "Gut, dann geht es weiter mit Punkt zwei. Punkt eins ist abgeschlossen."
    assert sum(1 for n in gesendet if n["typ"] == "stimme") == 2  # zwei Sätze, je ein Tonstück
    assert c.assistent.zustand == "bereit" and len(c.assistent.sprechzeiten) == 2


def test_ohne_namen_keine_antwort():
    async def ablauf():
        c = Coach()
        c._client = _attrappe(["AKTION: keine\nHallo."])
        c.meeting.starten(virtuell=True)
        await c.satz(Segment("Person 1", "Wir sollten das Budget prüfen.", 1, 3))
        return c

    c = asyncio.run(ablauf())
    assert c.assistent._aufgabe is None and c.assistent.letzte is None


def test_aktion_keine_wird_nicht_vorgelesen(monkeypatch):
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)

    async def ablauf():
        c = Coach()
        c._client = _attrappe(["AKTION: keine\nIhr seid bei Punkt eins."])
        c.meeting.starten(virtuell=True)
        await c.satz(Segment("Person 1", "Nestor, wo stehen wir gerade?", 1, 3))
        await c.assistent._aufgabe
        return c

    assert asyncio.run(ablauf()).assistent.letzte["antwort"] == "Ihr seid bei Punkt eins."


def test_recherche_text_ohne_eingebettete_quellen():
    from coach.recherche import vorlesbar

    roh = "Der Mindestlohn liegt bei 13,90 Euro. ([bmas.de](https://www.bmas.de/x?utm=a))  Mehr [hier](https://y)."
    assert vorlesbar(roh) == "Der Mindestlohn liegt bei 13,90 Euro. Mehr hier."
    assert a.aktion_lesen("AKTION: recherche Mindestlohn aktuell") == {"typ": "recherche", "frage": "Mindestlohn aktuell"}


def test_folie_nach_recherche():
    import asyncio
    from types import SimpleNamespace

    from coach import folie, kosten
    from coach.assistent import aktion_lesen

    assert aktion_lesen("AKTION: folie") == {"typ": "folie"}
    assert kosten.dollar({"art": "folie", "modell": "gpt-5.4-mini", "tokens_rein": 1e6, "tokens_raus": 0}) == 0.75

    class Attrappe:  # liefert eine feste JSON-Antwort statt OpenAI
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def create(self, **_):
            inhalt = '{"titel": "Mindestlohn 2026", "kernaussage": "13,90 Euro je Stunde.", "punkte": ["a", "b"], "offen": ""}'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=inhalt))],
                                   usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))

    f, n = asyncio.run(folie.erstellen(Attrappe(), {"frage": "Mindestlohn?", "text": "…", "zeit": 5,
                                                    "quellen": [{"titel": "", "url": "https://www.bmas.de/x"}]}))
    assert f["titel"] == "Mindestlohn 2026" and f["punkte"] == ["a", "b"]
    assert f["quellen"] == [{"titel": "bmas.de", "url": "https://www.bmas.de/x", "seite": "bmas.de"}]
    assert n["tokens_rein"] == 10


def test_karte_ohne_modell_und_kurze_antworten():
    import asyncio

    from coach import karten

    assert asyncio.run(karten.verdichten(None, "danke", "Gern, bis gleich.")) == (None, {})
    lang = "Ihr seid bei Punkt zwei. Das Budget liegt bei 25.000 Euro. Offen ist der Puffer für Getränke. Mehr nicht."
    karte, _ = asyncio.run(karten.verdichten(None, "wo stehen wir?", lang))
    assert karte == {"titel": "wo stehen wir?", "punkte": ["Ihr seid bei Punkt zwei.", "Das Budget liegt bei 25.000 Euro.",
                                                           "Offen ist der Puffer für Getränke.", "Mehr nicht."]}
