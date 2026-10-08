"""Meeting-Artefakte (Ticket #26): Vollständigkeit, Lücken-Reihenfolge, Nachfrage beim Punktwechsel, Schließen per
Stimme (Antwort ohne Namen, Basis-Aktion, Premium-Werkzeug), die Fünf-Minuten-Frage und „Nur auf Knopfdruck“."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from coach import artefakte as A
from coach.artefakte import Artefakt, Artefakte
from coach.pipeline import Coach
from coach.zustand import Segment


class Modell:
    """Liefert die Antworten der Reihe nach (JSON) und merkt sich die Anfragen."""

    def __init__(self, *antworten: dict) -> None:
        self.antworten = list(antworten)
        self.anfragen: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.anfragen.append(kw["messages"][-1]["content"])
        antwort = self.antworten.pop(0) if self.antworten else {"artefakte": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(antwort)))],
                               usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200))


def _coach(*antworten: dict, regel_ids=("zeit", "ergebnisse"), minuten=(5, 5)) -> tuple[Coach, list[str]]:
    c = Coach()
    c._einrichten({"titel": "Incident-Review", "agenda": [{"titel": "Ursache", "minuten": minuten[0]},
                                                          {"titel": "Maßnahmen", "minuten": minuten[1]}],
                   "regel_ids": list(regel_ids)})
    c._client = Modell(*antworten)
    c.meeting.starten(virtuell=True)
    gesagt: list[str] = []

    async def sagen(text: str) -> float:
        gesagt.append(text)
        return 0.0

    c.assistent.sagen = sagen
    return c, gesagt


def _satz(c: Coach, sprecher: str, text: str, start: float, ende: float) -> Segment:
    s = Segment(sprecher, text, start, ende)
    c.meeting.transkript.append(s)
    c.meeting.virtuelle_zeit = ende
    return s


# --- Vollständigkeit ------------------------------------------------------------------------------------------
def test_vollstaendigkeit_je_typ():
    assert Artefakt(1, "aufgabe", "Alerts anpassen", wer="Mara", bis="Freitag").vollstaendig
    assert Artefakt(1, "aufgabe", "Alerts anpassen", wer="wir", bis="Freitag").luecken() == ["wer"]  # „wir“ zählt nicht
    assert Artefakt(1, "aufgabe", "Monitoring anschauen", wer="Mara", bis="Freitag", vage=True).luecken() == ["was"]
    assert Artefakt(1, "entscheidung", "Variante B", status="vorschlag", wer="die Runde").luecken() == ["status"]
    assert Artefakt(1, "entscheidung", "Variante B", status="vorlaeufig", wer="die Runde").luecken() == ["bis"]
    assert Artefakt(1, "entscheidung", "Variante B", status="endgueltig", wer="die Runde").vollstaendig
    # offener Punkt: Lücke nur, wenn weder Zuständige noch Wiedervorlage
    assert Artefakt(1, "offen", "SLI berechnen?").luecken() == ["wer", "bis"]
    assert Artefakt(1, "offen", "SLI berechnen?", bis="nächste Sitzung").vollstaendig
    assert Artefakt(1, "offen", "SLI berechnen?", erledigt=True).vollstaendig
    # Risiko: hohes Risiko ohne Maßnahme ist eine Lücke, ein kleines nicht
    assert Artefakt(1, "risiko", "Hänger → Pods fallen raus", wer="Sofie").vollstaendig
    assert Artefakt(1, "risiko", "Hänger → Pods fallen raus", wer="Sofie", hoch=True).luecken() == ["reaktion"]


def test_luecken_reihenfolge_ohne_wer_dann_ohne_termin_dann_entscheidungen_und_hohe_risiken():
    art = Artefakte()
    risiko = art.anlegen("risiko", "SLI gefährdet", wer="Mara", hoch=True, zeit=10)
    entsch = art.anlegen("entscheidung", "Wartungsfenster 30 min", status="vorschlag", wer="die Runde", zeit=20)
    ohne_bis = art.anlegen("aufgabe", "Alerts anpassen", wer="Mara", zeit=30)
    ohne_wer = art.anlegen("aufgabe", "Statusseite schreiben", bis="Freitag", zeit=40)
    art.anlegen("aufgabe", "Template schicken", wer="Tarek", bis="Montag", zeit=5)  # vollständig
    abgelehnt = art.anlegen("aufgabe", "Kaffeemaschine entkalken", zeit=1)
    abgelehnt.abgelehnt = True
    art.anlegen("aufgabe", "Etwas Unsicheres", zeit=2, konfidenz=0.45)  # unsicher: nicht nachfragen
    assert [a.id for a in art.luecken_liste(3)] == [ohne_wer.id, ohne_bis.id, risiko.id]
    assert [a.id for a in art.luecken_liste(9)] == [ohne_wer.id, ohne_bis.id, risiko.id, entsch.id]


# --- Erkennung ------------------------------------------------------------------------------------------------
def test_erkennung_ergaenzt_statt_doppelt_und_kennt_quelle_und_agendapunkt():
    c, _ = _coach(
        {"artefakte": [{"nummer": None, "typ": "aufgabe", "was": "Zusammenfassung für die Statusseite erstellen",
                        "zeit": "1:10", "konfidenz": 0.9, "zitat": "Außerdem muss noch eine Zusammenfassung …"},
                       {"typ": "aufgabe", "was": "Nestor fragt etwas", "konfidenz": 0.2}]},  # zu unsicher
        {"artefakte": [{"nummer": 1, "wer": "Sofie", "bis": "Freitag"},
                       {"typ": "aufgabe", "was": "Zusammenfassung Statusseite erstellen", "wer": "Sofie"}]})
    m = c.meeting
    m.punkt_wechseln(1)
    m.punkt_beginne[-1] = (1, 60.0)
    _satz(c, "Jonas", "Außerdem muss noch eine Zusammenfassung für die Statusseite erstellt werden.", 70, 75)
    asyncio.run(c.artefakte.erkennen())
    a = c.artefakte.liste[0]
    assert len(c.artefakte.liste) == 1 and a.luecken() == ["wer", "bis"]
    assert a.zeit == 70 and a.sprecher == "Jonas" and a.punkt == 1 and a.zitat.startswith("Außerdem")
    _satz(c, "Sofie", "Mach ich bis Freitag.", 80, 82)
    asyncio.run(c.artefakte.erkennen())
    assert len(c.artefakte.liste) == 1 and a.wer == "Sofie" and a.bis == "Freitag" and a.vollstaendig
    assert "1. Aufgabe: Zusammenfassung für die Statusseite erstellen" in c._client.anfragen[1]  # mit Nummer
    assert c.meeting.ergebnisse[1]["aufgaben"] == [
        {"was": "Zusammenfassung für die Statusseite erstellen", "wer": "Sofie", "bis": "Freitag"}]


def test_erkennung_laeuft_je_minute_sprache_und_nicht_auf_knopfdruck():
    async def lauf(knopfdruck: bool):
        c, _ = _coach({"artefakte": []})
        c.modus = "knopfdruck" if knopfdruck else "live"
        for i in range(8):  # 8 × 8 s Sprache
            _satz(c, "Person 1", f"Satz {i}", i * 10.0, i * 10.0 + 8)
            c.artefakte.takt()
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)
        return c

    live = asyncio.run(lauf(False))
    assert len(live._client.anfragen) == 1  # nach 64 s Sprache ein Lauf, nicht je Satz
    assert asyncio.run(lauf(True))._client.anfragen == []  # Nur auf Knopfdruck: nichts von selbst


# --- Prüfung beim Punktwechsel --------------------------------------------------------------------------------
def test_nachfrage_beim_punktwechsel_gebuendelt_und_einmalig():
    c, gesagt = _coach({"artefakte": [
        {"typ": "aufgabe", "was": "Statusseite-Zusammenfassung erstellen", "zeit": "0:30", "konfidenz": 0.9},
        {"typ": "entscheidung", "was": "Wartungsfenster 30 Minuten", "status": "endgueltig", "wer": "die Runde",
         "zeit": "0:40", "konfidenz": 0.9}]})
    _satz(c, "Jonas", "Außerdem muss noch eine Statusseite-Zusammenfassung erstellt werden.", 30, 36)
    m = c.meeting

    async def lauf():
        m.punkt_wechseln(1)
        await c.artefakte.punkt_abgeschlossen(0)
        erste = list(gesagt)
        m.punkt_wechseln(0)
        await c.artefakte.punkt_abgeschlossen(1)
        m.punkt_wechseln(1)
        await c.artefakte.punkt_abgeschlossen(0)
        return erste

    erste = asyncio.run(lauf())
    assert erste == ["Kurz zu „Ursache“: Ich hab notiert: Statusseite-Zusammenfassung erstellen. "
                     "Wer übernimmt das, bis wann?"]  # die vollständige Entscheidung: kein Wort dazu
    assert gesagt == erste  # dieselbe Lücke wird nicht noch einmal erfragt
    assert c.artefakte.rueckfrage.ids == [1]


def test_bei_vollstaendigkeit_und_ohne_regel_10_schweigt_nestor():
    voll = {"artefakte": [{"typ": "aufgabe", "was": "Alerts anpassen", "wer": "Mara", "bis": "Freitag", "zeit": "0:30"}]}
    c, gesagt = _coach(voll)
    _satz(c, "Mara", "Ich passe die Alerts bis Freitag an.", 30, 34)
    c.meeting.punkt_wechseln(1)
    asyncio.run(c.artefakte.punkt_abgeschlossen(0))
    assert gesagt == [] and c.artefakte.rueckfrage is None
    luecke = {"artefakte": [{"typ": "aufgabe", "was": "Alerts anpassen", "zeit": "0:30"}]}
    c, gesagt = _coach(luecke, regel_ids=("zeit",))
    _satz(c, "Mara", "Die Alerts müssen angepasst werden.", 30, 34)
    c.meeting.punkt_wechseln(1)
    asyncio.run(c.artefakte.punkt_abgeschlossen(0))
    assert gesagt == [] and len(c.artefakte.liste) == 1  # erkannt wird trotzdem


# --- Lücken schließen per Stimme ------------------------------------------------------------------------------
def test_antwort_ohne_namen_schliesst_die_luecke_mit_kurzer_bestaetigung():
    c, gesagt = _coach({"artefakte": [{"typ": "aufgabe", "was": "Statusseite-Zusammenfassung erstellen",
                                       "zeit": "0:30"}]},
                       {"eintraege": [{"nummer": 1, "wer": "Sofie", "bis": "Freitag"}], "abgelehnt": []})
    _satz(c, "Jonas", "Außerdem muss noch eine Statusseite-Zusammenfassung erstellt werden.", 30, 36)
    beantwortet = []

    async def assistent_satz(text, ende):
        beantwortet.append(text)

    c.assistent.satz = assistent_satz

    async def lauf():
        c.meeting.punkt_wechseln(1)
        await c.artefakte.punkt_abgeschlossen(0)
        await c.satz(Segment("Jonas", "Sofie übernimmt die Statusseite bis Freitag.", 40, 43))

    asyncio.run(lauf())
    a = c.artefakte.liste[0]
    assert (a.wer, a.bis, a.bestaetigt, a.herkunft) == ("Sofie", "Freitag", True, "stimme") and a.vollstaendig
    assert gesagt[-1] == "Eingetragen: Sofie, bis Freitag."
    assert beantwortet == []  # die Antwort ging nicht zusätzlich an Nestors Ansprache
    assert c.artefakte.rueckfrage is None


def test_abgelehnte_nachfrage_wird_nicht_wiederholt():
    c, gesagt = _coach({"artefakte": [{"typ": "aufgabe", "was": "Kaffeemaschine entkalken", "zeit": "0:30"}]},
                       {"eintraege": [], "abgelehnt": [1]})
    _satz(c, "Tarek", "Die Kaffeemaschine müsste man mal entkalken.", 30, 34)

    async def lauf():
        c.meeting.punkt_wechseln(1)
        await c.artefakte.punkt_abgeschlossen(0)
        await c.artefakte.satz(Segment("Tarek", "Nee, brauchen wir nicht.", 40, 42))
        return c.artefakte.zusammenfassung()

    text, _, luecken = asyncio.run(lauf())
    assert c.artefakte.liste[0].abgelehnt and gesagt[-1] == "Okay, frag ich nicht mehr."
    assert luecken == [] and "Kaffeemaschine" not in text  # auch am Ende nicht mehr


def test_basis_aktion_eintragen():
    from coach.assistent import aktion_lesen

    aktion = aktion_lesen("AKTION: eintragen 1; wer=Sofie; bis=Freitag")
    assert aktion == {"typ": "eintragen", "daten": {"nummer": 1, "wer": "Sofie", "bis": "Freitag"}}
    c, _ = _coach()
    c.artefakte.anlegen("aufgabe", "Statusseite-Zusammenfassung erstellen")
    asyncio.run(c.assistent_aktion(aktion))
    neu = aktion_lesen("AKTION: eintragen neu entscheidung; was=Variante B nehmen")
    asyncio.run(c.assistent_aktion(neu))
    a, b = c.artefakte.liste
    assert (a.wer, a.bis, a.herkunft) == ("Sofie", "Freitag", "stimme") and a.vollstaendig
    assert (b.typ, b.was, b.status, b.bestaetigt) == ("entscheidung", "Variante B nehmen", "endgueltig", True)


def test_premium_werkzeug_artefakt_eintragen():
    from coach.gespraech import WERKZEUGE, Gespraech

    assert any(w["name"] == "artefakt_eintragen" for w in WERKZEUGE)
    c, _ = _coach()
    c.artefakte.anlegen("aufgabe", "Statusseite-Zusammenfassung erstellen")
    g = Gespraech(c.assistent)
    gesendet = []

    async def senden(e):
        gesendet.append(e)

    g._senden = senden
    asyncio.run(g._werkzeug("artefakt_eintragen", json.dumps({"nummer": 1, "wer": "Sofie", "bis": "Freitag"}), "c1"))
    a = c.artefakte.liste[0]
    assert (a.wer, a.bis) == ("Sofie", "Freitag")
    ausgabe = json.loads(gesendet[0]["item"]["output"])
    assert ausgabe["ok"] and ausgabe["bestaetigung"] == "Eingetragen: Sofie, bis Freitag."
    assert gesendet[-1] == {"type": "response.create"}  # Nestor bestätigt kurz


def test_klick_und_bearbeiten_im_dashboard():
    from fastapi.testclient import TestClient

    from coach import server

    server.coach.artefakte = Artefakte(server.coach)
    a = server.coach.artefakte.anlegen("aufgabe", "Alerts anpassen")
    with TestClient(server.app, client=("127.0.0.1", 5000)) as t:  # lokal: ohne Zugangsschutz
        assert t.post("/api/artefakte/bearbeiten", json={"id": a.id, "wer": "Mara", "bis": "Freitag"}).json()["ok"]
        assert t.post("/api/artefakte/neu", json={"typ": "offen", "was": "SLI berechnen?", "bis": "Montag"}).json()["ok"]
        assert t.post("/api/artefakte/ablehnen", json={"id": a.id}).json()["ok"]
        assert t.post("/api/artefakte/bearbeiten", json={"id": 99, "wer": "x"}).status_code == 404
    assert a.vollstaendig and a.bestaetigt and a.herkunft == "hand"
    assert [x.typ for x in server.coach.artefakte.liste] == ["aufgabe", "offen"]


# --- Fünf Minuten vor Schluss ---------------------------------------------------------------------------------
def test_fuenf_minuten_frage_und_zusammenfassung_bei_ja():
    c, gesagt = _coach({"artefakte": [
        {"typ": "entscheidung", "was": "Wartungsfenster 30 Minuten", "status": "endgueltig", "wer": "die Runde",
         "zeit": "1:00"},
        {"typ": "aufgabe", "was": "Alerts anpassen", "wer": "Mara", "zeit": "2:00"},
        {"typ": "aufgabe", "was": "Statusseite schreiben", "zeit": "3:00"},
        {"typ": "risiko", "was": "Hänger → alle Pods raus", "wer": "Sofie", "hoch": True, "zeit": "4:00"},
        {"typ": "aufgabe", "was": "Testdaten bauen", "bis": "Montag", "zeit": "5:00"}]}, minuten=(10, 10))
    m = c.meeting
    _satz(c, "Jonas", "Viel Gesprochenes.", 60, 70)
    fragen = []

    async def lauf():
        for t in (800.0, 899.0, 900.0, 901.0):  # 20 min geplant → Frage bei 15:00, genau einmal
            m.virtuelle_zeit = t
            c.artefakte.takt()
            await asyncio.sleep(0.01)
            fragen.append(c.artefakte.rueckfrage.art if c.artefakte.rueckfrage else None)
        await c.satz(Segment("Mara", "Ja, gerne.", 905, 906))

    asyncio.run(lauf())
    assert fragen == [None, None, "fuenf_minuten", "fuenf_minuten"]
    assert gesagt[0] == "Noch fünf Minuten. Soll ich zusammenfassen und die letzten Aufgaben verteilen?"
    text = gesagt[1]
    assert text.startswith("Kurz zusammengefasst: Entschieden habt ihr Wartungsfenster 30 Minuten.")
    # höchstens drei Lücken: ohne Wer (zwei, nach Zeit), dann ohne Termin – das hohe Risiko käme erst danach
    assert text.index("Statusseite schreiben") < text.index("Testdaten bauen") < text.index("Alerts anpassen")
    assert "Hänger" not in text
    karte = c.karten[-1]
    assert karte["art"] == "zusammenfassung" and "Entschieden: Wartungsfenster 30 Minuten" in karte["punkte"]
    assert c.artefakte.rueckfrage.art == "nachfrage" and len(c.artefakte.rueckfrage.ids) == 3


def test_fuenf_minuten_frage_nein_bleibt_still_und_kommt_nicht_wieder():
    c, gesagt = _coach(minuten=(10, 10))

    async def lauf():
        c.meeting.virtuelle_zeit = 900.0
        c.artefakte.takt()
        await asyncio.sleep(0.01)
        await c.artefakte.satz(Segment("Mara", "Nein, danke.", 903, 904))
        c.meeting.virtuelle_zeit = 950.0
        c.artefakte.takt()
        await asyncio.sleep(0.01)

    asyncio.run(lauf())
    assert len(gesagt) == 1 and c.artefakte.rueckfrage is None


def test_standardgliederung_und_aufgaben_fuer_den_export():
    c, _ = _coach()
    art = c.artefakte
    art.anlegen("entscheidung", "Wartungsfenster 30 Minuten", status="endgueltig", wer="die Runde", punkt=1)
    art.anlegen("aufgabe", "Statusseite schreiben", punkt=1, zitat="Außerdem muss noch …", zeit=671)
    art.anlegen("offen", "Kaffeemaschine?", ausserhalb=True)
    g = art.standardgliederung()
    assert g["format"] == "nestor-meeting/1" and g["kopf"]["titel"] == "Incident-Review"
    assert g["entscheidungen"][0]["agendapunkt_titel"] == "Maßnahmen"
    assert g["aufgaben"][0]["luecken"] == ["wer", "bis"] and g["aufgaben"][0]["quelle"]["zeit_text"] == "11:11"
    assert g["parkplatz"][0]["was"] == "Kaffeemaschine?" and g["offene_punkte"] == []
    assert [p["titel"] for p in g["agenda"]] == ["Ursache", "Maßnahmen"] and g["luecken"] == 2
    assert art.aufgaben_json() == [{"id": 2, "was": "Statusseite schreiben", "wer": None, "bis": None,
                                    "luecken": ["wer", "bis"], "bestaetigt": False, "konfidenz": 0.7,
                                    "agendapunkt": 2, "quelle": {"zeit_text": "11:11", "satz": "Außerdem muss noch …"}}]


def test_ergebnisse_ampel_zeigt_offene_luecken_nach_nachfrage():
    c, _ = _coach()
    a = c.artefakte.anlegen("aufgabe", "Alerts anpassen")
    _satz(c, "Mara", "x", 0, 1)
    ampel = lambda: next(r for r in c.schnappschuss()["regel_status"] if r["id"] == "ergebnisse")  # noqa: E731
    assert ampel()["farbe"] == "gruen" and ampel()["detail"] == "1 festgehalten"
    a.nachgefragt = True
    assert ampel()["farbe"] == "gelb" and ampel()["detail"] == "1 Lücke offen"
    a.abgelehnt = True
    assert ampel()["farbe"] == "gruen"


def test_normalisieren_und_aehnlich():
    e = A.normalisieren({"typ": "Beschluss", "was": " Variante B. ", "status": "endgültig", "wer": "null",
                         "zeit": "12:34", "konfidenz": "0.8"})
    assert (e["typ"], e["was"], e["status"], e["wer"], e["zeit"], e["konfidenz"]) == (
        "entscheidung", "Variante B", "endgueltig", None, 754, 0.8)
    assert A.normalisieren({"typ": "unsinn", "was": "x"}) is None
    assert A.inhaltsleer("das übernehmen") and A.inhaltsleer("bis wann ungefähr")
    assert not A.inhaltsleer("Protokoll verschicken") and not A.inhaltsleer("das Protokoll verschicken")
    assert A.aehnlich("Zusammenfassung für die Statusseite erstellen", "Statusseite-Zusammenfassung erstellen")
