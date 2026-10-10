"""Ticket #64: Kostenbremse – Meeting-Deckel je Stufe (coach/kosten.py), Höchstdauer mit Vorwarnung und
geordnetem Ende. Die Werte selbst sind Niclas' Entscheidung vom 10.10.2026 (gh issue 64).

Der Tagesdeckel je Kunde und der Notschalter NESTOR_PAUSE sitzen im Worker; ihre Tests liegen in
cloudflare/src/zaehler.test.ts bzw. cloudflare/src/sicherheit.test.ts (vitest).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from coach import anbieter as anbieter_mod
from coach import kosten, pipeline
from coach.assistent import Bogen
from coach.begruessung import Begruessung
from coach.gespraech import Gespraech, GespraechGesperrt
from coach.pipeline import Coach


class _FakeHoerstrom:
    """Nur so viel vom echten Hörstrom, wie `Coach.hoeren_beenden` und `Coach.kosten_stand` brauchen."""

    live = None

    async def beenden(self) -> None:
        pass


class _FakeStrom:
    """Attrappe für einen offenen Live-Text- oder Gesprächs-Strom: nur `schliessen()` zählt hier."""

    _ws = None  # Coach.kosten_stand liest live._ws (LiveText-Schnittstelle) – hier nie aktiv

    def __init__(self) -> None:
        self.geschlossen = False

    async def schliessen(self) -> None:
        self.geschlossen = True


def _ws_verbinden_verboten(monkeypatch: pytest.MonkeyPatch) -> list:
    """`anbieter.ws_verbinden` darf nach dem Deckel nicht mehr aufgerufen werden – schlägt sonst laut auf."""
    aufrufe: list = []

    async def _boom(*a, **k):
        aufrufe.append((a, k))
        raise AssertionError("ws_verbinden hätte nach dem Kostendeckel nicht aufgerufen werden dürfen")

    monkeypatch.setattr(anbieter_mod, "ws_verbinden", _boom)
    return aufrufe


async def _takt_mit_hintergrund(coach: Coach) -> None:
    """`takt()` plant bei Deckel/Höchstdauer einen Hintergrund-Task (`coach.pipeline.hintergrund`) – das braucht
    eine laufende Ereignisschleife, wie im echten Betrieb (coach/server.py: taktgeber)."""
    coach.takt()
    await asyncio.sleep(0.05)


def _coach(stufe: str = "premium") -> Coach:
    c = Coach()
    c._einrichten({"titel": "Testrunde"})
    c.stufe_setzen(stufe)
    c._client = object()  # kein Netzwerk: nur die zentrale Sperre wird geprüft, kein echter Aufruf
    c.meeting.starten(virtuell=True)
    return c


def test_meeting_deckel_sperrt_den_client_zentral_und_zeigt_hinweis(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "KOSTEN", kosten.Zaehler(tmp_path / "nutzung.jsonl"))
    coach = _coach("premium")
    # 1,2 Mio. Ausgabe-Tokens gpt-5.4-mini (4,50 $/1 Mio.) = 5,40 $ – über dem Premium-Deckel (5 $)
    pipeline.KOSTEN.buchen({"art": "themen", "modell": "gpt-5.4-mini", "tokens_rein": 0, "tokens_raus": 1_200_000})
    assert coach.kosten_stand()["meeting"] >= kosten.DECKEL_USD["premium"]

    asyncio.run(_takt_mit_hintergrund(coach))

    assert coach._client is None  # zentrale Sperre – keine Aufrufstelle einzeln geändert
    hinweis = next(h for h in coach.meeting.hinweise if h.art == "kosten")
    assert "Kostendeckel" in hinweis.text
    assert coach.meeting.laeuft  # das Meeting selbst läuft weiter, nur die KI-Auswertung ist aus

    # Ein zweiter Takt löst die Sperre und den Hinweis nicht noch einmal aus
    asyncio.run(_takt_mit_hintergrund(coach))
    assert len([h for h in coach.meeting.hinweise if h.art == "kosten"]) == 1


def test_meeting_deckel_in_basis_liegt_niedriger(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "KOSTEN", kosten.Zaehler(tmp_path / "nutzung.jsonl"))
    coach = _coach("basis")
    # 300.000 Ausgabe-Tokens mistral-medium-latest (7,50 $/1 Mio.) = 2,25 $ – über dem Basis-Deckel (2 $)
    pipeline.KOSTEN.buchen(
        {"art": "themen", "modell": "mistral-medium-latest", "tokens_rein": 0, "tokens_raus": 300_000}
    )

    asyncio.run(_takt_mit_hintergrund(coach))

    assert coach._client is None


def test_unter_dem_deckel_bleibt_der_client_bestehen(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "KOSTEN", kosten.Zaehler(tmp_path / "nutzung.jsonl"))
    coach = _coach("premium")
    pipeline.KOSTEN.buchen({"art": "themen", "modell": "gpt-5.4-mini", "tokens_rein": 0, "tokens_raus": 100_000})
    assert coach.kosten_stand()["meeting"] < kosten.DECKEL_USD["premium"]

    coach.takt()

    assert coach._client is not None
    assert not any(h.art == "kosten" for h in coach.meeting.hinweise)


def test_hoechstdauer_warnung_zehn_minuten_vorher():
    coach = _coach("premium")
    coach.meeting.virtuelle_zeit = kosten.HOECHSTDAUER_SEKUNDEN - kosten.HOECHSTDAUER_WARNUNG_SEKUNDEN

    coach.takt()

    hinweis = next(h for h in coach.meeting.hinweise if h.art == "hoechstdauer")
    assert "10 Min" in hinweis.text
    assert coach.meeting.laeuft  # noch nicht beendet


def test_hoechstdauer_beendet_das_meeting_geordnet():
    coach = _coach("premium")
    coach.hoerstrom = _FakeHoerstrom()
    coach.meeting.virtuelle_zeit = kosten.HOECHSTDAUER_SEKUNDEN

    asyncio.run(_takt_mit_hintergrund(coach))

    assert coach.hoerstrom is None  # hoeren_beenden ist tatsächlich gelaufen
    assert not coach.meeting.laeuft  # normaler Abschluss, kein harter Abbruch


# --- Die teuersten Ströme laufen über eigene WebSockets, nicht über self._client ---------------------------
# (coach/livetext.py, coach/gespraech.py, coach/begruessung.py; alle über coach/anbieter.py:ws_verbinden)

def test_meeting_deckel_schliesst_laufenden_live_text_und_gespraech(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "KOSTEN", kosten.Zaehler(tmp_path / "nutzung.jsonl"))
    coach = _coach("premium")
    pipeline.KOSTEN.buchen({"art": "themen", "modell": "gpt-5.4-mini", "tokens_rein": 0, "tokens_raus": 1_200_000})
    coach.hoerstrom = _FakeHoerstrom()
    coach.hoerstrom.live = live = _FakeStrom()
    coach.assistent.gespraech = gespraech = _FakeStrom()

    asyncio.run(_takt_mit_hintergrund(coach))

    assert coach._client is None
    assert live.geschlossen  # laufender Live-Text geordnet zu
    assert gespraech.geschlossen  # laufendes Gespräch geordnet zu


def test_gespraech_starten_verweigert_sich_zentral_nach_kostendeckel(monkeypatch):
    coach = _coach("premium")
    coach._kosten_gedeckelt = True  # wie von _kosten_pruefen gesetzt, hier ohne den ganzen Takt
    aufrufe = _ws_verbinden_verboten(monkeypatch)

    g = Gespraech(coach.assistent)
    with pytest.raises(GespraechGesperrt):
        asyncio.run(g.starten("Wie weit sind wir?"))
    assert aufrufe == []


def test_begruessung_starten_verweigert_sich_zentral_nach_kostendeckel(monkeypatch):
    coach = _coach("premium")
    coach._kosten_gedeckelt = True
    aufrufe = _ws_verbinden_verboten(monkeypatch)

    b = Begruessung(coach.assistent, vorstellung=False)
    with pytest.raises(GespraechGesperrt):
        asyncio.run(b.starten())
    assert aufrufe == []


def test_ansprache_startet_kein_gespraech_nach_kostendeckel(monkeypatch):
    """Reviewer-Vorgabe: „Ansprache startet kein Gespräch.“ `_gespraech_starten` ist die Stelle, an der eine neue
    Realtime-Sitzung für eine per Namen gestellte Frage entstünde (coach/assistent.py: `_frage_lauf`)."""
    coach = _coach("premium")
    coach._kosten_gedeckelt = True
    aufrufe = _ws_verbinden_verboten(monkeypatch)
    text_weg_versucht = []

    async def _stub_antworten(b, bestaetigt=False):
        text_weg_versucht.append(bestaetigt)

    monkeypatch.setattr(coach.assistent, "_antworten", _stub_antworten)
    b = Bogen(1, "frage", "Wie weit sind wir?", "stimme", time.monotonic())

    ok = asyncio.run(coach.assistent._gespraech_starten(b))

    assert ok is True  # „behandelt“ – per Rückfall auf den Text-Weg
    assert aufrufe == []  # keine neue Realtime-Verbindung
    assert text_weg_versucht  # der Rückfall wurde tatsächlich versucht
    assert coach.assistent.gespraech is None
