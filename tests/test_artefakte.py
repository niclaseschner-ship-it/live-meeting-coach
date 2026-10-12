"""Meeting-Artefakte (Ticket #26, Ablauf seit #27): Vollständigkeit, Lücken-Reihenfolge, Erkennung nur bei Bedarf,
stille Zusammenfassung je Abschnitt, Schließen per Stimme (Basis-Aktion, Premium-Werkzeug) und per Klick, das
Fünf-Minuten-Band und „Nur auf Knopfdruck“."""

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
    c.stufe_setzen("premium")
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
    assert c.artefakte.aufgaben_json()[0]["wer"] == "Sofie" and c.artefakte.beschluss(1) is None


def test_keine_staendige_erkennung_mehr():
    """Ticket #27: kein Lauf je Minute Sprache – erkannt wird beim Abschnittsende und auf Anfrage."""
    async def lauf():
        c, _ = _coach({"artefakte": []})
        for i in range(8):  # 8 × 8 s Sprache
            _satz(c, "Person 1", f"Satz {i}", i * 10.0, i * 10.0 + 8)
            c.artefakte.takt()
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)
        return c

    assert asyncio.run(lauf())._client.anfragen == []


# --- Zusammenfassung beim Punktwechsel (still) -----------------------------------------------------------------
def test_bei_vollstaendigkeit_oder_ohne_regel_10_kein_band():
    voll = {"artefakte": [{"typ": "aufgabe", "was": "Alerts anpassen", "wer": "Mara", "bis": "Freitag", "zeit": "0:30",
                           "konfidenz": 0.9}]}
    c, gesagt = _coach(voll)
    _satz(c, "Mara", "Ich passe die Alerts bis Freitag an.", 30, 34)
    c.meeting.punkt_wechseln(1)
    karte = asyncio.run(c.artefakte.abschnitt_abschliessen(0, 40, "punkt"))
    assert gesagt == [] and karte["ids"] == [1] and not [h for h in c.meeting.hinweise if h.art == "luecken"]
    luecke = {"artefakte": [{"typ": "aufgabe", "was": "Alerts anpassen", "zeit": "0:30", "konfidenz": 0.9}]}
    c, gesagt = _coach(luecke, regel_ids=("zeit",))
    _satz(c, "Mara", "Die Alerts müssen angepasst werden.", 30, 34)
    c.meeting.punkt_wechseln(1)
    karte = asyncio.run(c.artefakte.abschnitt_abschliessen(0, 40, "punkt"))
    assert gesagt == [] and len(c.artefakte.liste) == 1 and not karte["luecken_zeigen"]  # erkannt wird trotzdem
    assert not [h for h in c.meeting.hinweise if h.art == "luecken"]


def test_abgelehnte_luecke_kommt_nicht_mehr_ins_band():
    c, _ = _coach({"artefakte": [{"typ": "aufgabe", "was": "Kaffeemaschine entkalken", "zeit": "0:30",
                                  "konfidenz": 0.9}]})
    _satz(c, "Tarek", "Die Kaffeemaschine müsste man mal entkalken.", 30, 34)
    asyncio.run(c.artefakte.erkennen())
    assert c.artefakte.ablehnen(1)
    karte = asyncio.run(c.artefakte.abschnitt_abschliessen(0, 40, "punkt"))
    assert karte["ids"] == [1] and not [h for h in c.meeting.hinweise if h.art == "luecken"]
    assert c.artefakte.luecken_liste() == []


def test_werkzeug_eintragen_ergaenzt_vorhandenes_und_legt_neues_an():
    """Ein Werkzeug für beide Stufen (coach/kern.py): ergänzen mit Nummer, neu mit Typ – auch Optionen."""
    from coach import kern

    c, _ = _coach()
    c.artefakte.anlegen("aufgabe", "Statusseite-Zusammenfassung erstellen")
    a = c.assistent
    erg = asyncio.run(kern.ausfuehren(a, None, "artefakt_eintragen", {"nummer": 1, "wer": "Sofie", "bis": "Freitag"}))
    asyncio.run(kern.ausfuehren(a, None, "artefakt_eintragen", {"typ": "entscheidung", "was": "Variante B nehmen"}))
    asyncio.run(kern.ausfuehren(a, None, "artefakt_eintragen", {"typ": "option", "was": "Sofa an die lange Wand"}))
    x, y, z = c.artefakte.liste
    assert erg["ok"] and erg["fehlt_noch"] == [] and "Sofie" in erg["eingetragen"]
    assert (x.wer, x.bis, x.herkunft) == ("Sofie", "Freitag", "stimme") and x.vollstaendig
    assert (y.typ, y.was, y.status, y.bestaetigt) == ("entscheidung", "Variante B nehmen", "endgueltig", True)
    assert (z.typ, z.was) == ("option", "Sofa an die lange Wand") and z.vollstaendig and "wer" not in z.kurz()


def test_entfernen_validiert_nummer_und_rueckgaengig_bringt_dasselbe_objekt_mit_alter_nummer_zurueck():
    """Ticket #79 (Nacharbeit): Rückgängig stellt die ALTE Nummer und den vollen Stand wieder her – kein neuer
    Eintrag über `eintragen`, also keine Sonderfälle in Liste/Karten/Protokoll/meeting.json."""
    c, _ = _coach()
    a = c.artefakte.anlegen("aufgabe", "Monitor ersetzen", wer="Rao", bis="Freitag")
    b = c.artefakte.anlegen("offen", "Zweiter Punkt")  # bleibt stehen, nur zur Reihenfolgen-Probe
    assert c.artefakte.entfernen(99) is None and a in c.artefakte.liste  # unbekannte Nummer: nichts passiert
    entfernt = c.artefakte.entfernen(a.id)
    assert entfernt is a and a not in c.artefakte.liste
    band = [h for h in c.meeting.hinweise if h.art == "entfernt"]
    assert len(band) == 1 and band[0].text == 'Entfernt: „Monitor ersetzen“'
    assert band[0].aktion == {"text": "Rückgängig", "rueckgaengig": {"id": a.id}}

    assert c.artefakte.rueckgaengig(999) is None  # nichts zum Rückgängigmachen
    wieder = c.artefakte.rueckgaengig(a.id)
    assert wieder is a and a.id == entfernt.id  # dasselbe Objekt, dieselbe Nummer – kein neuer Eintrag
    assert (wieder.wer, wieder.bis, wieder.typ) == ("Rao", "Freitag", "aufgabe")  # voller Stand, nicht nur „was“
    assert [x.id for x in c.artefakte.liste] == sorted(x.id for x in c.artefakte.liste)  # Reihenfolge nach Nummer
    assert c.artefakte.rueckgaengig(a.id) is None  # ein zweites Mal: schon verbraucht


def test_aendern_validiert_nummer_und_rueckgaengig_setzt_wortlaut_und_bestaetigt_zurueck():
    """Ticket #79 (Nacharbeit): Rückgängig nach `aendern` setzt nicht nur den Wortlaut zurück, sondern auch
    bestätigt/Herkunft/vage – also den vollen Stand vor der Änderung, nicht nur den Text."""
    c, _ = _coach()
    a = c.artefakte.anlegen("offen", "Alter Wortlaut")  # erkannt, noch nicht bestätigt
    assert c.artefakte.aendern(99, "Neuer Wortlaut") is None  # unbekannte Nummer
    assert c.artefakte.aendern(a.id, "   ") is None and a.was == "Alter Wortlaut"  # leer: kein Rückgängig-Band
    geaendert = c.artefakte.aendern(a.id, "Neuer Wortlaut")
    assert geaendert is a and a.was == "Neuer Wortlaut" and a.bestaetigt and a.herkunft == "stimme"
    band = [h for h in c.meeting.hinweise if h.art == "geaendert"]
    assert len(band) == 1 and band[0].aktion == {"text": "Rückgängig", "rueckgaengig": {"id": a.id}}

    wieder = c.artefakte.rueckgaengig(a.id)
    assert wieder is a and a.was == "Alter Wortlaut" and not a.bestaetigt and a.herkunft == "erkannt"
    assert c.artefakte.rueckgaengig(a.id) is None  # schon verbraucht


def test_rueckgaengig_endpunkt_nimmt_nur_die_nummer_und_liefert_404_wenn_abgelaufen():
    """Der Knopf schickt nur {"id"} an POST /api/artefakte/rueckgaengig (Ticket #79) – kein Sonderpayload."""
    from fastapi.testclient import TestClient

    from coach import server

    server.coach.artefakte = Artefakte(server.coach)
    a = server.coach.artefakte.anlegen("aufgabe", "Monitor ersetzen", wer="Rao", bis="Freitag")
    with TestClient(server.app, client=("127.0.0.1", 5000)) as t:  # lokal: ohne Zugangsschutz
        server.coach.artefakte.entfernen(a.id)
        assert server.coach.artefakte.liste == []
        r = t.post("/api/artefakte/rueckgaengig", json={"id": a.id})
        assert r.json()["ok"] and r.json()["artefakt"]["id"] == a.id
        wieder = server.coach.artefakte.liste[0]
        assert wieder.id == a.id  # dieselbe Nummer, kein neuer Eintrag
        assert (wieder.typ, wieder.was, wieder.wer, wieder.bis) == ("aufgabe", "Monitor ersetzen", "Rao", "Freitag")

        b = server.coach.artefakte.anlegen("offen", "Vorher")
        server.coach.artefakte.aendern(b.id, "Nachher")
        r2 = t.post("/api/artefakte/rueckgaengig", json={"id": b.id})
        assert r2.json()["ok"] and server.coach.artefakte.holen(b.id).was == "Vorher"

        assert t.post("/api/artefakte/rueckgaengig", json={"id": 999}).status_code == 404
        assert t.post("/api/artefakte/rueckgaengig", json={"id": a.id}).status_code == 404  # schon verbraucht


def test_werkzeug_entfernen_und_aendern_ohne_eigene_floskel():
    """Ticket #79 im Kern: sofort ausgeführt, das Ergebnis geht ans Modell – das sagt selbst, was passiert ist."""
    from coach import kern

    c, _ = _coach()
    a = c.artefakte.anlegen("aufgabe", "Monitor ersetzen")
    b = c.artefakte.anlegen("offen", "Alter Wortlaut")
    gesagt = []

    async def floskel(text, bogen=None):
        gesagt.append(text)
        return 0.0

    c.assistent.floskel_sagen = floskel
    weg = asyncio.run(kern.ausfuehren(c.assistent, None, "ergebnis_entfernen", {"nummer": a.id}))
    neu = asyncio.run(kern.ausfuehren(c.assistent, None, "ergebnis_aendern", {"nummer": b.id, "text": "Neuer Wortlaut"}))
    fehlt = asyncio.run(kern.ausfuehren(c.assistent, None, "ergebnis_entfernen", {"nummer": 999}))
    assert weg["ok"] and neu["ok"] and fehlt["ok"] is False and "999" in fehlt["fehler"]
    assert c.artefakte.liste == [b] and b.was == "Neuer Wortlaut" and gesagt == []
    assert {h.art for h in c.meeting.hinweise} == {"entfernt", "geaendert"}  # Rückgängig im Band


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

    async def lauf():
        await g._werkzeug("artefakt_eintragen", json.dumps({"nummer": 1, "wer": "Sofie", "bis": "Freitag"}), "c1")
        await asyncio.sleep(0.01)

    asyncio.run(lauf())
    a = c.artefakte.liste[0]
    assert (a.wer, a.bis) == ("Sofie", "Freitag")
    ausgabe = json.loads(gesendet[0]["item"]["output"])
    assert ausgabe["ok"] and "Sofie" in ausgabe["eingetragen"]
    assert g._abschluss  # das Modell bestätigt danach in einer Abschlussantwort, kein „Notiert“ vom System


def test_premium_werkzeuge_ergebnis_entfernen_und_aendern():
    """Ticket #79: Nummer wird validiert; was passiert ist, geht ans Modell, das es in der Abschlussantwort sagt."""
    from coach.gespraech import WERKZEUGE, Gespraech

    assert {"ergebnis_entfernen", "ergebnis_aendern"} <= {w["name"] for w in WERKZEUGE}
    c, _ = _coach()
    a = c.artefakte.anlegen("aufgabe", "Monitor ersetzen")
    b = c.artefakte.anlegen("offen", "Alter Wortlaut")
    g = Gespraech(c.assistent)
    gesendet = []

    async def senden(e):
        gesendet.append(e)

    g._senden = senden

    async def lauf():
        await g._werkzeug("ergebnis_entfernen", json.dumps({"nummer": 999}), "c1")  # unbekannte Nummer
        await g._werkzeug("ergebnis_entfernen", json.dumps({"nummer": a.id}), "c2")
        await g._werkzeug("ergebnis_aendern", json.dumps({"nummer": b.id, "text": "Neuer Wortlaut"}), "c3")
        await asyncio.sleep(0.01)

    asyncio.run(lauf())
    ausgabe = {e["item"]["call_id"]: json.loads(e["item"]["output"]) for e in gesendet}
    assert ausgabe["c1"]["ok"] is False  # unbekannte Nummer: nichts entfernt, keine Karte
    assert ausgabe["c2"]["ok"] is True and a not in c.artefakte.liste
    assert ausgabe["c3"]["ok"] is True and b.was == "Neuer Wortlaut"
    assert not any(e.get("type") == "response.create" for e in gesendet)  # die Abschlussantwort kommt erst danach
    band = {h.art for h in c.meeting.hinweise}
    assert band == {"entfernt", "geaendert"}  # keine Karte für die unbekannte Nummer


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
def test_fuenf_minuten_band_einmal_und_ein_ja_in_den_raum_wirkt_nicht():
    c, gesagt = _coach(minuten=(10, 10))
    m = c.meeting
    _satz(c, "Jonas", "Viel Gesprochenes.", 60, 70)

    async def lauf():
        for t in (800.0, 899.0, 900.0, 901.0):  # 20 min geplant → Band bei 15:00, genau einmal
            m.virtuelle_zeit = t
            c.artefakte.takt()
            await asyncio.sleep(0.01)
        await c.satz(Segment("Mara", "Ja, gerne.", 905, 906))

    asyncio.run(lauf())
    band = [h for h in m.hinweise if h.art == "fuenf"]
    assert len(band) == 1 and band[0].text == "Noch 5 Minuten" and band[0].zeit == 900.0
    assert band[0].aktion == {"text": "Zusammenfassen", "bogen": "zusammenfassen"}
    assert gesagt == [] and not c.karten  # ein bloßes „Ja“ löst nichts aus


def test_zusammenfassung_aus_den_artefakten_mit_hoechstens_drei_luecken():
    from coach import bogen as BG

    c, _ = _coach({"artefakte": [
        {"typ": "entscheidung", "was": "Wartungsfenster 30 Minuten", "status": "endgueltig", "wer": "die Runde",
         "zeit": "1:00"},
        {"typ": "aufgabe", "was": "Alerts anpassen", "wer": "Mara", "zeit": "2:00"},
        {"typ": "aufgabe", "was": "Statusseite schreiben", "zeit": "3:00"},
        {"typ": "risiko", "was": "Hänger → alle Pods raus", "wer": "Sofie", "hoch": True, "zeit": "4:00"},
        {"typ": "aufgabe", "was": "Testdaten bauen", "bis": "Montag", "zeit": "5:00"}]})
    _satz(c, "Jonas", "Viel Gesprochenes.", 60, 70)
    karte, satz = asyncio.run(BG.zusammenfassen(c, None))
    assert karte["art"] == "zusammenfassung" and karte["luecken_zeigen"]
    assert karte["punkte"][0].startswith("Entscheidung: Wartungsfenster 30 Minuten")
    luecken = [a.was for a in c.artefakte.liste if a.nachgefragt]
    # höchstens drei Lücken: ohne Wer (zwei, nach Zeit), dann ohne Termin – das hohe Risiko käme erst danach
    assert luecken == ["Alerts anpassen", "Statusseite schreiben", "Testdaten bauen"]
    assert satz.startswith("Hier ist sie.")


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
