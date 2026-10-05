"""Regelbasierte Logik (Lastenheft Kap. 12): Monolog, Überlappung, Fokus-Status, vier Ampeln.

Alles hier ist reine Logik auf dem Meeting-Zustand und damit ohne Audio testbar.
"""

from __future__ import annotations

import re

from . import regeln
from .entscheider import Entscheider
from .zustand import Meeting, Segment

ZWISCHENLAUT_SEKUNDEN = 1.5  # kurze Einwürfe ("mhm") sind noch kein Dialog
BLOCKRAND_SEKUNDEN = 3.0  # Rede bis so kurz vor Ende des letzten Blocks gilt als "spricht noch"
SPRACHE_AKTUELL_SEKUNDEN = 2.5  # so frisch muss das Sprachsignal vom Mikrofon sein
# Hochrechnung über das Ende der letzten bekannten Äußerung hinaus: aus (0). Benchmark 05.10.2026: Die
# Sprecherspur kommt je Äußerung (≤ 25 s); wechselt in der laufenden Äußerung die Person, rechnete die
# Hochrechnung der vorigen Person deren Redezeit zu → 1–3 Fehlalarme je 12 min. Ohne sie kommt ein
# echter Monolog-Hinweis höchstens eine Äußerungslänge später.
MAX_HOCHRECHNUNG_SEKUNDEN = 0


def mmss(sekunden: float) -> str:
    s = int(max(0, sekunden))
    return f"{s // 60}:{s % 60:02d}"


# --- FR-03 Monolog ---------------------------------------------------------

def laufende_rede(segmente: list[Segment], luecke: float = 3.0) -> tuple[str, float, float] | None:
    """Wer spricht zuletzt wie lange am Stück? Liefert (sprecher, dauer, ende)."""
    if not segmente:
        return None
    relevante = [s for s in segmente if s.dauer >= ZWISCHENLAUT_SEKUNDEN or s is segmente[-1]]
    letzter = relevante[-1]
    beginn, ende = letzter.start, letzter.ende
    for s in reversed(relevante[:-1]):
        if s.sprecher != letzter.sprecher or beginn - s.ende > luecke:
            break
        beginn = s.start
    return letzter.sprecher, ende - beginn, ende


def monolog_live(meeting: Meeting, schwelle: float) -> tuple[bool, float]:
    """(gelb?, Dauer) der laufenden Rede, live hochgezählt.

    Die Sprecherspur kommt nur blockweise. Hat dieselbe Person bis zum Ende des letzten
    verarbeiteten Blocks gesprochen und meldet das Mikrofon weiter Sprache, zählt die Dauer
    bis jetzt weiter – so wird die Monolog-Schwelle erkannt, ohne auf den nächsten Block zu warten.
    Ein Sprecherwechsel wird spätestens mit dem nächsten Block sichtbar und setzt zurück.
    """
    rede = laufende_rede(meeting.segmente)
    if not rede:
        return False, 0.0
    _, dauer, ende = rede
    jetzt = meeting.jetzt()
    bis_blockende = ende >= meeting.letztes_block_ende - BLOCKRAND_SEKUNDEN
    if not bis_blockende:  # im letzten Block hat jemand anderes oder niemand mehr gesprochen
        return False, dauer
    spricht_noch = jetzt - meeting.sprache_bis <= SPRACHE_AKTUELL_SEKUNDEN
    if spricht_noch and jetzt - ende <= MAX_HOCHRECHNUNG_SEKUNDEN:
        dauer = jetzt - (ende - dauer)
    return dauer >= schwelle, dauer


def monolog(segmente: list[Segment], schwelle: float, luecke: float = 3.0) -> tuple[str, float] | None:
    """Spricht die zuletzt sprechende Person seit mindestens `schwelle` Sekunden am Stück?"""
    rede = laufende_rede(segmente, luecke)
    if rede and rede[1] >= schwelle:
        return rede[0], rede[1]
    return None


# --- FR-06 Sprecherüberlappung ---------------------------------------------

def ueberlappungen(segmente: list[Segment], seit: float, min_dauer: float) -> list[tuple[Segment, Segment, float]]:
    """Zeitabschnitte, in denen zwei verschiedene Personen gleichzeitig sprechen.

    Bewertet nicht, wer wen unterbricht – nur das technisch beobachtbare Signal.
    """
    treffer = []
    for j, b in enumerate(segmente):
        if b.start < seit:
            continue
        for a in segmente[max(0, j - 4):j]:
            if a.sprecher == b.sprecher:
                continue
            dauer = min(a.ende, b.ende) - max(a.start, b.start)
            if dauer >= min_dauer:
                treffer.append((a, b, dauer))
    return treffer


def zickzack(segmente: list[Segment], seit: float, fenster: float, min_wechsel: int) -> list[tuple[float, float]]:
    """Überlappung, wie sie die Diarisierung tatsächlich liefert.

    gpt-4o-transcribe-diarize gibt bei gleichzeitigem Sprechen keine überlappenden
    Zeitstempel aus, sondern zerlegt es in schnell abwechselnde Schnipsel
    (gemessen 02.10.2026: 8 Sprecherwechsel in 3,5 s). Ein normales Gespräch hat das nie.
    Liefert Zeitspannen (start, ende) mit mindestens `min_wechsel` Wechseln innerhalb `fenster` Sekunden.
    """
    kandidaten = [s for s in segmente if s.ende >= seit]
    spannen = []
    for i, s in enumerate(kandidaten):
        im_fenster = [x for x in kandidaten[i:] if x.start <= s.start + fenster]
        wechsel = sum(1 for a, b in zip(im_fenster, im_fenster[1:]) if a.sprecher != b.sprecher)
        if wechsel >= min_wechsel:
            spannen.append((s.start, im_fenster[-1].ende))
    return spannen


def ueberlappung_erkannt(
    segmente: list[Segment], seit: float, min_dauer: float, fenster: float, min_wechsel: int
) -> bool:
    """FR-06: echte Zeitüberlappung oder Zickzack-Muster der Diarisierung."""
    return bool(ueberlappungen(segmente, seit, min_dauer) or zickzack(segmente, seit, fenster, min_wechsel))


# --- FR-05 Fokus -----------------------------------------------------------

ABSEITS = ("neu", "vorgriff", "zurueck")


# Ausdrückliche Überleitung („wir kommen jetzt zu Punkt …“, „Tagesordnungspunkt 6“, „nächstes Thema“):
# löst die Themen-Zuordnung sofort aus und braucht keine Karenz – der Wechselvorschlag kommt direkt.
ANKUENDIGUNG = re.compile(
    r"tagesordnungspunkt|\btop\s*\d|agendapunkt|"
    r"(kommen|gehen|machen|springen) wir (jetzt |nun |dann |gleich )*(weiter )?(zu|zum|mit)\b|"
    r"weiter (zu|mit) (punkt|top|thema)|n(ä|ae)chste[nrs]? (punkt|thema|tagesordnungspunkt)|"
    r"zum n(ä|ae)chsten (punkt|thema)|punkt \w+ (der|unserer) (agenda|tagesordnung)",
    re.IGNORECASE,
)


def ankuendigung(text: str) -> bool:
    return bool(ANKUENDIGUNG.search(text))


ZAHLWORTE = {"eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8,
             "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12}
ORDNUNG = {"erst": 1, "zweit": 2, "dritt": 3, "viert": 4, "fünft": 5, "fuenft": 5, "sechst": 6, "siebt": 7,
           "acht": 8, "neunt": 9, "zehnt": 10}
_PUNKT_NR = re.compile(r"\b(?:punkt|top|tagesordnungspunkt|agendapunkt)\s*(?:nummer\s*|nr\.?\s*)?(\d{1,2}|"
                       + "|".join(ZAHLWORTE) + r")\b", re.IGNORECASE)
_PUNKT_ORD = re.compile(r"\b(" + "|".join(ORDNUNG) + r")(?:e|en|er|es)\s+(?:punkt|tagesordnungspunkt|agendapunkt|top)\b",
                        re.IGNORECASE)
_NAECHSTER = re.compile(r"n(?:ä|ae)chste[nrs]?\s+(?:punkt|thema|tagesordnungspunkt|agendapunkt|top)\b", re.IGNORECASE)


def angekuendigter_punkt(text: str, titel: list[str], aktiv: int) -> int | None:
    """Ausdrückliche Überleitung mit Ziel („weiter zu Punkt drei“, „zum nächsten Punkt“, „…zum Budget“):
    Index des Agendapunkts, sonst None. Ohne Überleitungsformel nie – „Punkt drei war gut“ wechselt nicht."""
    if not ankuendigung(text):
        return None
    ziel = None
    if t := _PUNKT_NR.search(text):
        wort = t.group(1).lower()
        ziel = (int(wort) if wort.isdigit() else ZAHLWORTE[wort]) - 1
    elif t := _PUNKT_ORD.search(text):
        ziel = ORDNUNG[t.group(1).lower()] - 1
    elif _NAECHSTER.search(text):
        ziel = aktiv + 1
    else:
        klein = text.lower()
        treffer = [(len(x), i) for i, x in enumerate(titel) if len(x) >= 4 and x.lower() in klein]
        ziel = max(treffer)[1] if treffer else None
    return ziel if ziel is not None and 0 <= ziel < len(titel) and ziel != aktiv else None


def fokus_status(verlauf: list[dict], karenz_bloecke: int) -> tuple[str, dict | None]:
    """Gelb, wenn die letzten `karenz_bloecke` zuordenbaren Abschnitte klar nicht zum aktiven Punkt passen.

    Abschnitte mit art "unklar" (Begrüßung, Füllsätze) ändern den Status nicht.
    """
    zuordenbar = [e for e in verlauf if e["art"] != "unklar"]
    letzte = zuordenbar[-karenz_bloecke:] if karenz_bloecke > 0 else []
    if len(letzte) == karenz_bloecke and all(e["art"] in ABSEITS and e["konfidenz"] >= 0.5 for e in letzte):
        return "gelb", letzte[-1]
    return "gruen", None


def fokus_hinweistext(meeting: Meeting, ergebnis: dict) -> str:
    punkt = ergebnis.get("punkt")
    if ergebnis["art"] in ("vorgriff", "zurueck") and punkt is not None:
        aktuell = meeting.aktiver_punkt + 1
        return (
            f"Das Thema passt eher zu Agendapunkt {punkt + 1} („{meeting.agenda[punkt].titel}“). "
            f"Möchtet ihr jetzt dorthin wechseln oder zunächst Agendapunkt {aktuell} abschließen?"
        )
    return "Bezug zum aktuellen Agendapunkt unklar."


def themen_auswerten(meeting: Meeting, entscheider: Entscheider, ergebnis: dict, karenz_bloecke: int) -> None:
    """Ergebnis der Themen-Zuordnung in Fokus-Hinweis und Wechselvorschlag (FR-02) übersetzen."""
    meeting.themen_verlauf.append(ergebnis)
    status, ausloeser = fokus_status(meeting.themen_verlauf, karenz_bloecke)
    if status == "gruen":
        if ergebnis["art"] == "aktiv":
            meeting.vorschlag = None
        return
    if ausloeser["art"] in ("vorgriff", "zurueck") and ausloeser["punkt"] is not None:
        ziel = ausloeser["punkt"]
        meeting.vorschlag = {"punkt": ziel, "titel": meeting.agenda[ziel].titel, "begruendung": ausloeser["begruendung"]}
        schluessel = f"fokus-punkt-{ziel}"
    else:
        schluessel = "fokus-unklar"
    text = fokus_hinweistext(meeting, ausloeser) + regeln.vereinbart(meeting.regel_ids, "thema")
    entscheider.vorschlagen(meeting, "fokus", "hinweis", "gruppe", text, schluessel)


# --- Vier Ampeln (Lastenheft 7.1 C) ----------------------------------------

def prozess_ampeln(
    meeting: Meeting,
    *,
    monolog_sekunden: float,
    karenz_bloecke: int,
    zeit_rot_prozent: float,
    ueberlappung_min: float,
    ueberlappung_halte: float,
    themen_aktiv: bool,
    zickzack_fenster: float = 3.0,
    zickzack_wechsel: int = 4,
) -> list[dict]:
    """Grün = im Rahmen, Gelb = Hinweis. Jede Ampel fällt von selbst zurück, wenn die Ursache endet (FR-08)."""
    jetzt = meeting.jetzt()
    ampeln = []

    # 1. Monolog (FR-03): Gelb ab Schwelle, Grün sobald jemand anderes spricht
    gelb, dauer = monolog_live(meeting, monolog_sekunden)
    if gelb:
        ampeln.append({"name": "Monolog", "farbe": "gelb", "detail": f"seit {mmss(dauer)} eine Stimme"})
    elif dauer >= monolog_sekunden / 2:
        ampeln.append({"name": "Monolog", "farbe": "gruen", "detail": f"eine Stimme seit {mmss(dauer)}"})
    else:
        ampeln.append({"name": "Monolog", "farbe": "gruen", "detail": "Gespräch im Wechsel"})

    # 2. Agenda & Zeit (FR-04)
    if 0 <= meeting.aktiver_punkt < len(meeting.agenda):
        p = meeting.agenda[meeting.aktiver_punkt]
        rest = p.minuten * 60 - meeting.genutzt(meeting.aktiver_punkt)
        farbe = p.ampel(meeting.genutzt(meeting.aktiver_punkt), zeit_rot_prozent)
        detail = f"{mmss(rest)} verbleibend" if rest > 0 else f"Zeitfenster um {mmss(-rest)} überschritten"
        ampeln.append({"name": "Agenda & Zeit", "farbe": farbe, "detail": detail})
    else:
        ampeln.append({"name": "Agenda & Zeit", "farbe": "aus", "detail": "keine Agenda"})

    # 3. Fokus (FR-05)
    if not themen_aktiv or not meeting.agenda:
        ampeln.append({"name": "Fokus", "farbe": "aus", "detail": "Themen-Zuordnung aus"})
    else:
        farbe, ausloeser = fokus_status(meeting.themen_verlauf, karenz_bloecke)
        if ausloeser and ausloeser["punkt"] is not None and ausloeser["art"] != "neu":
            detail = f"passt eher zu Punkt {ausloeser['punkt'] + 1}"
        elif ausloeser:
            detail = "Bezug zum Punkt unklar"
        else:
            detail = "beim aktuellen Punkt"
        ampeln.append({"name": "Fokus", "farbe": farbe, "detail": detail})

    # 4. Gesprächsregeln / Sprecherüberlappung (FR-06)
    seit = jetzt - ueberlappung_halte
    if any(t >= seit for t in meeting.mischungen) or ueberlappung_erkannt(
        meeting.segmente, seit, ueberlappung_min, zickzack_fenster, zickzack_wechsel
    ):
        ampeln.append({"name": "Sprecherüberlappung", "farbe": "gelb", "detail": "mehrere sprechen gleichzeitig"})
    else:
        ampeln.append({"name": "Sprecherüberlappung", "farbe": "gruen", "detail": "normale Sprecherwechsel"})
    return ampeln
