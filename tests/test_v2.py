"""Tests für die Bausteine von Version 2 – ohne Netzwerk und ohne Sprachmodelle."""

import numpy as np

from coach import analyse
from coach.hoeren import nach_16k, person_name
from coach.livetext import Zuordnung
from coach.stimmen import Personenregister, normiert
from coach.zustand import Agendapunkt, Meeting


def vek(*werte):
    return normiert(np.array(werte, dtype=float))


# --- Personenregister ------------------------------------------------------

def test_gleiche_stimme_bleibt_eine_person_andere_wird_neu():
    r = Personenregister(schwelle=0.84)
    a, a2, b = vek(1, 0, 0), vek(0.97, 0.2, 0), vek(0, 1, 0)
    assert r.zuordnen(a, 5)[0] == 0
    assert r.zuordnen(a2, 5)[0] == 0  # Ähnlichkeit ~0,98
    assert r.zuordnen(b, 5)[0] == 1
    assert r.sekunden == [10, 5]


def test_mischung_zweier_bekannter_stimmen():
    r = Personenregister(schwelle=0.84)
    r.zuordnen(vek(1, 0, 0), 20)
    r.zuordnen(vek(0, 1, 0), 20)
    gemischt = vek(1, 1, 0)  # ~0,71 zu beiden
    klar = vek(1, 0.05, 0)
    assert r.mischung([klar, gemischt, gemischt], max_sicher=0.75, zweit_min=0.55) == [1, 2]


def test_mischung_erst_ab_zwei_gut_bekannten_personen():
    r = Personenregister(schwelle=0.84)
    r.zuordnen(vek(1, 0, 0), 20)
    r.zuordnen(vek(0, 1, 0), 3)  # zu wenig Material
    assert r.mischung([vek(1, 1, 0)], 0.75, 0.55) == []


# --- Live-Text: Zuordnung der API-Ereignisse zu Äußerungen -----------------

def test_fertiger_text_vor_commit_bestaetigung():
    z = Zuordnung()
    z.commit_gesendet({"id": 1})
    assert z.fertig("item_a", "Hallo") is None
    assert z.commit_bestaetigt("item_a") == ({"id": 1}, "Hallo")


def test_reihenfolge_mehrerer_commits():
    z = Zuordnung()
    z.commit_gesendet({"id": 1})
    z.commit_gesendet({"id": 2})
    assert z.commit_bestaetigt("x") is None
    assert z.commit_bestaetigt("y") is None
    assert z.fertig("y", "zwei") == ({"id": 2}, "zwei")
    assert z.fertig("x", "eins") == ({"id": 1}, "eins")


# --- Hörstrom-Hilfen -------------------------------------------------------

def test_24k_nach_16k():
    a = np.sin(np.linspace(0, 20, 2400)).astype(np.float32)
    b = nach_16k(a)
    assert len(b) == 1600 and b.dtype == np.float32
    assert person_name(0) == "Person 1" and person_name(None) == "Person ?"


# --- Überlappung über Stimmen-Mischung -------------------------------------

def test_ueberlappungsampel_durch_mischung_und_zurueck():
    m = Meeting(agenda=[Agendapunkt("A")])
    m.starten(virtuell=True)
    m.mischungen = [10.0]
    m.virtuelle_zeit = 20

    def farbe():
        return {a["name"]: a["farbe"] for a in analyse.prozess_ampeln(
            m, monolog_sekunden=60, karenz_bloecke=1, zeit_rot_prozent=10,
            ueberlappung_min=0.5, ueberlappung_halte=30, themen_aktiv=True)}["Sprecherüberlappung"]

    assert farbe() == "gelb"
    m.virtuelle_zeit = 45
    assert farbe() == "gruen"


# --- Live-Bild (One-Pager) -----------------------------------------------

def test_meeting_text_enthaelt_agenda_status_und_transkript():
    from coach.onepager import meeting_text
    from coach.zustand import Segment

    m = Meeting(titel="T", agenda=[Agendapunkt("A"), Agendapunkt("B")])
    m.starten(virtuell=True)
    m.transkript = [Segment("Person 1", "Hallo Welt", 5, 7)]
    m.virtuelle_zeit = 8
    text = meeting_text(m)
    assert "1. A [aktuell]" in text and "2. B [offen]" in text and "[0:05] Person 1: Hallo Welt" in text


def test_bildwunsch_waehrend_des_zeichnens_wird_nachgeholt(monkeypatch):
    import asyncio

    from coach import bild_gpt
    from coach.pipeline import Coach
    from coach.zustand import Segment

    aufrufe = []

    async def attrappe(client, meeting, vorher=None, fokus=None, *, wahl):
        aufrufe.append(vorher)
        await asyncio.sleep(0.05)
        return {"analyse": "a", "png": b"test-png"}

    monkeypatch.setattr(bild_gpt, "erzeugen", attrappe)
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda eintrag: None)  # Kostenprotokoll sauber halten

    async def ablauf():
        c = Coach()
        c.stufe_setzen("premium")
        c._client = object()  # kein Netzwerk: Bild-KI ist vollständig durch die Attrappe ersetzt
        c.meeting.starten(virtuell=True)
        c.meeting.transkript = [Segment("Person 1", "Hallo", 0, 1)]
        assert c.onepager_starten() is True
        assert c.onepager_starten() is False  # läuft schon → wird vorgemerkt
        for _ in range(200):
            if not c._onepager_laeuft and len(aufrufe) >= 2:
                break
            await asyncio.sleep(0.01)
        return c

    c = asyncio.run(ablauf())
    assert len(aufrufe) == 2 and c.onepager_version == 2 and c.onepager_png == b"test-png"
    # das zweite Bild schreibt das erste fort
    assert aufrufe[0] is None and aufrufe[1]["analyse"] == "a" and aufrufe[1]["png"] == b"test-png"


# --- Fenster-Zuordnung (Sprecherwechsel ohne Pause) ------------------------

def test_fenster_neue_person_erst_nach_mehreren_fenstern_und_rueckwirkend():
    r = Personenregister(schwelle=0.5)
    a, b = vek(1, 0, 0), vek(0, 1, 0)
    assert r.fenster_zuordnen([a, a, a, a], 0.75) == [0, 0, 0, 0]
    # Wechsel mitten in der Äußerung: B wird nach 3 Fenstern neue Person, rückwirkend für alle drei
    assert r.fenster_zuordnen([a, a, b, b, b, b], 0.75) == [0, 0, 1, 1, 1, 1]
    assert len(r.sekunden) == 2


def test_fenster_einzelner_ausreisser_wird_geglaettet():
    r = Personenregister(schwelle=0.5)
    a, b = vek(1, 0, 0), vek(0, 1, 0)
    r.fenster_zuordnen([a, a, a], 0.75)
    r.fenster_zuordnen([b, b, b], 0.75)
    assert r.fenster_zuordnen([a, a, b, a, a], 0.75) == [0, 0, 0, 0, 0]


def test_prompt_echo_der_transkription_wird_erkannt():
    from coach.hoeren import prompt_echo

    prompt = ("Besprechung auf Deutsch. Der Moderationsassistent heißt Nestor. Thema: Kommunal-Wahl-Check Frankfurt. "
              "Agenda: Stadtentwicklung und Gewerbeflächen (Positionen vergleichen).")
    assert prompt_echo("Besprechung auf Deutsch. Der Moderationsassistent heißt. Thema", prompt)
    assert prompt_echo("Der Moderationsassistent heißt Nestor. Thema: Kommunal-Wahl-Check Frankfurt.", prompt)
    assert not prompt_echo("Nestor, wo stehen wir gerade?", prompt)
    assert not prompt_echo("Wir brauchen mehr Gewerbeflächen in Frankfurt, das ist klar.", prompt)


# --- Segmentierung, Überlappung, Klima ---------------------------------------

def test_glaetten_entfernt_flackern():
    from coach.segmentierung import glaetten

    k = np.array([1] * 10 + [2] + [1] * 10 + [4] * 20)
    g = glaetten(k, 5)
    assert (g[:21] == 1).all() and (g[-15:] == 4).all()


def test_ueberlappung_wird_als_person_unbekannt_ausgeschnitten():
    from coach.stimmen import ausschneiden

    aus = ausschneiden([(0.0, 4.0, 0), (4.0, 8.0, 1)], [(3.5, 4.5)])
    assert aus == [(0.0, 3.5, 0), (3.5, 4.5, None), (4.5, 8.0, 1)]


def test_teilnehmerzahl_begrenzt_neue_personen():
    r = Personenregister(schwelle=0.5, max_personen=1)
    a, b = vek(1, 0, 0), vek(0, 1, 0)
    r.fenster_zuordnen([a, a, a], 0.75)
    # eine zweite, ganz andere Stimme: keine neue Person, sondern „?“ (zu unähnlich zur einzigen bekannten)
    assert r.fenster_zuordnen([b, b, b, b], 0.75) == [None, None, None, None]
    assert len(r.sekunden) == 1


def test_klima_ruhig_und_hitzig():
    from coach.unterbrechung import Aeusserung

    m = Meeting(agenda=[Agendapunkt("A")])
    m.starten(virtuell=True)
    m.virtuelle_zeit = 600
    ruhig = analyse.klima(m, [], [], [])
    assert ruhig["stufe"] == "ruhig" and ruhig["gruende"] == []
    m.ueberlappungen = [[t, t + 1.0] for t in range(430, 600, 20)]  # 9 Vorfälle in 3 min
    heiss = analyse.klima(m, [Aeusserung(0, 1, [], [-20.0] * 8)], [500.0, 550.0], [590.0])
    assert heiss["stufe"] == "hitzig" and "9× gleichzeitig gesprochen" in heiss["gruende"]
