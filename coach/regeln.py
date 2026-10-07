"""Gesprächsregeln: fester Katalog statt Freifeld (docs/gespraechsregeln.md).

Jede Regel sagt ehrlich, was der Coach leisten kann (Stufe) und ob sie schon umgesetzt ist. Die Gruppe
wählt zu Beginn aus; der Coach prüft nur gewählte Regeln. Eigene Regeln bleiben möglich, gelten aber als
„Erinnerung – wird nicht geprüft“.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Frühere Dreiteilung (geprueft/hinweis/experimentell) beschrieb nur, WIE eine Regel gebaut ist – geprueft:
# deterministisch (Uhr, Zähler); hinweis: KI-gestützt, kann irren; experimentell: nie gemessen. Das sagt noch
# nichts darüber, ob sie im Betrieb stimmt. docs/lastenheft.md 4.3 misst das inzwischen nach: „geprueft“ ist
# dort durchweg verlässlich, „experimentell“ durchweg experimentell – nur bei „hinweis“ hängt es von der
# einzelnen Regel ab (ton: 31/32 erkannt → verlässlich; ausreden, ergebnisse: schwach im Feld → experimentell).
# Deshalb zwei sichtbare Stufen statt drei, direkt an jeder Regel, nicht mechanisch aus der alten Stufe
# abgeleitet.
STUFEN = {
    "verlaesslich": "verlässlich",
    "experimentell": "experimentell",
}


@dataclass(frozen=True)
class Regel:
    id: str
    titel: str
    stufe: str  # "verlaesslich" oder "experimentell" (Schlüssel aus STUFEN) – Grundlage: Lastenheft 4.3
    beobachtet: str  # was der Coach dafür tatsächlich beobachtet
    umgesetzt: bool
    kurzsatz: str | None = None  # nur für stufe == "experimentell": ein Satz für Laien, aus Lastenheft 4.3


KATALOG = [
    Regel("ausreden", "Ausreden lassen", "experimentell",
          "Wort übernommen, während noch gesprochen wurde (ohne Pause, neue Person behält das Wort ≥ 3 s); "
          "Hinweis ab 3 Stellen in 5 Minuten",
          True,
          "Experimentell: In geordneten Runden kaum Fehlalarme, in Proben mit vielen Zwischenrufen unbrauchbar."),
    Regel("seitengespraeche", "Keine Seitengespräche", "experimentell",
          "Länger parallel laufende, leisere zweite Unterhaltung", False),
    Regel("thema", "Beim Thema bleiben", "experimentell",
          "Inhalt passt ≥ 20 s nicht zum aktuellen Agendapunkt (Fokus-Ampel)", True,
          "Experimentell: erkennt Abschweifungen auf Satzebene zuverlässig (3 von 3 im Test), live seltener – "
          "bei fließenden Themenwechseln auch mal falsch."),
    Regel("zeit", "Zeit einhalten", "verlaesslich", "Zeitbudget je Agendapunkt (Countdown, Ampel)", True),
    Regel("kurz", "Sich kurz fassen – keine Monologe", "verlaesslich",
          "Zusammenhängende Redezeit einer Person ≥ 60 s (Monolog-Ampel)", True),
    Regel("alle", "Alle kommen zu Wort", "verlaesslich",
          "Angemeldete Personen ohne erkannte Stimme; eine Person mit mehr als der Hälfte der Redezeit", True),
    Regel("ton", "Respektvoller Ton – keine Beleidigungen, keine Kraftausdrücke", "verlaesslich",
          "Kraftausdrücke und persönliche Angriffe im Live-Text (Hinweis nur an die Moderation)", True),
    Regel("sachlich", "Sachlich bleiben – keine Killerphrasen", "experimentell",
          "Killerphrasen und Pauschalvorwürfe („immer“, „nie“) im Live-Text", False),
    Regel("eingehen", "Zuhören und aufeinander eingehen", "experimentell",
          "Wiederholte Argumente, Beiträge ohne Bezug", False),
    Regel("ergebnisse", "Ergebnisse festhalten – wer macht was bis wann", "experimentell",
          "Beim Wechsel: Punkt ohne ausgesprochenes Ergebnis, Aufgabe ohne Verantwortliche/n oder Termin", True,
          "Experimentell: erkennt 4 von 5 Beschlüssen richtig, bei englischsprachigem Material kaum."),
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
