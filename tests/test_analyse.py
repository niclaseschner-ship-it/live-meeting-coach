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
        m, karenz_bloecke=karenz, zeit_rot_prozent=10,
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
        "Agenda & Zeit": "gruen", "Fokus": "gruen", "Sprecherüberlappung": "gruen"}
    assert a["Agenda & Zeit"]["detail"] == "0:40 verbleibend"
    assert m.schnappschuss()["agenda"][0]["status"] == "aktuell"


# --- FR-03 Redeanteil (statt Monolog) ---------------------------------------

def test_redeanteil_grenze_ist_das_anderthalbfache_des_fairen_anteils():
    m = meeting_mit_agenda()
    m.teilnehmende = ["A", "B", "C"]
    m.segmente = [seg("A", 0, 160), seg("B", 160, 200)]  # A 80 % von 200 s
    m.virtuelle_zeit = 200
    r = analyse.redeanteil(m)
    assert r["personen"] == 3 and round(r["grenze"], 2) == 0.5 and r["ueber"]


def test_redeanteil_ausgeglichen_kein_hinweis():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 60), seg("B", 60, 120), seg("C", 120, 170)]  # A 35 %, Grenze 50 %
    m.virtuelle_zeit = 170
    assert analyse.redeanteil(m)["ueber"] is False


def test_redeanteil_zaehlt_nur_die_letzten_fuenf_minuten():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 400), seg("B", 400, 520), seg("A", 520, 580), seg("C", 580, 700)]
    m.virtuelle_zeit = 700  # Fenster 400–700: A 60 s, B 120 s, C 120 s
    assert analyse.redeanteil(m)["ueber"] is False


def test_redeanteil_braucht_genug_gespraech_und_zwei_personen():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 50), seg("B", 50, 62)]
    m.virtuelle_zeit = 62  # nur 62 s Rede im Fenster
    assert analyse.redeanteil(m)["ueber"] is False
    m.segmente = [seg("A", 0, 300)]
    m.virtuelle_zeit = 300
    assert analyse.redeanteil(m) is None  # allein im Raum: kein fairer Anteil


def test_unsichere_stimme_zaehlt_nicht():
    m = meeting_mit_agenda()
    m.segmente = [seg("A", 0, 100), seg("Person ?", 100, 250), seg("B", 250, 300)]
    m.virtuelle_zeit = 300  # A 100 von 150 s sicher Zugeordnetem = 67 %, Grenze bei 2 Personen 75 %
    assert analyse.redeanteil(m)["ueber"] is False


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
    m.regel_ids = ["thema"]
    analyse.themen_auswerten(m, e, erg("neu"), karenz_bloecke=1)
    assert ampeln(m)["Fokus"]["farbe"] == "gelb"
    assert m.hinweise[-1].text.startswith("Bezug zum aktuellen Agendapunkt unklar.")
    analyse.themen_auswerten(m, e, erg("aktiv", 0), karenz_bloecke=1)
    assert ampeln(m)["Fokus"]["farbe"] == "gruen"


def test_fokus_spaeterer_punkt_wird_genannt():
    m, e = meeting_mit_agenda(), Entscheider(0)
    m.regel_ids = ["thema"]
    analyse.themen_auswerten(m, e, erg("vorgriff", 2), karenz_bloecke=1)
    a = ampeln(m)["Fokus"]
    assert a["farbe"] == "gelb" and "Punkt 3" in a["detail"]
    assert "Agendapunkt 3" in m.hinweise[-1].text
    assert m.hinweise[-1].punkt == 0  # gilt nur, solange Punkt 1 aktiv ist (Band, Ticket #27)
    assert m.vorschlag["punkt"] == 2


def test_fokus_ohne_regel_unsichtbar_agenda_vorschlag_bleibt():
    """Ticket #27: nicht gewählte Regeln sind unsichtbar – kein Fokus-Hinweis; der Agenda-Vorschlag („Weiter zu …?“
    als Band mit Knopf) gehört nicht zu einer Regel und bleibt."""
    m, e = meeting_mit_agenda(), Entscheider(0)
    m.regel_ids = []
    analyse.themen_auswerten(m, e, erg("vorgriff", 2), karenz_bloecke=1)
    assert m.hinweise == []
    assert m.vorschlag["punkt"] == 2
    analyse.themen_auswerten(m, e, erg("neu"), karenz_bloecke=1)
    assert m.hinweise == []


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


def test_lass_uns_zu_titel_gehen_ist_eine_ankuendigung():
    """„Lass uns zu … gehen“ ist dieselbe Ankündigungsform wie „gehen wir zu …“, nur mit vorangestelltem Ziel –
    beide zählen, ohne dass der Titel selbst ins Muster muss."""
    from coach.analyse import ankuendigung

    assert ankuendigung("Lass uns zu den Finanzen gehen.")
    assert ankuendigung("Lasst uns zum Budget wechseln.")
    assert ankuendigung("Gehen wir zum Budget.")
    # Ziel ohne Zeitwort danach ist kein Wechsel, nur ein Beitrag zum laufenden Punkt
    assert not ankuendigung("Lass uns zu dem Punkt noch kurz was dazu sagen.")


def test_frageform_haelt_die_feste_ansage_regel_nicht_auf():
    """Entscheidung: Eine Frage ist keine Ansage, auch wenn sie Ankündigungswörter wie „nächster Punkt“ enthält –
    Nestor soll den ganzen Satz bekommen, bevor irgendetwas die Agenda wechselt."""
    from coach.analyse import frageform

    assert frageform("Und was ist der nächste Punkt beim Budget?")
    assert frageform("Nestor, fass zusammen, was wir besprochen haben, und was kommt danach bei Finanzen?")
    assert not frageform("Dann kommen wir jetzt zum nächsten Punkt.")


def test_feste_ansage_regel_wechselt_nicht_bei_frage_oder_zuruf_an_nestor():
    """Ticketgrundlage (anonymisiert, andere Agenda als im Pilot): eine Frage mit „nächster Punkt“ und ein Zuruf an
    Nestor dürfen die Agenda nicht über die feste Ansage-Regel wechseln – das Werkzeug/die Aktion entscheidet."""
    import asyncio

    from coach.pipeline import Coach
    from coach.zustand import Agendapunkt, Segment

    async def ablauf():
        c = Coach()
        c._client = None
        c.meeting.agenda = [Agendapunkt(t) for t in ("Finanzen", "Projektplan", "Verschiedenes")]
        c.meeting.aktiver_punkt = 0
        c.meeting.regel_ids = []
        c.meeting.starten(virtuell=True)
        c.meeting.virtuelle_zeit = 120.0
        await c.satz(Segment("Person 1", "Nestor, fass den Punkt zusammen: was haben wir besprochen, und was ist "
                                        "der nächste Punkt beim Projektplan?", 118.0, 120.0))
        return c

    c = asyncio.run(ablauf())
    assert c.meeting.aktiver_punkt == 0
    assert not any(e["art"] == "wechsel" and e["durch"] == "ansage" for e in c.protokoll)


def test_feste_ansage_regel_wechselt_ohne_namen_weiter():
    """Dieselbe Formel ohne Frage und ohne Namen wechselt weiterhin direkt – die Regel selbst bleibt bestehen."""
    import asyncio

    from coach.pipeline import Coach
    from coach.zustand import Agendapunkt, Segment

    async def ablauf():
        c = Coach()
        c._client = None
        c.meeting.agenda = [Agendapunkt(t) for t in ("Finanzen", "Projektplan", "Verschiedenes")]
        c.meeting.aktiver_punkt = 0
        c.meeting.regel_ids = []
        c.meeting.starten(virtuell=True)
        c.meeting.virtuelle_zeit = 120.0
        await c.satz(Segment("Person 1", "Gut, dann kommen wir jetzt zum nächsten Punkt.", 118.0, 120.0))
        return c

    c = asyncio.run(ablauf())
    assert c.meeting.aktiver_punkt == 1
    assert any(e["art"] == "wechsel" and e["durch"] == "ansage" for e in c.protokoll)


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


def test_luecken_text_fuer_das_band():
    """Ticket #27: statt einer gesprochenen Nachfrage ein stiller Band-Hinweis mit Sprung zur Karte."""
    from coach.artefakte import Artefakt
    from coach.bogen import luecken_text

    a = Artefakt(1, "aufgabe", "Validierung bauen", bis="Freitag")
    b = Artefakt(2, "aufgabe", "Import durchführen")
    c = Artefakt(3, "aufgabe", "Text schreiben", wer="Sofie")
    d = Artefakt(4, "entscheidung", "Variante B", status="vorschlag", wer="Runde")
    assert luecken_text([a, b, c, d]) == "2 Aufgaben ohne Verantwortliche · 1 ohne Termin · 1 weitere Lücke"


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
