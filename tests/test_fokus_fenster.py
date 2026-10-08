"""Ticket #24: Themen-Zuordnung in gleitenden Fenstern, Abschnitte schließen auch nach Zeit, kein veralteter
Fokus-Hinweis nach der Rückkehr. Situation aus dem Cloud-Lauf premium_grenz2 (08.10.): Kaffeemaschine 5:32–6:03,
danach 30 s Pause. Die Zuordnung ist ein Stellvertreter ohne Netz (Schlüsselwörter statt Sprachmodell)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from coach import analyse, pipeline, themen
from coach.pipeline import Coach
from coach.zustand import Agendapunkt, Meeting, Segment

FREMD = ("kaffee", "wasser", "tank", "küche", "start", "post mortem", "entkalker")

# (start, ende, Ankunft im Dashboard, Text) – Zeiten wie im Mitschnitt ws.jsonl
VORHER = [
    (243.3, 257.0, 259.7, "Genau. Der eigentliche Fehler war, dass es für die Schemaänderung keinen getesteten "
                          "Downpfad gab, das Runbook war veraltet."),
    (257.2, 258.8, 260.1, "Wollte ich nichts Ungeprüftes ausführen."),
    (308.5, 309.5, 310.9, "Und wer kümmert sich darum?"),
]
KAFFEE = [
    (331.9, 337.5, 338.6, "Ganz kurz, weil wir gerade bei Montagmorgen und ungeprüften Dingen sind: Die Kaffeemaschine "
                          "war ja ebenfalls kaputt."),
    (338.0, 341.9, 343.1, "Ich stand um halb neun davor, sie blinkte dreimal, dann kam nur lauwarmes Wasser."),
    (342.8, 347.7, 348.9, "Jonas meinte nochmal, man müsse den Tank einmal herausnehmen, aber danach lief das Ding aus."),
    (348.2, 351.9, 352.8, "Halbe Küchenboden war nass und gleichzeitig kamen die ersten Kundentickets rein."),
    (352.7, 355.0, 355.9, "Das war ein wirklich ein beschissener Start."),
    (355.7, 357.9, 359.0, "Vielleicht schreiben wir dafür aber kein Post mortem."),
    (358.5, 361.3, 362.5, "Und dann kleben einfach einen Zettel dran und bestellen Entkalker."),
]
ZURUECK = (362.5, 363.4, 364.6, "Gut. Zurück zur Datenbank.")
DANACH = [  # nach 30 s Pause wieder bei der Ursache
    (397.0, 398.4, 399.6, "Das war ein echtes Eigentor von uns, die Migration lief ohne Concurrent-Option."),
    (400.2, 404.1, 406.8, "Das ist ein Nest von Abhängigkeiten zwischen Deployment und Datenbank-Schema."),
    (404.1, 405.6, 406.8, "Da müssen wir beim Rollback vorsichtig sein."),
]
BEGINN, RUECKKEHR = 331.9, 363.4


class Zuordnung:
    """Stellvertreter für das Sprachmodell: „neu“, wenn im neuen Abschnitt das Kaffee-Thema überwiegt."""

    def __init__(self) -> None:
        self.aufrufe: list[str] = []
        self.halt: asyncio.Event | None = None  # gesetzt: die Antwort wartet darauf (Zuordnung läuft noch)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kw):
        text = kw["messages"][1]["content"].split("Neuer Abschnitt:\n", 1)[1]
        self.aufrufe.append(text)
        if self.halt is not None:
            await self.halt.wait()
        zeilen = [z for z in text.splitlines() if z and not z.startswith("[")]
        fremd = sum(len(z) for z in zeilen if any(w in z.lower() for w in FREMD))
        art = "neu" if fremd > sum(len(z) for z in zeilen) / 2 else "aktiv"
        inhalt = {"punkt": None if art == "neu" else 2, "art": art, "konfidenz": 0.95, "begruendung": art}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(inhalt)))],
                               usage=None)


@pytest.fixture
def coach(monkeypatch):
    monkeypatch.setattr(pipeline, "nutzung_loggen", lambda eintrag: None)
    c = Coach()
    c._client = Zuordnung()
    c.meeting.agenda = [Agendapunkt(t) for t in ("Ablauf des Ausfalls", "Ursache", "Maßnahmen")]
    c.meeting.aktiver_punkt = 1
    c.meeting.regel_ids = ["thema"]
    c.assistent.aktiv = False
    c.meeting.starten(virtuell=True)
    return c


async def abspielen(c: Coach, saetze: list[tuple], bis: float, von: float = 240.0) -> None:
    """Sätze zu ihrer Ankunftszeit zuführen, dazwischen den Takt (halbe Sekunde) wie im Server; die Sprachaktivität
    (VAD) folgt den Satzzeiten. Laufende Zuordnungen werden abgewartet."""
    warte = sorted(saetze, key=lambda s: s[2])
    t = von
    while t <= bis:
        c.meeting.virtuelle_zeit = t
        if any(s[0] <= t <= s[1] for s in saetze):
            c.sprache_melden()
        while warte and warte[0][2] <= t:
            start, ende, _, text = warte.pop(0)
            await c.satz(Segment("Person 4", text, start, ende))
        c.takt()
        await asyncio.sleep(0)
        async with c._themen_sperre:
            pass
        await asyncio.sleep(0)
        t = round(t + 0.5, 1)


def fokus_hinweise(c: Coach) -> list[float]:
    return [h.zeit for h in c.meeting.hinweise if h.art == "fokus"]


def fokus_ampel(c: Coach) -> str:
    return analyse.fokus_status(c.meeting.themen_verlauf, c.karenz_bloecke)[0]


def test_kaffeemaschine_hinweis_binnen_25_s_und_nicht_nach_der_rueckkehr(coach):
    asyncio.run(abspielen(coach, VORHER + KAFFEE + [ZURUECK] + DANACH, bis=420))
    hinweise = fokus_hinweise(coach)
    assert len(hinweise) == 1
    assert BEGINN < hinweise[0] <= BEGINN + 25  # vorher: 6:48, 76 s nach Beginn
    assert hinweise[0] < RUECKKEHR
    assert fokus_ampel(coach) == "gruen"


def test_abschweifung_bis_zur_pause_dann_zurueck_zur_datenbank(coach):
    """Wie im Ticket beschrieben: Kaffee bis 6:03, 30 s Pause, erst dann „Zurück zur Datenbank“."""
    spaet = (394.0, 395.2, 396.4, "Zurück zur Datenbank.")
    danach = [(s[0] + 2, s[1] + 2, s[2] + 2, s[3]) for s in DANACH]
    asyncio.run(abspielen(coach, VORHER + KAFFEE + [spaet] + danach, bis=430))
    hinweise = fokus_hinweise(coach)
    assert len(hinweise) == 1 and hinweise[0] <= BEGINN + 25
    assert not [t for t in hinweise if t > 394.0]
    assert fokus_ampel(coach) == "gruen"


def test_abschnitt_schliesst_nach_pause_ohne_naechsten_satz(coach):
    """Der letzte Abschnitt der Abschweifung (unter der Sprechmenge eines Schritts) wartet nicht mehr auf den
    nächsten Satz nach der Pause – er wird nach der Ruhezeit eingeordnet."""
    asyncio.run(abspielen(coach, VORHER + KAFFEE, bis=380))
    assert not coach._abschnitt
    assert any("Entkalker" in a for a in coach._client.aufrufe)  # letzter Kaffee-Satz ist eingeordnet


def test_kurzer_einzelsatz_loest_keine_zuordnung_aus(coach):
    """Karenz-Grundidee: ein einzelner kurzer Satz in der Stille wird nicht für sich eingeordnet."""
    asyncio.run(abspielen(coach, [(300.0, 301.5, 302.5, "Die Kaffeemaschine ist übrigens kaputt.")], bis=330,
                          von=299))
    assert coach._client.aufrufe == []
    assert fokus_hinweise(coach) == []


def test_rueckkehr_waehrend_der_zuordnung_verwirft_den_hinweis(coach):
    """Die Zuordnung des Kaffee-Fensters läuft noch, da fällt „Gut. Zurück zur Datenbank.“ – kein Hinweis mehr."""

    async def ablauf():
        m = coach.meeting
        m.virtuelle_zeit = 349.0
        for start, ende, _, text in KAFFEE[:3]:
            coach._abschnitt.append(Segment("Person 4", text, start, ende))
        coach._client.halt = asyncio.Event()
        coach._abschnitt_schliessen()
        await asyncio.sleep(0)
        assert coach._themen_sperre.locked()
        m.virtuelle_zeit = 364.6
        await coach.satz(Segment("Person 4", ZURUECK[3], ZURUECK[0], ZURUECK[1]))
        coach._client.halt.set()
        await asyncio.sleep(0)
        async with coach._themen_sperre:
            pass

    asyncio.run(ablauf())
    assert coach.meeting.themen_verlauf[0]["art"] == "neu"  # die Zuordnung selbst bleibt im Verlauf
    assert fokus_hinweise(coach) == []
    assert fokus_ampel(coach) == "gruen"


def test_fenster_ueberlappen_und_kontext_ohne_doppelung(coach):
    """Jedes Fenster umfasst die neuen Sätze und davor eingeordnete (bis ~15 s Sprache); Kontext ist nur Älteres."""
    asyncio.run(abspielen(coach, VORHER + KAFFEE, bis=380))
    aufrufe = coach._client.aufrufe
    zweites_kaffee = next(a for a in aufrufe if "Küchenboden" in a)
    assert "Kaffeemaschine" in zweites_kaffee or "lauwarmes Wasser" in zweites_kaffee  # Überlappung
    assert "Und wer kümmert sich darum?" not in aufrufe[1]  # zu lange her (Pause) – nicht im Fenster


def test_rueckkehr_ansage():
    titel = ["Ablauf des Ausfalls", "Ursache", "Maßnahmen"]
    assert analyse.rueckkehr("Gut. Zurück zur Datenbank.", titel, 1)
    assert analyse.rueckkehr("Ja, zurück zum Incident. Als Root Cause halten wir fest …", titel, 1)
    assert analyse.rueckkehr("Gehen wir zurück zur Ursache.", titel, 1)  # Ziel ist der aktive Punkt
    assert not analyse.rueckkehr("Lass uns nochmal kurz zu Punkt eins zurück.", titel, 1)  # Wechsel, keine Rückkehr
    assert not analyse.rueckkehr("Darauf kommen wir später zurück.", titel, 1)
    assert not analyse.rueckkehr("Das hat zwar die Pods zurückgesetzt.", titel, 1)


def test_themen_auswerten_nach_rueckkehr_ohne_hinweis():
    from coach.entscheider import Entscheider

    m = Meeting(agenda=[Agendapunkt("A"), Agendapunkt("B")], regel_ids=["thema"])
    m.starten(virtuell=True)
    e = Entscheider(90)
    analyse.themen_auswerten(m, e, {"art": "neu", "punkt": None, "konfidenz": 0.9, "begruendung": "b"}, 1,
                             zurueckgekehrt=True)
    assert m.hinweise == []
    assert analyse.fokus_status(m.themen_verlauf, 1)[0] == "gruen"
    analyse.themen_auswerten(m, e, {"art": "neu", "punkt": None, "konfidenz": 0.9, "begruendung": "b"}, 1)
    assert [h.art for h in m.hinweise] == ["fokus"]


def test_karenz_bleibt_ein_fenster_bei_den_startwerten():
    assert Coach().karenz_bloecke == 1


def test_nachricht_mit_eigenem_kontext():
    m = Meeting(agenda=[Agendapunkt("A")], block_texte=["alt 1", "alt 2", "alt 3"])
    assert "alt 3" in themen.nachricht(m, "neu")
    text = themen.nachricht(m, "neu", ["Person 1: davor"])
    assert "Person 1: davor" in text and "alt 3" not in text


def test_cloudtest_kennzahl_verzug_abschweifung():
    """Prüfpunkt im Cloudtest: Verzug ≤ 25 s und kein Hinweis nach der Rückkehr (Zahlen aus premium_grenz2)."""
    import os
    import sys
    from pathlib import Path

    pytest.importorskip("playwright")
    tmpdir = os.environ.get("TMPDIR")  # cloudtest setzt TMPDIR beim Import – für die übrigen Tests zurück
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import cloudtest
    finally:
        sys.path.pop(0)
        if tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = tmpdir
    ref = {"ereignisse": [{"ereignis": "abschweifung", "zeit_s": 332.3,
                           "text": "Die Kaffeemaschine war ja ebenfalls kaputt. Gut, zurück zur Datenbank."}]}
    segmente = [{"text": "Gut. Zurück zur Datenbank.", "start": 362.5, "ende": 363.4}]
    vorher = cloudtest.abschweifung_kennzahl(ref, segmente, [{"art": "fokus", "zeit": 408.1}])
    assert vorher[0]["status"] == "fehlt" and "veraltet" in vorher[0]["detail"]
    nachher = cloudtest.abschweifung_kennzahl(ref, segmente, [{"art": "fokus", "zeit": 348.1}])
    assert nachher[0]["status"] == "ok" and "+16s" in nachher[0]["detail"]
    spaet = cloudtest.abschweifung_kennzahl(ref, segmente, [{"art": "fokus", "zeit": 360.0}])
    assert spaet[0]["status"] == "fehlt"  # vor der Rückkehr, aber 28 s nach Beginn
    assert cloudtest.abschweifung_kennzahl(ref, segmente, [], ohne_themen=True)[0]["status"] == "beobachtet"
