"""Kostenzähler: rechnet die Einträge aus logs/nutzung.jsonl mit den OpenAI-Listenpreisen in Dollar um.

Schätzung nach Listenpreis (Stand 05.10.2026, developers.openai.com/api/docs/pricing); maßgeblich ist die
Abrechnung unter platform.openai.com/usage. Cache-Rabatte werden nur beim Gespräch mit Nestor berücksichtigt,
sonst ist die Schätzung eher zu hoch als zu niedrig.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

# Dollar je 1 Mio. Tokens: (rein, raus)
TOKENPREISE = {
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    # Nestor Basis (Mistral, Stand 08.10.2026, docs.mistral.ai/inference/pricing): Medium 3.5, Small 4
    "mistral-medium-latest": (1.50, 7.50),
    "mistral-small-latest": (0.15, 0.60),
}
# Dollar je Zeichen der Sprachausgabe (Voxtral TTS: 16 $ je 1 Mio. Zeichen)
ZEICHENPREISE = {"voxtral-mini-tts-latest": 16.0 / 1e6}
# Dollar je Minute Audio
MINUTENPREISE = {
    "gpt-live-transcribe": 0.017,
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-transcribe-diarize": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
    "gpt-4o-mini-tts": 0.015,
    "voxtral-mini-transcribe-realtime-2602": 0.006,  # Modellkarte docs.mistral.ai, 08.10.2026
    "voxtral-mini-latest": 0.003,  # Voxtral Mini Transcribe (Batch)
}
# gpt-realtime je 1 Mio. Tokens
REALTIME = {"text_rein": 4.00, "audio_rein": 32.00, "cache_rein": 0.40, "text_raus": 16.00, "audio_raus": 64.00}
WEBSUCHE = 0.01  # je Aufruf (10 $ je 1000)
# Mistral web_search: kein offizieller Preis gefunden (08.10.2026); Sekundärquellen nennen 30 $ je 1000 – vorsichtig so
WEBSUCHE_MISTRAL = 0.03
BILD = 0.05  # gpt-image-2, 1536×1024, medium, je Bild
BILD_VORLAGE = 0.01  # Eingabebild bei der Fortschreibung

# Anzeige im Dashboard: Funktion -> Arten im Nutzungsprotokoll
BEREICHE = {
    "live-text": ("Live-Text", ("live-text", "text", "sprecherspur")),
    "nestor": ("Nestor spricht", ("gespraech", "stimme", "assistent", "karte")),
    "recherche": ("Recherche", ("recherche", "folie")),
    "analyse": ("Agenda, Ton, Ergebnisse", ("themen", "ergebnisse")),
    "bild": ("Live-Bild, Überblick", ("onepager", "ueberblick")),
}
_ART_ZU_BEREICH = {art: b for b, (_, arten) in BEREICHE.items() for art in arten}


def _tokens(modell: str, rein, raus) -> float:
    p = TOKENPREISE.get(modell)
    if not p:
        return 0.0
    return ((rein or 0) * p[0] + (raus or 0) * p[1]) / 1e6


def dollar(e: dict) -> float:
    """Geschätzte Kosten eines Protokolleintrags in Dollar."""
    art, modell = e.get("art"), e.get("modell", "")
    if art == "stimme" and modell in ZEICHENPREISE:
        return (e.get("zeichen") or 0) * ZEICHENPREISE[modell]
    if art in ("live-text", "text", "sprecherspur", "stimme"):
        return (e.get("sekunden_audio") or 0) / 60 * MINUTENPREISE.get(modell, 0.0)
    if art in ("themen", "ergebnisse", "assistent", "folie", "karte", "ueberblick"):
        return _tokens(modell, e.get("tokens_rein"), e.get("tokens_raus"))
    if art == "recherche":
        suche = WEBSUCHE_MISTRAL * (e.get("suchen") or 1) if modell.startswith("mistral") else WEBSUCHE
        return _tokens(modell, e.get("tokens_rein"), e.get("tokens_raus")) + suche
    if art == "gespraech":
        rein, raus = e.get("details_rein") or {}, e.get("details_raus") or {}
        cache = rein.get("cached_tokens_details") or {}
        audio_rein = (rein.get("audio_tokens") or 0) - (cache.get("audio_tokens") or 0)
        text_rein = (rein.get("text_tokens") or 0) - (cache.get("text_tokens") or 0)
        if not rein and not raus:  # ohne Details: alles als Text-Tokens rechnen
            return ((e.get("tokens_rein") or 0) * REALTIME["text_rein"]
                    + (e.get("tokens_raus") or 0) * REALTIME["text_raus"]) / 1e6
        return (max(audio_rein, 0) * REALTIME["audio_rein"] + max(text_rein, 0) * REALTIME["text_rein"]
                + (rein.get("cached_tokens") or 0) * REALTIME["cache_rein"]
                + (raus.get("text_tokens") or 0) * REALTIME["text_raus"]
                + (raus.get("audio_tokens") or 0) * REALTIME["audio_raus"]) / 1e6
    if art == "onepager":
        if e.get("anbieter") != "openai":
            return 0.0  # Claude-Abo
        summe = BILD + (BILD_VORLAGE if e.get("fortschreibung") else 0.0)
        for s in e.get("schritte") or []:
            summe += _tokens(s.get("modell", "").split("+")[0], s.get("tokens_rein"), s.get("tokens_raus"))
        return summe
    return 0.0


class Zaehler:
    """Summen für das laufende Meeting, heute und insgesamt (laut Protokolldatei)."""

    def __init__(self, protokoll: Path | None = None) -> None:
        self._protokoll = protokoll
        self._sperre = threading.Lock()
        self.meeting = {b: 0.0 for b in BEREICHE}
        self._heute_tag = time.strftime("%Y-%m-%d")
        self._heute = 0.0
        self._gesamt: float | None = None  # wird beim ersten Lesen aus der Datei berechnet

    def _einlesen(self) -> None:
        self._gesamt, self._heute = 0.0, 0.0
        if not self._protokoll or not self._protokoll.exists():
            return
        with self._protokoll.open(encoding="utf-8") as f:
            for zeile in f:
                try:
                    e = json.loads(zeile)
                except ValueError:
                    continue
                d = e.get("usd")
                d = dollar(e) if d is None else d
                self._gesamt += d
                if str(e.get("zeit", "")).startswith(self._heute_tag):
                    self._heute += d

    def buchen(self, e: dict) -> float:
        """Eintrag verbuchen (die Datei schreibt nutzung_loggen); liefert die Kosten in Dollar."""
        d = dollar(e)
        with self._sperre:
            if self._gesamt is None:
                self._einlesen()  # liest den Eintrag schon mit, falls er bereits in der Datei steht
            else:
                self._tag_pruefen()
                self._gesamt += d
                self._heute += d
            b = _ART_ZU_BEREICH.get(e.get("art"))
            if b:
                self.meeting[b] += d
        return d

    def _tag_pruefen(self) -> None:
        tag = time.strftime("%Y-%m-%d")
        if tag != self._heute_tag:
            self._heute_tag, self._heute = tag, 0.0

    def neues_meeting(self) -> None:
        with self._sperre:
            self.meeting = {b: 0.0 for b in BEREICHE}

    def stand(self, live_sekunden: float = 0.0, live_modell: str = "gpt-live-transcribe",
              meeting_sekunden: float = 0.0, geplant_minuten: float = 0.0) -> dict:
        """live_sekunden: Audio, das gerade an den Live-Text geht und erst am Ende verbucht wird."""
        with self._sperre:
            if self._gesamt is None:
                self._einlesen()
            self._tag_pruefen()
            laufend = live_sekunden / 60 * MINUTENPREISE.get(live_modell, 0.0)
            bereiche = [{"id": b, "name": BEREICHE[b][0],
                         "usd": round(self.meeting[b] + (laufend if b == "live-text" else 0.0), 4)}
                        for b in BEREICHE]
            meeting = sum(x["usd"] for x in bereiche)
            pro_stunde = meeting / (meeting_sekunden / 3600) if meeting_sekunden >= 120 else None
            return {
                "meeting": round(meeting, 4),
                "bereiche": bereiche,
                "pro_stunde": round(pro_stunde, 3) if pro_stunde is not None else None,
                "hochrechnung": round(pro_stunde * geplant_minuten / 60, 2)
                if pro_stunde is not None and geplant_minuten else None,
                "heute": round(self._heute + laufend, 4),
                "gesamt": round(self._gesamt + laufend, 4),
            }
