"""Premium im Gespräch ohne Vorklassifikation – ohne Netz, mit einer Attrappe der Realtime-Verbindung.

Geprüft wird der Ablauf, nicht das Sprachverständnis: Gesprächszug (Segmente bis zur Pause werden eine Anfrage),
Hörfenster mit Sätzen anderer Sprecher, Werkzeug-Prüfung, Schranken (eine Werkzeugrunde, eine Abschlussantwort,
Frist), Bereichs-Zusammenfassung und die Leitplanke Halt. Die Grenzfälle sind umformulierte Fälle aus einem
Pilottest (andere Themen, andere Agenda): eine zerlegte Bitte ums Zusammenfassen, „fass den Punkt zusammen … und
was ist der nächste Punkt“, eine Recherche über zwei Sätze, „bereite das anders auf“ und „fürs Protokoll: …“.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from coach import bogen as BG
from coach import gespraechszug as GZ
from coach import werkzeuge as W
from coach.artefakte import Artefakt
from coach.config import EINST
from coach.gespraech import Gespraech
from coach.pipeline import Coach
from coach.zustand import Agendapunkt, Meeting, Segment


@pytest.fixture(autouse=True)
def umgebung(monkeypatch):
    felder = {"assistent_modus": "gespraech", "nachfrage_sekunden": 8.0, "zug_pause_sekunden": 0.3,
              "zug_max_warten": 3.0, "bestaetigung": False, "stimme_aus": True}
    alt = {k: getattr(EINST, k) for k in felder}
    for k, v in felder.items():
        object.__setattr__(EINST, k, v)
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)
    monkeypatch.setattr("coach.pipeline._zeit_loggen", lambda e: None)
    yield
    for k, v in alt.items():
        object.__setattr__(EINST, k, v)


class Verbindung:
    def __init__(self):
        self.gesendet: list[dict] = []

    async def send(self, roh: str) -> None:
        self.gesendet.append(json.loads(roh))

    async def close(self) -> None:
        pass

    def typen(self) -> list[str]:
        return [e["type"] for e in self.gesendet]

    def anfragen(self) -> list[str]:
        return [e["item"]["content"][0]["text"] for e in self.gesendet
                if e["type"] == "conversation.item.create" and e["item"].get("type") == "message"]

    def ausgaben(self) -> list[dict]:
        return [json.loads(e["item"]["output"]) for e in self.gesendet
                if e["type"] == "conversation.item.create" and e["item"].get("type") == "function_call_output"]


def _coach(agenda=("Finanzen", "Projektplan", "Verschiedenes")) -> tuple[Coach, Gespraech, Verbindung]:
    c = Coach()
    c.stufe_setzen("premium")
    c._einrichten({"titel": "Vereinsabend", "agenda": [{"titel": t, "minuten": 10} for t in agenda]})
    c.meeting.starten(virtuell=True)
    c.meeting.virtuelle_zeit = 100.0
    g = Gespraech(c.assistent)
    g._ws = Verbindung()
    g.offen = True
    c.assistent.gespraech = g
    return c, g, g._ws


async def _bis_bogen(c: Coach, sekunden: float = 3.0):
    for _ in range(int(sekunden / 0.02)):
        if c.assistent.bogen is not None:
            await asyncio.sleep(0.02)
            return c.assistent.bogen
        await asyncio.sleep(0.02)
    return None


async def _fertig(c: Coach, g: Gespraech, b) -> None:
    """Die (Abschluss-)Antwort des Modells ist da, ohne Ton."""
    await g._antwort_fertig({})
    await asyncio.wait_for(b.task, 3)


def _artefakt(nr, typ, was, zeit, punkt, status=None) -> Artefakt:
    return Artefakt(nr, typ, was, wer="Jonas" if typ == "aufgabe" else None, bis="Freitag" if typ == "aufgabe" else None,
                    status=status, zeit=zeit, punkt=punkt, konfidenz=0.9)


# --- Gesprächszug als reine Logik --------------------------------------------------------------------------------
def test_zug_fuehrt_segmente_desselben_sprechers_zu_einer_anfrage_zusammen():
    z = GZ.Zug("ansprache", True, "Person 1", 0.0, [GZ.Teil("Person 1", "kannst du uns nochmal zusammenfassen", 10, 12)])
    z.dazu(GZ.Teil("Person 1", "was wir bis jetzt beschlossen haben", 12.4, 14), 1.0)
    assert z.anfrage() == "kannst du uns nochmal zusammenfassen was wir bis jetzt beschlossen haben"
    assert z.ende == 14


def test_zug_mit_anderem_sprecher_nennt_die_sprecher():
    z = GZ.Zug("hoerfenster", False, "Person 2", 0.0, [GZ.Teil("Person 2", "Und bis wann?", 10, 11)])
    z.dazu(GZ.Teil("Mara", "Das klären wir nachher.", 11.2, 12.5), 0.5)
    assert z.anfrage() == "Person 2: Und bis wann?\nMara: Das klären wir nachher."
    assert GZ.fuer_modell(z.anfrage(), z.gerichtet).startswith(GZ.OHNE_NAMEN)
    assert GZ.fuer_modell("Wo stehen wir?", True) == "Wo stehen wir?"


def test_zug_endet_mit_der_pause_nicht_solange_jemand_spricht_und_spaetestens_nach_der_hoechstzeit():
    z = GZ.Zug("ansprache", True, "Person 1", 50.0, [GZ.Teil("Person 1", "fass zusammen", 10, 12)])
    assert not z.fertig(12.5, 50.5, False, 1.2, 6.0)      # erst 0,5 s Pause
    assert z.fertig(13.3, 51.0, False, 1.2, 6.0)          # 1,3 s Pause
    assert not z.fertig(13.3, 51.0, True, 1.2, 6.0)       # jemand spricht gerade (Teiltext)
    assert z.fertig(13.3, 56.1, True, 1.2, 6.0)           # zu lange gewartet
    for i in range(GZ.HOECHSTENS_SAETZE - 1):
        z.dazu(GZ.Teil("Mara", f"Satz {i}", 13 + i, 13.5 + i), 50.0)
    assert z.fertig(0.0, 50.0, True, 1.2, 6.0)            # zu viele Sätze


def test_hoerfenster_zaehlt_den_beginn_des_satzes():
    assert GZ.im_hoerfenster(start=105.0, ende=109.0, ab=99.0, bis=108.0)
    assert not GZ.im_hoerfenster(start=108.5, ende=110.0, ab=99.0, bis=108.0)  # zu spät begonnen
    assert not GZ.im_hoerfenster(start=90.0, ende=95.0, ab=99.0, bis=108.0)    # vor Nestors Antwort
    assert not GZ.im_hoerfenster(start=105.0, ende=106.0, ab=-1e9, bis=-1e9)   # kein Fenster


# --- Werkzeug-Prüfung ----------------------------------------------------------------------------------------------
def _pruefen(name, arg, gerichtet=True):
    return W.pruefen(name, arg, nummern={1, 2, 3}, agenda=3, aktiver_punkt=1, jetzt=900.0, gerichtet=gerichtet)


def test_werkzeug_pruefung_nummer_und_punkt_muessen_existieren():
    assert _pruefen("ergebnis_entfernen", {"nummer": 2})[1] is None
    assert "Nummer 7" in _pruefen("ergebnis_entfernen", {"nummer": 7})[1]
    assert "vorhanden: 1, 2, 3" in _pruefen("ergebnis_aendern", {"nummer": 9, "text": "x"})[1]
    assert _pruefen("ergebnis_aendern", {"nummer": 1, "text": " "})[1] == "Der neue Wortlaut fehlt."
    assert _pruefen("artefakt_eintragen", {"typ": "aufgabe", "was": "Flyer drucken"})[1] is None  # Neues ohne Nummer
    assert "Nummer 5" in _pruefen("artefakt_eintragen", {"nummer": 5, "wer": "Mara"})[1]
    assert _pruefen("agendapunkt_wechseln", {"nummer": 3})[1] is None
    assert "Agendapunkt 4" in _pruefen("agendapunkt_wechseln", {"nummer": 4})[1]
    assert _pruefen("gibt_es_nicht", {})[1]


def test_werkzeug_pruefung_zusammenfassen_bereich():
    assert _pruefen("zusammenfassen", {"bereich": "punkt"}) == ({"bereich": "punkt", "punkt": 2}, None)  # aktueller
    assert _pruefen("zusammenfassen", {"bereich": "punkt", "punkt": 1}) == ({"bereich": "punkt", "punkt": 1}, None)
    assert "Agendapunkt 6" in _pruefen("zusammenfassen", {"bereich": "punkt", "punkt": 6})[1]
    assert _pruefen("zusammenfassen", {"bereich": "seit", "seit": "12:30"}) == ({"bereich": "seit", "seit": 750}, None)
    assert _pruefen("zusammenfassen", {"bereich": "seit", "seit": "20:00"})[1]  # liegt nach „jetzt“
    assert _pruefen("zusammenfassen", {"bereich": "seit", "seit": "gestern"})[1]
    assert _pruefen("zusammenfassen", {"bereich": "alles"})[1]
    ohne_agenda = W.pruefen("zusammenfassen", {"bereich": "punkt"}, nummern=set(), agenda=0, aktiver_punkt=0,
                            jetzt=10.0)
    assert ohne_agenda == ({"bereich": "gesamt"}, None)


def test_werkzeug_pruefung_karte_und_nicht_an_mich():
    arg, fehler = _pruefen("karte", {"titel": "Vergleich", "punkte": ["a", " ", "b"] + ["x"] * 20})
    assert fehler is None and arg["titel"] == "Vergleich" and arg["punkte"][:2] == ["a", "b"]
    assert len(arg["punkte"]) == W.KARTE_HOECHSTENS
    assert _pruefen("karte", {"titel": "", "punkte": ["a"]})[1]
    assert _pruefen("nicht_an_mich", {}, gerichtet=True)[1]          # direkt angesprochen: antworten
    assert _pruefen("nicht_an_mich", {}, gerichtet=False)[1] is None  # Hörfenster: das Modell darf schweigen
    assert _pruefen("auftrag_abbrechen", {"art": "recherche"})[1] is None
    assert _pruefen("auftrag_abbrechen", {"art": "kaffee"})[1]


def test_werkzeug_katalog_enthaelt_die_neuen_werkzeuge_und_keine_statusabfrage():
    for name in ("zusammenfassen", "karte", "nicht_an_mich", "auftrag_abbrechen"):
        assert name in W.NAMEN
    assert "status_abfragen" not in W.NAMEN
    assert set(W.SYSTEM_SPRICHT) <= W.NAMEN and set(W.ABSCHLUSS) <= W.NAMEN


# --- Bereichs-Zusammenfassung ----------------------------------------------------------------------------------
def test_bereich_waehlen_nach_punkt_seit_und_gesamt():
    m = Meeting(agenda=[Agendapunkt("Finanzen"), Agendapunkt("Projektplan")])
    m.starten(virtuell=True)
    m.transkript = [Segment("Person 1", "Zu den Finanzen.", 10, 12), Segment("Person 2", "Zum Projektplan.", 70, 72)]
    m.virtuelle_zeit = 60.0
    m.punkt_wechseln(1)
    m.virtuelle_zeit = 120.0
    liste = [_artefakt(1, "entscheidung", "Beitrag bleibt gleich", 20, 0, "endgueltig"),
             _artefakt(2, "aufgabe", "Zeitplan verschicken", 80, 1)]
    titel, art, saetze = BG.bereich_waehlen(m, liste, "punkt", 1)
    assert titel == "Zusammenfassung · Punkt 1 · Finanzen" and [a.id for a in art] == [1]
    assert [s.text for s in saetze] == ["Zu den Finanzen."]
    titel, art, saetze = BG.bereich_waehlen(m, liste, "seit", seit=65)
    assert titel == "Zusammenfassung · seit 1:05" and [a.id for a in art] == [2] and len(saetze) == 1
    titel, art, _ = BG.bereich_waehlen(m, liste, "gesamt")
    assert titel.startswith("Zusammenfassung · Stand") and len(art) == 2


def test_zusammenfassung_auswahl_beschlossenes_zuerst():
    liste = [_artefakt(1, "aufgabe", "Flyer", 1, 0), _artefakt(2, "entscheidung", "Termin steht", 2, 0, "endgueltig"),
             _artefakt(3, "entscheidung", "Vielleicht Grillen", 3, 0, "vorschlag"), _artefakt(4, "offen", "Ort?", 4, 0)]
    assert [a.id for a in BG.zusammenfassung_auswahl(liste)] == [2, 1, 3, 4]


# --- Grenzfälle aus dem Pilot (umformuliert) ---------------------------------------------------------------------
def test_zerlegte_bitte_ums_zusammenfassen_kommt_als_ein_satz_an():
    """Der Live-Text liefert zwei Segmente – Nestor bekommt beide als eine Anfrage, keine feste Standardkarte."""
    async def ablauf():
        c, g, ws = _coach()
        await c.satz(Segment("Person 1", "Nestor, kannst du uns nochmal zusammenfassen", 96.0, 98.0))
        await c.satz(Segment("Person 1", "was wir bis jetzt beschlossen haben", 98.3, 99.6))
        c.meeting.virtuelle_zeit = 100.5
        b = await _bis_bogen(c)
        anfragen = ws.anfragen()
        await _fertig(c, g, b)
        return b, anfragen, c

    b, anfragen, c = asyncio.run(ablauf())
    assert b.art == "frage" and b.gerichtet
    assert anfragen == ["kannst du uns nochmal zusammenfassen was wir bis jetzt beschlossen haben"]
    eintrag = [p for p in c.protokoll if p["art"] == "anfrage"][-1]
    assert eintrag["ausloeser"] == "stimme" and eintrag["text"] == anfragen[0] and "dauer" in eintrag


def test_frage_mit_naechstem_punkt_ueber_zwei_segmente_wechselt_die_agenda_nicht():
    """„Fass den Punkt zusammen … und dann sag, was der nächste Punkt beim Projektplan ist“: das zweite Segment hat
    weder Namen noch Fragezeichen – es gehört zum Zug, die feste Ansage-Regel greift nicht."""
    async def ablauf():
        c, g, ws = _coach()
        await c.satz(Segment("Person 1", "Nestor, fass den Punkt zusammen, was haben wir besprochen", 96.0, 98.0))
        await c.satz(Segment("Person 1", "und dann kommen wir zum nächsten Punkt beim Projektplan", 98.2, 99.5))
        c.meeting.virtuelle_zeit = 100.5
        b = await _bis_bogen(c)
        anfragen = ws.anfragen()
        await _fertig(c, g, b)
        return c, anfragen

    c, anfragen = asyncio.run(ablauf())
    assert c.meeting.aktiver_punkt == 0
    assert not any(e["art"] == "wechsel" for e in c.protokoll)
    assert len(anfragen) == 1 and "nächsten Punkt beim Projektplan" in anfragen[0]


def test_recherche_ueber_zwei_saetze_geht_als_ganzes_an_das_modell():
    """Kein Recherche-Muster entscheidet vorher: „Recherche“ als Hauptwort und der Name am Ende sind kein Problem."""
    async def ablauf():
        c, g, ws = _coach()
        await c.satz(Segment("Person 2", "Mach mal eine kurze Recherche, Nestor", 96.0, 97.5))
        await c.satz(Segment("Person 2", "zu Förderprogrammen für Vereinsheime", 97.8, 99.4))
        c.meeting.virtuelle_zeit = 100.5
        b = await _bis_bogen(c)
        anfragen = ws.anfragen()
        await _fertig(c, g, b)
        return b, anfragen, c

    b, anfragen, c = asyncio.run(ablauf())
    assert b.art == "frage" and anfragen == ["Mach mal eine kurze Recherche zu Förderprogrammen für Vereinsheime"]
    assert c.assistent.auftraege.liste == []  # die Recherche startet erst, wenn das Modell das Werkzeug ruft


def test_anders_aufbereiten_und_fuers_protokoll_gehen_unsortiert_ans_modell():
    async def ablauf():
        c, g, ws = _coach()
        for i, satz in enumerate(("Nestor, bereite die Recherche anders auf.",
                                  "Nestor, fürs Protokoll: Jonas klärt das mit dem Ordnungsamt.")):
            t = 96.0 + i * 10
            c.meeting.virtuelle_zeit = t + 2.0
            await c.satz(Segment("Person 1", satz, t, t + 1.5))
            c.meeting.virtuelle_zeit = t + 3.0
            b = await _bis_bogen(c)
            assert b.art == "frage"
            await _fertig(c, g, b)
        return ws.anfragen()

    assert asyncio.run(ablauf()) == ["bereite die Recherche anders auf.",
                                     "fürs Protokoll: Jonas klärt das mit dem Ordnungsamt."]


def test_satz_eines_anderen_im_hoerfenster_geht_mit_in_den_aufruf_und_nicht_an_mich_schweigt():
    async def ablauf():
        c, g, ws = _coach()
        a = c.assistent
        b = a.bogen_starten("frage", "Wie viel Zeit haben wir noch?", "stimme", "Person 1")
        await asyncio.sleep(0.01)
        await _fertig(c, g, b)
        assert a.schnappschuss()["hoert_bis"] == pytest.approx(100.0 + 8.0, abs=0.1)
        await a.satz("Mara, machst du das bis Freitag?", 102.0, "Person 1", 101.0)
        await a.satz("Ja, mach ich.", 103.0, "Mara", 102.2)
        c.meeting.virtuelle_zeit = 104.0
        b2 = await _bis_bogen(c)
        anfrage = ws.anfragen()[-1]
        await g._werkzeug("nicht_an_mich", "{}", "call_1")
        g._antwort_text = "Gern, ich trage das ein."  # spräche das Modell trotzdem: verworfen
        await _fertig(c, g, b2)
        return a, b2, anfrage, ws, c

    a, b2, anfrage, ws, c = asyncio.run(ablauf())
    assert not b2.gerichtet and b2.quelle == "nachfrage" and b2.verworfen
    assert anfrage == f"{GZ.OHNE_NAMEN}\nPerson 1: Mara, machst du das bis Freitag?\nMara: Ja, mach ich."
    assert a.schnappschuss()["hoert_bis"] is None  # kein neues Hörfenster nach einem verworfenen Zug
    assert a.letzte is None or a.letzte.get("antwort") != "Gern, ich trage das ein."
    assert any(p["art"] == "nicht_an_mich" for p in c.protokoll)
    assert ws.typen().count("response.create") == 2  # kein Abschluss nach nicht_an_mich


def test_nicht_an_mich_bei_direkter_ansprache_wird_abgelehnt():
    async def ablauf():
        c, g, ws = _coach()
        b = c.assistent.bogen_starten("frage", "Wo stehen wir?", "stimme")
        await asyncio.sleep(0.01)
        await g._werkzeug("nicht_an_mich", "{}", "call_1")
        await g._antwort_fertig({})  # Werkzeugrunde fertig, ohne Ton → genau eine Abschlussantwort
        await asyncio.sleep(0.05)
        await _fertig(c, g, b)
        return b, ws

    b, ws = asyncio.run(ablauf())
    assert not b.verworfen and ws.ausgaben()[0]["ok"] is False
    assert ws.typen().count("response.create") == 2


def test_zusammenfassen_mit_bereich_legt_die_karte_ab_und_stoesst_genau_eine_abschlussantwort_an():
    async def ablauf():
        c, g, ws = _coach()
        c.artefakte.liste = [_artefakt(1, "entscheidung", "Beitrag bleibt gleich", 20, 0, "endgueltig"),
                             _artefakt(2, "aufgabe", "Zeitplan verschicken", 80, 1)]

        async def nichts(**k):
            return 0
        c.artefakte.erkennen = nichts
        b = c.assistent.bogen_starten("frage", "fass den ersten Punkt zusammen", "stimme")
        await asyncio.sleep(0.01)
        await g._werkzeug("zusammenfassen", json.dumps({"bereich": "punkt", "punkt": 1}), "call_1")
        await g._antwort_fertig({})  # Werkzeugrunde fertig
        await asyncio.sleep(0.1)
        await g._werkzeug("karte", json.dumps({"titel": "Noch eine", "punkte": ["x"]}), "call_2")  # in der Abschluss-
        await _fertig(c, g, b)  # antwort: abgelehnt, keine weitere Runde
        return c, ws, b

    c, ws, b = asyncio.run(ablauf())
    karten = [k for k in c.karten if k.get("art") == "zusammenfassung"]
    assert len(karten) == 1 and karten[0]["titel"] == "Zusammenfassung · Punkt 1 · Finanzen" and karten[0]["ids"] == [1]
    ausgaben = ws.ausgaben()
    assert ausgaben[0]["ok"] and ausgaben[0]["karte"]["titel"] == karten[0]["titel"]
    assert ausgaben[1]["ok"] is False and "eine Werkzeugrunde" in ausgaben[1]["fehler"]
    assert ws.typen().count("response.create") == 2  # Frage + genau eine Abschlussantwort
    assert b.werkzeuge == ["zusammenfassen", "karte"]
    assert not [k for k in c.karten if k.get("titel") == "Noch eine"]


def test_ergebnis_mit_unbekannter_nummer_wird_nicht_entfernt():
    async def ablauf():
        c, g, ws = _coach()
        c.artefakte.liste = [_artefakt(1, "aufgabe", "Flyer drucken", 20, 0)]
        b = c.assistent.bogen_starten("frage", "nimm das von der Liste", "stimme")
        await asyncio.sleep(0.01)
        await g._werkzeug("ergebnis_entfernen", json.dumps({"nummer": 4}), "call_1")
        await _fertig(c, g, b)
        return c, ws

    c, ws = asyncio.run(ablauf())
    assert [a.id for a in c.artefakte.liste] == [1]
    assert ws.ausgaben()[0]["ok"] is False and "Nummer 4" in ws.ausgaben()[0]["fehler"]
    assert ws.typen().count("response.create") == 1


def test_agendawechsel_auf_einen_fehlenden_punkt_wechselt_nicht_und_das_modell_sagt_es():
    async def ablauf():
        c, g, ws = _coach()
        b = c.assistent.bogen_starten("frage", "geh zu Punkt sieben", "stimme")
        await asyncio.sleep(0.01)
        await g._werkzeug("agendapunkt_wechseln", json.dumps({"nummer": 7}), "call_1")
        await g._antwort_fertig({})
        await asyncio.sleep(0.05)
        await _fertig(c, g, b)
        return c, ws

    c, ws = asyncio.run(ablauf())
    assert c.meeting.aktiver_punkt == 0 and ws.ausgaben()[0]["ok"] is False
    assert ws.typen().count("response.create") == 2


def test_auftrag_abbrechen_per_werkzeug():
    async def ablauf():
        c, g, ws = _coach()
        a = c.assistent
        auftrag = a.auftraege.neu("recherche", "Förderprogramme", 90.0)
        b = a.bogen_starten("frage", "lass die Recherche", "stimme")
        await asyncio.sleep(0.01)
        await g._werkzeug("auftrag_abbrechen", json.dumps({"art": "recherche"}), "call_1")
        await _fertig(c, g, b)
        return a, auftrag, ws

    a, auftrag, ws = asyncio.run(ablauf())
    assert a.auftraege.liste == [] and ws.ausgaben()[0]["ok"]


def test_ohne_ton_bis_zur_frist_kommt_das_ergebnis_still():
    async def ablauf():
        object.__setattr__(EINST, "anfrage_frist_sekunden", 0.1)
        try:
            c, g, ws = _coach()
            b = c.assistent.bogen_starten("frage", "Wo stehen wir?", "stimme")
            await asyncio.sleep(0.3)
            still = b.abgeloest and g._stumm
            await _fertig(c, g, b)
        finally:
            object.__setattr__(EINST, "anfrage_frist_sekunden", 15.0)
        return still, c

    still, c = asyncio.run(ablauf())
    assert still and any(p["art"] == "anfrage_frist" for p in c.protokoll)


def test_halt_bleibt_deterministisch_auch_im_gespraech():
    async def ablauf():
        c, g, ws = _coach()
        await c.assistent.satz("Nestor, warte mal.", 99.0, "Person 1", 98.0)
        await asyncio.sleep(0.5)
        return c, ws

    c, ws = asyncio.run(ablauf())
    assert c.assistent.zug is None and c.assistent.bogen is None
    assert any(p["art"] == "halt" for p in c.protokoll) and ws.anfragen() == []


def test_nur_der_name_sagt_ja_und_der_naechste_zug_ist_die_frage():
    async def ablauf():
        c, g, ws = _coach()
        a = c.assistent
        await a.satz("Nestor?", 99.0, "Person 1", 98.5)
        c.meeting.virtuelle_zeit = 100.0
        for _ in range(50):
            await asyncio.sleep(0.02)
            if a._aufgabe is not None:
                break
        await a._aufgabe
        await a.satz("Was steht beim Projektplan noch offen?", 102.0, "Person 1", 100.5)
        c.meeting.virtuelle_zeit = 103.0
        b = await _bis_bogen(c)
        anfragen = ws.anfragen()
        await _fertig(c, g, b)
        return b, anfragen

    b, anfragen = asyncio.run(ablauf())
    assert b.gerichtet and anfragen == ["Was steht beim Projektplan noch offen?"]
