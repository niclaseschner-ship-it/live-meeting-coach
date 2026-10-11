"""Karte per Zuruf neu aufbereiten (Ticket #84): „Nestor, bereite die Recherche anders auf“ – bisher ohne
Werkzeug (Pilot 10.10. abends, F12). Die zuletzt gezeigte Karte (coach.karten[-1]) wird per LLM-Aufruf umgeformt
und erscheint als neue Karte; die alte bleibt im Verlauf stehen. Nichts wird inhaltlich ergänzt oder weggelassen,
nur die Form ändert sich – wie bei der Folie/dem Überblick läuft das Analysemodell der Stufe (wahl.analyse_modell).
"""

from __future__ import annotations

import json
import time

WIE = ("kürzer", "ausführlicher", "als_liste", "einfacher")
WIE_TEXT = {
    "kürzer": "Deutlich kürzer – nur das Allerwichtigste, weniger Stichpunkte.",
    "ausführlicher": "Ausführlicher – mehr Einzelheiten aus dem Material unten, nichts erfinden.",
    "als_liste": "Als klare Liste von Stichpunkten, falls es noch Fließtext ist.",
    "einfacher": "In einfacherer Sprache, weniger Fachbegriffe, kurze Sätze.",
}

AUFTRAG = """\
Eine Karte, die einer Besprechungsrunde schon gezeigt wurde, soll auf Zuruf neu aufbereitet werden: {wie}
Ändere nur die Form. Erfinde nichts hinzu und lass nichts Inhaltlich Wichtiges weg.
Antworte ausschließlich mit JSON:
{{"titel": "Thema in höchstens 6 Wörtern", "punkte": ["3 bis 5 Stichpunkte, je höchstens 20 Wörter, wichtige "
"Stichworte **fett** markiert"]}}

Bisherige Karte:
Titel: {titel}
{inhalt}
"""

# Keine Live-Bilder, Folien, Überblicke oder Artefakt-Listen (eigene Darstellung, kein Text zum Umformen) und
# keine Beispielkarte (leerer Verlauf) – nur Karten mit Titel und Stichpunkten bzw. Fließtext.
_NICHT = ("bild", "folie", "ueberblick", "festgehalten", "zusammenfassung", "beispiel", "ergebnis")


def moeglich(karte: dict | None) -> bool:
    return bool(karte) and karte.get("art") not in _NICHT and not karte.get("ids") \
        and bool(karte.get("punkte") or karte.get("details"))


def _inhalt(karte: dict) -> str:
    if karte.get("details"):
        return karte["details"][:3000]
    return "\n".join(f"- {p}" for p in karte.get("punkte") or [])


async def erstellen(client, karte: dict, wie: str, *, wahl) -> tuple[dict | None, dict]:
    """Liefert (neue Karte oder None, Nutzung). `wie` muss einer der vier Begriffe oben sein."""
    if client is None or wie not in WIE or not moeglich(karte):
        return None, {}
    t0 = time.monotonic()
    auftrag = AUFTRAG.format(wie=WIE_TEXT[wie], titel=karte.get("titel") or "-", inhalt=_inhalt(karte))
    r = await client.chat.completions.create(
        model=wahl.analyse_modell, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": auftrag}],
        **({"reasoning_effort": wahl.analyse_aufwand} if wahl.analyse_aufwand else {}))
    try:
        roh = json.loads(r.choices[0].message.content or "{}")
    except ValueError:
        roh = {}
    roh = roh if isinstance(roh, dict) else {}
    punkte = [str(p)[:160] for p in (roh.get("punkte") or [])][:5]
    if not punkte:
        return None, {}
    u = getattr(r, "usage", None)
    nutzung = {"tokens_rein": getattr(u, "prompt_tokens", None), "tokens_raus": getattr(u, "completion_tokens", None),
               "sekunden": round(time.monotonic() - t0, 1)}
    neu = {"art": karte.get("art") or "antwort", "frage": karte.get("frage"),
           "titel": str(roh.get("titel") or karte.get("titel") or "Karte")[:80], "punkte": punkte,
           "quellen": karte.get("quellen") or []}
    return neu, nutzung
