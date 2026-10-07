"""Agenda per Prompt (Lastenheft 4.1): Fließtext, eingefügte Tabelle, Änderungswunsch, kaputtes JSON."""

import asyncio
import json
from types import SimpleNamespace

from coach.agenda_prompt import MAX_MINUTEN, MAX_PUNKTE, agenda_vorschlagen, normalisieren


def _client(*antworten):
    """Liefert bei jedem Aufruf die nächste vorbereitete Antwort (Inhalt des Chat-Objekts)."""
    folge = iter(antworten)

    async def create(**_):
        inhalt = next(folge)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=inhalt))])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _json(**obj):
    return json.dumps(obj, ensure_ascii=False)


# --- normalisieren ----------------------------------------------------------

def test_normalisieren_begrenzt_minuten_und_anzahl():
    roh = {"titel": "Team", "punkte": [{"titel": f"P{i}", "minuten": 500} for i in range(20)], "antwort": "ok"}
    erg = normalisieren(roh, None)
    assert len(erg["punkte"]) == MAX_PUNKTE
    assert all(p["minuten"] == MAX_MINUTEN for p in erg["punkte"])


def test_normalisieren_verwirft_punkte_ohne_titel_und_rundet_minuten():
    roh = {"punkte": [{"titel": "", "minuten": 5}, {"titel": "Budget", "minuten": 12.6}]}
    erg = normalisieren(roh, None)
    assert erg["punkte"] == [{"titel": "Budget", "minuten": 13, "ziel": ""}]


def test_normalisieren_behaelt_bisherigen_titel_wenn_keiner_kommt():
    erg = normalisieren({"punkte": []}, {"titel": "Altes Meeting"})
    assert erg["titel"] == "Altes Meeting"


# --- agenda_vorschlagen: Abnahme-Fälle ---------------------------------------

def test_fliesstext_wird_zu_tabelle():
    antwort = _json(titel="Teamrunde", punkte=[
        {"titel": "Stand Projekt Elbgarten", "minuten": 10, "ziel": ""},
        {"titel": "Urlaubsplanung Dezember", "minuten": 20, "ziel": ""},
        {"titel": "Neue Zeiterfassung", "minuten": 15, "ziel": ""},
        {"titel": "Verschiedenes", "minuten": 15, "ziel": ""},
    ], antwort="Ich habe 4 Punkte angelegt, zusammen 60 Minuten.")
    erg = asyncio.run(agenda_vorschlagen(_client(antwort), "modell", "Teamrunde, eine Stunde: …", None))
    assert erg["titel"] == "Teamrunde"
    assert [p["titel"] for p in erg["punkte"]] == [
        "Stand Projekt Elbgarten", "Urlaubsplanung Dezember", "Neue Zeiterfassung", "Verschiedenes"]
    assert sum(p["minuten"] for p in erg["punkte"]) == 60
    assert erg["antwort"]


def test_outlook_tsv_mit_uhrzeiten():
    tsv = "Zeit\tThema\tVerantwortlich\n10:00-10:15\tBegrüßung und Stand\tNiclas\n10:15-10:45\tBudget 2027\tSophie"
    antwort = _json(titel="", punkte=[
        {"titel": "Begrüßung und Stand", "minuten": 15, "ziel": "Niclas"},
        {"titel": "Budget 2027", "minuten": 30, "ziel": "Sophie"},
    ], antwort="Ich habe 2 Punkte aus den Uhrzeiten übernommen, zusammen 45 Minuten.")
    erg = asyncio.run(agenda_vorschlagen(_client(antwort), "modell", tsv, None))
    assert [p["minuten"] for p in erg["punkte"]] == [15, 30]


def test_aenderungswunsch_auf_bestehende_tabelle():
    bisher = {"titel": "Teamrunde", "punkte": [
        {"titel": "Begrüßung und Stand", "minuten": 15, "ziel": "Niclas"},
        {"titel": "Budget 2027", "minuten": 30, "ziel": "Sophie"},
        {"titel": "Offene Punkte", "minuten": 15, "ziel": "alle"},
    ]}
    antwort = _json(titel="Teamrunde", punkte=[
        {"titel": "Begrüßung und Stand", "minuten": 15, "ziel": "Niclas"},
        {"titel": "Budget 2027", "minuten": 20, "ziel": "Sophie"},
        {"titel": "Offene Punkte", "minuten": 15, "ziel": "alle"},
        {"titel": "Aufgabenverteilung", "minuten": 10, "ziel": ""},
    ], antwort="Budget auf 20 Minuten gekürzt, dafür 10 Minuten Aufgabenverteilung am Ende.")
    client = _client(antwort)
    erg = asyncio.run(agenda_vorschlagen(
        client, "modell", "Budget nur 20 Minuten, dafür am Ende 10 Minuten Aufgabenverteilung", bisher))
    assert erg["punkte"][1] == {"titel": "Budget 2027", "minuten": 20, "ziel": "Sophie"}
    assert erg["punkte"][-1]["titel"] == "Aufgabenverteilung"

    async def nachricht_pruefen():
        gesehen = {}

        async def create(*, messages, **_):
            gesehen["text"] = messages[-1]["content"]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=antwort))])

        c = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        await agenda_vorschlagen(c, "modell", "Budget nur 20 Minuten", bisher)
        return gesehen["text"]

    gesehene_nachricht = asyncio.run(nachricht_pruefen())
    assert "Bisherige Tabelle" in gesehene_nachricht and "Budget 2027" in gesehene_nachricht


def test_kaputtes_json_erst_wiederholung_dann_fehlermeldung():
    gut = _json(titel="T", punkte=[{"titel": "Punkt", "minuten": 10, "ziel": ""}], antwort="Ich habe 1 Punkt angelegt.")
    erg = asyncio.run(agenda_vorschlagen(_client("kein json", gut), "modell", "Eingabe", None))
    assert erg["punkte"][0]["titel"] == "Punkt"  # zweiter Versuch hat gegriffen

    bisher = {"titel": "Altes Meeting", "punkte": [{"titel": "Bleibt", "minuten": 5, "ziel": ""}]}
    erg2 = asyncio.run(agenda_vorschlagen(_client("kein json", "immer noch kein json"), "modell", "Eingabe", bisher))
    assert erg2["punkte"] == bisher["punkte"] and erg2["titel"] == "Altes Meeting"
    assert erg2["antwort"]  # Fehlermeldung an den Nutzer


def test_rueckfrage_ohne_brauchbare_agenda():
    antwort = _json(titel="", punkte=[], antwort="Worum soll es in dem Meeting gehen?")
    erg = asyncio.run(agenda_vorschlagen(_client(antwort), "modell", "ein Meeting", None))
    assert erg["punkte"] == [] and "?" in erg["antwort"]
