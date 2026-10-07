"""Konfidenz der Signale, die keine Gesprächsregel sind (docs/lastenheft.md 4.3).

coach/regeln.py stuft die Gesprächsregeln ein (verlässlich/experimentell, je mit Kurzsatz für die
experimentellen). Dieses Modul ergänzt dieselben zwei Stufen für die übrigen Signale im Dashboard, die nicht
zur Auswahl stehen: Zeit/Agenda-Ampel, wer spricht, Live-Transkript, Agendawechsel (mit/ohne Ansage), Klima,
gleichzeitiges Sprechen und Nestors Antworten. Keine zweite Skala – nur eine zweite, kleine Liste derselben Art.
"""

from __future__ import annotations

from dataclasses import dataclass

from .regeln import KATALOG, STUFEN


@dataclass(frozen=True)
class Signal:
    id: str
    titel: str
    stufe: str  # "verlaesslich" oder "experimentell" (Schlüssel aus regeln.STUFEN)
    kurzsatz: str | None = None  # nur für stufe == "experimentell": ein Satz für Laien, aus Lastenheft 4.3


# Reihenfolge und Wortlaut wie in docs/lastenheft.md 4.3. Kurzsätze nur für die experimentellen Zeilen, Zahlen
# aus genau der Grundlage-Spalte dieser Zeile – keine aus Nachbarzeilen übernommen.
SIGNALE = [
    Signal("zeit_agenda", "Zeit und Agenda-Ampel", "verlaesslich"),
    Signal("wer_spricht", "Wer spricht (anonym)", "verlaesslich"),
    Signal("live_transkript", "Live-Transkript", "verlaesslich"),
    Signal("agenda_mit", "Agendawechsel mit Ansage", "verlaesslich"),
    Signal("agenda_ohne", "Agendawechsel ohne Ansage", "experimentell",
           "Experimentell: meldet einen stillen Themenwechsel meist erst nach 15 bis 60 Sekunden, "
           "kurze Punkte werden dabei manchmal verpasst."),
    Signal("klima", "Klima", "experimentell",
           "Experimentell: noch nicht gegen eine Referenz gemessen."),
    Signal("gleichzeitig", "Gleichzeitiges Sprechen", "experimentell",
           "Experimentell: findet 41 bis 68 % der echten Stellen; was gemeldet wird, stimmt in 84 bis 86 % "
           "der Fälle."),
    Signal("nestor_fragen", "Nestor beantwortet Fragen", "verlaesslich"),
]
NACH_ID = {s.id: s for s in SIGNALE}


def katalog() -> list[dict]:
    """Umgesetzte Regeln und Signale zusammen, verlässliche zuerst – eine Quelle fürs Dashboard."""
    eintraege = [
        {"id": r.id, "titel": r.titel.split(" – ")[0], "stufe": r.stufe, "stufe_text": STUFEN[r.stufe],
         "kurzsatz": r.kurzsatz}
        for r in KATALOG if r.umgesetzt
    ] + [
        {"id": s.id, "titel": s.titel, "stufe": s.stufe, "stufe_text": STUFEN[s.stufe], "kurzsatz": s.kurzsatz}
        for s in SIGNALE
    ]
    return sorted(eintraege, key=lambda e: e["stufe"] == "experimentell")
