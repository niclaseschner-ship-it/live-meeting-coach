"""Gesprächsregeln: fester Katalog statt Freifeld (docs/gespraechsregeln.md).

Jede Regel sagt ehrlich, was der Coach leisten kann (Stufe) und ob sie schon umgesetzt ist. Die Gruppe
wählt zu Beginn aus; der Coach prüft nur gewählte Regeln. Eigene Regeln bleiben möglich, gelten aber als
„Erinnerung – wird nicht geprüft“.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

STUFEN = {
    "geprueft": "wird geprüft",
    "hinweis": "Hinweis möglich, kann irren",
    "experimentell": "experimentell, nur Moderation",
}


@dataclass(frozen=True)
class Regel:
    id: str
    titel: str
    stufe: str
    beobachtet: str  # was der Coach dafür tatsächlich beobachtet
    umgesetzt: bool


KATALOG = [
    Regel("ausreden", "Ausreden lassen", "hinweis",
          "Wort übernommen, während noch gesprochen wurde (ohne Pause, neue Person behält das Wort ≥ 3 s); "
          "Hinweis ab 3 Stellen in 5 Minuten",
          True),
    Regel("seitengespraeche", "Keine Seitengespräche", "experimentell",
          "Länger parallel laufende, leisere zweite Unterhaltung", False),
    Regel("thema", "Beim Thema bleiben", "geprueft",
          "Inhalt passt ≥ 20 s nicht zum aktuellen Agendapunkt (Fokus-Ampel)", True),
    Regel("zeit", "Zeit einhalten", "geprueft", "Zeitbudget je Agendapunkt (Countdown, Ampel)", True),
    Regel("kurz", "Sich kurz fassen – keine Monologe", "geprueft",
          "Zusammenhängende Redezeit einer Person ≥ 60 s (Monolog-Ampel)", True),
    Regel("alle", "Alle kommen zu Wort", "geprueft",
          "Angemeldete Personen ohne erkannte Stimme; eine Person mit mehr als der Hälfte der Redezeit", True),
    Regel("ton", "Respektvoller Ton – keine Beleidigungen, keine Kraftausdrücke", "hinweis",
          "Kraftausdrücke und persönliche Angriffe im Live-Text (Hinweis nur an die Moderation)", True),
    Regel("sachlich", "Sachlich bleiben – keine Killerphrasen", "experimentell",
          "Killerphrasen und Pauschalvorwürfe („immer“, „nie“) im Live-Text", False),
    Regel("eingehen", "Zuhören und aufeinander eingehen", "experimentell",
          "Wiederholte Argumente, Beiträge ohne Bezug", False),
    Regel("ergebnisse", "Ergebnisse festhalten – wer macht was bis wann", "hinweis",
          "Beim Wechsel: Punkt ohne ausgesprochenes Ergebnis, Aufgabe ohne Verantwortliche/n oder Termin", True),
]
NACH_ID = {r.id: r for r in KATALOG}
STANDARD = ["ausreden", "thema", "zeit", "kurz"]


def katalog() -> list[dict]:
    return [asdict(r) | {"stufe_text": STUFEN[r.stufe]} for r in KATALOG]


def gueltige(ids: list[str]) -> list[str]:
    """Nur bekannte und umgesetzte Regeln, Reihenfolge wie im Katalog."""
    gewaehlt = set(ids)
    return [r.id for r in KATALOG if r.id in gewaehlt and r.umgesetzt]


def vereinbart(ids: list[str], regel_id: str) -> str:
    """Zusatz für einen Hinweis, wenn die Gruppe die passende Regel gewählt hat."""
    return f" Vereinbart war: „{NACH_ID[regel_id].titel}“." if regel_id in ids else ""
