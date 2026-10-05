"""Gesprächsregeln: Katalog, Auswahl und Regel „Alle kommen zu Wort“."""

from coach import regeln
from coach.pipeline import Coach
from coach.zustand import Segment


def test_nur_bekannte_und_umgesetzte_regeln_gelten():
    assert regeln.gueltige(["zeit", "gibtsnicht", "sachlich", "ausreden"]) == ["ausreden", "zeit"]


def test_hinweis_nennt_regel_nur_wenn_gewaehlt():
    assert "Ausreden lassen" in regeln.vereinbart(["ausreden"], "ausreden")
    assert regeln.vereinbart(["zeit"], "ausreden") == ""


def test_einrichten_mit_und_ohne_regelauswahl():
    c = Coach()
    c._einrichten({"titel": "T", "regel_ids": ["alle", "sachlich"], "regeln": ["Handys weg"]})
    assert c.meeting.regel_ids == ["alle"] and c.meeting.regeln == ["Handys weg"]
    c._einrichten({"titel": "T"})  # ältere Einrichtung ohne Auswahl → Standardregeln
    assert c.meeting.regel_ids == regeln.STANDARD


def _coach(teilnehmende, segmente, jetzt, regel_ids=("alle",)):
    c = Coach()
    c._einrichten({"titel": "T", "teilnehmende": teilnehmende, "regel_ids": list(regel_ids)})
    c.meeting.starten(virtuell=True)
    c.meeting.segmente = segmente
    c.meeting.virtuelle_zeit = jetzt
    c.takt()
    return [h.text for h in c.meeting.hinweise if h.art == "alle"]


def test_stille_angemeldete_werden_gemeldet():
    seg = [Segment("Person 1", "", 0, 300), Segment("Person 2", "", 300, 600)]
    texte = _coach(["A", "B", "C", "D"], seg, 650)
    assert any("2 von 4 Teilnehmenden haben noch nicht gesprochen" in t for t in texte)


def test_dominanz_im_gleitenden_fenster():
    seg = [Segment("Person 1", "", 0, 500), Segment("Person 2", "", 500, 560)]
    texte = _coach(["A", "B"], seg, 600)
    assert any("mehr als 50 % der Redezeit" in t for t in texte)


def test_ohne_gewaehlte_regel_kein_hinweis():
    seg = [Segment("Person 1", "", 0, 600)]
    assert _coach(["A", "B", "C"], seg, 650, regel_ids=()) == []


def test_ergebnis_hinweise_bei_fehlendem_ergebnis_und_unvollstaendiger_aufgabe():
    from coach import ergebnisse

    erg = ergebnisse.normalisieren({"ergebnis": None, "entscheidungen": [],
                                    "aufgaben": [{"was": "Angebot einholen", "wer": "Frau Lang", "bis": None}]})
    texte = ergebnisse.hinweise("Budget", erg)
    assert any("kein" in t or "nicht ausgesprochen" in t for t in texte)
    assert any("Angebot einholen" in t and "Termin" in t and "Verantwortliche" not in t for t in texte)
    voll = ergebnisse.normalisieren({"ergebnis": "Einstimmig beschlossen", "aufgaben": []})
    assert ergebnisse.hinweise("Budget", voll) == []


def test_transkript_je_agendapunkt_auch_bei_rueckkehr():
    from coach.zustand import Agendapunkt, Meeting

    m = Meeting(agenda=[Agendapunkt("A"), Agendapunkt("B")])
    m.starten(virtuell=True)
    m.transkript = [Segment("P", "a1", 5, 8), Segment("P", "b1", 25, 28), Segment("P", "a2", 45, 48)]
    m.virtuelle_zeit = 20; m.punkt_wechseln(1)
    m.virtuelle_zeit = 40; m.punkt_wechseln(0)
    assert [s.text for s in m.punkt_transkript(0)] == ["a1", "a2"]
    assert [s.text for s in m.punkt_transkript(1)] == ["b1"]
