"""Ticket #83: Nestors Seite in Paket und Spende. Eine Anfrage an Nestor erzeugt genau eine Zeile in
logs/nestor.jsonl (Auslöser, erkannte Absicht/Werkzeugaufruf, Antworttext, Kartenart, Zeit bis zum ersten Ton,
Fehler); die Hörfenster-Ereignisse sind eigene Zeilen im selben Strom. Die Datei landet in Paket und Spende."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from modell_attrappe import Zug

from coach.abschluss import paket, spenden_dateien
from coach.archiv import Archiv
from coach.config import EINST
from coach.pipeline import Coach


@pytest.fixture(autouse=True)
def umgebung(tmp_path, monkeypatch):
    """Nestor.jsonl in ein Testverzeichnis umleiten statt in die echten logs/ des Repos."""
    felder = ("assistent_modus", "stimme_aus", "bestaetigung", "archiv")
    alt = {k: getattr(EINST, k) for k in felder}
    object.__setattr__(EINST, "assistent_modus", "text")
    object.__setattr__(EINST, "stimme_aus", True)
    object.__setattr__(EINST, "bestaetigung", False)
    object.__setattr__(EINST, "archiv", str(tmp_path / "meetings"))
    # archiv.py kopiert aus WURZEL/logs/nestor.jsonl (coach.archiv.WURZEL), unabhängig von coach.pipeline.NESTOR_ZEITEN
    # – im Test müssen beide auf denselben Testordner zeigen statt auf die echten logs/ des Repos.
    monkeypatch.setattr("coach.pipeline.NESTOR_ZEITEN", tmp_path / "logs" / "nestor.jsonl")
    monkeypatch.setattr("coach.archiv.WURZEL", tmp_path)
    yield
    for k, v in alt.items():
        object.__setattr__(EINST, k, v)


class Attrappe:
    """Nur der Chat-Weg wird gebraucht: EINST.stimme_aus überspringt die echte Sprachausgabe. Nicht gestreamte
    Aufrufe (z. B. die Karte zur Antwort, Ticket #74) bekommen eine einfache, nicht-leere Antwort."""

    def __init__(self, *zuege) -> None:
        self.zuege = list(zuege)  # Züge des Modells (tests/modell_attrappe.py)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        if kw.get("stream"):
            from modell_attrappe import Strom

            return Strom(self.zuege.pop(0) if self.zuege else "")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"zeigen": false}'))], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def _coach(*zuege) -> Coach:
    c = Coach()
    c.stufe_setzen("premium")
    c._einrichten({"titel": "Team Runde", "agenda": [{"titel": "Start", "minuten": 5}]})
    c._client = Attrappe(*zuege)
    c.meeting.starten(virtuell=True)
    c.direkt.append(lambda n: asyncio.sleep(0))  # Nachrichten ans Dashboard müssen niemand erreichen
    return c


def _zeilen(pfad) -> list[dict]:
    if not pfad.exists():
        return []
    return [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()]


# --- Eine Anfrage, eine Zeile mit den geforderten Feldern ----------------------------------------------------------
def test_eine_anfrage_erzeugt_eine_zeile_mit_allen_feldern(tmp_path):
    async def ablauf():
        c = _coach("Ihr liegt gut in der Zeit.")
        b = c.assistent.bogen_starten("frage", "Wo stehen wir?", "stimme")
        await b.task
        return c, b

    c, b = asyncio.run(ablauf())
    zeilen = _zeilen(tmp_path / "logs" / "nestor.jsonl")
    bogen_zeilen = [z for z in zeilen if z.get("ausloeser") == "bogen"]
    assert len(bogen_zeilen) == 1
    z = bogen_zeilen[0]
    assert z["quelle"] == "stimme"  # Auslöser: hier per Ansprache/Stimme
    assert z["art"] == "frage"
    assert z["aktion"] is None and z["werkzeuge"] == []  # kein Werkzeugaufruf
    assert z["antwort"] == "Ihr liegt gut in der Zeit."  # Nestors gesprochener Text
    assert z["kartenart"] is None  # reine Antwort, keine Karte
    assert z["fehler"] is None
    assert "zeit" in z and isinstance(z["zeit"], str)
    assert z["satz"] >= 0  # Dauer bis zum ersten Ton (Zeitpunkt des ersten gesprochenen Satzes)


def test_werkzeugaufruf_mit_argumenten_und_kartenart_landen_in_der_zeile(tmp_path):
    """Ein Werkzeugaufruf steht mit seinen Argumenten in der Zeile; die Kartenart leitet sich daraus ab."""
    async def ablauf():
        c = _coach(Zug(werkzeuge=[("karte_zeigen", {"art": "stand"})]), "Hier ist der Stand.")
        b = c.assistent.bogen_starten("frage", "Zeig mir den Stand", "knopf")
        await b.task
        for z in list(b.zusatz):
            await asyncio.gather(z, return_exceptions=True)
        return c, b

    c, b = asyncio.run(ablauf())
    zeilen = _zeilen(tmp_path / "logs" / "nestor.jsonl")
    [z] = [e for e in zeilen if e.get("ausloeser") == "bogen"]
    assert z["quelle"] == "knopf"
    assert z["aktion"] == {"werkzeuge": ["karte_zeigen"]}
    assert z["werkzeuge"] == [{"name": "karte_zeigen", "argumente": {"art": "stand"}}]
    assert z["kartenart"] == "stand" and z["antwort"] == "Hier ist der Stand."


# --- Paket und Spende enthalten nestor.jsonl, wenn es etwas zu zeigen gibt ------------------------------------------
def test_nestor_jsonl_landet_im_paket_und_in_der_spende(tmp_path):
    async def ablauf():
        c = _coach("Alles im Blick.")
        c.archiv = Archiv(c, audio=False)  # vor der Anfrage: self.seit muss davor liegen (archiv.py: _jsonl_seit)
        b = c.assistent.bogen_starten("frage", "Wie stehen wir?", "stimme")
        await b.task
        await asyncio.sleep(0.05)  # die Karte zur Antwort (Ticket #74) läuft im Hintergrund nach
        await c.hoeren_beenden()
        c.archiv.schreiben(endgueltig=True)
        return c

    c = asyncio.run(ablauf())
    assert (c.archiv.ordner / "nestor.jsonl").exists()
    assert not (c.archiv.ordner / "debug" / "nestor.jsonl").exists()  # nicht unter debug/ (Ticket #83)

    with __import__("zipfile").ZipFile(__import__("io").BytesIO(paket(c.archiv.ordner, mit_aufnahme=False))) as z:
        assert "nestor.jsonl" in z.namelist()

    dateien = spenden_dateien(c.archiv.ordner, "", mit_aufnahme=False)
    [nestor_datei] = [d for d in dateien if d.name == "nestor.jsonl"]
    assert nestor_datei.pfad is not None and nestor_datei.inhalt is None  # gestreamt, wie die Aufnahme
    zeilen = _zeilen(nestor_datei.pfad)
    assert any(z.get("frage", None) or z.get("art") == "frage" for z in zeilen)  # die Drehbuch-Anfrage steht drin
