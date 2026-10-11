"""Ticket #84 ohne Netz: Karte per Zuruf neu aufbereiten – coach/neu_aufbereiten.py (das Modul), das Werkzeug
„karte_neu_aufbereiten“ im Realtime-Gespräch (Premium) und die AKTION-Zeile „neu_aufbereiten“ (Basis)."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from coach import assistent as A
from coach import neu_aufbereiten as N
from coach.assistent import Bogen
from coach.config import EINST
from coach.gespraech import Gespraech
from coach.pipeline import Coach


@pytest.fixture(autouse=True)
def umgebung(monkeypatch):
    """Keine Sprachausgabe (die Dauer wird grob geschätzt), Nutzung nicht protokollieren."""
    alt = EINST.stimme_aus
    object.__setattr__(EINST, "stimme_aus", True)
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)
    yield
    object.__setattr__(EINST, "stimme_aus", alt)


def _client(punkte=("**Preis**: 500 Euro", "**Frist**: Ende Monat"), titel="Kurzfassung"):
    async def create(**kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"titel": titel, "punkte": list(punkte)})))],
            usage=SimpleNamespace(prompt_tokens=42, completion_tokens=7))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


_WAHL = SimpleNamespace(analyse_modell="analyse-modell", analyse_aufwand=None)


# --- coach/neu_aufbereiten.py für sich: welche Karten lassen sich umformen, was liefert der Aufruf ----------------
def test_moeglich_nur_fuer_karten_mit_titel_und_text():
    assert N.moeglich({"art": "recherche", "details": "Text"})
    assert N.moeglich({"art": "antwort", "punkte": ["Eins"]})
    assert not N.moeglich(None)
    assert not N.moeglich({"art": "bild", "punkte": ["x"]})
    assert not N.moeglich({"art": "folie", "punkte": ["x"]})
    assert not N.moeglich({"art": "ueberblick", "punkte": ["x"]})
    assert not N.moeglich({"art": "festgehalten", "ids": [1], "punkte": ["x"]})
    assert not N.moeglich({"art": "beispiel", "punkte": ["x"]})
    assert not N.moeglich({"art": "antwort"})  # weder punkte noch details


def test_erstellen_ohne_passende_karte_client_oder_gueltiges_wie():
    async def ablauf():
        karte = {"art": "antwort", "punkte": ["x"]}
        a1, _ = await N.erstellen(_client(), None, "kürzer", wahl=_WAHL)
        a2, _ = await N.erstellen(None, karte, "kürzer", wahl=_WAHL)
        a3, _ = await N.erstellen(_client(), karte, "unbekannt", wahl=_WAHL)
        return a1, a2, a3
    assert asyncio.run(ablauf()) == (None, None, None)


def test_erstellen_formt_die_karte_um_ohne_quellen_oder_frage_zu_verlieren():
    karte = {"art": "recherche", "frage": "Mietpreise Hannover", "titel": "Mietpreise",
             "details": "Kernsatz.\n- **Median**: 11 Euro/m²\n- **Trend**: steigend",
             "quellen": [{"titel": "Quelle", "url": "https://beispiel.de"}]}

    async def ablauf():
        return await N.erstellen(_client(), karte, "als_liste", wahl=_WAHL)

    neu, nutzung = asyncio.run(ablauf())
    assert neu["art"] == "recherche" and neu["frage"] == "Mietpreise Hannover" and neu["titel"] == "Kurzfassung"
    assert neu["punkte"] == ["**Preis**: 500 Euro", "**Frist**: Ende Monat"]
    assert neu["quellen"] == karte["quellen"]  # unverändert übernommen
    assert nutzung["tokens_rein"] == 42


def test_erstellen_ohne_punkte_in_der_antwort_liefert_nichts():
    async def leer(**kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"titel": "x", "punkte": []})))], usage=None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=leer)))

    async def ablauf():
        return await N.erstellen(client, {"art": "antwort", "punkte": ["x"]}, "kürzer", wahl=_WAHL)

    neu, _ = asyncio.run(ablauf())
    assert neu is None


# --- Basis: AKTION-Zeile ------------------------------------------------------------------------------------------
def test_aktion_lesen_neu_aufbereiten():
    assert A.aktion_lesen("AKTION: neu_aufbereiten kürzer") == {"typ": "neu_aufbereiten", "wie": "kürzer"}
    assert A.aktion_lesen("AKTION: neu_aufbereiten als_liste") == {"typ": "neu_aufbereiten", "wie": "als_liste"}
    assert A.aktion_lesen("AKTION: neu_aufbereiten irgendwas") is None
    assert "neu_aufbereiten" in A.STILLE_AKTIONEN


def test_aktion_ausfuehren_neu_aufbereiten_zeigt_eine_neue_karte_die_alte_bleibt():
    async def ablauf():
        c = Coach()
        c.stufe_setzen("basis")
        c._client = _client()
        c.meeting.starten(virtuell=True)
        c._karte_ablegen({"art": "antwort", "frage": "Budget?", "titel": "Budget", "punkte": ["500 Euro"]})
        b = Bogen(1, "frage", "bereite das kürzer auf", "stimme", time.monotonic())
        await c.assistent.aktion_ausfuehren({"typ": "neu_aufbereiten", "wie": "kürzer"}, b)
        return c

    c = asyncio.run(ablauf())
    assert [k["titel"] for k in c.karten] == ["Budget", "Kurzfassung"]
    assert c.karten[-1]["art"] == "antwort" and c.karten[-1]["frage"] == "Budget?"


def test_aktion_ausfuehren_neu_aufbereiten_ohne_vorherige_karte_zeigt_nichts_neues():
    async def ablauf():
        c = Coach()
        c.stufe_setzen("basis")
        c._client = _client()
        c.meeting.starten(virtuell=True)
        b = Bogen(1, "frage", "bereite das kürzer auf", "stimme", time.monotonic())
        await c.assistent.aktion_ausfuehren({"typ": "neu_aufbereiten", "wie": "kürzer"}, b)
        return c

    c = asyncio.run(ablauf())
    assert c.karten == []


# --- Premium: Realtime-Werkzeug im Gespräch ----------------------------------------------------------------------
class _Verbindung:
    def __init__(self):
        self.gesendet: list[dict] = []

    async def send(self, roh):
        self.gesendet.append(json.loads(roh))

    async def close(self):
        pass


def _gespraech(client):
    c = Coach()
    c.stufe_setzen("premium")
    c._client = client
    c.meeting.starten(virtuell=True)
    g = Gespraech(c.assistent)
    g._ws = _Verbindung()
    g.offen = True
    c.assistent.gespraech = g
    return c, g


def test_werkzeug_karte_neu_aufbereiten_zeigt_die_karte_still_neu():
    async def ablauf():
        c, g = _gespraech(_client())
        c._karte_ablegen({"art": "antwort", "frage": "Budget?", "titel": "Budget", "punkte": ["500 Euro"]})
        await g._werkzeug("karte_neu_aufbereiten", json.dumps({"wie": "kürzer"}), "call_1")
        if c.assistent.bogen is not None and c.assistent.bogen.task is not None:
            await c.assistent.bogen.task
        return c, g

    c, g = asyncio.run(ablauf())
    assert [k["titel"] for k in c.karten] == ["Budget", "Kurzfassung"]
    ausgabe = [e for e in g._ws.gesendet if e["type"] == "conversation.item.create"]
    ausgabe_ergebnis = json.loads(ausgabe[0]["item"]["output"])
    assert ausgabe_ergebnis["ok"] and "sag nichts" in ausgabe_ergebnis["hinweis"]


def test_werkzeug_karte_neu_aufbereiten_unbekanntes_wie_wird_abgewiesen():
    async def ablauf():
        c, g = _gespraech(_client())
        c._karte_ablegen({"art": "antwort", "frage": "Budget?", "titel": "Budget", "punkte": ["500 Euro"]})
        await g._werkzeug("karte_neu_aufbereiten", json.dumps({"wie": "unbekannt"}), "call_1")
        await asyncio.sleep(0.02)
        return c, g

    c, g = asyncio.run(ablauf())
    assert len(c.karten) == 1  # keine zweite Karte
    ausgabe = json.loads(g._ws.gesendet[0]["item"]["output"])
    assert not ausgabe["ok"]
