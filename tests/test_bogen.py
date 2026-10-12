"""Ticket #27 ohne Netz: Antwortbogen (ein Bogen zur Zeit, Unterbrechen stoppt nur die Stimme), Stau 2/3 bei langen
Aufträgen, Stille bei Automatik, Regeln aus = unsichtbar, Funkgerät ohne Namen, kein Hörfenster auf dem Text-Weg,
Lücke korrigieren und die Namensrunde."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import numpy as np
import pytest
from modell_attrappe import Zug

from coach import bestaetigung as B
from coach import bogen as BG
from coach.assistent import BogenBelegt
from coach.config import EINST
from coach.pipeline import Coach
from coach.zustand import Segment


_STUFE = ["premium"]  # Stufe der nächsten Coach-Attrappe (_coach)


def stufe_setzen(stufe: str) -> None:
    _STUFE[0] = stufe


@pytest.fixture(autouse=True)
def umgebung(tmp_path, monkeypatch):
    """Bestätigung an (Floskeln im eigenen Ordner), Text-Weg, Premium; Nutzung nicht protokollieren."""
    felder = ("bestaetigung", "floskel_ordner", "assistent_modus", "stimme_aus", "nachfrage_sekunden",
              "vorstellung_sekunden")
    alt = {k: getattr(EINST, k) for k in felder}
    object.__setattr__(EINST, "bestaetigung", True)
    object.__setattr__(EINST, "floskel_ordner", str(tmp_path / "floskeln"))
    object.__setattr__(EINST, "assistent_modus", "text")
    object.__setattr__(EINST, "stimme_aus", False)
    object.__setattr__(EINST, "nachfrage_sekunden", 15.0)
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)
    monkeypatch.setattr("coach.pipeline._zeit_loggen", lambda e: None)
    yield
    stufe_setzen("premium")
    for k, v in alt.items():
        object.__setattr__(EINST, k, v)


class _Ton:
    def __init__(self, zaehler, dauer=0.2):
        self.zaehler, self.dauer = zaehler, dauer

    async def __aenter__(self):
        self.zaehler.append(1)
        return self

    async def __aexit__(self, *x):
        return False

    async def iter_bytes(self, n):
        for _ in range(3):
            await asyncio.sleep(0.01)
            yield b"\x00\x30" * int(24000 * self.dauer / 3)


class Attrappe:
    """Ein Client für alles: Antworten (Strom), JSON-Aufrufe nach Inhalt, Sprachausgabe."""

    def __init__(self, antwort=("Ihr seid bei Punkt eins.",), artefakte=(), verzoegerung: float = 0.0):
        self.antwort = list(antwort)  # Züge des Modells (tests/modell_attrappe.py), der letzte wiederholt sich
        self.artefakte = list(artefakte)
        self.verzoegerung = verzoegerung
        self.anfragen: list[str] = []
        self.tts: list = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.audio = SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(
            create=lambda **kw: _Ton(self.tts))))

    async def _create(self, **kw):
        inhalt = kw["messages"][-1]["content"]
        self.anfragen.append(inhalt)
        if self.verzoegerung:
            await asyncio.sleep(self.verzoegerung)
        if kw.get("stream"):
            from modell_attrappe import Strom

            return Strom(self.antwort.pop(0) if len(self.antwort) > 1 else self.antwort[0])
        if "NEUE Sätze" in inhalt:
            roh = {"artefakte": self.artefakte.pop(0) if self.artefakte else []}
        elif "Karte" in inhalt and "zeigen" in inhalt:
            roh = {"zeigen": True, "titel": "Antwort", "punkte": ["Punkt eins läuft", "Noch 3 Minuten"]}
        elif "Wo stehen" in inhalt or "naechster_punkt" in kw["messages"][0]["content"]:
            roh = {"titel": "Stand", "punkte": ["Punkt 1 läuft"], "naechster_punkt": None,
                   "sagen": "Hier ist sie. Ihr liegt gut in der Zeit."}
        elif kw.get("response_format"):
            roh = {}
        else:  # Moderationssatz
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="Hier ist sie. Zwei Aufgaben haben noch niemanden, der sich kümmert."))], usage=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(roh)))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))


def _coach(client=None, regel_ids=(), agenda=("Ursache", "Maßnahmen")) -> tuple[Coach, list[dict]]:
    c = Coach()
    c.stufe_setzen(_STUFE[0])
    c._einrichten({"titel": "Incident-Review", "agenda": [{"titel": t, "minuten": 10} for t in agenda],
                   "regel_ids": list(regel_ids)})
    c._client = client or Attrappe()
    c.meeting.starten(virtuell=True)
    gesendet: list[dict] = []

    async def senden(n):
        gesendet.append(n)
    c.direkt.append(senden)
    for t in B.ALLE:  # Floskeln liegen im Zwischenspeicher (wie nach dem ersten Meeting mit dieser Stimme)
        p = c.assistent.floskeln.pfad(t)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00\x40" * 2400)
    return c, gesendet


def _texte(gesendet) -> list[str]:
    return [n["text"] for n in gesendet if n["typ"] == "nestor_text"]


async def _fertig(c: Coach) -> None:
    b = c.assistent.bogen
    if b is not None and b.task is not None:
        await b.task
    for _ in range(5):
        await asyncio.sleep(0.01)


# --- Antwortbogen: Bestätigung, Karte, Satz; Sperre ---------------------------------------------------------------
def test_karten_bogen_bestaetigt_zeigt_die_karte_und_sagt_was_auffaellt():
    async def ablauf():
        c, gesendet = _coach(Attrappe(artefakte=[[
            {"typ": "aufgabe", "was": "Runbook schreiben", "zeit": "0:05", "konfidenz": 0.9},
            {"typ": "aufgabe", "was": "Alerts anpassen", "zeit": "0:08", "konfidenz": 0.9}]]))
        c.meeting.transkript.append(Segment("Person 1", "Wir müssen noch das Runbook schreiben.", 4, 7))
        c.meeting.virtuelle_zeit = 20
        b = c.assistent.bogen_starten("zusammenfassen", "Zusammenfassen", "knopf")
        await b.task
        return c, gesendet, b

    c, gesendet, b = asyncio.run(ablauf())
    texte = _texte(gesendet)
    assert texte[0] in B.KURZ  # Bestätigung sofort, aus dem Vorrat
    assert texte[-1].startswith("Hier ist sie.")  # was auffällt – nicht die Karte vorgelesen
    karte = c.karten[-1]
    assert karte["art"] == "zusammenfassung" and len(karte["ids"]) == 2 and karte["luecken_zeigen"]
    assert not karte["still"]
    assert b.zeiten["floskel"] <= b.zeiten["karte"] <= b.zeiten["satz"]
    assert c.assistent.bogen is None


def test_bogen_sperre_knopf_wird_abgewiesen_zuruf_unterbricht_nur_die_stimme():
    """Nur ein Bogen zur Zeit: ein Knopf wird abgewiesen; ein Zuruf unterbricht die Stimme des laufenden Bogens –
    seine Karte kommt trotzdem, still (Nachtrag B)."""
    async def ablauf():
        c, gesendet = _coach(Attrappe(verzoegerung=0.05))
        c.meeting.transkript.append(Segment("Person 1", "Wir sprechen über die Ursache.", 1, 3))
        erster = c.assistent.bogen_starten("stand", "Wo stehen wir?", "knopf")
        await asyncio.sleep(0.01)
        with pytest.raises(BogenBelegt):
            c.assistent.bogen_starten("festgehalten", "Protokoll", "knopf")
        zweiter = c.assistent.bogen_starten("fehlt", "was fehlt noch?", "stimme")
        await erster.task
        await zweiter.task
        return c, gesendet, erster, zweiter

    c, gesendet, erster, zweiter = asyncio.run(ablauf())
    assert erster.abgeloest and not zweiter.abgeloest
    assert any(n["typ"] == "stimme_stopp" for n in gesendet)
    karten = {k["bogen"]: k for k in c.karten if "bogen" in k}
    assert karten[erster.id]["still"] and karten[erster.id]["art"] == "stand"  # Arbeit fertig, Karte still da
    assert not karten[zweiter.id]["still"]
    assert "Ihr liegt gut in der Zeit." not in " ".join(_texte(gesendet))  # der abgelöste Bogen schweigt


def test_bogen_stand_schlaegt_naechsten_punkt_vor():
    """Ticket #80 (vormals knopfdruck._stand, toter Reservieren/Ausführen-Pfad): „Wo stehen wir?“ schlägt auf der
    Karte den nächsten Agendapunkt vor, wenn das Modell ihn benennt – die Runde entscheidet (meeting.vorschlag)."""
    async def ablauf():
        c, gesendet = _coach()

        async def chat(**kw):
            inhalt = {"titel": "Budget offen", "punkte": ["Ihr seid bei Punkt eins.", "Vorschlag: zum Budget."],
                      "naechster_punkt": 2}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(inhalt)))],
                                   usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))
        c._client.chat = SimpleNamespace(completions=SimpleNamespace(create=chat))
        b = c.assistent.bogen_starten("stand", "Wo stehen wir?", "knopf")
        await b.task
        return c

    c = asyncio.run(ablauf())
    karte = c.karten[-1]
    assert karte["art"] == "stand" and karte["punkte"][-1].startswith("Vorschlag")
    assert c.meeting.vorschlag["punkt"] == 1  # „Weiter zu Maßnahmen?“ – die Runde entscheidet


def test_knopf_ueber_die_api_ist_waehrend_eines_bogens_gesperrt(monkeypatch):
    from fastapi.testclient import TestClient

    import coach.server as server

    c, _ = _coach(Attrappe(verzoegerung=0.3))
    monkeypatch.setattr(server, "coach", c)
    from unittest.mock import AsyncMock
    c.hoerstrom = SimpleNamespace(text_abwarten=AsyncMock())
    with TestClient(server.app, client=("127.0.0.1", 5000)) as client:
        assert client.post("/api/knopf/stand", json={}).status_code == 200
        r = client.post("/api/knopf/zusammenfassen", json={})
        assert r.status_code == 409 and "Wo stehen wir?" in r.json()["detail"]
    c.hoerstrom = None


# --- Lange Aufträge: Stau 2/3 --------------------------------------------------------------------------------------
def test_stau_zwei_lange_auftraege_der_dritte_wird_abgewehrt(monkeypatch):
    async def langsam(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr("coach.recherche.recherchieren", langsam)

    async def ablauf():
        c, gesendet = _coach()
        c.bild_erstellen = langsam
        a = c.assistent
        assert await a.lang_annehmen("bild", "zeig uns ein Bild")
        assert await a.lang_annehmen("recherche", "Mindestlohn 2027")
        assert not await a.lang_annehmen("recherche", "Mietpreise Hannover")
        stand = a.auftraege.schnappschuss()
        for x in list(a.auftraege.liste):
            a.auftrag_abbrechen(x.id)
        await asyncio.sleep(0.02)
        return c, gesendet, stand

    c, gesendet, stand = asyncio.run(ablauf())
    texte = _texte(gesendet)
    assert texte[0] in B.LANGE and texte[1] == B.STAU[("bild", "recherche")] and texte[2] == B.ABWEHR
    assert [(x["art"], x["zustand"]) for x in stand] == [("bild", "laeuft"), ("recherche", "wartet")]
    assert c.assistent.auftraege.liste == []


def test_kurze_frage_laeuft_neben_einem_langen_auftrag(monkeypatch):
    async def langsam(*a, **k):
        await asyncio.sleep(30)

    async def ablauf():
        c, gesendet = _coach()
        c.bild_erstellen = langsam
        await c.assistent.lang_annehmen("bild", "Bild")
        b = c.assistent.bogen_starten("frage", "Wie viel Zeit haben wir noch?", "stimme")
        await b.task
        offen = [x.art for x in c.assistent.auftraege.liste]
        for x in list(c.assistent.auftraege.liste):
            c.assistent.auftrag_abbrechen(x.id)
        return gesendet, offen

    gesendet, offen = asyncio.run(ablauf())
    assert "Ihr seid bei Punkt eins." in _texte(gesendet) and offen == ["bild"]


def test_recherche_kommt_still_als_karte_ohne_ansage(monkeypatch):
    async def recherche(client, frage, titel, *, wahl):
        return {"text": "Der Mindestlohn steigt 2027 auf 14,60 Euro je Stunde, beschlossen von der Kommission.",
                "quellen": [{"titel": "BMAS", "url": "https://bmas.de", "seite": "bmas.de"}], "tokens_rein": 1,
                "tokens_raus": 1, "sekunden": 0.1}

    monkeypatch.setattr("coach.recherche.recherchieren", recherche)

    async def ablauf():
        c, gesendet = _coach(Attrappe(antwort=[Zug(werkzeuge=[("recherchieren", {"frage": "Mindestlohn 2027"})]),
                                               "Ich schau nach, die Karte kommt gleich."]))
        b = c.assistent.bogen_starten("frage", "gib uns einen Überblick zum Mindestlohn", "stimme")
        await b.task
        for _ in range(20):
            await asyncio.sleep(0.01)
        return c, gesendet

    c, gesendet = asyncio.run(ablauf())
    texte = _texte(gesendet)
    assert texte == [texte[0], "Ich schau nach, die Karte kommt gleich."] and texte[0] in B.KURZ  # kein „fertig“
    karte = c.karten[-1]
    assert karte["art"] == "recherche" and karte["still"] and karte["quellen"][0]["titel"] == "BMAS"


# --- Automatik: immer still --------------------------------------------------------------------------------------
def test_punktwechsel_legt_still_eine_zusammenfassung_ab_mit_regel_luecken_und_band():
    async def ablauf(regel_ids):
        c, gesendet = _coach(Attrappe(artefakte=[[
            {"typ": "aufgabe", "was": "Runbook schreiben", "zeit": "0:05", "konfidenz": 0.9},
            {"typ": "entscheidung", "was": "Migrationen nur im Wartungsfenster", "status": "endgueltig",
             "wer": "die Runde", "zeit": "0:30", "konfidenz": 0.9}]]), regel_ids=regel_ids)
        for i in range(8):
            c.meeting.transkript.append(Segment("Person 1", f"Satz {i} über die Ursache.", i * 8.0, i * 8.0 + 7))
        c.meeting.virtuelle_zeit = 70
        c.punkt_wechseln(1)
        for _ in range(20):
            await asyncio.sleep(0.01)
        return c, gesendet

    c, gesendet = asyncio.run(ablauf(["ergebnisse"]))
    assert not [n for n in gesendet if n["typ"] in ("stimme", "nestor_text")]  # Nestor schweigt
    karte = c.karten[-1]
    assert karte["art"] == "punkt" and karte["still"] and karte["titel"] == "Punkt 1 · Ursache"
    assert karte["luecken_zeigen"] and len(karte["ids"]) == 2
    band = c.meeting.hinweise[-1]
    assert band.art == "luecken" and band.text.startswith("1 Aufgabe ohne Verantwortliche")
    assert band.aktion == {"text": "Zur Karte", "karte": karte["id"]}

    c, gesendet = asyncio.run(ablauf([]))  # ohne Regel: Karte ja, keine Markierung, kein Band
    assert c.karten[-1]["art"] == "punkt" and not c.karten[-1]["luecken_zeigen"]
    assert not [h for h in c.meeting.hinweise if h.art == "luecken"]


def test_zwanzig_minuten_am_selben_punkt_und_nachholen_nur_des_laufenden_abschnitts():
    async def ablauf():
        c, _ = _coach(Attrappe(artefakte=[[], []]))
        for i in range(10):
            c.meeting.transkript.append(Segment("Person 1", f"Satz {i}", i * 120.0, i * 120.0 + 60))
        c.meeting.virtuelle_zeit = 1201
        c.artefakte.takt()
        for _ in range(20):
            await asyncio.sleep(0.01)
        erste = list(c._client.anfragen)
        c.meeting.transkript.append(Segment("Person 1", "Neuer Satz nach dem Abschnitt", 1210, 1215))
        c.meeting.virtuelle_zeit = 1220
        await c.artefakte.nachholen()
        return c, erste

    c, erste = asyncio.run(ablauf())
    assert c.karten[-1]["art"] == "punkt" and c.karten[-1]["titel"].startswith("Zwischenstand · Ursache")
    assert len(erste) == 1 and "Satz 9" in erste[0]
    assert "Neuer Satz" in c._client.anfragen[-1] and "Satz 3]" not in c._client.anfragen[-1].split("NEUE")[1]


def test_fuenf_minuten_vor_schluss_still_ins_band_mit_knopf():
    async def ablauf():
        c, gesendet = _coach()
        c.meeting.virtuelle_zeit = 15 * 60 + 1  # 20 min geplant
        c.artefakte.takt()
        await asyncio.sleep(0.01)
        return c, gesendet

    c, gesendet = asyncio.run(ablauf())
    h = c.meeting.hinweise[-1]
    assert h.art == "fuenf" and h.text == "Noch 5 Minuten" and h.aktion["bogen"] == "zusammenfassen"
    assert not [n for n in gesendet if n["typ"] in ("stimme", "nestor_text")]


def test_bild_kommt_still_als_karte(monkeypatch):
    async def erzeugen(client, m, vorher, fokus, *, wahl):
        return {"png": b"PNG", "analyse": "a", "messung": {}}

    monkeypatch.setattr("coach.bild_gpt.erzeugen", erzeugen)

    async def ablauf():
        c, gesendet = _coach()
        c.meeting.transkript.append(Segment("Person 1", "Wir planen den Stand.", 0, 2))
        await c.bild_erstellen(None)
        return c, gesendet

    c, gesendet = asyncio.run(ablauf())
    assert c.karten[-1]["art"] == "bild" and c.karten[-1]["still"] and c.bilder[1] == b"PNG"
    assert not [n for n in gesendet if n["typ"] in ("stimme", "nestor_text")]


# --- Regeln aus = unsichtbar --------------------------------------------------------------------------------------
def test_nicht_gewaehlte_regeln_sind_unsichtbar():
    def lauf(regel_ids):
        c, _ = _coach(regel_ids=regel_ids)
        m = c.meeting
        m.teilnehmende = ["A", "B"]
        m.segmente = [Segment("Person 1", "", 0, 650)]
        m.virtuelle_zeit = 660  # 11 min am ersten Punkt (10 min geplant), eine Stimme allein
        c.takt()
        m.ueberlappungen_gezaehlt = True
        m.ueberlappungen = [[650.0, 652.0], [655.0, 657.0]]
        c._ueberlappung_pruefen()
        return {h.art for h in m.hinweise}, {r["id"] for r in c.regel_status(c.schnappschuss()["ampeln"])}

    arten, ampeln = lauf([])
    assert arten == set() and ampeln == set()
    arten, ampeln = lauf(["zeit", "alle", "ausreden"])
    assert {"zeit", "anteil", "ueberlappung"} <= arten and ampeln == {"alle", "ausreden"}  # Zeit steht links


# --- Funkgerät (Basis) -------------------------------------------------------------------------------------------
def test_funkgeraet_reagiert_nicht_auf_den_namen_sondern_auf_die_taste():
    async def ablauf():
        stufe_setzen("basis")
        object.__setattr__(EINST, "bestaetigung", True)
        c, gesendet = _coach()
        a = c.assistent
        c.meeting.virtuelle_zeit = 100
        await a.satz("Nestor, wo stehen wir gerade?", 99.0, "Person 1")
        await a.satz("Nestor, was ist mit dem Budget?", 99.5, "Person 1")  # nur ein Band-Hinweis je Minute
        nach_name = (a.bogen, list(gesendet), [h.text for h in c.meeting.hinweise])
        a.halten_start()
        assert a.zustand == "taste"
        a.halten_ende()
        a.frage_beantworten("Nestor, wie viel Zeit haben wir noch?", "taste")
        await _fertig(c)
        await a.satz("Nestor, nein.", 120.0, "Person 1")  # das späte Nein geht weiter per Stimme
        return c, nach_name, gesendet

    c, (bogen, vorher, band), gesendet = asyncio.run(ablauf())
    assert bogen is None and vorher == [] and len(band) == 1 and band[0].startswith("In Basis: Sprechtaste halten")
    assert "Ihr seid bei Punkt eins." in _texte(gesendet)
    assert c.assistent.pausiert


def test_sprechtaste_unterbricht_den_laufenden_bogen():
    async def ablauf():
        c, gesendet = _coach(Attrappe(verzoegerung=0.05))
        b = c.assistent.bogen_starten("stand", "Wo stehen wir?", "knopf")
        await asyncio.sleep(0.01)
        c.assistent.halten_start()
        await b.task
        return c, b, gesendet

    c, b, gesendet = asyncio.run(ablauf())
    assert b.abgeloest and any(n["typ"] == "stimme_stopp" for n in gesendet) and c.karten[-1]["still"]


def test_basis_begruessung_erklaert_das_funkgeraet_und_bittet_um_namen():
    from coach import assistent as A

    c, _ = _coach()
    gruss, rest = A.begruessungstext(c.meeting, basis=True, namen=True)
    assert "Funkgerät" in rest and "Taste halten, sprechen, loslassen" in rest and "Nestor, nein" in gruss
    assert rest.endswith(A.NAMEN_BITTE)
    _, rest = A.begruessungstext(c.meeting, basis=False, namen=True)
    assert "Telefon" in rest and rest.endswith(A.NAMEN_BITTE)


# --- Hörfenster: nur im Gespräch (das Modell entscheidet über nicht_an_mich) --------------------------------------
def test_kurzantwort_hat_kein_hoerfenster():
    """Premium-Kurzantwort (Text-Weg) sortiert nicht vor, ob ein Satz ohne Namen gemeint war – deshalb kein Hörfenster;
    das gibt es nur im Gespräch (tests/test_agent_light.py)."""
    async def ablauf():
        c, _ = _coach()
        a = c.assistent
        b = a.bogen_starten("frage", "Wie viel Zeit haben wir noch?", "stimme")
        await b.task
        ende = a.sprechzeiten[-1][1]
        c.meeting.virtuelle_zeit = ende + 2
        await a.satz("Und bis wann?", ende + 1.5, "Person 2")
        return a.schnappschuss(), a.bogen

    bild, neu = asyncio.run(ablauf())
    assert bild["hoert_bis"] is None and neu is None


def test_basis_hat_kein_nachfrage_fenster():
    async def ablauf():
        stufe_setzen("basis")
        c, _ = _coach()
        b = c.assistent.bogen_starten("frage", "Wie viel Zeit haben wir noch?", "taste")
        await b.task
        return c.assistent.schnappschuss()

    assert asyncio.run(ablauf())["hoert_bis"] is None


def test_28_nach_ja_gilt_der_naechste_satz_12_s_lang_als_frage():
    """„Nestor?“ → „Ja?“ → die Frage kommt – auch 11 s nach dem Ende von „Ja?“ und mit Verzug des Live-Texts – und
    wird beantwortet. Auf dem Text-Weg gibt es danach kein Hörfenster ohne Namen."""
    async def ablauf():
        c, gesendet = _coach(Attrappe(antwort=("Zu Punkt eins habt ihr den Down-Pfad beschlossen.",)))
        a = c.assistent
        c.meeting.virtuelle_zeit = 274.8
        await a.satz("Nestor,", 274.0, "Person 2")
        await a._aufgabe
        ja_ende = a.sprechzeiten[-1][1]
        zustand_nach_ja = a.zustand, a.schnappschuss()["hoert_bis"]
        c.meeting.virtuelle_zeit = ja_ende + 12.8  # der Satz endete 11,5 s nach „Ja?“, kam aber erst jetzt als Text an
        a.takt()
        await a.satz("Was haben wir zu Punkt eins beschlossen?", ja_ende + 11.5, "Person 2")
        frage = a.bogen
        await frage.task
        ende = a.sprechzeiten[-1][1]
        c.meeting.virtuelle_zeit = ende + 3
        await a.satz("Und wer übernimmt das?", ende + 2.2, "Person 2")
        rueckfrage = a.bogen
        if rueckfrage:
            await rueckfrage.task
        return ja_ende, zustand_nach_ja, frage, rueckfrage, gesendet

    ja_ende, (zustand, hoert_bis), frage, rueckfrage, gesendet = asyncio.run(ablauf())
    assert "Ja?" in _texte(gesendet)
    assert zustand == "angesprochen" and hoert_bis == pytest.approx(ja_ende + 12.0, abs=0.01)  # Ring „Ich höre zu“
    assert frage is not None and frage.frage == "Was haben wir zu Punkt eins beschlossen?"
    assert rueckfrage is None


def test_28_nach_ja_endet_das_fenster_nach_12_s_und_nestor_hoert_wieder_zu():
    async def ablauf():
        c, _ = _coach(Attrappe())
        a = c.assistent
        c.meeting.virtuelle_zeit = 274.8
        await a.satz("Nestor?", 274.0, "Person 2")
        await a._aufgabe
        ja_ende = a.sprechzeiten[-1][1]
        c.meeting.virtuelle_zeit = ja_ende + 12.5
        a.takt()
        noch = a.zustand  # ein Satz, der bis 12 s nach „Ja?“ endete, darf noch als Text ankommen
        c.meeting.virtuelle_zeit = ja_ende + 15.5
        a.takt()
        zustand = a.zustand
        await a.satz("Das schieben wir auf next week.", ja_ende + 13.5, "Person 1")  # endete nach dem Fenster
        return noch, zustand, a.bogen

    noch, zustand, bogen = asyncio.run(ablauf())
    assert noch == "angesprochen" and zustand == "bereit" and bogen is None


# --- Lücke korrigieren (Nachtrag A) --------------------------------------------------------------------------------
def test_luecke_korrigieren_bestaetigt_und_aendert_die_vorhandene_karte():
    async def ablauf():
        c, gesendet = _coach(Attrappe(
            antwort=[Zug(werkzeuge=[("artefakt_eintragen", {"nummer": 1, "wer": "Anna", "bis": "Freitag"})]),
                     "Notiert, Anna schreibt das Runbook bis Freitag."],
            artefakte=[[{"typ": "aufgabe", "was": "Runbook schreiben", "zeit": "0:05", "konfidenz": 0.9}]]))
        c.meeting.transkript.append(Segment("Person 1", "Wir müssen das Runbook schreiben.", 4, 7))
        b = c.assistent.bogen_starten("fehlt", "was fehlt noch?", "knopf")
        await b.task
        karten_vorher = len(c.karten)
        gesendet.clear()
        c.assistent.annehmen("Anna macht das bis Freitag", "stimme")
        await _fertig(c)
        return c, gesendet, karten_vorher

    c, gesendet, karten_vorher = asyncio.run(ablauf())
    a = c.artefakte.holen(1)
    assert a.wer == "Anna" and a.bis == "Freitag" and not a.luecken()
    texte = _texte(gesendet)
    assert texte[-1] == "Notiert, Anna schreibt das Runbook bis Freitag."
    assert len(c.karten) == karten_vorher  # keine neue Karte – die vorhandene zeigt jetzt grün
    karte = c.karten[-1]
    assert karte["ids"] == [1] and karte["luecken_vorher"]["1"] == ["wer", "bis"]


# --- Namensrunde ------------------------------------------------------------------------------------------------
def _vektor(i: int, rauschen: float = 0.0, rng=np.random.default_rng(1)) -> np.ndarray:
    v = np.zeros(16)
    v[i] = 1.0
    v = v + rauschen * rng.normal(size=16)
    return v / np.linalg.norm(v)


class _Hoerstrom:
    """Nur das, was die Namenszuordnung braucht: Stimmregister und Fingerabdrücke je Äußerung."""

    def __init__(self):
        from coach.stimmen import Personenregister

        self.stimmen = SimpleNamespace(register=Personenregister(0.5, 0.4))
        self.vektoren = []

    def vektor_an(self, start, ende):
        return next((v for a, b, v in self.vektoren if a <= start < b), None)


def test_namensrunde_ordnet_kurze_vorstellungen_still_der_richtigen_stimme_zu():
    """In den Demos wurde nur eine Person erkannt: kurze Vorstellungen kamen als „Person ?“ oder bei einer schon
    benannten Person an. Jetzt: Name mit dem Fingerabdruck der Äußerung merken, später zuordnen."""
    async def ablauf():
        c, _ = _coach()
        hs = _Hoerstrom()
        c.hoerstrom = hs
        reg = hs.stimmen.register
        c.assistent.vorstellung_bis = 100
        reg.zuordnen(_vektor(0), 6.0)  # Anna sprach schon in der Begrüßungspause: Person 1
        vorstellungen = [("Person 1", "Ich bin Anna.", 0), ("Person ?", "Ich heiße David.", 1),
                         ("Person 1", "Hallo, ich bin Lea.", 2), ("Person ?", "Tarek hier.", 3)]
        for k, (sprecher, text, person) in enumerate(vorstellungen):
            start = 10.0 + k * 3
            hs.vektoren.append((start, start + 1.2, _vektor(person, 0.25)))
            c.meeting.virtuelle_zeit = start + 1.5
            await c.satz(Segment(sprecher, text, start, start + 1.2))
        nach_runde = dict(c.namen)
        for person in (1, 2, 3):  # danach redet jede – das Register lernt die Stimmen
            reg.zuordnen(_vektor(person, 0.1), 8.0)
        c.meeting.virtuelle_zeit = 60
        c._namen_zuordnen()
        return c, nach_runde

    c, nach_runde = asyncio.run(ablauf())
    assert nach_runde == {"Person 1": "Anna"}
    assert c.namen == {"Person 1": "Anna", "Person 2": "David", "Person 3": "Lea", "Person 4": "Tarek"}
    assert [h.text for h in c.meeting.hinweise if h.art == "namen"][-1] == "Erkannt: Anna, David, Lea, Tarek"


def test_name_aus_auch_mit_hier_und_zusatz():
    from coach.assistent import name_aus

    assert name_aus("Lea hier, ich mache das Marketing.") == "Lea"
    assert name_aus("Mein Name ist Tarek.") == "Tarek" and name_aus("Hallo, ich bin Anna.") == "Anna"
