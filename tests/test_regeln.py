"""Gesprächsregeln: Katalog, Auswahl, Regel „Alle kommen zu Wort“ und Konfidenz-Einstufung (Ticket #4)."""

from coach import konfidenz, regeln
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


def test_nur_zwei_sichtbare_stufen():
    assert set(regeln.STUFEN) == {"verlaesslich", "experimentell"}


def test_jede_umgesetzte_regel_hat_einstufung_und_kurzsatz_nur_bei_experimentell():
    for r in regeln.KATALOG:
        assert r.stufe in regeln.STUFEN
        if not r.umgesetzt:
            continue
        if r.stufe == "experimentell":
            assert r.kurzsatz, f"{r.id}: experimentell ohne Kurzsatz"
        else:
            assert r.kurzsatz is None, f"{r.id}: verlässlich, sollte keinen Kurzsatz haben"


def test_jedes_signal_hat_einstufung_und_kurzsatz_nur_bei_experimentell():
    for s in konfidenz.SIGNALE:
        assert s.stufe in regeln.STUFEN
        if s.stufe == "experimentell":
            assert s.kurzsatz, f"{s.id}: experimentell ohne Kurzsatz"
        else:
            assert s.kurzsatz is None, f"{s.id}: verlässlich, sollte keinen Kurzsatz haben"


def test_konfidenz_katalog_zeigt_verlaessliche_signale_zuerst():
    eintraege = konfidenz.katalog()
    stufen = [e["stufe"] for e in eintraege]
    assert stufen == sorted(stufen, key=lambda s: s == "experimentell")
    # Nur umgesetzte Regeln, keine Platzhalter wie „sachlich“ (noch nicht umgesetzt)
    ids = {e["id"] for e in eintraege}
    assert "sachlich" not in ids and "ausreden" in ids and "gleichzeitig" in ids


def test_regel_status_ordnet_verlaessliche_vor_experimentelle_mit_kurzsatz():
    c = Coach()
    c._einrichten({"titel": "T", "regel_ids": ["ausreden", "thema", "zeit", "kurz", "alle", "ton", "ergebnisse"]})
    c.meeting.starten(virtuell=True)
    status = c.regel_status([])
    stufen = [s["stufe"] for s in status]
    assert stufen == sorted(stufen, key=lambda s: s == "experimentell")
    ausreden = next(s for s in status if s["id"] == "ausreden")
    assert ausreden["stufe"] == "experimentell" and ausreden["kurzsatz"]
    ton = next(s for s in status if s["id"] == "ton")
    assert ton["stufe"] == "verlaesslich" and ton["kurzsatz"] is None


def test_transkript_je_agendapunkt_auch_bei_rueckkehr():
    from coach.zustand import Agendapunkt, Meeting

    m = Meeting(agenda=[Agendapunkt("A"), Agendapunkt("B")])
    m.starten(virtuell=True)
    m.transkript = [Segment("P", "a1", 5, 8), Segment("P", "b1", 25, 28), Segment("P", "a2", 45, 48)]
    m.virtuelle_zeit = 20; m.punkt_wechseln(1)
    m.virtuelle_zeit = 40; m.punkt_wechseln(0)
    assert [s.text for s in m.punkt_transkript(0)] == ["a1", "a2"]
    assert [s.text for s in m.punkt_transkript(1)] == ["b1"]
