"""Tests entlang der MVP-Testmatrix (Lastenheft Kap. 9) – ohne Audio und ohne KI."""

from coach import analyse
from coach.entscheider import Entscheider
from coach.themen import normalisieren
from coach.zustand import Agendapunkt, Meeting, Segment


def seg(sprecher, start, ende, text="Satz."):
    return Segment(sprecher, text, start, ende)


def meeting_mit_agenda(minuten=(1, 2, 2)):
    m = Meeting(agenda=[Agendapunkt(f"Punkt {i + 1}", minuten=x) for i, x in enumerate(minuten)])
    m.starten(virtuell=True)
    return m


def ampeln(m, themen_aktiv=True, karenz=1):
    liste = analyse.prozess_ampeln(
        m, monolog_sekunden=60, karenz_bloecke=karenz, zeit_rot_prozent=10,
        ueberlappung_min=0.5, ueberlappung_halte=30, themen_aktiv=themen_aktiv,
    )
    return {a["name"]: a for a in liste}


def erg(art, punkt=None, konfidenz=0.9):
    return {"art": art, "punkt": punkt, "konfidenz": konfidenz, "begruendung": "b"}


# --- Szene 1: normaler Start -----------------------------------------------

def test_szene1_alle_ampeln_gruen_und_countdown_laeuft():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 10), seg("B", 11, 20)]
    m.virtuelle_zeit = 20
    a = ampeln(m)
    assert {n: x["farbe"] for n, x in a.items()} == {
        "Monolog": "gruen", "Agenda & Zeit": "gruen", "Fokus": "gruen", "Sprecherüberlappung": "gruen"}
    assert a["Agenda & Zeit"]["detail"] == "0:40 verbleibend"
    assert m.schnappschuss()["agenda"][0]["status"] == "aktuell"


# --- FR-03 Monolog ---------------------------------------------------------

def test_monolog_ab_einer_minute_gelb_und_nach_wechsel_gruen():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 30), seg("A", 31, 61)]
    m.virtuelle_zeit = 62
    assert ampeln(m)["Monolog"]["farbe"] == "gelb"
    m.segmente.append(seg("B", 62, 70))
    m.virtuelle_zeit = 70
    assert ampeln(m)["Monolog"]["farbe"] == "gruen"


def test_monolog_unter_schwelle_gruen():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 55)]
    m.virtuelle_zeit = 55
    assert ampeln(m)["Monolog"]["farbe"] == "gruen"


def test_kurzer_einwurf_ist_noch_kein_dialog():
    segs = [seg("A", 0, 40), seg("B", 40.5, 41.2, "Mhm."), seg("A", 41.5, 80)]
    assert analyse.monolog(segs, schwelle=60) == ("A", 80)


def test_monolog_ampel_erlischt_nach_stille():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 70)]
    m.virtuelle_zeit = 90
    m.letztes_block_ende = 90  # ein späterer Block ohne Rede wurde verarbeitet
    assert ampeln(m)["Monolog"]["farbe"] == "gruen"


def test_monolog_rechnet_nicht_ueber_die_letzte_bekannte_aeusserung_hinaus():
    """Benchmark 05.10.: Hochrechnung schrieb der vorigen Person die Rede der nächsten zu → Fehlalarme."""
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 20), seg("A", 20.5, 40)]  # A spricht bis zum Blockende
    m.letztes_block_ende = 40
    m.virtuelle_zeit = 62
    m.sprache_bis = 61.5  # es wird gesprochen – aber von wem, zeigt erst die nächste Äußerung
    assert ampeln(m)["Monolog"]["farbe"] == "gruen"
    m.segmente.append(seg("A", 40.5, 61))  # die Äußerung ist ausgewertet: weiter A
    m.letztes_block_ende = 61
    assert ampeln(m)["Monolog"]["farbe"] == "gelb"


def test_monolog_zaehlt_nicht_weiter_wenn_rede_vor_blockende_endete():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 30)]
    m.letztes_block_ende = 40  # danach 10 s ohne A
    m.sprache_bis = 61.5
    m.virtuelle_zeit = 62
    assert ampeln(m)["Monolog"]["farbe"] == "gruen"


# --- FR-04 / Szene 3 Zeit --------------------------------------------------

def test_zeit_gelb_bei_ablauf_rot_optional():
    p = Agendapunkt("X", minuten=10)
    assert p.ampel(599, 10) == "gruen"
    assert p.ampel(600, 10) == "gelb"
    assert p.ampel(661, 10) == "rot"
    assert p.ampel(900, 0) == "gelb"  # Rot abgeschaltet


def test_countdown_nach_wechsel_fuer_neuen_punkt():  # FR-02
    m = meeting_mit_agenda()
    m.virtuelle_zeit = 70
    m.punkt_wechseln(1)
    m.virtuelle_zeit = 100
    s = m.schnappschuss()
    assert s["agenda"][0]["status"] == "abgeschlossen"
    assert s["agenda"][1]["status"] == "aktuell"
    assert s["agenda"][2]["status"] == "offen"
    assert s["agenda"][1]["verbleibend"] == 90
    assert ampeln(m)["Agenda & Zeit"]["detail"] == "1:30 verbleibend"


# --- FR-05 / Szene 4 Fokus -------------------------------------------------

def test_fokus_themenfremd_gelb_rueckkehr_gruen():
    m, e = meeting_mit_agenda(), Entscheider(0)
    analyse.themen_auswerten(m, e, erg("neu"), karenz_bloecke=1)
    assert ampeln(m)["Fokus"]["farbe"] == "gelb"
    assert m.hinweise[-1].text == "Bezug zum aktuellen Agendapunkt unklar."
    analyse.themen_auswerten(m, e, erg("aktiv", 0), karenz_bloecke=1)
    assert ampeln(m)["Fokus"]["farbe"] == "gruen"


def test_fokus_spaeterer_punkt_wird_genannt():
    m, e = meeting_mit_agenda(), Entscheider(0)
    analyse.themen_auswerten(m, e, erg("vorgriff", 2), karenz_bloecke=1)
    a = ampeln(m)["Fokus"]
    assert a["farbe"] == "gelb" and "Punkt 3" in a["detail"]
    assert "Agendapunkt 3" in m.hinweise[-1].text
    assert m.vorschlag["punkt"] == 2


def test_fokus_unklare_abschnitte_aendern_nichts():
    m, e = meeting_mit_agenda(), Entscheider(0)
    analyse.themen_auswerten(m, e, erg("neu"), karenz_bloecke=1)
    analyse.themen_auswerten(m, e, erg("unklar"), karenz_bloecke=1)
    assert ampeln(m)["Fokus"]["farbe"] == "gelb"


def test_fokus_karenz_mehrere_bloecke():
    m, e = meeting_mit_agenda(), Entscheider(0)
    analyse.themen_auswerten(m, e, erg("neu"), karenz_bloecke=2)
    assert ampeln(m, karenz=2)["Fokus"]["farbe"] == "gruen"
    analyse.themen_auswerten(m, e, erg("neu"), karenz_bloecke=2)
    assert ampeln(m, karenz=2)["Fokus"]["farbe"] == "gelb"


def test_fokus_aus_ohne_ki():
    assert ampeln(meeting_mit_agenda(), themen_aktiv=False)["Fokus"]["farbe"] == "aus"


def test_punktwechsel_setzt_fokus_zurueck():
    m, e = meeting_mit_agenda(), Entscheider(0)
    analyse.themen_auswerten(m, e, erg("vorgriff", 1), karenz_bloecke=1)
    m.punkt_wechseln(1)
    assert ampeln(m)["Fokus"]["farbe"] == "gruen"


# --- FR-06 / Szene 5 Sprecherüberlappung -----------------------------------

def test_ueberlappung_gelb_und_wieder_gruen():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 10), seg("B", 8.5, 12)]
    m.virtuelle_zeit = 15
    assert ampeln(m)["Sprecherüberlappung"]["farbe"] == "gelb"
    m.virtuelle_zeit = 60  # Haltezeit von 30 s vorbei
    assert ampeln(m)["Sprecherüberlappung"]["farbe"] == "gruen"


def test_normaler_wechsel_und_kurze_beruehrung_sind_keine_ueberlappung():
    segs = [seg("A", 0, 10), seg("B", 10.2, 12), seg("A", 11.8, 14)]  # 0,2 s < Mindestdauer
    assert analyse.ueberlappungen(segs, seit=0, min_dauer=0.5) == []


GEMESSEN = [  # echte Ausgabe von gpt-4o-transcribe-diarize für zwei gleichzeitige Stimmen (02.10.2026)
    ("A", 3.9, 4.0), ("B", 4.0, 4.1), ("A", 4.1, 4.7), ("B", 4.7, 4.8), ("A", 4.8, 5.4),
    ("B", 5.4, 5.6), ("A", 5.6, 5.8), ("B", 5.8, 5.9), ("A", 5.9, 6.3), ("B", 6.3, 6.9),
]


def test_zickzack_der_diarisierung_wird_als_ueberlappung_erkannt():
    segs = [seg(w, a, b) for w, a, b in GEMESSEN]
    assert analyse.ueberlappungen(segs, seit=0, min_dauer=0.5) == []  # keine echte Zeitüberlappung …
    assert analyse.ueberlappung_erkannt(segs, 0, 0.5, fenster=3, min_wechsel=4)  # … aber das Muster


def test_lebhafter_normaler_dialog_ist_kein_zickzack():
    segs = [seg("A", 0, 4), seg("B", 4.3, 6), seg("A", 6.2, 9), seg("B", 9.4, 12), seg("C", 12.2, 15)]
    assert not analyse.ueberlappung_erkannt(segs, 0, 0.5, fenster=3, min_wechsel=4)


# --- Text und Sprecherspur zusammenführen ----------------------------------

def sp(wer, a, b):
    return {"sprecher": wer, "start": a, "ende": b}


def test_beitraege_fassen_gleiche_person_zusammen():
    from coach.transkription import beitraege

    spur = [sp("A", 0, 0.9), sp("A", 1.4, 4.2), sp("B", 5.7, 7.0), sp("B", 7.5, 9.7), sp("A", 11.2, 14.2)]
    assert [(b["sprecher"], b["start"], b["ende"]) for b in beitraege(spur)] == [
        ("A", 0, 4.2), ("B", 5.7, 9.7), ("A", 11.2, 14.2)]


def test_zickzack_schnipsel_gehen_im_beitrag_auf():
    from coach.transkription import beitraege

    spur = [sp("A", 0, 3.9)] + [sp(w, a, b) for w, a, b in GEMESSEN] + [sp("B", 7.5, 9.0)]
    ergebnis = beitraege(spur)
    assert [b["sprecher"] for b in ergebnis] == ["A", "B"]
    # lückenlos: das Zickzack geht an A, der letzte B-Schnipsel in B's folgenden Beitrag
    assert (ergebnis[0]["start"], ergebnis[0]["ende"], ergebnis[1]["start"], ergebnis[1]["ende"]) == (0, 6.3, 6.3, 9.0)


def test_pegel_angleichen_verstaerkt_leise_begrenzt():
    from array import array

    from coach.transkription import MAX_VERSTAERKUNG, pegel_angleichen, rms

    leise = array("h", [100, -100] * 1000)
    assert rms(pegel_angleichen(leise)) == 100 * MAX_VERSTAERKUNG
    laut = array("h", [5000, -5000] * 1000)
    assert pegel_angleichen(laut) == laut


def test_ausschneiden_mit_rand():
    from array import array

    from coach.transkription import RATE, ausschneiden

    p = array("h", [0] * (10 * RATE))
    assert len(ausschneiden(p, 2.0, 3.0)) == int(1.5 * RATE)
    assert len(ausschneiden(p, 0.0, 0.5)) == int(0.75 * RATE)


# --- FR-07 Redeanteile -----------------------------------------------------

def test_redeanteile_summieren_sich():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 10), seg("B", 10, 15), seg("A", 15, 20)]
    assert m.redeanteile() == {"A": 15, "B": 5}


# --- Entscheider -----------------------------------------------------------

def test_cooldown_unterdrueckt_wiederholung():
    m = Meeting()
    m.starten(virtuell=True)
    e = Entscheider(cooldown_sekunden=120)
    assert e.vorschlagen(m, "fokus", "hinweis", "gruppe", "x")
    m.virtuelle_zeit = 60
    assert e.vorschlagen(m, "fokus", "hinweis", "gruppe", "x") is None
    m.virtuelle_zeit = 130
    assert e.vorschlagen(m, "fokus", "hinweis", "gruppe", "x")


def test_einmalig():
    m = Meeting()
    e = Entscheider(0)
    assert e.einmalig(m, "k", "zeit", "hinweis", "gruppe", "x")
    assert e.einmalig(m, "k", "zeit", "hinweis", "gruppe", "x") is None


def test_normalisieren_faengt_unsinn_ab():
    assert normalisieren({"punkt": 9, "art": "quatsch", "konfidenz": "hoch"}, 3) == {
        "punkt": None, "art": "unklar", "konfidenz": 0.0, "begruendung": "", "ton": []}
    assert normalisieren({"punkt": 2, "art": "vorgriff", "konfidenz": 1.7}, 3)["punkt"] == 1


def test_ausdrueckliche_ueberleitung_wird_erkannt():
    from coach.analyse import ankuendigung

    assert ankuendigung("Gut, dann kommen wir jetzt zum nächsten Punkt, der Budgetplanung.")
    assert ankuendigung("Unter dem Tagesordnungspunkt 6 haben wir die Beschlussvorlage 0341.")
    assert ankuendigung("Ähm, nächstes Thema.")
    assert not ankuendigung("Das kommt gleich noch, lass uns beim Budget bleiben.")


def test_angekuendigter_punkt_wechselt_direkt():
    from coach.analyse import angekuendigter_punkt

    titel = ["Termin und Messestand", "Budget", "Aufgaben verteilen"]
    assert angekuendigter_punkt("Dann gehen wir weiter zu Punkt drei, Aufgaben verteilen.", titel, 1) == 2
    assert angekuendigter_punkt("Nun gehen wir weiter zu Punkt 2.", titel, 0) == 1
    assert angekuendigter_punkt("Gut, dann kommen wir zum dritten Punkt.", titel, 0) == 2
    assert angekuendigter_punkt("Dann kommen wir jetzt zum nächsten Punkt.", titel, 0) == 1
    assert angekuendigter_punkt("Dann kommen wir zum Budget.", titel, 0) == 1
    # ohne Überleitungsformel, schon dort oder außerhalb der Agenda: kein Wechsel
    assert angekuendigter_punkt("Punkt drei war gut vorbereitet.", titel, 0) is None
    assert angekuendigter_punkt("Gehen wir weiter zu Punkt zwei.", titel, 1) is None
    assert angekuendigter_punkt("Kommen wir zu Punkt neun.", titel, 0) is None


def test_ankuendigung_mit_wechseln_und_ordnungszahl():
    from coach.analyse import angekuendigter_punkt, ankuendigung

    titel = ["Projektstand", "Urlaubsplanung im Dezember", "Zeiterfassung"]
    assert angekuendigter_punkt("Und jetzt wechseln wir ausdrücklich zum zweiten Punkt, der Urlaubsplanung.", titel, 0) == 1
    assert ankuendigung("Dann kommen wir jetzt endlich mal zur Zeiterfassung.")
    assert not ankuendigung("Wir wechseln die Agentur nicht, das ist klar.")
    assert not ankuendigung("Das kommt gleich noch, lass uns beim Budget bleiben.")


def test_ansage_in_voxtral_schreibweise():
    """Ticket #15: so kamen die Ansagen im Cloud-Lauf in Nestor Basis (Voxtral) an – keine wurde erkannt."""
    from coach.analyse import angekuendigter_punkt, ankuendigung

    titel = ["Kassenbericht", "Budget für das Sommerfest", "Anschaffung eines Vereinsbusses"]
    assert angekuendigter_punkt("Wir wechseln jetzt ausdrücklich zu Agenda Punkt 2, dem Budget für das Sommerfest. "
                                "Geplant waren dafür sechs Minuten, es ist jetzt 19.10 Uhr.", titel, 0) == 1
    assert angekuendigter_punkt("Wir gehen jetzt zu Agendapunkt drei, der möglichen Anschaffung eines "
                                "Vereinsbusses.", titel, 1) == 2
    assert angekuendigter_punkt("Dann weiter mit Agenda-Punkt drei.", titel, 1) == 2
    assert angekuendigter_punkt("Wir kommen nun zum Budget für das Sommerfest.", titel, 0) == 1
    assert angekuendigter_punkt("Tagesordnungs-Punkt 2 ist dran.", titel, 0) == 1
    # Subjekt zuerst ohne Zeitwort ist keine Überleitung
    assert not ankuendigung("Wir kommen zu dem Schluss, dass das Budget reicht.")
    assert not ankuendigung("Wir gehen zum Sommerfest alle zusammen hin.")
    assert angekuendigter_punkt("Nestor, fass bitte kurz zusammen, was wir zu Punkt 2 besprochen haben.",
                                titel, 1) is None


def test_rueckwaerts_ansage_wechselt():
    """Ticket #17, Grenzfall 11: „Lass uns nochmal kurz zu Punkt eins zurück“ kam in allen Cloud-Läufen 08.10.
    wörtlich an (OpenAI „eins“, Voxtral „1“) und wechselte nie. Vertagen und Rückkehr ohne Agenda-Ziel nicht."""
    from coach.analyse import angekuendigter_punkt

    titel = ["Ablauf des Ausfalls", "Ursache", "Maßnahmen", "Kommunikation an Kunden"]
    for satz, ziel in [("Lass uns nochmal kurz zu Punkt eins zurück.", 0),
                       ("Lass uns nochmal kurz zu Punkt 1 zurück.", 0),
                       ("Zurück zu Punkt eins, bitte.", 0),
                       ("Gehen wir zurück zur Ursache.", 1),
                       ("Gehen wir zurück zum ersten Punkt.", 0),
                       ("Nochmal zu Punkt zwei.", 1),
                       ("Noch einmal kurz zum ersten Punkt.", 0),
                       ("Kommen wir noch mal auf Punkt eins zurück.", 0),
                       ("Lasst uns zum Ablauf des Ausfalls zurückgehen.", 0)]:
        assert angekuendigter_punkt(satz, titel, 2) == ziel, satz
    for satz in ["Wir kommen später darauf zurück.",
                 "Wir kommen später auf Punkt eins zurück.",
                 "Darauf kommen wir nachher bei Punkt eins zurück.",
                 "Lass uns zu Punkt eins am Ende zurückkommen.",
                 "Gut, zurück zur Datenbank.",  # Ende der Abschweifung im Cloud-Lauf – kein Agendapunkt
                 "Ja, zurück zum Incident. Als Root Cause halten wir fest: blockierende Postgres-Migration.",
                 "Ich will noch mal zur Ursache was sagen.",
                 "Das hat zwar die Pods zurückgesetzt, aber nicht das Datenbank-Schema."]:
        assert angekuendigter_punkt(satz, titel, 2) is None, satz
    assert angekuendigter_punkt("Lass uns nochmal kurz zu Punkt eins zurück.", titel, 0) is None  # schon dort


def test_nachfrage_fasst_offene_aufgaben_zusammen():
    """Ticket #26 statt der früheren Sammelzeile je Punkt: eine Frage je Artefakt mit konkretem Vorschlag, gebündelt."""
    from coach.artefakte import Artefakt, nachfrage_text

    a = Artefakt(1, "aufgabe", "Validierung bauen", bis="Freitag")
    b = Artefakt(2, "aufgabe", "Import durchführen")
    assert nachfrage_text("Projektstand", [a, b], weitere=1) == (
        "Kurz zu „Projektstand“: Ich hab notiert: Validierung bauen, bis Freitag. Wer übernimmt das? "
        "Ich hab notiert: Import durchführen. Wer übernimmt das, bis wann? Eine weitere Lücke steht im Dashboard.")


def test_rueckwaerts_ansage_im_live_text_wechselt_den_punkt():
    """Grenzfall 11 durch die Pipeline: Satz wie im Cloud-Lauf premium_grenz2 (Punkt 2 aktiv)."""
    import asyncio

    from coach.pipeline import Coach
    from coach.zustand import Agendapunkt, Segment

    async def ablauf():
        c = Coach()
        c._client = None
        c.meeting.agenda = [Agendapunkt(t) for t in ("Ablauf des Ausfalls", "Ursache", "Maßnahmen")]
        c.meeting.aktiver_punkt = 1
        c.meeting.regel_ids = []
        c.meeting.starten(virtuell=True)
        c.meeting.virtuelle_zeit = 546.4
        await c.satz(Segment("Person 4", "Gut, zurück zur Datenbank.", 362.5, 363.4))
        assert c.meeting.aktiver_punkt == 1
        await c.satz(Segment("Person 4", "Lass uns nochmal kurz zu Punkt eins zurück.", 543.3, 545.4))
        return c

    c = asyncio.run(ablauf())
    assert c.meeting.aktiver_punkt == 0
    assert any(e["art"] == "wechsel" and e["durch"] == "ansage" for e in c.protokoll)
