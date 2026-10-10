"""Ticket #74: Nestor Basis (nur Mistral) liefert Ergebnisse gleichwertig zu Premium – Beschlüsse mit Beträgen,
Aufgaben mit Verantwortlichen, offene Punkte, und jede Antwort auf die Sprechtaste als Karte.

Die Antwortformen unten sind echte Antworten von mistral-small-latest auf den Schnell-Prompt (Probe 10.10.2026):
erfundene Nummern bei leerer Liste und eine Entscheidung ohne die Beträge."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from coach import artefakte as A
from coach import karten
from coach.anbieter import wahl_fuer
from coach.pipeline import Coach
from coach.zustand import Segment


class Modell:
    def __init__(self, *antworten) -> None:
        self.antworten = list(antworten)
        self.modelle: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.modelle.append(kw["model"])
        antwort = self.antworten.pop(0) if self.antworten else {"artefakte": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(antwort)))],
                               usage=SimpleNamespace(prompt_tokens=600, completion_tokens=100))


def _coach(*antworten, stufe: str = "basis") -> Coach:
    c = Coach()
    c.stufe_setzen(stufe)
    c._einrichten({"titel": "Vorstand", "agenda": [{"titel": "Ziel und Ablauf klären", "minuten": 2},
                                                   {"titel": "Sommerfest-Budget", "minuten": 10}],
                   "regel_ids": ["ergebnisse"]})
    c._client = Modell(*antworten)
    c.meeting.starten(virtuell=True)
    return c


def _satz(c: Coach, text: str, start: float, ende: float) -> Segment:
    s = Segment("Person 1", text, start, ende)
    c.meeting.transkript.append(s)
    c.meeting.virtuelle_zeit = ende
    return s


async def _warten_bis(bedingung, sekunden: float = 2.0) -> None:
    for _ in range(int(sekunden / 0.01)):
        if bedingung():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Bedingung nicht erreicht")


@pytest.fixture(autouse=True)
def _ohne_sammeln(monkeypatch):
    monkeypatch.setattr(A, "SAMMELN_SEKUNDEN", 0.0)


# Mistral-small, Probe 10.10.: Nummer 2 bzw. 1 bei leerer Liste, Beschluss nur als Thema
SMALL_BESCHLUSS = {"nummer": 2, "typ": "entscheidung", "was": "Sommerfest-Budgetrahmen festlegen", "wer": "die Runde",
                   "bis": None, "status": "endgültig", "vage": False, "konfidenz": None, "zeit": "00:33",
                   "zitat": "Wir beschließen für das Sommerfest maximal 9.000 Euro Ausgaben"}
SMALL_AUFGABE = {"nummer": 1, "typ": "aufgabe", "was": "Fahrten der Jugend des letzten Jahres liefern", "wer": "Sabine",
                 "bis": "2026-10-15T23:59:59+02:00", "status": None, "vage": False, "konfidenz": 0.95, "zeit": "00:41",
                 "zitat": "Sabine liefert bis Freitag die Fahrten der Jugend des letzten Jahres"}
VOLL_BESCHLUSS = {"nummer": None, "typ": "entscheidung",
                  "was": "Sommerfestbudget: maximal 9.000 Euro Ausgaben und 3.500 Euro Zuschuss", "wer": "die Runde",
                  "status": "endgueltig", "konfidenz": 1.0, "zeit": "00:33",
                  "zitat": "Wir beschließen für das Sommerfest maximal 9.000 Euro Ausgaben"}
VOLL_OFFEN = {"nummer": 3, "typ": "offen", "was": "ob sich ein Kauf des Vereinsbusses lohnt", "wer": None, "bis": None,
              "konfidenz": 1.0, "zeit": "00:51", "zitat": "Beim Vereinsbus prüfen wir noch, ob sich ein Kauf lohnt"}


def test_schnell_erkennung_nutzt_das_analysemodell_der_stufe_nicht_das_kleine_zuordnungsmodell():
    async def ablauf(stufe):
        c = _coach({"artefakte": [VOLL_BESCHLUSS]}, stufe=stufe)
        c.artefakte.satz([_satz(c, "Wir beschließen für das Sommerfest maximal 9.000 Euro Ausgaben.", 33, 38)])
        await _warten_bis(lambda: len(c.artefakte.liste) == 1 and not c.artefakte._schnell_laeuft)
        return c

    basis = asyncio.run(ablauf("basis"))
    assert basis._client.modelle == [wahl_fuer("basis").analyse_modell]
    assert basis._client.modelle[0].startswith("mistral-medium")  # Basis bleibt bei Mistral
    premium = asyncio.run(ablauf("premium"))
    assert premium._client.modelle == [wahl_fuer("premium").analyse_modell]


def test_erfundene_nummer_eines_anderen_typs_ergaenzt_nichts_sondern_legt_neu_an():
    """Mistral nannte für die Aufgabe „nummer 1“ – das war die Entscheidung. Die Aufgabe ging verloren, Sabine fehlte."""
    async def ablauf():
        c = _coach({"artefakte": [SMALL_BESCHLUSS]}, {"artefakte": [SMALL_AUFGABE]})
        c.artefakte.satz([_satz(c, "Wir beschließen für das Sommerfest maximal 9.000 Euro Ausgaben.", 33, 38)])
        await _warten_bis(lambda: len(c.artefakte.liste) == 1 and not c.artefakte._schnell_laeuft)
        c.artefakte.satz([_satz(c, "Sabine liefert bis Freitag die Fahrten der Jugend des letzten Jahres.", 41, 46)])
        await _warten_bis(lambda: len(c.artefakte.liste) == 2 and not c.artefakte._schnell_laeuft)
        return c

    c = asyncio.run(ablauf())
    entscheidung, aufgabe = c.artefakte.liste
    assert entscheidung.typ == "entscheidung" and entscheidung.wer == "die Runde"
    assert aufgabe.typ == "aufgabe" and aufgabe.wer == "Sabine" and aufgabe.schnell
    karte = [k for k in c.karten if k["art"] == "ergebnis"][0]
    assert karte["ids"] == [1, 2]


def test_vollauswertung_bringt_die_betraege_in_einen_schnell_erkannten_beschluss_ohne_zahlen():
    async def ablauf():
        c = _coach({"artefakte": [SMALL_BESCHLUSS]}, {"artefakte": [VOLL_BESCHLUSS, VOLL_OFFEN]})
        c.artefakte.satz([_satz(c, "Wir beschließen für das Sommerfest maximal 9.000 Euro Ausgaben.", 33, 38)])
        await _warten_bis(lambda: len(c.artefakte.liste) == 1 and not c.artefakte._schnell_laeuft)
        _satz(c, "Beim Vereinsbus prüfen wir noch, ob sich ein Kauf lohnt.", 51, 55)
        await c.artefakte.erkennen()
        return c

    c = asyncio.run(ablauf())
    beschluss, offen = c.artefakte.liste
    assert "9.000" in beschluss.was and beschluss.status == "endgueltig"
    assert offen.typ == "offen" and "Vereinsbus" in offen.was  # Nummer 3 gab es nicht → neu
    gliederung = c.artefakte.standardgliederung()
    assert "9.000" in gliederung["entscheidungen"][0]["was"]


def test_wortlaut_ohne_neue_zahl_bleibt_stehen():
    a = A.Artefakte()
    alt = a.anlegen("entscheidung", "Sommerfest: maximal 9.000 Euro Ausgaben", status="endgueltig", wer="die Runde")
    a._ergaenzen(alt, {"was": "Budget für das Fest: Ausgabengrenze 9.000 Euro"})
    assert alt.was == "Sommerfest: maximal 9.000 Euro Ausgaben"
    aufgabe = a.anlegen("aufgabe", "Fahrten liefern", wer="Sabine")
    a._ergaenzen(aufgabe, {"was": "Fahrten bis 16.10. liefern"})
    assert aufgabe.was == "Fahrten liefern"  # nur Beschlüsse holen Beträge nach


def test_meetingdatum_nennt_den_wochentag():
    c = _coach()
    text = A.nachricht(c.meeting, [], [], [])
    assert any(f"Meetingdatum (Europe/Berlin): {t}, " in text for t in A.WOCHENTAGE)


def test_prompts_verlangen_betraege_und_pruefauftraege():
    for prompt in (A.SYSTEM, A.SCHNELL):
        assert "Beträge" in prompt and "prüfen wir noch" in prompt and "nie Agendapunkte" in prompt


# --- Sprechtaste: jede Antwort als Karte (Bedienlogik) ------------------------------------------------------------
class KartenModell:
    def __init__(self, antwort: dict) -> None:
        self.antwort = antwort
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.antwort)))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def test_pflichtkarte_auch_wenn_das_modell_zeigen_false_sagt():
    wahl = wahl_fuer("basis")
    client = KartenModell({"zeigen": False})
    frage, antwort = "Bitte bereite eine kurze Vorstandssitzung vor.", "Das Meeting läuft schon. Soll ich zusammenfassen?"
    ohne, _ = asyncio.run(karten.verdichten(client, frage, antwort, kontext="Stand", wahl=wahl))
    assert ohne is None
    mit, _ = asyncio.run(karten.verdichten(client, frage, antwort, kontext="Stand", wahl=wahl, pflicht=True))
    assert mit == {"titel": frage, "punkte": ["Das Meeting läuft schon.", "Soll ich zusammenfassen?"]}
    kurz, _ = asyncio.run(karten.verdichten(client, frage, "Gern.", kontext="Stand", wahl=wahl, pflicht=True))
    assert kurz is not None
    leer, _ = asyncio.run(karten.verdichten(client, frage, "  ", kontext="Stand", wahl=wahl, pflicht=True))
    assert leer is None
