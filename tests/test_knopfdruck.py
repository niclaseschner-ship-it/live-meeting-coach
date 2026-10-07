"""Modus „Auf Knopfdruck“ (Ticket #6, Lastenheft 3 und 4.2): ohne Knopf kein KI-Aufruf, Knopf transkribiert genau
das Offene, Verwerfen nimmt Warteschlange, Transkript und Aufnahme-Abschnitt heraus."""

import asyncio
import json
import os
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("LMC_OFFLINE", "1")

from coach import knopfdruck  # noqa: E402
from coach.config import EINST, WURZEL  # noqa: E402
from coach.hoeren import wav_aus  # noqa: E402
from coach.pipeline import Coach  # noqa: E402

DEMO = WURZEL / "demo" / "messeplanung.wav"


@pytest.fixture(autouse=True)
def ohne_protokolldateien(monkeypatch):
    """Keine Einträge in logs/nutzung.jsonl und logs/nestor_zeiten.jsonl aus Tests."""
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)
    monkeypatch.setattr("coach.pipeline._zeit_loggen", lambda e: None)


_ZURUECK: list = []


def _einstellen(**werte):
    for k, v in werte.items():
        _ZURUECK.append((k, getattr(EINST, k)))
        object.__setattr__(EINST, k, v)  # Einstellungen sind eingefroren


@pytest.fixture(autouse=True)
def einstellungen_zuruecksetzen():
    yield
    while _ZURUECK:
        k, alt = _ZURUECK.pop()
        object.__setattr__(EINST, k, alt)


class Explodiert:
    """Client, der bei jedem Zugriff fehlschlägt – und sich jeden Versuch merkt (die Pipeline fängt Fehler ab)."""

    def __init__(self) -> None:
        self.aufrufe: list[str] = []

    def __getattr__(self, name):
        self.aufrufe.append(name)
        raise RuntimeError(f"KI-Aufruf ohne Knopf: {name}")


# --- Einverständnis-Hinweis: weitere (freie) Regeln, Ticket #10 ------------------

def test_einverstaendnis_nennt_weitere_regeln():
    from coach.zustand import Agendapunkt, Meeting

    m = Meeting(agenda=[Agendapunkt("Budget")], regeln=["Handys bleiben in der Tasche"])
    text = knopfdruck.einverstaendnis(m)
    assert "Handys bleiben in der Tasche" in text and "prüfe ich nicht" in text


def test_einverstaendnis_ohne_weitere_regeln_unveraendert():
    from coach.zustand import Agendapunkt, Meeting

    m = Meeting(agenda=[Agendapunkt("Budget")])
    assert knopfdruck.einverstaendnis(m) == knopfdruck.EINVERSTAENDNIS


# --- 1. Ohne Knopf kein Aufruf ----------------------------------------------------

def test_ohne_knopf_kein_ki_aufruf_lokale_signale_laufen(monkeypatch):
    """Abgespieltes Meeting (die ersten 75 s der Demo) im Modus Knopfdruck mit einem Client, der bei jedem Aufruf
    fehlschlägt: kein Aufruf, keine Live-Text-Verbindung, kein Gespräch, kein Bild – Redeanteile und Monolog da."""
    andere = []

    class KeinLiveText:
        def __init__(self, *a, **k):
            andere.append("livetext")

    async def kein_bild(*a, **k):
        andere.append("claude-bild")
        raise RuntimeError("Bild ohne Knopf")

    monkeypatch.setattr("coach.hoeren.LiveText", KeinLiveText)
    monkeypatch.setattr("coach.onepager.erzeugen", kein_bild)
    monkeypatch.setattr("coach.gespraech.Gespraech", KeinLiveText)
    _einstellen(onepager_minuten=0.25, live_art="schnell", stimme_aus=False)  # live: Bild im Takt alle 15 s

    async def lauf():
        c = Coach()
        c.modus = "knopfdruck"
        c._client = client = Explodiert()
        einrichtung = json.loads(DEMO.with_suffix(".json").read_text(encoding="utf-8"))
        c.einrichten(einrichtung | {"regel_ids": ["ausreden", "thema", "zeit", "kurz", "ton", "ergebnisse", "alle"]})
        c.monolog_sekunden = 5.0  # die Demo hat nur kurze Beiträge (längster ~8 s) – Monolog hier schon ab 5 s
        c.simulation_laeuft = True  # wie Coach.abspielen
        await c.hoeren_starten()
        c.assistent.knopf()  # Dashboard-Knopf „fragen“ der Nestor-Leiste
        c.assistent.ansagen("Das Bild ist fertig.")
        kurz_seen = set()
        with wave.open(str(DEMO)) as w:
            n = 0
            while n < 75 * 24000:
                daten = w.readframes(2400)
                if not daten:
                    break
                await c.hoeren_zufuehren(daten)
                n += len(daten) // 2
                c.takt()
                if n == 40 * 24000:
                    c.punkt_wechseln(1)  # Agendawechsel per Klick: Regel 10 würde live den Punkt prüfen
                kurz_seen.update(r["farbe"] for r in c.schnappschuss()["regel_status"] if r["id"] == "kurz")
                if n % 24000 == 0:  # wie in Echtzeit: Stimmanalysen jeder Sekunde abwarten
                    await asyncio.gather(*c.hoerstrom._analysen)
        offen = c.hoerstrom.offen()
        await c.hoeren_beenden()
        await asyncio.sleep(0.2)
        return c, client, offen, kurz_seen

    c, client, offen, kurz_seen = asyncio.run(lauf())
    assert client.aufrufe == [], f"KI-Aufrufe ohne Knopf: {client.aufrufe}"
    assert andere == []
    m = c.meeting
    assert m.transkript == [] and offen["aeusserungen"] > 5  # alles wartet auf den Knopf
    assert len(m.redeanteile()) >= 2 and sum(m.redeanteile().values()) > 30
    assert any(h.art == "monolog" for h in m.hinweise) or kurz_seen & {"gelb", "rot"}
    assert any(h.art == "info" and "Knopf" in h.text for h in m.hinweise)  # Einverständnis als Hinweis
    assert c.assistent.zustand == "bereit" and not c.assistent.sprechzeiten and c.karten == []
    status = {r["id"]: r for r in c.schnappschuss()["regel_status"]}
    assert status["thema"]["detail"] == "auf Knopfdruck" and status["ton"]["detail"] == "auf Knopfdruck"


# --- 2. Knopf transkribiert genau das Offene, in Reihenfolge -------------------------

class Attrappe:
    """Transkription: Text je WAV, die frühen Äußerungen antworten am langsamsten; Chat: feste Karte."""

    def __init__(self, texte: dict[bytes, str]) -> None:
        self.texte = texte
        self.transkribiert: list[str] = []
        self.gleichzeitig = self.hoechstens = 0
        self.chat_aufrufe = 0

        async def transkribieren(*, file, **kw):
            text = self.texte[file[1]]
            self.gleichzeitig += 1
            self.hoechstens = max(self.hoechstens, self.gleichzeitig)
            await asyncio.sleep(0.01 * (10 - int(text.split()[-1])))  # Nr. 1 kommt zuletzt zurück
            self.gleichzeitig -= 1
            self.transkribiert.append(text)
            return SimpleNamespace(text=text)

        async def chat(**kw):
            self.chat_aufrufe += 1
            inhalt = {"titel": "Budget offen", "punkte": ["Ihr seid bei Punkt eins.", "Vorschlag: zum Budget."],
                      "naechster_punkt": 2}
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(inhalt)))],
                                   usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))

        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=transkribieren))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=chat))


def _proben(nr: int, sekunden: float = 1.0) -> np.ndarray:
    return np.full(int(16000 * sekunden), 0.001 * nr, dtype=np.float32)


async def _knopf_meeting(texte: dict[bytes, str], archiv: bool = False) -> Coach:
    c = Coach()
    c.modus = "knopfdruck"
    c._client = Attrappe(texte)
    c.archiv_aktiv = archiv
    c.einrichten({"titel": "Knopf", "agenda": [{"titel": "Termin", "minuten": 5}, {"titel": "Budget", "minuten": 5}],
                  "regel_ids": ["thema", "ton", "kurz"]})
    await c.hoeren_starten()
    # Stimmanalyse ohne Modell: eine Person je Äußerung
    c.hoerstrom.stimmen.analysieren = lambda p: {"person": 0, "abschnitte": [(0.0, len(p) / 16000, 0)],
                                                 "mischung": [], "ueberlappung": []}
    return c


async def _sagen(c: Coach, nr: int, start: float) -> None:
    c.hoerstrom.sekunden = c.meeting.virtuelle_zeit = start + 1.5
    await c.hoerstrom._aeusserung(start, start + 1.0, _proben(nr))


def test_knopf_transkribiert_genau_das_offene_in_reihenfolge():
    texte = {wav_aus(_proben(nr)): f"Satz Nummer {nr}" for nr in range(1, 9)}

    async def lauf():
        c = await _knopf_meeting(texte)
        for nr in range(1, 7):
            await _sagen(c, nr, nr * 3.0)
        assert c.meeting.transkript == [] and c.hoerstrom.offen()["aeusserungen"] == 6
        meldungen = []

        async def senden(n):
            meldungen.append(n)
        await knopfdruck.ausfuehren(c, "stand", senden=senden)
        assert c.knopf.fehler is None
        erster = list(c._client.transkribiert)
        nach_erstem = [s.text for s in c.meeting.transkript]
        for nr in (7, 8):
            await _sagen(c, nr, 20.0 + nr)
        await knopfdruck.ausfuehren(c, "stand", senden=senden)
        return c, erster, nach_erstem, meldungen

    c, erster, nach_erstem, meldungen = asyncio.run(lauf())
    a = c._client
    assert sorted(erster) == [f"Satz Nummer {n}" for n in range(1, 7)]
    assert erster[0] != "Satz Nummer 1"  # parallel: die erste kam zuletzt zurück …
    assert nach_erstem == [f"Satz Nummer {n}" for n in range(1, 7)]  # … steht aber vorn im Transkript
    assert a.hoechstens == 4  # höchstens vier gleichzeitig
    assert sorted(a.transkribiert[6:]) == ["Satz Nummer 7", "Satz Nummer 8"]  # zweiter Knopf: nur die neuen
    assert [s.text for s in c.meeting.transkript] == [f"Satz Nummer {n}" for n in range(1, 9)]
    assert a.chat_aufrufe == 2 and c.hoerstrom.offen()["aeusserungen"] == 0
    karte = c.karten[-1]
    assert karte["art"] == "stand" and karte["punkte"][-1].startswith("Vorschlag")
    assert c.meeting.vorschlag["punkt"] == 1  # „Weiter zu Budget?“ – die Runde entscheidet
    schritte = [m["schritt"] for m in meldungen[: len(meldungen) // 2 + 1]]
    assert schritte[0] == "transkribiere" and "denke" in schritte and meldungen[-1]["schritt"] == "fertig"
    assert all(m["typ"] == "knopf" and m["art"] == "stand" and 0 <= m["anteil"] <= 1 for m in meldungen)
    assert c.knopf.laeuft is None and c.knopf.fehler is None


def test_zweiter_knopf_waehrend_eines_laufs_wird_abgewiesen():
    async def lauf():
        c = await _knopf_meeting({})
        knopfdruck.reservieren(c, "bild")
        with pytest.raises(knopfdruck.KnopfFehler):
            knopfdruck.reservieren(c, "stand")
        c.knopf.laeuft = None
        c.modus = "live"
        with pytest.raises(knopfdruck.KnopfFehler):
            knopfdruck.reservieren(c, "stand")
    asyncio.run(lauf())


# --- 3. Verwerfen ------------------------------------------------------------------

@pytest.fixture
def ablage():
    # Unter der Arbeitskopie statt /tmp (RAM-Disk); logs/ ist von Git ausgenommen
    ordner = WURZEL / "logs" / f"test_knopfdruck_{os.getpid()}"
    alt = EINST.archiv, EINST.aufnahme_speichern
    object.__setattr__(EINST, "archiv", str(ordner))
    object.__setattr__(EINST, "aufnahme_speichern", True)
    yield ordner
    object.__setattr__(EINST, "archiv", alt[0])
    object.__setattr__(EINST, "aufnahme_speichern", alt[1])
    shutil.rmtree(ordner, ignore_errors=True)


def test_letzte_5_minuten_verwerfen(ablage):
    texte = {wav_aus(_proben(nr)): f"Satz Nummer {nr}" for nr in range(1, 7)}
    dauer = 330  # 5:30 min Meeting

    async def lauf():
        c = await _knopf_meeting(texte, archiv=True)
        ton = np.full(24000, 1000, dtype="<i2").tobytes()  # 1 s hörbarer Ton für die Aufnahme
        for _ in range(dauer):
            c.archiv.audio(ton)
        for nr, start in ((1, 5.0), (2, 12.0), (3, 25.0), (4, 40.0)):
            await _sagen(c, nr, start)
        c.meeting.virtuelle_zeit = c.hoerstrom.sekunden = 100.0
        await knopfdruck.ausfuehren(c, "stand")  # Sätze 1–4 im Transkript, Karte um 1:40
        for nr, start in ((5, 200.0), (6, 320.0)):
            await _sagen(c, nr, start)
        c.meeting.virtuelle_zeit = c.hoerstrom.sekunden = float(dauer)
        anteile = dict(c.meeting.redeanteile())
        erg = await knopfdruck.verwerfen(c, 5)
        zustand = ([s.text for s in c.meeting.transkript], c.hoerstrom.offen(), list(c.karten), anteile,
                   dict(c.meeting.redeanteile()))
        await c.hoeren_beenden()
        c.archiv.schreiben(endgueltig=True)
        return c, erg, zustand

    c, erg, (transkript, offen, karten, anteile_vorher, anteile_nachher) = asyncio.run(lauf())
    assert erg["ab"] == 30.0 and erg["aeusserungen"] == 2 and erg["saetze"] == 1
    assert transkript == ["Satz Nummer 1", "Satz Nummer 2", "Satz Nummer 3"]  # Satz 4 (0:40) ist weg
    assert offen["aeusserungen"] == 0  # Sätze 5 und 6 nie transkribiert
    assert karten == []  # die Karte von 1:40 kann Inhalte von 0:40 enthalten
    assert anteile_nachher == anteile_vorher  # Redeanteile bleiben
    with wave.open(str(c.archiv.ordner / "aufnahme.wav")) as w:
        assert w.getnframes() == dauer * 24000  # Zeitachse bleibt
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert (a[: 30 * 24000] == 1000).all()  # davor unverändert
    assert not a[30 * 24000:].any()  # danach Stille – der Ton ist gelöscht
    arten = [json.loads(z)["art"] for z in (c.archiv.ordner / "debug" / "ereignisse.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "verworfen" in arten


def test_alles_verwerfen_und_danach_weiter(ablage):
    texte = {wav_aus(_proben(nr)): f"Satz Nummer {nr}" for nr in range(1, 4)}

    async def lauf():
        c = await _knopf_meeting(texte, archiv=True)
        c.archiv.audio(np.full(24000 * 10, 500, dtype="<i2").tobytes())
        await _sagen(c, 1, 2.0)
        await knopfdruck.ausfuehren(c, "stand")
        await _sagen(c, 2, 6.0)
        c.meeting.virtuelle_zeit = c.hoerstrom.sekunden = 10.0
        await knopfdruck.verwerfen(c, None)
        c.archiv.audio(np.full(24000 * 2, 700, dtype="<i2").tobytes())  # Aufnahme läuft weiter
        await _sagen(c, 3, 10.5)
        await knopfdruck.ausfuehren(c, "stand")
        await c.hoeren_beenden()
        c.archiv.schreiben(endgueltig=True)
        return c

    c = asyncio.run(lauf())
    assert [s.text for s in c.meeting.transkript] == ["Satz Nummer 3"]
    with wave.open(str(c.archiv.ordner / "aufnahme.wav")) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert len(a) == 12 * 24000 and not a[: 10 * 24000].any() and (a[10 * 24000:] == 700).all()


# --- Weitere Knöpfe und Endpunkte ------------------------------------------------------

def test_regeln_und_protokoll_knopf(monkeypatch):
    texte = {wav_aus(_proben(nr, 12.0)): f"Satz Nummer {nr}" for nr in range(1, 4)}

    async def lauf():
        c = await _knopf_meeting(texte)
        c.meeting.regel_ids = ["thema", "ton", "kurz", "ergebnisse"]
        antworten = iter([
            {"thema": {"eingehalten": False, "befund": "Ab 0:20 ging es um das Catering."},
             "ergebnisse": {"eingehalten": True, "befund": "Termin beschlossen."},
             "ton": [{"zitat": "so ein Mist", "art": "kraftausdruck"}]},
            {"ergebnis": "Termin im April beschlossen", "entscheidungen": [{"was": "Termin", "ergebnis": "einstimmig"}],
             "aufgaben": [{"was": "Stand buchen", "wer": "Lea", "bis": None}]},
        ])

        async def chat(**kw):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(next(antworten))))],
                                   usage=None)
        c._client.chat = SimpleNamespace(completions=SimpleNamespace(create=chat))
        for nr in (1, 2, 3):
            c.hoerstrom.sekunden = c.meeting.virtuelle_zeit = nr * 13.0
            await c.hoerstrom._aeusserung(nr * 13.0 - 12.5, nr * 13.0 - 0.5, _proben(nr, 12.0))
        await knopfdruck.ausfuehren(c, "regeln")
        await knopfdruck.ausfuehren(c, "protokoll")
        return c

    c = asyncio.run(lauf())
    status = {r["id"]: r for r in c.schnappschuss()["regel_status"]}
    assert status["thema"]["farbe"] == "gelb" and status["ton"]["farbe"] == "rot"
    assert status["ergebnisse"]["farbe"] == "gruen" and "Stand" in status["ergebnisse"]["detail"]
    regeln, protokoll = c.karten[-2], c.karten[-1]
    assert regeln["art"] == "regeln" and any("Catering" in p for p in regeln["punkte"])
    assert protokoll["art"] == "protokoll" and protokoll["punkte"][0] == "1. Termin: Termin im April beschlossen"
    assert "Stand buchen (wer: Lea, bis: offen)" in c.knopf.protokoll and c.meeting.ergebnisse[0]["ergebnis"]
    assert any(h.art == "ton" for h in c.meeting.hinweise)


def test_knopf_endpunkte(monkeypatch):
    from fastapi.testclient import TestClient

    from coach.server import app, coach

    web = TestClient(app, client=("127.0.0.1", 5000))
    alt = coach.modus
    try:
        coach.modus = "knopfdruck"
        assert web.post("/api/knopf/stand", json={}).status_code == 409  # kein Meeting
        assert web.post("/api/knopf/frage", json={}).status_code == 400  # keine Frage
        assert web.post("/api/knopf/verwerfen", json={"minuten": 5}).status_code == 409
        assert web.get("/api/knopf/protokoll.md").status_code == 404
        coach.modus = "live"
        assert web.post("/api/knopf/verwerfen", json={"minuten": None}).status_code == 409
    finally:
        coach.modus = alt
