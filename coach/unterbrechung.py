"""Regel 1 „Ausreden lassen“: Unterbrechungen aus der lokalen Sprecherspur schätzen (reine Logik, ohne Modell).

Arbeitsdefinition (docs/gespraechsregeln.md): B beginnt, während A spricht (Überlappung oder Wechsel ohne
Pause), A bricht ab, B behält das Wort ≥ 3 s. Rückmeldungen („ja“, „mhm“) und reguläre Übergaben zählen nicht.

Umsetzung auf dem, was live vorliegt – je VAD-Äußerung die Abschnitte aus Stimmen.analysieren (Fenster 1,5 s,
Schritt 0,75 s) und der Pegel je 0,25 s:
1. Läufe je Person bilden (Lücken < 1 s überbrückt).
2. Wechsel A → B zählt, wenn A vorher ≥ 3 s sprach, B danach ≥ 3 s ohne Rückkehr von A spricht
   (A bricht ab, B behält das Wort; kurze Rückmeldungen fallen durch die Fensterglättung ohnehin weg) und
3. ohne Pause: A und B liegen in derselben VAD-Äußerung (keine Pause ≥ 0,5 s) **und** der Pegel an der
   Wechselstelle fällt nicht tiefer als 15 dB unter den Sprachpegel der Äußerung (sonst kurze Pause = Übergabe).

Nicht geprüft wird, ob A mitten im Satz war (dafür bräuchte es Text je Sprecher). Gemessen 05.10.2026 mit
scripts/bench_unterbrechung.py, Ergebnis in docs/messung_unterbrechung.md.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import numpy as np

RASTER = 0.25  # Pegel-Raster in Sekunden
MIN_VORHER = 3.0  # so lange muss A schon sprechen
MIN_NACHHER = 3.0  # so lange behält B das Wort
LUECKE = 1.0  # kürzere Lücken derselben Person gehören zum selben Lauf
PAUSE_DB = 15.0  # Pegel-Einbruch an der Wechselstelle, ab dem eine Pause angenommen wird
PAUSE_FENSTER = (-1.0, 0.5)  # Suchbereich um die Wechselstelle (Abschnittsgrenzen sind ±0,75 s ungenau)
STILLE_DB = -60.0  # Rahmen darunter gelten als Stille und zählen nicht zum Sprachpegel


@dataclass
class Aeusserung:
    """Eine VAD-Äußerung, wie sie live vorliegt."""

    start: float
    ende: float
    abschnitte: list[tuple[float, float, int]]  # relativ zum Start (Stimmen.analysieren)
    pegel: list[float] = field(default_factory=list)  # dB je RASTER ab Start, leer = keine Pegelprüfung


@dataclass
class Unterbrechung:
    zeit: float  # Beginn von B (absolut)
    von_person: int  # A, wurde unterbrochen
    zu_person: int  # B, hat das Wort übernommen
    vorher: float  # so lange sprach A
    nachher: float  # so lange sprach B danach


def pegel_db(proben: np.ndarray, rate: int = 16000, raster: float = RASTER) -> list[float]:
    """Pegel (RMS in dB) je Raster – für Aeusserung.pegel."""
    n = int(rate * raster)
    return [float(20 * np.log10(np.sqrt(np.mean(proben[i:i + n] ** 2)) + 1e-9))
            for i in range(0, len(proben) - n + 1, n)]


def laeufe(aeusserungen: list[Aeusserung], luecke: float = LUECKE) -> list[dict]:
    """Zusammenhängende Rede je Person über Äußerungsgrenzen hinweg (absolute Zeiten)."""
    aus: list[dict] = []
    for i, ae in enumerate(aeusserungen):
        for a, b, p in ae.abschnitte:
            von, bis = ae.start + a, ae.start + b
            if aus and aus[-1]["person"] == p and von - aus[-1]["bis"] < luecke:
                aus[-1]["bis"], aus[-1]["ae_bis"] = bis, i
            else:
                aus.append({"von": von, "bis": bis, "person": p, "ae_von": i, "ae_bis": i})
    return aus


def pause_an(ae: Aeusserung, zeit: float, pause_db: float = PAUSE_DB) -> bool:
    """Fällt der Pegel um die Wechselstelle `zeit` (absolut) tief unter den Sprachpegel der Äußerung?"""
    if not ae.pegel:
        return False
    sprache = [x for x in ae.pegel if x > STILLE_DB]
    if not sprache:
        return False
    i0 = max(0, int((zeit - ae.start + PAUSE_FENSTER[0]) / RASTER))
    i1 = min(len(ae.pegel), int((zeit - ae.start + PAUSE_FENSTER[1]) / RASTER) + 1)
    if i1 <= i0:
        return False
    return min(ae.pegel[i0:i1]) < statistics.median(sprache) - pause_db


def unterbrechungen(
    aeusserungen: list[Aeusserung],
    *,
    min_vorher: float = MIN_VORHER,
    min_nachher: float = MIN_NACHHER,
    luecke: float = LUECKE,
    pause_db: float | None = PAUSE_DB,
) -> list[Unterbrechung]:
    """Wechsel A → B ohne Pause, nach denen B das Wort behält. pause_db=None schaltet die Pegelprüfung ab.

    Stabil bei wachsender Spur: Ein einmal gefundener Wechsel bleibt mit derselben Zeit erhalten.
    """
    L = laeufe(aeusserungen, luecke)
    treffer = []
    for a, b in zip(L, L[1:]):
        if a["person"] == b["person"] or a["ae_bis"] != b["ae_von"]:
            continue  # gleiche Person (nach Lücke) oder Pause ≥ VAD-Pause dazwischen
        vorher, nachher = a["bis"] - a["von"], b["bis"] - b["von"]
        if vorher < min_vorher or nachher < min_nachher:
            continue
        if pause_db is not None and pause_an(aeusserungen[b["ae_von"]], b["von"], pause_db):
            continue
        treffer.append(Unterbrechung(b["von"], a["person"], b["person"], vorher, nachher))
    return treffer


def je_10_min(ereignisse: list[Unterbrechung], von: float, bis: float) -> float:
    """Rate im Zeitraum [von, bis) – für Kontrastvergleich und Schwellen."""
    dauer = bis - von
    if dauer <= 0:
        return 0.0
    return sum(von <= u.zeit < bis for u in ereignisse) / dauer * 600


def hinweistext(anzahl: int, minuten: int) -> str:
    """Gesammelter Hinweis an die Gruppe: ohne Namen, beobachtend, ohne Bewertung."""
    mal = "einmal" if anzahl == 1 else f"{anzahl}-mal"
    return (f"In den letzten {minuten} Minuten hat {mal} jemand das Wort übernommen, "
            "während noch gesprochen wurde.")
