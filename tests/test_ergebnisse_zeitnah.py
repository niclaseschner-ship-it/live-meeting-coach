"""Ticket #72: Ergebnisse zeitnah und nie still – Schnell-Erkennung bei klaren Signalen, sichtbare Fehler der
Hintergrund-KI mit Wiederholung und Technikbericht, einmaliger Funkgerät-Hinweis in Basis."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from coach import artefakte as A
from coach import ki_fehler
from coach.archiv import bericht
from coach.pipeline import Coach
from coach.zustand import Segment


class Fehler500(Exception):
    status_code = 500


class Modell:
    """Antworten der Reihe nach; eine Exception in der Liste wird geworfen. Merkt sich System- und Nutzertext."""

    def __init__(self, *antworten) -> None:
        self.antworten = list(antworten)
        self.anfragen: list[tuple[str, str]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.anfragen.append((kw["messages"][0]["content"], kw["messages"][-1]["content"]))
        antwort = self.antworten.pop(0) if self.antworten else {"artefakte": []}
        if isinstance(antwort, BaseException):
            raise antwort
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(antwort)))],
                               usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=150))


def _coach(*antworten, stufe: str = "premium") -> Coach:
    c = Coach()
    c.stufe_setzen(stufe)
    c._einrichten({"titel": "Vorstand", "agenda": [{"titel": "Sommerfest-Budget", "minuten": 15},
                                                   {"titel": "Vereinsbus", "minuten": 10}], "regel_ids": ["ergebnisse"]})
    c._client = Modell(*antworten)
    c.meeting.starten(virtuell=True)
    return c


def _satz(c: Coach, text: str, start: float, ende: float, sprecher: str = "Person 1") -> Segment:
    s = Segment(sprecher, text, start, ende)
    c.meeting.transkript.append(s)
    c.meeting.virtuelle_zeit = ende
    return s


BESCHLUSS = {"nummer": None, "typ": "entscheidung", "was": "Sommerfest höchstens 9.000 Euro", "wer": "die Runde",
             "status": "endgueltig", "konfidenz": 0.9, "zeit": "00:40", "zitat": "Wir beschließen …"}
AUFGABE = {"nummer": None, "typ": "aufgabe", "was": "Fahrten der Jugend liefern", "wer": "Sabine", "bis": "Freitag",
           "konfidenz": 0.9, "zeit": "00:50", "zitat": "Sabine liefert bis Freitag …"}


async def _warten_bis(bedingung, sekunden: float = 2.0) -> None:
    for _ in range(int(sekunden / 0.01)):
        if bedingung():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Bedingung nicht erreicht")


@pytest.fixture(autouse=True)
def _ohne_sammeln(monkeypatch):
    monkeypatch.setattr(A, "SAMMELN_SEKUNDEN", 0.0)


# --- Vorfilter ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("satz, art", [
    ("Wir beschließen für das Sommerfest maximal neuntausend Euro.", "entscheidung"),
    ("Gut, dann machen wir das so, abgemacht.", "entscheidung"),
    ("Sabine liefert bis Freitag die Fahrten.", "aufgabe"),
    ("Machst du das bis Montag, Jörg?", "aufgabe"),
    ("Ich kümmere mich um die Getränke.", "aufgabe"),
    ("Der Termin für die Abnahme ist der 14. November.", "termin"),
    ("Offen ist noch, wer die Halle bucht.", "offen"),
    ("Beim Vereinsbus prüfen wir noch, ob sich ein Kauf lohnt.", "offen"),
    ("Das Wetter könnte uns einen Strich durch die Rechnung machen.", "risiko"),
])
def test_signal_vorfilter_erkennt_klare_signale(satz, art):
    assert A.signal(satz) == art


@pytest.mark.parametrize("satz", [
    "Willkommen zur Vorstandssitzung, wir beginnen mit dem Sommerfest-Budget.",
    "Letztes Jahr war das Fest gut besucht.",
    "Ich finde die Idee mit dem Grill schön.",
])
def test_signal_vorfilter_laesst_gewoehnliche_saetze_durch(satz):
    assert A.signal(satz) is None


# --- Schnell-Erkennung ------------------------------------------------------------------------------------------
def test_schnell_erkennung_bringt_karte_binnen_sekunden_und_vollauswertung_legt_nicht_doppelt_an():
    async def ablauf():
        # Vollauswertung formuliert dieselbe Entscheidung anders (gleicher Satz) – darf keine Dublette werden
        anders = {**BESCHLUSS, "was": "Budget für das Fest: Ausgabengrenze neuntausend", "zeit": "00:40"}
        c = _coach({"artefakte": [BESCHLUSS]}, {"artefakte": [AUFGABE]}, {"artefakte": [anders, AUFGABE]})
        c.artefakte.satz([_satz(c, "Wir beschließen für das Sommerfest maximal neuntausend Euro.", 40, 45)])
        await _warten_bis(lambda: len(c.artefakte.liste) == 1 and not c.artefakte._schnell_laeuft)
        karten = [k for k in c.karten if k["art"] == "ergebnis"]
        assert len(karten) == 1 and karten[0]["ids"] == [1] and karten[0]["titel"] == "Punkt 1 · Sommerfest-Budget"
        system, nutzer = c._client.anfragen[0]
        assert system == A.SCHNELL and "neuntausend" in nutzer
        assert c.artefakte.liste[0].schnell
        # zweiter Signalsatz innerhalb einer Minute: dieselbe Karte wächst mit
        c.artefakte.satz([_satz(c, "Sabine liefert bis Freitag die Fahrten.", 50, 54)])
        await _warten_bis(lambda: len(c.artefakte.liste) == 2 and not c.artefakte._schnell_laeuft)
        karten = [k for k in c.karten if k["art"] == "ergebnis"]
        assert len(karten) == 1 and karten[0]["ids"] == [1, 2]
        # die gebündelte Vollauswertung danach: ergänzt, legt nichts doppelt an
        await c.artefakte.erkennen()
        return c

    c = asyncio.run(ablauf())
    assert [a.typ for a in c.artefakte.liste] == ["entscheidung", "aufgabe"]
    assert c._client.anfragen[-1][0] == A.SYSTEM
    assert any(e["art"] == "artefakte_schnell" for e in c.protokoll)


def test_ansprache_an_nestor_und_gewoehnliche_saetze_kosten_nichts():
    async def ablauf():
        c = _coach()
        c.artefakte.satz([_satz(c, "Nestor, wie viel Budget haben wir beschlossen?", 10, 13)])
        c.artefakte.satz([_satz(c, "Letztes Jahr war das Fest gut besucht.", 14, 17)])
        await asyncio.sleep(0.05)
        return c

    c = asyncio.run(ablauf())
    assert c._client.anfragen == [] and not c.karten


# --- Kein stiller Ausfall -----------------------------------------------------------------------------------------
def test_fehler_der_automatischen_erkennung_sichtbar_im_band_und_wiederholt_im_naechsten_takt():
    async def ablauf():
        c = _coach(Fehler500(), {"artefakte": [AUFGABE]})
        _satz(c, "Sabine liefert bis Freitag die Fahrten.", 50, 54)
        await c.artefakte.erkennen()  # wie Punktwechsel/20-Minuten-Takt
        nach_fehler = (c.fehler, [(h.art, h.stufe, h.text) for h in c.meeting.hinweise], list(c.artefakte.liste))
        c.meeting.virtuelle_zeit = 54 + A.WIEDERHOLEN_AB + 1
        c.artefakte.takt()  # nächster fälliger Takt
        await _warten_bis(lambda: len(c.artefakte.liste) == 1 and not c.artefakte.laeuft)
        return c, nach_fehler

    c, (fehler, band, liste) = asyncio.run(ablauf())
    assert liste == []
    assert fehler.startswith("Ergebnis-Erkennung gestört") and "HTTP 500" in fehler and "30 s" in fehler
    assert [(art, stufe) for art, stufe, _ in band] == [("fehler", "warnung")]
    # erholt: Fehlerzeile weg, Band-Hinweis beendet, beides im Protokoll und im Technikbericht
    assert c.fehler is None
    h = c.meeting.hinweise[0]
    assert h.zeit + h.dauer <= c.meeting.jetzt()
    technik = bericht(c)["technik"]["ki_fehler"]
    assert [(e["art"], e["bereich"]) for e in technik] == [("ki_fehler", "artefakte"), ("ki_erholt", "artefakte")]
    assert technik[0]["fehler"] == "Fehler500 (HTTP 500)"


def test_fehler_der_schnell_erkennung_wartet_auf_den_takt_mit_wachsendem_abstand():
    async def ablauf():
        c = _coach(Fehler500(), Fehler500(), {"artefakte": [BESCHLUSS]})
        a = c.artefakte
        a.satz([_satz(c, "Wir beschließen für das Sommerfest maximal neuntausend Euro.", 40, 45)])
        await _warten_bis(lambda: not a._schnell_laeuft and a._wiederholen_um is not None)
        assert a._wiederholen_um == pytest.approx(45 + 30)
        a.satz([_satz(c, "Machst du das bis Montag?", 46, 48)])  # wartet auf den Takt statt den Anbieter zu bedrängen
        await asyncio.sleep(0.02)
        assert len(c._client.anfragen) == 1
        c.meeting.virtuelle_zeit = 76
        a.takt()
        await _warten_bis(lambda: not a._schnell_laeuft and len(c._client.anfragen) == 2)
        assert a._wiederholen_um == pytest.approx(76 + 60)  # Abstand verdoppelt
        c.meeting.virtuelle_zeit = 137
        a.takt()
        await _warten_bis(lambda: len(a.liste) == 1 and not a._schnell_laeuft)
        return c

    c = asyncio.run(ablauf())
    # alle wartenden Sätze gingen beim erfolgreichen Versuch mit
    assert "neuntausend" in c._client.anfragen[-1][1] and "Montag" in c._client.anfragen[-1][1]
    assert c.fehler is None and c.artefakte._abstand == A.WIEDERHOLEN_AB
    assert sum(1 for h in c.meeting.hinweise if h.art == "fehler") == 1  # höchstens einmal je Minute im Band


def test_themen_zuordnung_meldet_ueber_dieselbe_stelle(monkeypatch):
    from coach import themen

    async def kaputt(*a, **k):
        raise Fehler500()

    async def ablauf():
        c = _coach()
        monkeypatch.setattr(themen, "zuordnen", kaputt)
        await c._themen_pruefen("Person 1: Wir reden über das Budget.")
        return c

    c = asyncio.run(ablauf())
    assert c.fehler.startswith("Themen-Zuordnung gestört")
    assert [h.art for h in c.meeting.hinweise] == ["fehler"]
    assert [e["bereich"] for e in ki_fehler.ereignisse(c)] == ["themen"]


def test_fremder_fehler_bleibt_beim_erholen_stehen():
    c = _coach()
    ki_fehler.melden(c, "artefakte", Fehler500())
    c.fehler = "Live-Text: Verbindung weg"
    ki_fehler.erholt(c, "artefakte")
    assert c.fehler == "Live-Text: Verbindung weg"


# --- Basis: Funkgerät-Hinweis einmal ------------------------------------------------------------------------------
def test_basis_erklaert_das_funkgeraet_beim_ersten_ignorierten_ansprechen_einmal():
    c = _coach(stufe="basis")
    for t in (10, 80, 200):  # auch nach mehr als einer Minute nicht noch einmal
        c.meeting.virtuelle_zeit = t
        c.taste_hinweis()
    texte = [h.text for h in c.meeting.hinweise if h.art == "taste"]
    assert len(texte) == 1 and texte[0].startswith("In Basis: Sprechtaste halten")
