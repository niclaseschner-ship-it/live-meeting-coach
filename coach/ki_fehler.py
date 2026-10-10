"""Kein stiller Ausfall der Hintergrund-KI (Ticket #72) – die eine Stelle für alle Aufrufe, die ohne Knopf laufen.

Bis #72 meldete jeder Hintergrundaufruf anders: die Themen-Zuordnung setzte nur `coach.fehler`, Überblick und
Live-Bild ihr eigenes Feld, Folie, Protokoll am Ende und die automatische Artefakt-Erkennung schrieben nur ins Log.
Im Pilot sah das Dashboard deshalb nichts Auffälliges, während die Ergebnisse ausblieben („er verarbeitet nichts“).

Jetzt gilt für jeden Hintergrundaufruf dasselbe Muster wie im Knopfpfad (coach/knopfdruck.py `ausfuehren`):

- **sichtbar:** eine rote Zeile im Band (Hinweis-Art „fehler“, je Bereich höchstens einmal je Minute) und die
  Fehlerzeile im Dashboard (`coach.fehler`);
- **belegt:** Ereignis `ki_fehler` im Coach-Protokoll (bericht.json, Technikbericht `technik.json` → `ki_fehler`) und
  in der Meeting-Ablage (`debug/ereignisse.jsonl`);
- **wiederholt:** der Aufrufer plant den nächsten Versuch selbst (Artefakte: nächster Takt mit wachsendem Abstand)
  und sagt das im Text; klappt es wieder, räumt `erholt()` Fehlerzeile und Band auf.

Nur Typ und Statuscode landen in Text und Protokoll (`pipeline.fehlertext`) – keine API-Meldungen mit Kennungen.
"""

from __future__ import annotations

import logging

log = logging.getLogger("coach.ki_fehler")

BEREICHE = {
    "artefakte": "Ergebnis-Erkennung",
    "themen": "Themen-Zuordnung",
    "ueberblick": "Überblick",
    "bild": "Live-Bild",
    "folie": "Folie",
    "recherche": "Recherche",
    "protokoll": "Protokoll am Meetingende",
}
BAND_SEKUNDEN = 90.0     # so lange steht der Hinweis im Band, wenn nichts ihn vorher aufräumt
BAND_ABSTAND = 60.0      # derselbe Bereich höchstens einmal je Minute im Band


def name(bereich: str) -> str:
    return BEREICHE.get(bereich, bereich)


def melden(coach, bereich: str, e: BaseException, wiederholung: str = "", band: bool = True) -> str:
    """Ein Hintergrundaufruf ist gescheitert: Band, Fehlerzeile, Protokoll, Ablage. Liefert den angezeigten Text.
    `wiederholung`: was als Nächstes passiert („Nestor versucht es in 30 s noch einmal“). `band=False`, wenn der
    Aufrufer den Fehler schon selbst sichtbar macht (Recherche: Karte mit Fehlertext)."""
    from .pipeline import fehlertext

    ursache = fehlertext(e)  # type: ignore[arg-type]
    text = f"{name(bereich)} gestört ({ursache})" + (f" – {wiederholung}" if wiederholung else "")
    log.warning("%s fehlgeschlagen: %s", name(bereich), ursache)
    coach.fehler = text
    m = coach.meeting
    coach.protokoll.append({"zeit": round(m.jetzt(), 1), "art": "ki_fehler", "bereich": bereich, "fehler": ursache})
    archiv = getattr(coach, "archiv", None)
    if archiv is not None and not archiv.fertig:
        archiv.ereignis("ki_fehler", bereich=bereich, fehler=ursache)
    if band and m.laeuft:
        coach.entscheider.vorschlagen(m, "fehler", "warnung", "gruppe", text, schluessel=f"ki-fehler-{bereich}",
                                      cooldown=BAND_ABSTAND, dauer=BAND_SEKUNDEN)
    return text


def erholt(coach, bereich: str) -> None:
    """Der Bereich arbeitet wieder: eigene Fehlerzeile und Band-Hinweis weg, Ereignis `ki_erholt`. Fremde Fehler
    (Live-Text, Anbieter-Sperre) bleiben stehen."""
    praefix = f"{name(bereich)} gestört"
    letztes = next((e for e in reversed(coach.protokoll) if e.get("art") in ("ki_fehler", "ki_erholt")
                    and e.get("bereich") == bereich), None)
    if letztes is None or letztes["art"] != "ki_fehler":
        return
    if coach.fehler and coach.fehler.startswith(praefix):
        coach.fehler = None
    m = coach.meeting
    coach.protokoll.append({"zeit": round(m.jetzt(), 1), "art": "ki_erholt", "bereich": bereich})
    archiv = getattr(coach, "archiv", None)
    if archiv is not None and not archiv.fertig:
        archiv.ereignis("ki_erholt", bereich=bereich)
    for h in m.hinweise:
        if h.art == "fehler" and h.text.startswith(praefix):
            h.dauer = min(h.dauer, max(0.0, m.jetzt() - h.zeit))


def ereignisse(coach) -> list[dict]:
    """Für den Technikbericht: alle Ausfälle und Erholungen der Hintergrund-KI dieses Meetings."""
    return [e for e in coach.protokoll if e.get("art") in ("ki_fehler", "ki_erholt")]
