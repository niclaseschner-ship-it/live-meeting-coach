"""Agenda per Prompt (Lastenheft 4.1): Fließtext, eingefügte Tabelle, Änderungswunsch, kaputtes JSON."""

import asyncio
import json
from types import SimpleNamespace

from coach.agenda_prompt import MAX_MINUTEN, MAX_PUNKTE, agenda_vorschlagen, normalisieren, dialog_nachrichten


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


def test_normalisieren_behaelt_bisheriges_ziel_und_teilnehmende_wenn_nichts_kommt():
    bisher = {"titel": "Altes Meeting", "ziel": "Altes Ziel", "teilnehmende": ["Lea", "Jonas"], "punkte": []}
    erg = normalisieren({"punkte": []}, bisher)
    assert erg["ziel"] == "Altes Ziel"
    assert erg["teilnehmende"] == ["Lea", "Jonas"]


def test_normalisieren_begrenzt_teilnehmende():
    roh = {"punkte": [{"titel": "Planen", "minuten": 10}], "teilnehmende": [f"Person {i}" for i in range(30)]}
    erg = normalisieren(roh, None)
    assert len(erg["teilnehmende"]) == 20


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

    bisher = {"titel": "Altes Meeting", "ziel": "Altes Ziel", "teilnehmende": ["Lea"],
              "punkte": [{"titel": "Bleibt", "minuten": 5, "ziel": ""}]}
    erg2 = asyncio.run(agenda_vorschlagen(_client("kein json", "immer noch kein json"), "modell", "Eingabe", bisher))
    assert erg2["punkte"] == bisher["punkte"] and erg2["titel"] == "Altes Meeting"
    assert erg2["ziel"] == "Altes Ziel" and erg2["teilnehmende"] == ["Lea"]
    assert erg2["antwort"]  # Fehlermeldung an den Nutzer


def test_rueckfrage_ohne_brauchbare_agenda():
    antwort = _json(titel="", punkte=[], antwort="Worum soll es in dem Meeting gehen?")
    erg = asyncio.run(agenda_vorschlagen(_client(antwort), "modell", "ein Meeting", None))
    assert erg["punkte"] == [] and "?" in erg["antwort"]


def test_einladungsmail_liefert_titel_ziel_punkte_und_teilnehmende():
    """Abnahme-Fall aus dem Ticket: eine ganze Einladungsmail ergibt Titel, Ziel, 4 Punkte (60 min) und
    4 Teilnehmende. Die Antwort des Sprachmodells ist hier gemockt (siehe Bericht für den echten Codex-Lauf
    mit genau dieser Mail)."""
    mail = (
        "Betreff: Jour fixe Messe 2027 – Standkonzept festzurren\n"
        "Hallo zusammen, am Donnerstag 10:00–11:00 im Raum Elbe wollen wir das Standkonzept für die Messe "
        "2027 entscheiden.\n"
        "Teilnehmende: Lea Brandt, Jonas Weber, Mira Schulz, Tim Krause\n"
        "Agenda:\n"
        "1. Rückblick Messe 2026 (kurz)\n"
        "2. Standgröße und Budget\n"
        "3. Gestaltung und Give-aways\n"
        "4. Aufgaben und nächste Schritte\n"
        "Viele Grüße, Lea"
    )
    antwort = _json(
        titel="Jour fixe Messe 2027 – Standkonzept festzurren",
        ziel="Entscheidung über das Standkonzept für die Messe 2027",
        punkte=[
            {"titel": "Rückblick Messe 2026", "minuten": 10, "ziel": ""},
            {"titel": "Standgröße und Budget", "minuten": 20, "ziel": ""},
            {"titel": "Gestaltung und Give-aways", "minuten": 20, "ziel": ""},
            {"titel": "Aufgaben und nächste Schritte", "minuten": 10, "ziel": ""},
        ],
        teilnehmende=["Lea Brandt", "Jonas Weber", "Mira Schulz", "Tim Krause"],
        antwort="Ich habe 4 Punkte angelegt, zusammen 60 Minuten, mit 4 Teilnehmenden.",
    )
    erg = asyncio.run(agenda_vorschlagen(_client(antwort), "modell", mail, None))
    assert erg["titel"] == "Jour fixe Messe 2027 – Standkonzept festzurren"
    assert "Standkonzept" in erg["ziel"]
    assert len(erg["punkte"]) == 4
    assert sum(p["minuten"] for p in erg["punkte"]) == 60
    assert erg["teilnehmende"] == ["Lea Brandt", "Jonas Weber", "Mira Schulz", "Tim Krause"]


def test_gezielter_aenderungswunsch_an_bisheriges_ziel():
    """Die Entscheidung, ob Titel/Ziel/Teilnehmende überschrieben werden, liegt beim Sprachmodell (System-
    Prompt); hier wird nur geprüft, dass ein gezielt geändertes Ziel normal durchgereicht wird, ohne den
    bisherigen Titel oder die Teilnehmenden zu verlieren."""
    bisher = {"titel": "Teamrunde", "ziel": "Altes Ziel", "teilnehmende": ["Lea", "Jonas"],
              "punkte": [{"titel": "Budget", "minuten": 10, "ziel": ""}]}
    antwort = _json(titel="Teamrunde", ziel="Neues Ziel", punkte=bisher["punkte"],
                     teilnehmende=bisher["teilnehmende"], antwort="Ziel angepasst.")
    erg = asyncio.run(agenda_vorschlagen(_client(antwort), "modell", "Ziel ist eigentlich: Neues Ziel", bisher))
    assert erg["ziel"] == "Neues Ziel"
    assert erg["titel"] == "Teamrunde"
    assert erg["teilnehmende"] == ["Lea", "Jonas"]


def test_rueckfrage_bewahrt_alle_bestehenden_felder():
    bisher = {"titel": "Team", "ziel": "Planen", "teilnehmende": ["Lea"],
              "punkte": [{"titel": "Budget", "minuten": 10, "ziel": "Rahmen klären"}]}
    erg = normalisieren({"status": "rueckfrage", "punkte": [], "ziel": "Nicht übernehmen",
                         "antwort": "Welchen Punkt soll ich ändern?"}, bisher)
    assert erg["status"] == "rueckfrage"
    for feld, wert in bisher.items():
        assert erg[feld] == wert


def test_nur_ziel_ist_keine_stille_erfolgsantwort():
    erg = normalisieren({"ziel": "Hausbau", "punkte": [], "antwort": "Ziel übernommen."}, None)
    assert erg["status"] == "rueckfrage" and "?" in erg["antwort"]
    assert erg["ziel"] == ""  # keine unvollständige Eingabe als fertiges Meeting ausgeben


def test_dialog_begrenzt_und_ohne_systemrollen():
    verlauf = [{"role": "user", "content": "a" * 3000}] * 9 + [{"role": "system", "content": "nein"}]
    erg = dialog_nachrichten(verlauf)
    assert len(erg) == 7 and all(len(n["content"]) == 2000 for n in erg)
    assert dialog_nachrichten("kaputt") == []


def test_folgeantwort_erhaelt_rueckfragekontext():
    gesehen = {}
    async def create(**kwargs):
        gesehen.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=_json(
            status="entwurf", titel="WG-Hausbau", punkte=[{"titel": "Keller", "minuten": 15}],
            antwort="Ein Entwurf mit geschätzten Zeiten.")))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    dialog = [{"role": "user", "content": "Wir wollen etwas gemeinsam planen."},
              {"role": "assistant", "content": "Welches Vorhaben?"}]
    erg = asyncio.run(agenda_vorschlagen(client, "modell", "Ein Hausbau mit der WG", None, dialog))
    assert gesehen["messages"][1:3] == dialog
    assert "Hausbau" in gesehen["messages"][-1]["content"]
    assert erg["status"] == "entwurf" and erg["punkte"]
