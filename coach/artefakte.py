"""Meeting-Artefakte (Ticket #26, Ablauf seit Ticket #27): Aufgabe, Entscheidung, offener Punkt, Risiko – erkannt,
Lücken markiert, per Stimme oder Klick geschlossen. Grundlage: docs/meeting_artefakte_2026-10-08.md.

- **Ein Datenmodell** (`Artefakt`): Typ, Felder, Vollständigkeit, Lücken, Konfidenz, Quelle (Zeit, Satz),
  Agendabezug, bestätigt ja/nein. Daraus abgeleitet: `Meeting.ergebnisse` im alten Format (Kontext für Nestor,
  Überblick, Protokoll, Abschluss-Kopf) und die Standardgliederung für Abschluss und Export (#22).
- **Erkennung bei Bedarf** (Ticket #27): keine ständige Erkennung mehr. Erkannt wird still je **Abschnitt** – beim
  Punktwechsel, nach 20 Minuten am selben Punkt bzw. ohne Agenda alle 20 Minuten – und nur über diesen Abschnitt;
  daraus wird still eine Karte „Zusammenfassung · Punkt …“ im Verlauf. Auf Anfrage (Zusammenfassen, Was fehlt,
  Protokoll) wird nur der laufende Abschnitt nachgeholt (`nachholen`, in parallelen Stücken), damit der Bogen unter
  15 s bleibt. Das Modell sieht die schon festgehaltenen Artefakte mit Nummer und ergänzt, statt doppelt anzulegen.
- **Regel „Ergebnisse festhalten“** heißt nur noch: Lücken in den Abschnitts-Karten rot markieren plus ein Band-Hinweis
  („2 Aufgaben ohne Verantwortliche ›“, der Knopf springt zur Karte). Ohne Regel keine Markierung, kein Band.
- **Fünf Minuten vor dem geplanten Ende** (immer): Band „Noch 5 Minuten · Zusammenfassen ›“ – der Knopf löst den
  Bogen „Zusammenfassen“ aus. Nestor fragt nicht mit der Stimme.
- **Lücken schließen:** „Nestor, Sofie übernimmt die Statusseite bis Freitag“ (Premium: Realtime-Werkzeug
  `artefakt_eintragen`, Basis per Sprechtaste: `AKTION: eintragen`) – Nestor sagt „Notiert“, die Karte wird grün;
  oder Klick auf die Lücke in der Karte.

- **Schnell-Erkennung bei klaren Signalen** (Ticket #72): Fällt in einem fertigen Satz ein klares Signal
  („beschlossen“, „machst du bis“, „Termin“, „offen ist“ – Vorfilter `signal()`, lokal und kostenlos), prüft ein
  kleiner, günstiger Aufruf nur diese Sätze (Zuordnungsmodell der Stufe, über die Anbieterfabrik). Neues kommt als
  Karte „Gerade festgehalten“ in den Verlauf, meist binnen 10–20 s. Die gebündelte Vollauswertung bleibt; sie sieht die
  schnell erkannten Artefakte mit Nummer und ergänzt sie, statt sie doppelt anzulegen (`uebernehmen`).
- **Kein stiller Ausfall** (Ticket #72): Scheitert ein Aufruf, steht das sichtbar im Band (coach/ki_fehler.py), und
  der nächste Takt versucht es wieder (30 s, dann 60, 120 … höchstens 5 min Abstand).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field

from .analyse import mmss

log = logging.getLogger("coach.artefakte")

TYPEN = ("aufgabe", "entscheidung", "offen", "risiko")
TYP_NAME = {"aufgabe": "Aufgabe", "entscheidung": "Entscheidung", "offen": "Offener Punkt", "risiko": "Risiko"}
STATUS = ("endgueltig", "vorlaeufig", "vorschlag")
# Pflichtfelder je Typ (Ticket #26, Tabelle „Artefakte und wann sie vollständig sind“); was = Handlung / was gilt /
# präzise Frage / Ursache → Auswirkung
PFLICHT = {
    "aufgabe": ("was", "wer", "bis"),
    "entscheidung": ("was", "status", "wer"),
    "offen": ("was", "wer", "bis"),
    "risiko": ("was", "wer", "reaktion"),
}
FELD_NAME = {"was": "was", "wer": "wer", "bis": "bis wann", "status": "beschlossen?", "reaktion": "Reaktion"}
# „Wir“ ist keine verantwortliche Person (PMI: genau ein Owner)
KOLLEKTIV = {"wir", "uns", "alle", "jemand", "man", "ihr", "team", "das team", "die runde", "alle zusammen",
             "irgendwer", "einer", "eine", "wer"}

MIN_SPRACHE = 30.0        # ein Abschnitt mit weniger Sprache und ohne Artefakte bekommt keine Karte
KONTEXT_SEKUNDEN = 40.0   # Gesprochenes vor den neuen Sätzen als Kontext
MAX_ZEICHEN = 6000        # größere Mengen (20-Minuten-Abschnitt) in mehreren Aufrufen
MAX_ZEICHEN_PARALLEL = 3500  # auf Anfrage (Bogen) kleinere Stücke, alle gleichzeitig – der Bogen soll unter 15 s bleiben
MIN_KONFIDENZ = 0.4       # darunter wird nichts festgehalten
FRAGE_KONFIDENZ = 0.5     # darunter fragt Nestor nicht nach (die Karte bleibt sichtbar)
FUENF_MINUTEN = 300.0
# Schnell-Erkennung (Ticket #72)
SAMMELN_SEKUNDEN = 4.0    # nach dem Signalsatz kurz warten: „… bis Freitag“ kommt oft im nächsten Satz
SCHNELL_KONTEXT = 20.0    # so viel Gesprochenes davor geht als Kontext mit
SCHNELL_MAX_STUNDE = 60   # Deckel je Meetingstunde; darüber übernimmt die gebündelte Auswertung allein
WIEDERHOLEN_AB = 30.0     # erster neuer Versuch nach einem Fehler, danach doppelt so lange, höchstens …
WIEDERHOLEN_MAX = 300.0


def _text(v, n: int = 160) -> str | None:
    if v is None or isinstance(v, bool):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip(" .")
    return s[:n] if s and s.lower() not in ("null", "none", "-", "offen", "unbekannt", "fehlt") else None


def sekunden(zeit) -> float | None:
    """„12:34“ oder 754 → Sekunden."""
    if isinstance(zeit, (int, float)) and not isinstance(zeit, bool):
        return float(zeit)
    m = re.match(r"^\s*(\d+):(\d{1,2})\s*$", str(zeit or ""))
    return int(m[1]) * 60 + int(m[2]) if m else None


LEER_RE = re.compile(r"^(?:(?:das|es|dies|dieses)\s+\w+|(?:und\s+)?bis\s+wann(?:\s+\w+)?)$", re.IGNORECASE)


def inhaltsleer(was: str) -> bool:
    """„das übernehmen“, „bis wann ungefähr“: ein Bruchstück ohne erkennbaren Inhalt (Cloud-Lauf grenz2, Grenzfall 6a –
    das Modell hielt es nicht immer heraus)."""
    return bool(LEER_RE.match(was.strip(" ?.!")))


def kollektiv(wer: str | None) -> bool:
    return bool(wer) and wer.strip().lower() in KOLLEKTIV


def sprechbar_wer(wer: str | None) -> str:
    """Nestor nennt niemanden „Person 2“ (Lastenheft: keine Labels vorlesen)."""
    if not wer or re.match(r"^Person\b", wer):
        return "jemand von euch"
    return wer


@dataclass
class Artefakt:
    id: int
    typ: str
    was: str
    wer: str | None = None
    bis: str | None = None           # Termin; bei Entscheidung die Wiedervorlage, bei offenem Punkt der Termin
    status: str | None = None        # nur Entscheidung: endgueltig | vorlaeufig | vorschlag
    reaktion: str | None = None      # nur Risiko: vermeiden/reduzieren/akzeptieren mit Maßnahme
    hoch: bool = False               # nur Risiko: große Auswirkung
    vage: bool = False               # Aufgabe ohne prüfbares Ergebnis („prüfen“, „anschauen“) bzw. diffuse Sorge
    ausserhalb: bool = False         # nicht zur Agenda (Parkplatz, wenn offener Punkt)
    erledigt: bool = False           # offener Punkt im Gespräch beantwortet
    konfidenz: float = 0.7
    zeit: float = 0.0                # Quelle: Meetingzeit des Satzes
    zitat: str = ""                  # Quelle: der Satz, gekürzt
    sprecher: str | None = None
    punkt: int | None = None         # Agendapunkt (0-basiert), der zur Zeit der Quelle aktiv war
    bestaetigt: bool = False         # von der Runde bestätigt (Stimme, Klick, Bearbeiten)
    herkunft: str = "erkannt"        # erkannt | stimme | hand
    nachgefragt: bool = False        # Nestor hat einmal nachgefragt (nicht wiederholen)
    abgelehnt: bool = False          # die Runde wollte die Nachfrage nicht – nie wieder fragen
    geaendert: float = 0.0
    gemeinsam: bool = False          # ausdrücklich gemeinsame Verantwortlichkeit, kein vages „jemand“
    schnell: bool = False            # von der Schnell-Erkennung angelegt (Ticket #72)

    def luecken(self) -> list[str]:
        """Fehlende Pflichtfelder in Anzeigereihenfolge. Leer = vollständig."""
        aus: list[str] = []
        if self.erledigt:
            return aus
        if self.typ == "aufgabe":
            if self.vage:
                aus.append("was")
            if not self.wer or (kollektiv(self.wer) and not self.gemeinsam):
                aus.append("wer")
            if not self.bis:
                aus.append("bis")
        elif self.typ == "entscheidung":
            if self.status in (None, "vorschlag"):
                aus.append("status")
            if not self.wer:
                aus.append("wer")
            if self.status == "vorlaeufig" and not self.bis:
                aus.append("bis")  # vorläufig ohne Wiedervorlage
        elif self.typ == "offen":
            if not self.wer and not self.bis:  # weder Zuständige noch Wiedervorlage
                aus += ["wer", "bis"]
        elif self.typ == "risiko":
            if self.vage:
                aus.append("was")  # nur diffuse Sorge, keine Auswirkung
            if not self.wer:
                aus.append("wer")
            if self.hoch and not self.reaktion:
                aus.append("reaktion")
        return aus

    @property
    def vollstaendig(self) -> bool:
        return not self.luecken()

    def bild(self) -> dict:
        d = asdict(self)
        d["luecken"] = self.luecken()
        d["vollstaendig"] = not d["luecken"]
        d["zeit_text"] = mmss(self.zeit)
        d["typ_name"] = TYP_NAME[self.typ]
        return d

    def kurz(self) -> str:
        """Eine Zeile für Kontext und Protokoll."""
        teile = [f"{self.id}. {TYP_NAME[self.typ]}: {self.was}"]
        if self.typ == "entscheidung":
            teile.append({"endgueltig": "beschlossen", "vorlaeufig": "vorläufig", "vorschlag": "nur Vorschlag"}.get(
                self.status or "vorschlag", ""))
        if self.wer or self.typ != "entscheidung":
            teile.append(f"wer: {self.wer or 'fehlt'}")
        if self.bis or self.typ in ("aufgabe", "offen"):
            teile.append(f"bis: {self.bis or 'fehlt'}")
        if self.typ == "risiko":
            teile.append(f"Reaktion: {self.reaktion or 'fehlt'}" + (", hoch" if self.hoch else ""))
        if self.ausserhalb:
            teile.append("außerhalb der Agenda")
        return " · ".join(teile)


# --- Erkennung ------------------------------------------------------------------------------------------------
SYSTEM = """\
Du bist neutraler Protokollhelfer einer Besprechung auf Deutsch. Du bekommst die Agenda, die schon festgehaltenen
Artefakte (mit Nummer) und neue Sätze aus dem Live-Transkript ([mm:ss] Sprecher: Text, davor etwas Kontext).
Erkenne in den NEUEN Sätzen Meeting-Artefakte – unabhängig davon, ob sie zu einem Agendapunkt passen:
- aufgabe: jemand soll nach dem Meeting etwas Konkretes tun („ich kümmere mich“, „kannst du“, „wir müssen noch“, „X
  liefert bis Freitag“, „muss noch erstellt werden“). was = Handlung mit Verb und Gegenstand, kurz; bis = Termin wie
  gesagt; vage = true, wenn nur „prüfen/anschauen/klären“ ohne erkennbares Ergebnis.
- entscheidung: etwas gilt ab jetzt („beschlossen“, „dann machen wir“, „halten wir fest“, „einverstanden“, „wir legen
  uns heute nicht fest“). was = was gilt; status = "endgueltig" (beschlossen oder von der Runde bestätigt),
  "vorlaeufig" oder "vorschlag" (nur vorgeschlagen, „ich schlage vor“, „sollte“, noch nicht beschlossen); wer = wer
  entschieden hat („die Runde“, „Vorstand“, eine Person); bis = nur bei vorläufig: wann es wieder vorgelegt wird.
- offen: Frage oder ungeklärter Punkt, der für später liegen bleibt („müssen wir noch klären“, „parken wir“, „die
  Berechnung fehlt noch“, „darauf kommen wir zurück“). was = die Frage, präzise; wer = wer klärt; bis = bis wann oder
  welcher Termin; ausserhalb = true, wenn es nicht zur Agenda gehört (Parkplatz).
- risiko: mögliches KÜNFTIGES Problem („wenn X, dann“, „Gefahr“, „könnte uns verzögern“, „ist gefährdet“, „müssen
  aufpassen, dass“). was = Ursache → Auswirkung; wer = wer es beobachtet; reaktion = vermeiden/verringern/in Kauf
  nehmen mit Maßnahme; hoch = true bei großer Auswirkung; vage = true bei diffuser Sorge ohne Auswirkung.
Was NICHT dazugehört:
- Ankündigungen zum Ablauf des Meetings („heute müssen wir zu einer Zahl kommen“, „beim Bus reicht mir ein
  Überblick“), was die Runde gerade jetzt im Meeting tut („ich rekonstruiere die Zeitlinie“), Berichte
  über Vergangenes und Ursachen eines schon eingetretenen Vorfalls, Fragen, die gleich im Gespräch beantwortet werden,
  und das Thema des Agendapunkts selbst.
- Alles, was an den Assistenten „Nestor“ geht, auch Antworten auf seine Angebote („ja, mach eine Folie“).
- Bruchstücke ohne erkennbaren Inhalt („kannst du das übernehmen?“, „und bis wann?“) – außer sie ergänzen ein
  festgehaltenes Artefakt eindeutig.
Felder:
- Nur ausdrücklich Gesagtes, nichts ergänzen. Fehlt etwas, ist es null.
- Eine ausdrücklich vereinbarte gemeinsame Verantwortung („alle sind verantwortlich“, „gemeinsam verantwortlich")
  bekommt gemeinsam=true. Bloßes „wir sollten“ oder „jemand“ ist keine bestätigte gemeinsame Verantwortung.
- Ein gemeinsamer Termin („alle diese Aufgaben bis morgen“) ergänzt JEDE betroffene vorhandene Nummer separat.
  Eine später ausdrücklich genannte Ausnahme überschreibt nur den Termin der betreffenden Aufgabe.
- Relative Fristen anhand des unten angegebenen Meetingdatums auflösen, z. B. „morgen“ zu einem konkreten Datum.
- Explizite Berichtigungen („nicht X, sondern Y“, „ich korrigiere“) ersetzen das falsche Feld am bestehenden Artefakt:
  nummer angeben, korrigiert=true und den korrigierenden Satz als zitat. Kein zweites Artefakt anlegen.
- wer: nur, wenn eine Person genannt wird oder jemand in der Ich-Form zusagt („mach ich“, „passe ich an“ → der
  Sprecher, z. B. „Person 2“). Passiv oder „muss noch …“ ohne Namen → null, auch wenn der Sprecher es sagt. Sagt
  jemand ausdrücklich „wir“, „alle“ oder „jemand“, genau das. Übernehmen mehrere Personen verschiedene Teile
  („Sabine liefert die Fahrten, Jörg die Kosten“), je Person eine Aufgabe.
- Ergänzt ein neuer Satz ein festgehaltenes Artefakt (jemand übernimmt es, ein Termin kommt dazu, ein Vorschlag wird
  beschlossen, eine offene Frage wird beantwortet → erledigt = true), gib dessen nummer und nur die neuen Felder an.
  Dasselbe Vorhaben mit anderen Worten ist kein neues Artefakt. Sonst nummer null.
- konfidenz 0 bis 1: wie sicher es ein solches Artefakt ist. zeit = Zeitstempel des Satzes, aus dem es stammt;
  zitat = dieser Satz, höchstens 15 Wörter.
Antworte nur mit JSON: {"artefakte": [{"nummer": null, "typ": "aufgabe", "was": "…", "wer": null, "bis": null,
"status": null, "reaktion": null, "hoch": false, "vage": false, "ausserhalb": false, "erledigt": false,
"gemeinsam": false, "korrigiert": false, "konfidenz": 0.8, "zeit": "mm:ss", "zitat": "…"}]}.
Leere Liste, wenn die neuen Sätze nichts davon enthalten."""

def _artefakte_text(liste: list[Artefakt], n: int = 30) -> str:
    return "\n".join(a.kurz() for a in liste[-n:]) or "(noch keine)"


def nachricht(meeting, liste: list[Artefakt], neu: list, kontext: list) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    datum = datetime.fromtimestamp(meeting.gestartet_um or time.time(), ZoneInfo("Europe/Berlin")).isoformat()
    agenda = "\n".join(f"{i + 1}. {p.titel}" + (f" – {p.ziel}" if p.ziel else "") for i, p in enumerate(meeting.agenda))
    zeile = lambda s: f"[{mmss(s.start)}] {s.sprecher}: {s.text}"  # noqa: E731
    return (f"Meetingdatum (Europe/Berlin): {datum}\nMeeting: {meeting.titel or '-'} · Ziel: {meeting.ziel or '-'}\nAgenda:\n{agenda or '(keine)'}\n\n"
            f"Schon festgehalten:\n{_artefakte_text(liste)}\n\n"
            + (f"Kontext (schon ausgewertet):\n" + "\n".join(zeile(s) for s in kontext) + "\n\n" if kontext else "")
            + "NEUE Sätze:\n" + "\n".join(zeile(s) for s in neu))


# --- Schnell-Erkennung bei klaren Signalen (Ticket #72) ---------------------------------------------------------
_TAG = (r"(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|morgen|übermorgen|heute|monatsende|"
        r"jahresende|ende\s+(?:der|des|nächster|kommender)\s+\w+|(?:die\s+)?nächste[nrm]?\s+woche|kw\s*\d+|"
        r"\d{1,2}\.\s*(?:\d{1,2}\.?|januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|"
        r"dezember))")
SIGNALE = {
    "entscheidung": re.compile(
        r"\b(?:beschlie(?:ß|ss)en|beschlossen|beschluss|entschieden|entscheiden\s+wir|wir\s+entscheiden|geeinigt|"
        r"einigen\s+uns|halten\s+(?:wir\s+)?(?:das\s+)?fest|festgehalten|machen\s+wir\s+so|abgemacht|vereinbart|"
        r"festgelegt|legen\s+(?:wir\s+)?(?:uns\s+)?fest)\b", re.IGNORECASE),
    "aufgabe": re.compile(
        r"\b(?:machst\s+du|kannst\s+du|übernimmst\s+du|übernimm\w*|übernehme|kümmer\w*|ich\s+mach(?:e)?\b|"
        r"liefer\w*|schick\w*|erledig\w*|bis\s+(?:zum\s+|spätestens\s+)?" + _TAG + r")", re.IGNORECASE),
    "termin": re.compile(
        r"\b(?:termin|frist|deadline|stichtag|wiedervorlage|spätestens|am\s+" + _TAG + r")", re.IGNORECASE),
    "offen": re.compile(
        r"\b(?:offen\s+ist|ist\s+(?:noch\s+)?offen|bleibt\s+offen|offene\s+frage|(?:noch|müssen\s+wir)\s+(?:\w+\s+){0,2}"
        r"klären|klären\s+wir|ungeklärt|parken|kommen\s+wir\s+(?:noch\s+)?(?:darauf\s+)?zurück|prüfen\s+wir\s+noch|"
        r"noch\s+prüfen)", re.IGNORECASE),
    "risiko": re.compile(r"\b(?:risiko|gefahr|gefährdet|könnte\s+uns)", re.IGNORECASE),
}


def signal(text: str) -> str | None:
    """Lokaler Vorfilter, kostenlos: welche Art Ergebnis ein Satz ankündigt (oder None). Nur bei Treffer läuft die
    Schnell-Erkennung – die meisten Sätze kosten also nichts."""
    for art, muster in SIGNALE.items():
        if muster.search(text or ""):
            return art
    return None


SCHNELL = """\
Schnellprüfung im laufenden Meeting (Deutsch): Die NEUEN Sätze enthalten ein Signalwort für ein Meeting-Ergebnis.
Prüfe nur diese neuen Sätze, ob wirklich eines darin steckt:
- entscheidung: etwas gilt ab jetzt; status "endgueltig" (beschlossen), "vorlaeufig" oder "vorschlag"; wer = wer
  entschieden hat („die Runde“, eine Person).
- aufgabe: jemand soll nach dem Meeting etwas Konkretes tun; wer = genannte Person oder bei Ich-Form der Sprecher;
  bis = Termin wie gesagt; vage = true bei bloßem „prüfen/anschauen“ ohne Ergebnis.
- offen: Frage oder Punkt, der für später liegen bleibt; wer klärt, bis wann.
- risiko: mögliches künftiges Problem (Ursache → Auswirkung).
Nicht dazu: alles an den Assistenten „Nestor“, der Ablauf des Meetings, Berichte über Vergangenes, Ideen ohne Zusage.
Nur ausdrücklich Gesagtes, fehlende Felder null. Relative Fristen anhand des Meetingdatums auflösen.
Ergänzt ein Satz ein schon festgehaltenes Artefakt (Termin, Verantwortliche, Beschluss eines Vorschlags), gib dessen
nummer und nur die neuen Felder an – nie doppelt anlegen. Im Zweifel eine leere Liste.
Antworte nur mit JSON: {"artefakte": [{"nummer": null, "typ": "aufgabe", "was": "…", "wer": null, "bis": null,
"status": null, "vage": false, "konfidenz": 0.8, "zeit": "mm:ss", "zitat": "…"}]}."""


async def _json_aufruf(client, modell: str, system: str, nutzer: str, aufwand: str = "") -> tuple[dict, dict]:
    extra = {"reasoning_effort": aufwand} if aufwand else {}
    antwort = await client.chat.completions.create(
        model=modell, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": nutzer}], **extra)
    try:
        roh = json.loads(antwort.choices[0].message.content or "{}")
    except (json.JSONDecodeError, TypeError):
        roh = {}
    nutzung = {}
    u = getattr(antwort, "usage", None)
    if u:
        nutzung = {"tokens_rein": u.prompt_tokens, "tokens_raus": u.completion_tokens}
    return (roh if isinstance(roh, dict) else {}), nutzung


def normalisieren(e: dict) -> dict | None:
    """Ein Eintrag aus der Modellantwort → saubere Felder (None, wenn unbrauchbar)."""
    if not isinstance(e, dict):
        return None
    typ = str(e.get("typ") or "").lower().strip()
    typ = {"frage": "offen", "offener punkt": "offen", "offene frage": "offen", "beschluss": "entscheidung",
           "massnahme": "aufgabe", "maßnahme": "aufgabe"}.get(typ, typ)
    nummer = e.get("nummer")
    try:
        nummer = int(nummer) if nummer not in (None, "", "null") else None
    except (TypeError, ValueError):
        nummer = None
    if typ not in TYPEN and nummer is None:
        return None
    status = str(e.get("status") or "").lower().replace("ü", "ue").replace("ä", "ae") or None
    status = status if status in STATUS else None
    try:
        konf = max(0.0, min(1.0, float(e.get("konfidenz"))))
    except (TypeError, ValueError):
        konf = None
    return {"nummer": nummer, "typ": typ if typ in TYPEN else None, "was": _text(e.get("was")),
            "wer": _text(e.get("wer"), 60), "bis": _text(e.get("bis"), 60), "status": status,
            "reaktion": _text(e.get("reaktion")), "hoch": e.get("hoch") if isinstance(e.get("hoch"), bool) else None,
            "vage": e.get("vage") if isinstance(e.get("vage"), bool) else None,
            "ausserhalb": e.get("ausserhalb") if isinstance(e.get("ausserhalb"), bool) else None,
            "erledigt": e.get("erledigt") if isinstance(e.get("erledigt"), bool) else None,
            "konfidenz": konf, "zeit": sekunden(e.get("zeit")), "zitat": _text(e.get("zitat"), 140),
            "gemeinsam": e.get("gemeinsam") is True, "korrigiert": e.get("korrigiert") is True}


def _woerter(t: str) -> set[str]:
    return {w for w in re.findall(r"\w+", (t or "").lower()) if len(w) >= 4}


def aehnlich(a: str, b: str) -> bool:
    """Gleiches Artefakt mit anderen Worten? Mindestens 60 % der Wörter des kürzeren kommen im anderen vor."""
    wa, wb = _woerter(a), _woerter(b)
    if not wa or not wb:
        return False
    return len(wa & wb) >= 0.6 * min(len(wa), len(wb))


def punkt_an(meeting, t: float) -> int | None:
    """Agendapunkt, der zur Meetingzeit t aktiv war."""
    if not meeting.agenda:
        return None
    aktiv = meeting.punkt_beginne[0][0] if meeting.punkt_beginne else meeting.aktiver_punkt
    for p, ab in meeting.punkt_beginne:
        if ab <= t:
            aktiv = p
    return aktiv


# --- Stimme: Texte für Nachfrage, Zusammenfassung, Bestätigung -------------------------------------------------
def frage_zu(a: Artefakt) -> str:
    """Eine Frage je Artefakt, mit konkretem Vorschlag (Ticket #26 Punkt 3)."""
    l = a.luecken()
    was = a.was.rstrip(". ")
    if was.endswith("?"):  # eine Frage als Inhalt: „Offen ist noch: Ist … enthalten? Wer klärt das …“
        was = was[:-1]
    if a.typ == "aufgabe":
        if "was" in l and "wer" not in l and "bis" not in l:
            return f"Ich hab notiert: {was}. Was genau soll dabei herauskommen?"
        if "wer" in l and "bis" in l:
            return f"Ich hab notiert: {was}. Wer übernimmt das, bis wann?"
        if "wer" in l:
            termin = "" if a.bis.lower() in was.lower() else f", bis {a.bis}"
            return f"Ich hab notiert: {was}{termin}. Wer übernimmt das?"
        wer = sprechbar_wer(a.wer)
        return f"Ich hab notiert: {was}" + ("" if wer == "jemand von euch" else f", {wer}") + ". Bis wann?"
    if a.typ == "entscheidung":
        if "status" in l:
            return f"Das klang nach einer Entscheidung: {was}. Soll ich das so festhalten?"
        if "bis" in l:
            return f"{was} gilt vorläufig. Wann schaut ihr wieder drauf?"
        return f"{was} – wer hat das entschieden?"
    if a.typ == "offen":
        return f"Offen ist noch: {was}. Wer klärt das, bis wann?"
    if "was" in l:
        return f"Ihr habt eine Sorge genannt: {was}. Was wäre die Auswirkung?"
    if "reaktion" in l and "wer" in l:
        return f"Risiko notiert: {was}. Wer behält das im Blick, und wie wollt ihr reagieren?"
    if "reaktion" in l:
        return f"Risiko notiert: {was}. Wie wollt ihr reagieren – vermeiden, verringern oder in Kauf nehmen?"
    return f"Risiko notiert: {was}. Wer behält das im Blick?"


def rang(a: Artefakt) -> int | None:
    """Reihenfolge der Lücken am Meetingende (Ticket #26 Punkt 4): Aufgaben ohne Wer, dann ohne Termin, dann unklare
    Entscheidungen bzw. hohe Risiken; der Rest danach. None = keine Lücke."""
    l = a.luecken()
    if not l:
        return None
    if a.typ == "aufgabe" and "wer" in l:
        return 0
    if a.typ == "aufgabe" and "bis" in l:
        return 1
    if a.typ == "entscheidung" or (a.typ == "risiko" and a.hoch):
        return 2
    return 3


def bestaetigung_text(a: Artefakt, felder: dict) -> str:
    teile = []
    if felder.get("wer"):
        teile.append(sprechbar_wer(felder["wer"]) if not re.match(r"^Person\b", felder["wer"]) else "bei dir")
    if felder.get("bis"):
        teile.append(f"bis {felder['bis']}")
    if felder.get("status") == "endgueltig":
        teile.append("als beschlossen")
    if felder.get("reaktion"):
        teile.append(felder["reaktion"])
    if not teile and felder.get("was"):
        teile.append(felder["was"])
    return "Eingetragen" + (": " + ", ".join(teile) if teile else "") + "."


def _liste_sprechen(dinge: list[str]) -> str:
    return dinge[0] if len(dinge) == 1 else ", ".join(dinge[:-1]) + " und " + dinge[-1]


# --- Speicher und Ablauf ---------------------------------------------------------------------------------------
class Artefakte:
    """Artefakte eines Meetings und ihr Ablauf; am Coach als `coach.artefakte`."""

    def __init__(self, coach=None) -> None:
        self.coach = coach
        self.liste: list[Artefakt] = []
        self._n = 0
        self.bis = -1.0              # Meetingzeit, bis zu der das Transkript ausgewertet ist (Satzende)
        self.letzter_lauf = 0.0
        self.sperre = asyncio.Lock()
        self.laeuft = False
        self.abschnitt_ab = 0.0      # Beginn des laufenden Abschnitts (Ticket #27: Zusammenfassung je Abschnitt)
        self._abschnitt_laeuft = False
        self.fuenf_gefragt = False
        self.verlauf: list[dict] = []  # Zusammenfassungen, Abschnitte (ohne Inhalte der Sätze) für den Bericht
        # Ticket #72: Schnell-Erkennung und Wiederholung nach einem Fehler
        self._schnell_ab: float | None = None  # frühester Signalsatz, der noch auf die Schnell-Erkennung wartet
        self._schnell_laeuft = False
        self._schnell_zeiten: list[float] = []  # Meetingzeiten der Schnell-Aufrufe (Deckel je Stunde)
        self._voll_offen = False                 # gebündelte Erkennung scheiterte – der Takt holt sie nach
        self._wiederholen_um: float | None = None
        self._abstand = WIEDERHOLEN_AB

    # --- Daten ---------------------------------------------------------------------------------------------
    def holen(self, nr: int) -> Artefakt | None:
        return next((a for a in self.liste if a.id == nr), None)

    def _jetzt(self) -> float:
        return self.coach.meeting.jetzt() if self.coach else 0.0

    def anlegen(self, typ: str, was: str, **felder) -> Artefakt:
        self._n += 1
        a = Artefakt(self._n, typ, was, geaendert=self._jetzt(), **felder)
        self.liste.append(a)
        return a

    def uebernehmen(self, e: dict, quelle_zeit: float, saetze: list | None = None,
                    schnell: bool = False) -> Artefakt | None:
        """Ein normalisierter Eintrag aus der Erkennung: neues Artefakt oder Ergänzung eines bestehenden.
        `schnell`: kommt aus der Schnell-Erkennung (Ticket #72)."""
        m = self.coach.meeting if self.coach else None
        e = dict(e)
        quelle_text = " ".join(s.text for s in saetze or [])
        # Modellflags allein reichen nicht: ausdrückliche Vereinbarung/Berichtigung muss in der Quelle stehen.
        e["gemeinsam"] = bool(e.get("gemeinsam") and re.search(
            r"(?:alle|gemeinsam|team|runde).{0,50}(?:verantwort|zuständig)|(?:verantwort|zuständig).{0,50}(?:alle|gemeinsam)",
            quelle_text, re.I))
        e["korrigiert"] = bool(e.get("korrigiert") and re.search(
            r"korrig|berichti|nicht.{1,80}sondern", quelle_text, re.I))
        a = self.holen(e["nummer"]) if e.get("nummer") else None
        if a is None and e.get("typ") and e.get("was"):
            a = next((x for x in self.liste if x.typ == e["typ"] and aehnlich(x.was, e["was"])), None)
        if a is None and not schnell and e.get("typ") and e.get("zeit") is not None:
            # Ticket #72: Die Vollauswertung formuliert ein schnell erkanntes Artefakt anders – derselbe Typ aus demselben
            # Satz (±2 s) und keine andere Person ist dasselbe Artefakt, keine Dublette.
            a = next((x for x in self.liste if x.schnell and x.typ == e["typ"] and abs(x.zeit - e["zeit"]) <= 2.0
                      and (not e.get("wer") or not x.wer or x.wer == e["wer"])), None)
        if a is not None:
            self._ergaenzen(a, e)
            return a
        konf = e["konfidenz"] if e.get("konfidenz") is not None else 0.7
        if not e.get("typ") or not e.get("was") or konf < MIN_KONFIDENZ or e.get("erledigt") or inhaltsleer(e["was"]):
            return None
        zeit = e["zeit"] if e.get("zeit") is not None else quelle_zeit
        quelle = min(saetze or [], key=lambda s: abs(s.start - zeit), default=None)
        if quelle is not None and abs(quelle.start - zeit) <= 2.0:
            zeit = quelle.start
        a = self.anlegen(e["typ"], e["was"], wer=e["wer"], bis=e["bis"], status=e["status"] if e["typ"] == "entscheidung"
                         else None, reaktion=e["reaktion"] if e["typ"] == "risiko" else None,
                         hoch=bool(e.get("hoch")), vage=bool(e.get("vage")), ausserhalb=bool(e.get("ausserhalb")),
                         gemeinsam=bool(e.get("gemeinsam")),
                         konfidenz=konf, zeit=zeit, zitat=e.get("zitat") or (quelle.text[:140] if quelle else ""),
                         sprecher=quelle.sprecher if quelle is not None and quelle.start == zeit else None,
                         punkt=punkt_an(m, zeit) if m is not None else None)
        if a.typ == "entscheidung" and a.status is None:
            a.status = "vorschlag"
        return a

    def _ergaenzen(self, a: Artefakt, e: dict) -> None:
        """Neue Felder eintragen. Was die Runde selbst gesetzt hat (Stimme, Klick), überschreibt die Erkennung nicht."""
        geaendert = False
        wer_vorher = a.wer
        for k in ("wer", "bis", "status", "reaktion", "was"):
            v = e.get(k)
            if not v or v == getattr(a, k):
                continue
            if a.herkunft != "erkannt" and getattr(a, k) and not e.get("korrigiert"):
                continue
            if k == "was" and getattr(a, k) and not e.get("korrigiert"):
                continue  # der Wortlaut bleibt, sonst springt die Anzeige
            if k == "status" and a.status == "endgueltig" and v == "vorschlag":
                continue
            setattr(a, k, v)
            geaendert = True
        if e.get("gemeinsam") and not a.gemeinsam:
            a.gemeinsam, geaendert = True, True
        if a.wer != wer_vorher and not e.get("gemeinsam"):
            a.gemeinsam = False
        if e.get("wer") and not kollektiv(e["wer"]):
            a.gemeinsam = False
        if e.get("erledigt") and a.typ == "offen" and not a.erledigt:
            a.erledigt, geaendert = True, True
        for k in ("hoch", "vage"):
            if e.get(k) is not None and getattr(a, k) != e[k] and not (k == "vage" and a.herkunft != "erkannt"):
                setattr(a, k, e[k])
                geaendert = True
        if e.get("konfidenz") is not None:
            a.konfidenz = max(a.konfidenz, e["konfidenz"])
        if geaendert:
            a.geaendert = self._jetzt()

    def bearbeiten(self, nr: int, felder: dict, herkunft: str = "hand") -> Artefakt | None:
        """Von der Runde gesetzt (Klick, Stimme): gilt als bestätigt; leere Werte löschen ein Feld."""
        a = self.holen(nr)
        if a is None:
            return None
        for k in ("was", "wer", "bis", "reaktion"):
            if k in felder:
                v = _text(felder[k], 160 if k in ("was", "reaktion") else 60)
                if k == "was" and not v:
                    continue
                setattr(a, k, v)
        if "status" in felder and felder["status"] in STATUS and a.typ == "entscheidung":
            a.status = felder["status"]
        if "typ" in felder and felder["typ"] in TYPEN:
            a.typ = felder["typ"]
            if a.typ == "entscheidung" and a.status is None:
                a.status = "endgueltig"
        for k in ("hoch",):
            if isinstance(felder.get(k), bool):
                setattr(a, k, felder[k])
        if "was" in felder:
            a.vage = False
        a.bestaetigt, a.herkunft, a.geaendert = True, herkunft, self._jetzt()
        self.ableiten()
        return a

    def loeschen(self, nr: int) -> bool:
        a = self.holen(nr)
        if a is None:
            return False
        self.liste.remove(a)
        self.ableiten()
        return True

    def luecken_liste(self, n: int = 3, punkt: int | None = None) -> list[Artefakt]:
        """Unvollständige Artefakte in der festgelegten Reihenfolge, ohne abgelehnte und ohne unsichere."""
        kandidaten = [a for a in self.liste if rang(a) is not None and not a.abgelehnt and a.konfidenz >= FRAGE_KONFIDENZ
                      and (punkt is None or a.punkt == punkt)]
        return sorted(kandidaten, key=lambda a: (rang(a), a.zeit))[:n]

    def ergebnisse_je_punkt(self) -> dict[int, dict]:
        """Altes Format von Regel 10 (Meeting.ergebnisse) – für Nestors Kontext, Überblick, Protokoll und den
        Abschluss-Kopf. Ergebnis eines Punkts = seine beschlossenen Entscheidungen."""
        aus: dict[int, dict] = {}
        for a in self.liste:
            if a.punkt is None or a.ausserhalb:
                continue
            e = aus.setdefault(a.punkt, {"ergebnis": None, "entscheidungen": [], "aufgaben": []})
            if a.typ == "entscheidung" and a.status != "vorschlag":
                e["entscheidungen"].append({"was": a.was, "ergebnis": "vorläufig" if a.status == "vorlaeufig"
                                            else "beschlossen"})
            elif a.typ == "aufgabe":
                e["aufgaben"].append({"was": a.was, "wer": None if kollektiv(a.wer) else a.wer, "bis": a.bis})
        for e in aus.values():
            beschl = [d["was"] for d in e["entscheidungen"]]
            e["ergebnis"] = "; ".join(beschl)[:300] if beschl else None
        return aus

    def ableiten(self) -> None:
        if self.coach is not None:
            self.coach.meeting.ergebnisse = self.ergebnisse_je_punkt()

    def schnappschuss(self) -> dict:
        return {"liste": [a.bild() for a in self.liste],
                "luecken": sum(1 for a in self.liste if a.luecken() and not a.abgelehnt),
                "laeuft": self.laeuft}

    def kontext_zeilen(self) -> list[str]:
        """Für Nestors Kontext (beide Stufen): mit Nummer, damit „eintragen“ das richtige Artefakt trifft."""
        if not self.liste:
            return []
        return ["Festgehaltene Artefakte (Nummer für eintragen; „fehlt“ = Lücke):"] + [a.kurz() for a in self.liste[-25:]]

    # --- Standardgliederung für Abschluss und Export (#22) ------------------------------------------------------
    def standardgliederung(self) -> dict:
        """Grundlage für meeting.json und das Export-Dokument (#22): Kopf, Entscheidungen, Aufgaben, offene Punkte,
        Risiken, Parkplatz, Agenda Soll/Ist. Felder mit Lücken stehen in `luecken` (im Dokument rot)."""
        c = self.coach
        m = c.meeting
        titel = lambda a: (m.agenda[a.punkt].titel if a.punkt is not None and 0 <= a.punkt < len(m.agenda)  # noqa: E731
                           else None)

        def eintrag(a: Artefakt) -> dict:
            d = {k: v for k, v in a.bild().items() if k not in ("nachgefragt", "geaendert", "typ_name", "zeit_text")}
            d["quelle"] = {"zeit": round(a.zeit, 1), "zeit_text": mmss(a.zeit), "satz": a.zitat, "sprecher": a.sprecher}
            d["agendapunkt"] = (a.punkt + 1) if a.punkt is not None else None
            d["agendapunkt_titel"] = titel(a)
            for k in ("zeit", "zitat", "sprecher", "punkt"):
                d.pop(k, None)
            return d

        nach = lambda typ: [eintrag(a) for a in self.liste if a.typ == typ]  # noqa: E731
        offen = [eintrag(a) for a in self.liste if a.typ == "offen" and not a.ausserhalb]
        parkplatz = [eintrag(a) for a in self.liste if a.typ == "offen" and a.ausserhalb]
        geplant = sum(p.minuten for p in m.agenda)
        return {
            "format": "nestor-meeting/1",
            "kopf": {"titel": m.titel, "ziel": m.ziel, "datum": time.strftime("%Y-%m-%d"),
                     "dauer_sekunden": round(m.jetzt(), 1), "geplant_minuten": geplant,
                     "ziel_erreicht": None},  # Urteil der Runde, kommt mit der Korrekturansicht (#22)
            "entscheidungen": nach("entscheidung"),
            "aufgaben": nach("aufgabe"),
            "offene_punkte": offen,
            "risiken": nach("risiko"),
            "parkplatz": parkplatz,
            "agenda": [{"nr": i + 1, "titel": p.titel, "ziel": p.ziel, "soll_minuten": p.minuten,
                        "ist_minuten": round(m.genutzt(i) / 60, 1), "status": m.status(i)}
                       for i, p in enumerate(m.agenda)],
            "luecken": sum(1 for a in self.liste if a.luecken()),
        }

    def aufgaben_json(self) -> list[dict]:
        """tasks.json: nur die Aufgaben, flach – für Planner/Jira/Asana später (#22)."""
        return [{"id": a.id, "was": a.was, "wer": None if kollektiv(a.wer) else a.wer, "bis": a.bis,
                 "luecken": a.luecken(), "bestaetigt": a.bestaetigt, "konfidenz": round(a.konfidenz, 2),
                 "agendapunkt": (a.punkt + 1) if a.punkt is not None else None,
                 "quelle": {"zeit_text": mmss(a.zeit), "satz": a.zitat}}
                for a in self.liste if a.typ == "aufgabe"]

    # --- Erkennung bei Bedarf (Ticket #27) ---------------------------------------------------------------------
    def _neue_saetze(self) -> list:
        return [s for s in self.coach.meeting.transkript if s.text and s.ende > self.bis]

    def takt(self) -> None:
        """Vom Coach-Takt: Abschnitt nach 20 Minuten schließen (still), Fünf-Minuten-Band."""
        c = self.coach
        m = c.meeting
        if not m.laeuft:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # Takt ohne Ereignisschleife (Tests): keine Hintergrundaufgaben
        from .config import EINST

        if (c._client is not None and not self._abschnitt_laeuft
                and m.jetzt() - self.abschnitt_ab >= EINST.abschnitt_minuten * 60):
            from .pipeline import hintergrund

            self._abschnitt_laeuft = True
            hintergrund(self.abschnitt_abschliessen(m.aktiver_punkt if m.agenda else None, m.jetzt(), "zeit"))
        if (self._wiederholen_um is not None and m.jetzt() >= self._wiederholen_um
                and c._client is not None):
            # Ticket #72: nach einem Fehler beim nächsten fälligen Takt noch einmal
            from .pipeline import hintergrund

            self._wiederholen_um = None
            if self._voll_offen and not self.laeuft:
                self._voll_offen = False
                hintergrund(self.erkennen())
            if self._schnell_ab is not None and not self._schnell_laeuft:
                self._schnell_starten(0.0)
        self._fuenf_pruefen()

    def _stuecke(self, neu: list, groesse: int = MAX_ZEICHEN) -> list[list]:
        stuecke, stueck, zeichen = [], [], 0
        for s in neu:
            if stueck and zeichen + len(s.text) > groesse:
                stuecke.append(stueck)
                stueck, zeichen = [], 0
            stueck.append(s)
            zeichen += len(s.text) + 20
        if stueck:
            stuecke.append(stueck)
        return stuecke

    def _kontext_vor(self, t: float, sekunden: float = KONTEXT_SEKUNDEN) -> list:
        kontext, dauer = [], 0.0
        for s in reversed([x for x in self.coach.meeting.transkript if x.text and x.ende <= t]):
            if dauer >= sekunden:
                break
            kontext.insert(0, s)
            dauer += s.dauer
        return kontext

    async def _aufruf(self, stueck: list, kontext: list, liste: list) -> tuple[dict, dict]:
        from .config import EINST

        return await _json_aufruf(self.coach._client, self.coach.wahl.analyse_modell, SYSTEM,
                                  nachricht(self.coach.meeting, liste, stueck, kontext), self.coach.wahl.analyse_aufwand)

    async def erkennen(self, bis: float | None = None, parallel: bool = False) -> int:
        """Alle noch nicht ausgewerteten Sätze (bis `bis`) auswerten, in Stücken. `parallel`: auf Anfrage alle Stücke
        gleichzeitig (Bogen unter 15 s); sonst nacheinander, damit jedes Stück die Ergebnisse des vorigen sieht.
        Liefert die Zahl neuer/ergänzter Artefakte."""
        c = self.coach
        self.laeuft = True
        n = 0
        try:
            async with self.sperre:
                neu = [s for s in self._neue_saetze() if bis is None or s.start <= bis]
                if not neu or c._client is None:
                    return 0
                stuecke = self._stuecke(neu, MAX_ZEICHEN_PARALLEL if parallel else MAX_ZEICHEN)
                if parallel and len(stuecke) > 1:
                    liste = list(self.liste)
                    ergebnisse = await asyncio.gather(
                        *(self._aufruf(st, self._kontext_vor(st[0].start), liste) for st in stuecke),
                        return_exceptions=True)
                else:
                    ergebnisse = []
                    for st in stuecke:
                        try:
                            ergebnisse.append(await self._aufruf(st, self._kontext_vor(st[0].start), self.liste))
                        except Exception as e:  # noqa: BLE001
                            ergebnisse.append(e)
                            break
                        self._uebernehmen_alle(ergebnisse[-1], st)
                        ergebnisse[-1] = None  # schon übernommen
                fehler = None
                for st, erg in zip(stuecke, ergebnisse):
                    if isinstance(erg, Exception):
                        fehler = erg
                        break  # beim nächsten Lauf noch einmal ab hier
                    if erg is not None:
                        n += self._uebernehmen_alle(erg, st)
                    self.bis = max(self.bis, max(s.ende for s in st))
                if fehler is not None:  # Ticket #72: sichtbar statt nur im Log, und der Takt wiederholt
                    self._voll_offen = True
                    self._fehler(fehler)
                else:
                    self._voll_offen = False
                    self._erfolg()
                self.letzter_lauf = c.meeting.jetzt()
                c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "artefakte", "saetze": len(neu),
                                    "stuecke": len(stuecke), "parallel": parallel, "anzahl": len(self.liste)})
        finally:
            self.laeuft = False
            self.ableiten()
            await c.melden()
        return n

    def _uebernehmen_alle(self, erg: tuple[dict, dict], stueck: list) -> int:
        from .config import EINST
        from .pipeline import nutzung_loggen

        roh, nutzung = erg
        nutzung_loggen({"art": "artefakte", "modell": self.coach.wahl.analyse_modell, **nutzung})
        n = 0
        for e in roh.get("artefakte") or []:
            e = normalisieren(e)
            if e and self.uebernehmen(e, stueck[0].start, stueck):
                n += 1
        return n

    # --- Fehler und Wiederholung (Ticket #72) ----------------------------------------------------------------
    def _fehler(self, e: BaseException) -> None:
        """Sichtbar melden (Band, Fehlerzeile, Technikbericht) und den nächsten Versuch planen – Abstand wächst."""
        from .ki_fehler import melden

        m = self.coach.meeting
        abstand = self._abstand
        self._wiederholen_um = m.jetzt() + abstand
        self._abstand = min(WIEDERHOLEN_MAX, abstand * 2)
        melden(self.coach, "artefakte", e, f"Nestor versucht es in {int(abstand)} s noch einmal." if m.laeuft else "")

    def _erfolg(self) -> None:
        from .ki_fehler import erholt

        self._abstand = WIEDERHOLEN_AB
        if self._voll_offen:  # der Anbieter antwortet wieder: die gescheiterte Vollauswertung gleich nachholen
            self._wiederholen_um = self._jetzt()
        else:
            erholt(self.coach, "artefakte")

    # --- Schnell-Erkennung (Ticket #72) -------------------------------------------------------------------------
    def satz(self, saetze: list) -> None:
        """Vom Coach je fertigem Satz: lokaler Signal-Vorfilter; bei Treffer startet die Schnell-Erkennung (nach
        kurzem Sammeln, damit „… bis Freitag“ im Folgesatz mitkommt). Ansprachen an Nestor zählen nicht."""
        from .assistent import angesprochen

        c = self.coach
        if c is None or c._client is None or not c.meeting.laeuft:
            return
        text = " ".join(s.text for s in saetze if s.text)
        if not text or angesprochen(text) or not signal(text):
            return
        start = min(s.start for s in saetze)
        self._schnell_ab = start if self._schnell_ab is None else min(self._schnell_ab, start)
        if not self._schnell_laeuft and self._wiederholen_um is None:  # nach einem Fehler wartet sie auf den Takt
            self._schnell_starten(SAMMELN_SEKUNDEN)

    def _schnell_starten(self, warten: float) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # ohne Ereignisschleife (Tests): keine Hintergrundaufgaben
        from .pipeline import hintergrund

        self._schnell_laeuft = True
        hintergrund(self._schnell_lauf(warten))

    async def _schnell_lauf(self, warten: float) -> None:
        from .assistent import angesprochen
        from .pipeline import nutzung_loggen

        c = self.coach
        m = c.meeting
        try:
            if warten:
                await asyncio.sleep(warten)
            while self._schnell_ab is not None and c._client is not None:
                jetzt = m.jetzt()
                self._schnell_zeiten = [t for t in self._schnell_zeiten if jetzt - t < 3600]
                if len(self._schnell_zeiten) >= SCHNELL_MAX_STUNDE:
                    self._schnell_ab = None  # Deckel erreicht: die gebündelte Auswertung holt es nach
                    c.protokoll.append({"zeit": jetzt, "art": "artefakte_schnell_deckel"})
                    return
                ab, self._schnell_ab = self._schnell_ab, None
                neu = [s for s in m.transkript if s.text and s.start >= ab - 0.05 and not angesprochen(s.text)]
                if not neu:
                    continue
                self._schnell_zeiten.append(jetzt)
                t0 = time.monotonic()
                modell = c.wahl.zuordnung_modell
                kontext = self._kontext_vor(neu[0].start, SCHNELL_KONTEXT)
                try:
                    roh, nutzung = await _json_aufruf(c._client, modell, SCHNELL, nachricht(m, self.liste, neu, kontext),
                                                      c.wahl.analyse_aufwand)
                except Exception as e:  # noqa: BLE001 – sichtbar melden, der Takt versucht es wieder
                    self._schnell_ab = ab if self._schnell_ab is None else min(ab, self._schnell_ab)
                    self._fehler(e)
                    await c.melden()
                    return
                nutzung_loggen({"art": "artefakte", "schnell": True, "modell": modell, **nutzung})
                self._erfolg()
                neue = []
                for e in roh.get("artefakte") or []:
                    e = normalisieren(e)
                    if not e:
                        continue
                    vorher = len(self.liste)
                    a = self.uebernehmen(e, neu[0].start, neu, schnell=True)
                    if a is not None and len(self.liste) > vorher:
                        a.schnell = True
                        neue.append(a)
                self.ableiten()
                c.protokoll.append({"zeit": m.jetzt(), "art": "artefakte_schnell", "saetze": len(neu),
                                    "neu": [a.id for a in neue], "sekunden": round(time.monotonic() - t0, 2)})
                if neue:
                    self._ergebnis_karte(neue)
                await c.melden()
        finally:
            self._schnell_laeuft = False

    def _ergebnis_karte(self, neue: list[Artefakt]) -> None:
        """Karte „Gerade festgehalten“. Ist die neueste Karte schon eine solche und jünger als eine Minute, wächst sie
        mit (Entscheidung und Aufgabe aus zwei Sätzen in einer Karte). Still: eine frische Antwort bleibt vorn."""
        from .bogen import artefakt_karte

        c = self.coach
        m = c.meeting
        regel = "ergebnisse" in m.regel_ids
        letzte = c.karten[-1] if c.karten else None
        if letzte is not None and letzte.get("art") == "ergebnis" and m.jetzt() - letzte["zeit"] < 60:
            dazu = artefakt_karte(c, "ergebnis", letzte["titel"], neue, regel)
            letzte["ids"] = letzte["ids"] + dazu["ids"]
            letzte["punkte"] = letzte["punkte"] + dazu["punkte"]
            letzte["luecken_vorher"] = {**letzte["luecken_vorher"], **dazu["luecken_vorher"]}
            return
        p = neue[0].punkt
        titel = f"Punkt {p + 1} · {m.agenda[p].titel}" if p is not None and 0 <= p < len(m.agenda) else "Aus dem Gespräch"
        c._karte_ablegen(artefakt_karte(c, "ergebnis", titel, neue, regel, still=True, frage="Festgehalten"))

    async def nachholen(self) -> int:
        """Auf Anfrage (Zusammenfassen, Was fehlt, Protokoll): nur den laufenden Abschnitt nachholen, parallel."""
        return await self.erkennen(parallel=True)

    # --- Zusammenfassung je Abschnitt (still, Ticket #27) ----------------------------------------------------------
    async def abschnitt_abschliessen(self, punkt: int | None, bis: float, grund: str) -> dict | None:
        """Agendapunkt endet (grund „punkt“) oder 20 min am selben Punkt (grund „zeit“): Artefakte nur aus diesem
        Abschnitt erkennen und still eine Karte in den Verlauf legen. Mit der Regel „Ergebnisse festhalten“ sind die
        Lücken markiert und ein Band-Hinweis springt zur Karte."""
        from .bogen import artefakt_karte, luecken_text

        c = self.coach
        m = c.meeting
        von, self.abschnitt_ab = self.abschnitt_ab, max(self.abschnitt_ab, bis)
        try:
            if c._client is None:
                return None
            await self.erkennen(bis=bis)
            sprache = sum(s.dauer for s in m.transkript if s.text and von <= s.start < bis)
            liste = [a for a in self.liste if von <= a.zeit < bis and not a.ausserhalb]
            if sprache < MIN_SPRACHE and not liste:
                return None
            ordnung = {"entscheidung": 0, "aufgabe": 1, "offen": 2, "risiko": 3}
            liste.sort(key=lambda a: (ordnung[a.typ], a.zeit))
            titel_punkt = m.agenda[punkt].titel if punkt is not None and 0 <= punkt < len(m.agenda) else None
            if grund == "punkt" and titel_punkt:
                titel = f"Punkt {punkt + 1} · {titel_punkt}"
            elif titel_punkt:
                titel = f"Zwischenstand · {titel_punkt} · bis {mmss(bis)}"
            else:
                titel = f"Zwischenstand · {mmss(von)}–{mmss(bis)}"
            regel = "ergebnisse" in m.regel_ids
            karte = artefakt_karte(c, "punkt", titel, liste, regel, still=True, punkt=punkt, frage="Zusammenfassung")
            if not liste:
                karte["punkte"] = ["Nichts festgehalten – keine Entscheidung, keine Aufgabe."]
            karte = c._karte_ablegen(karte)
            self.verlauf.append({"zeit": round(m.jetzt(), 1), "art": "abschnitt", "grund": grund, "punkt": punkt,
                                 "ids": [a.id for a in liste]})
            c.protokoll.append({"zeit": m.jetzt(), "art": "abschnitt", "grund": grund, "punkt": punkt,
                                "ids": [a.id for a in liste], "karte": karte["id"]})
            luecken = [a for a in liste if a.luecken() and not a.abgelehnt and a.konfidenz >= FRAGE_KONFIDENZ]
            if regel and luecken and m.laeuft:
                for a in luecken:
                    a.nachgefragt = True
                text = luecken_text(luecken) + (f" in „{titel_punkt}“" if titel_punkt else "")
                c.entscheider.vorschlagen(m, "luecken", "hinweis", "gruppe", text, schluessel=f"luecken-{karte['id']}",
                                          aktion={"text": "Zur Karte", "karte": karte["id"]}, dauer=90.0)
            await c.melden()
            return karte
        finally:
            if grund == "zeit":
                self._abschnitt_laeuft = False

    # --- Fünf Minuten vor Schluss --------------------------------------------------------------------------
    def geplantes_ende(self) -> float | None:
        m = self.coach.meeting
        geplant = sum(p.minuten for p in m.agenda) * 60
        return geplant if geplant > 0 else None

    def _fuenf_pruefen(self) -> None:
        """Immer, auch ohne Regel: 5 min vor dem geplanten Ende (bei kurzen Meetings zur Hälfte) still ins Band –
        als Angebot mit Knopf, ohne Frage (Ticket #27). Ein bloßes „Ja“ in den Raum wirkt nicht."""
        ende = self.geplantes_ende()
        c = self.coach
        m = c.meeting
        if self.fuenf_gefragt or ende is None or not m.laeuft:
            return
        if m.jetzt() >= max(ende - FUENF_MINUTEN, ende / 2):
            self.fuenf_gefragt = True
            rest = ende - m.jetzt()
            text = "Noch 5 Minuten" if rest >= FUENF_MINUTEN - 30 else f"Noch etwa {max(1, round(rest / 60))} Minuten"
            c.entscheider.einmalig(m, "fuenf-minuten", "fuenf", "hinweis", "gruppe", text,
                                   aktion={"text": "Zusammenfassen", "bogen": "zusammenfassen"}, dauer=180.0)
            c.protokoll.append({"zeit": m.jetzt(), "art": "fuenf_minuten"})

    def ablehnen(self, nr: int) -> bool:
        """„Nicht nötig“ an einer Lücke: nicht mehr markieren, nicht mehr im Band."""
        a = self.holen(nr)
        if a is None:
            return False
        a.abgelehnt = True
        return True

    def eintragen(self, daten: dict, herkunft: str = "stimme") -> tuple[Artefakt | None, str]:
        """„Nestor, Sofie übernimmt die Statusseite bis Freitag“: Premium-Werkzeug bzw. Basis-Aktion. Mit Nummer wird
        ergänzt, ohne Nummer ein ähnliches gesucht oder neu angelegt. Liefert (Artefakt, kurze Bestätigung)."""
        e = normalisieren({**daten, "typ": daten.get("typ") or "aufgabe", "konfidenz": 1.0}) or {}
        a = self.holen(e["nummer"]) if e.get("nummer") else None
        if a is None and e.get("was"):
            a = next((x for x in self.liste if aehnlich(x.was, e["was"]) and (not daten.get("typ") or x.typ == e["typ"])),
                     None)
        felder = {k: e[k] for k in ("was", "wer", "bis", "status", "reaktion") if e.get(k)}
        if a is not None:
            a = self.bearbeiten(a.id, felder, herkunft)  # ein neuer Wortlaut von der Runde gilt
        elif e.get("was"):
            m = self.coach.meeting if self.coach else None
            jetzt = self._jetzt()
            a = self.anlegen(e["typ"] or "aufgabe", e["was"], wer=e.get("wer"), bis=e.get("bis"),
                             status=(e.get("status") or "endgueltig") if e["typ"] == "entscheidung" else None,
                             reaktion=e.get("reaktion"), konfidenz=1.0, zeit=jetzt, bestaetigt=True,
                             herkunft=herkunft, punkt=punkt_an(m, jetzt) if m is not None else None)
            self.ableiten()
        else:
            return None, "Das konnte ich keinem Eintrag zuordnen."
        return a, bestaetigung_text(a, felder)


def aktion_lesen(rest: str) -> dict:
    """Basis: „AKTION: eintragen 3; wer=Sofie; bis=Freitag“ oder „AKTION: eintragen neu aufgabe; was=…; wer=…“."""
    teile = [t.strip() for t in re.split(r"[;|]", rest) if t.strip()]
    daten: dict = {}
    if teile:
        kopf = teile[0].lower()
        if (z := re.match(r"^#?(\d+)$", kopf)):
            daten["nummer"] = int(z[1])
            teile = teile[1:]
        elif kopf.startswith("neu"):
            typ = kopf[3:].strip()
            if typ in TYPEN:
                daten["typ"] = typ
            teile = teile[1:]
    for t in teile:
        k, _, v = t.partition("=")
        if not _:
            k, _, v = t.partition(":")
        k = k.strip().lower()
        if k in ("was", "wer", "bis", "status", "reaktion", "typ") and v.strip():
            daten[k] = v.strip()
    return {"typ": "eintragen", "daten": daten}
