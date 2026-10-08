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
# Voxtral (Nestor Basis) schreibt anders als OpenAI „Agenda Punkt 2“/„Agenda-Punkt“ statt „Agendapunkt zwei“ und
# lässt die Ansage gern mit „Wir wechseln jetzt …“ beginnen (Cloud-Lauf 08.10., Ticket #15) – beides zählt.
_PUNKTWORT = r"(?:tagesordnungs|agenda)[\s-]?punkt"
ANKUENDIGUNG = re.compile(
    _PUNKTWORT + r"|\btop\s*\d|"
    r"(kommen|gehen|machen|springen|wechseln) wir (?:\w+ ){0,3}?(zu|zum|zur|mit)\b|"
    # Subjekt zuerst, nur mit Zeitwort („Wir gehen jetzt zu …“) – „wir kommen zu dem Schluss“ bleibt außen vor
    r"\bwir (kommen|gehen|machen|springen|wechseln) (?:jetzt|nun|dann|gleich|als n(ä|ae)chstes)\b"
    r"(?: \w+){0,2}? (zu|zum|zur|mit)\b|"
    r"\bzum (zweiten|dritten|vierten|f(ü|ue)nften|sechsten|letzten) (punkt|thema|tagesordnungspunkt)|"
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
_PUNKT_NR = re.compile(r"\b(?:punkt|top|" + _PUNKTWORT + r")\s*(?:nummer\s*|nr\.?\s*)?(\d{1,2}|"
                       + "|".join(ZAHLWORTE) + r")\b", re.IGNORECASE)
_PUNKT_ORD = re.compile(r"\b(" + "|".join(ORDNUNG) + r")(?:e|en|er|es)\s+(?:punkt|" + _PUNKTWORT + r"|top)\b",
                        re.IGNORECASE)
_NAECHSTER = re.compile(r"n(?:ä|ae)chste[nrs]?\s+(?:punkt|thema|" + _PUNKTWORT + r"|top)\b", re.IGNORECASE)


# Rückwärts-Ansage („Lass uns nochmal kurz zu Punkt eins zurück“, „zurück zur Ursache“, „nochmal zu Punkt zwei“):
# In allen drei Cloud-Läufen 08.10. kam der Satz wörtlich richtig im Live-Text an, ANKUENDIGUNG kannte aber nur
# Vorwärts-Formeln – kein Wechsel (Ticket #17, Grenzfall 11). Zählt nur mit ausdrücklichem Ziel (Nummer,
# Ordnungszahl, Titel), sonst wechselte „Gut, zurück zur Datenbank“ nach einer Abschweifung. Vertagen („wir kommen
# später auf Punkt zwei zurück“, „darauf kommen wir nachher zurück“) ist keine Ansage.
_RUECKWAERTS = re.compile(
    r"\bzur(?:ü|ue)ck\s+(?:zu|zum|zur)\b|"  # „zurück zu Punkt eins“, „gehen wir zurück zur Ursache“
    r"\b(?:zu|zum|zur)\s+(?:[\w.-]+\s+){1,4}?zur(?:ü|ue)ck(?:gehen|kommen|kehren|springen)?\b|"  # „zu P. 1 zurück“
    # „nochmal zu Punkt zwei“ nur mit Punkt-Wort – „noch mal zu den Kosten: …“ ist ein Beitrag, kein Wechsel
    r"\bnoch\s?(?:mal|einmal|mals)\s+(?:(?:kurz|eben|schnell)\s+)?(?:zu|zum)\s+(?:\w+\s+)?(?:punkt|top|"
    + _PUNKTWORT + r")\b|"
    r"\b(?:lass|lasst|kommen|gehen) (?:uns|wir)\b(?:\s+\w+){0,4}?\s+auf\s+(?:[\w.-]+\s+){1,4}?zur(?:ü|ue)ck",
    re.IGNORECASE,
)
_VERTAGT = re.compile(r"\b(?:sp(?:ä|ae)ter|nachher|danach|anschlie(?:ß|ss)end|irgendwann|am ende|morgen|"
                      r"n(?:ä|ae)chste[ns]? (?:mal|woche|termin|meeting|runde))\b", re.IGNORECASE)


def rueckwaerts(text: str) -> bool:
    """Ausdrückliche Rückkehr zu einem früheren Punkt (ohne Vertagung) – das Ziel prüft angekuendigter_punkt."""
    return bool(_RUECKWAERTS.search(text)) and not _VERTAGT.search(text)


def angekuendigter_punkt(text: str, titel: list[str], aktiv: int) -> int | None:
    """Ausdrückliche Überleitung mit Ziel („weiter zu Punkt drei“, „zum nächsten Punkt“, „…zum Budget“,
    „nochmal zurück zu Punkt eins“): Index des Agendapunkts, sonst None. Ohne Überleitungsformel nie –
    „Punkt drei war gut“ wechselt nicht."""
    if not (ankuendigung(text) or rueckwaerts(text)):
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


def rueckkehr(text: str, titel: list[str], aktiv: int) -> bool:
    """„Gut, zurück zur Datenbank“, „zurück zum Thema“: Rückkehr ohne neues Ziel – die Runde ist wieder beim
    aktiven Punkt (Ticket #24). Mit anderem Agendapunkt als Ziel ist es ein Wechsel (angekuendigter_punkt)."""
    return rueckwaerts(text) and angekuendigter_punkt(text, titel, aktiv) is None


RUECKKEHR = "Rückkehr zum Thema angesagt"


def rueckkehr_merken(meeting: Meeting) -> None:
    """Fokus wieder beim aktiven Punkt: ein Eintrag „aktiv“ im Verlauf, so wird die Ampel grün."""
    meeting.themen_verlauf.append({"punkt": meeting.aktiver_punkt, "art": "aktiv", "konfidenz": 1.0,
                                   "begruendung": RUECKKEHR, "ton": []})


def themen_auswerten(meeting: Meeting, entscheider: Entscheider, ergebnis: dict, karenz_bloecke: int,
                     zurueckgekehrt: bool = False) -> None:
    """Ergebnis der Themen-Zuordnung in Fokus-Hinweis und Wechselvorschlag (FR-02) übersetzen.

    `zurueckgekehrt`: Seit Beginn des eingeordneten Fensters fiel eine Rückkehr-Ansage. Ein Hinweis käme dann
    veraltet (Cloud-Lauf 08.10.: „Bezug unklar“ 45 s nach „Gut, zurück zur Datenbank“) – er wird verworfen.
    """
    meeting.themen_verlauf.append(ergebnis)
    status, ausloeser = fokus_status(meeting.themen_verlauf, karenz_bloecke)
    if status == "gruen":
        if ergebnis["art"] == "aktiv":
            meeting.vorschlag = None
        return
    if zurueckgekehrt:
        rueckkehr_merken(meeting)
        return
    if ausloeser["art"] in ("vorgriff", "zurueck") and ausloeser["punkt"] is not None:
        # Agenda-Vorschlag „Weiter zu …?“ – ein Band-Hinweis mit Knopf (Ticket #27), auch ohne die Regel
        ziel = ausloeser["punkt"]
        meeting.vorschlag = {"punkt": ziel, "titel": meeting.agenda[ziel].titel, "begruendung": ausloeser["begruendung"],
                             "von": meeting.aktiver_punkt}
        schluessel = f"fokus-punkt-{ziel}"
    else:
        schluessel = "fokus-unklar"
    if "thema" not in meeting.regel_ids:
        return  # Ticket #27: nicht gewählte Regeln sind unsichtbar – kein Fokus-Hinweis
    text = fokus_hinweistext(meeting, ausloeser) + regeln.vereinbart(meeting.regel_ids, "thema")
    entscheider.vorschlagen(meeting, "fokus", "hinweis", "gruppe", text, schluessel, punkt=meeting.aktiver_punkt)


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
    if meeting.ueberlappungen_gezaehlt:
        if ueberlappungs_vorfaelle(meeting, seit):
            ampeln.append({"name": "Sprecherüberlappung", "farbe": "gelb", "detail": "mehrere sprechen gleichzeitig"})
        else:
            ampeln.append({"name": "Sprecherüberlappung", "farbe": "gruen", "detail": "normale Sprecherwechsel"})
        return ampeln
    if any(t >= seit for t in meeting.mischungen) or ueberlappung_erkannt(
        meeting.segmente, seit, ueberlappung_min, zickzack_fenster, zickzack_wechsel
    ):
        ampeln.append({"name": "Sprecherüberlappung", "farbe": "gelb", "detail": "mehrere sprechen gleichzeitig"})
    else:
        ampeln.append({"name": "Sprecherüberlappung", "farbe": "gruen", "detail": "normale Sprecherwechsel"})
    return ampeln


# --- Gesprächsdynamik: wie oft gleichzeitig, wie oft ins Wort, wie „heiß“ -----------------------------------
# Vorbild aus der Forschung: Konflikt- und „Hot-Spot“-Erkennung in Besprechungen stützt sich vor allem auf Rate von
# Überlappungen und Unterbrechungen, dazu Lautstärke und Sprechtempo (Wrede & Shriberg 2003, ICSI-Meetings; Kim et
# al. 2012, Konflikte in politischen Debatten). Gewichte und Stufen sind Startwerte – im Raumtest kalibrieren.
KLIMA_FENSTER = 180.0


def ueberlappungs_vorfaelle(meeting: Meeting, seit: float = 0.0, min_dauer: float = 1.0) -> list[list[float]]:
    """Gleichzeitiges Sprechen ab 1 s zählt als Vorfall („konkurrierende“ Überlappung). Kürzere sind meist
    Zustimmung („ja“, „mhm“) oder Saalhall: Testlauf 06.10., je 10 min ab 1 s – Talkshow 8,3, Stadtrat Koblenz 3,5,
    Stadtrat Hoyerswerda 1,7, Anhörung/Podium/Bürgerversammlung 0–0,5; ohne Mindestdauer lag Koblenz gleichauf
    mit der Talkshow."""
    return [u for u in meeting.ueberlappungen if u[1] - u[0] >= min_dauer and u[0] >= seit]


def klima(meeting: Meeting, aeusserungen: list, unterbrechungen: list[float], ton: list[float]) -> dict:
    """Gesprächsklima der letzten 3 Minuten: ruhig / lebhaft / hitzig, mit Gründen."""
    import statistics

    jetzt = meeting.jetzt()
    seit = max(0.0, jetzt - KLIMA_FENSTER)
    minuten = max(1.0, min(KLIMA_FENSTER, jetzt) / 60)
    ov = len(ueberlappungs_vorfaelle(meeting, seit))
    ib = sum(1 for t in unterbrechungen if t >= seit)
    tn = sum(1 for t in ton if t >= jetzt - 300)

    def pegel(ae) -> float | None:
        sprache = [x for x in ae.pegel if x > -50]
        return statistics.median(sprache) if len(sprache) >= 4 else None

    alle = [p for p in (pegel(a) for a in aeusserungen) if p is not None]
    jung = [p for p in (pegel(a) for a in aeusserungen if a.ende >= seit) if p is not None]
    lauter = (statistics.mean(sorted(jung)[len(jung) // 2:]) - statistics.median(alle)) if len(alle) >= 10 and len(jung) >= 3 else 0.0
    punkte = ov / minuten + 1.5 * ib / minuten + max(0.0, lauter - 3) / 3 + tn
    gruende = []
    if ov:
        gruende.append(f"{ov}× gleichzeitig gesprochen")
    if ib:
        gruende.append(f"{ib}× ins Wort gefallen")
    if lauter >= 3:
        gruende.append(f"lauter als sonst (+{lauter:.0f} dB)")
    if tn:
        gruende.append(f"{tn}× rauer Ton")
    # „Hitzig“ nur mit Lautstärke oder rauem Ton: Viel Überlappung allein heißt Engagement, nicht Konflikt
    # (AMI-Designbesprechungen 06.10.: freundlich, aber 25–30 Überlappungen je 10 min – mehr als die Talkshow)
    erregt = lauter >= 3 or tn > 0
    stufe = "hitzig" if punkte >= 2.5 and erregt else "lebhaft" if punkte >= 1.0 else "ruhig"
    return {"stufe": stufe, "punkte": round(punkte, 2), "gruende": gruende}
