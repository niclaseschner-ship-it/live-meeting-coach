"""Meeting-Artefakte (Ticket #26): Aufgabe, Entscheidung, offener Punkt, Risiko – live erkannt, Lücken markiert,
per Stimme oder Klick geschlossen. Grundlage: docs/meeting_artefakte_2026-10-08.md.

Ersetzt die frühere Ergebnisprüfung je Agendapunkt (Regel 10, coach/ergebnisse.py) statt sie zu verdoppeln:

- **Erkennung live** und unabhängig von der Agenda: Neue Sätze aus dem Live-Transkript gehen gesammelt an ein
  Sprachmodell (`analyse_modell`: Premium gpt-5.4-mini, Basis mistral) – etwa einmal je Minute Sprache, dazu beim
  Punktwechsel, vor der Fünf-Minuten-Frage, auf den Protokoll-Knopf und am Ende. Das Modell sieht die schon
  festgehaltenen Artefakte mit Nummer und ergänzt sie, statt sie doppelt anzulegen.
- **Ein Datenmodell** (`Artefakt`): Typ, Felder, Vollständigkeit, Lücken, Konfidenz, Quelle (Zeit, Satz),
  Agendabezug, bestätigt ja/nein. Daraus abgeleitet: `Meeting.ergebnisse` im alten Format (Kontext für Nestor,
  Überblick, Protokoll, Abschluss-Kopf) und die Standardgliederung für Abschluss und Export (#22).
- **Prüfung beim Punktwechsel** (nur mit Regel „Ergebnisse festhalten“): eine gebündelte Nachfrage mit konkretem
  Vorschlag je unvollständigem Artefakt, sonst Schweigen. Eine Nachfrage kommt je Artefakt nur einmal; abgelehnt
  bleibt abgelehnt.
- **Fünf Minuten vor dem geplanten Ende** (immer): Rückfrage im Nestor-Feld und gesprochen; bei Ja
  Zusammenfassung plus höchstens drei Lücken (Aufgaben ohne Wer, dann ohne Termin, dann unklare Entscheidungen
  bzw. hohe Risiken).
- **Lücken schließen:** Antwort auf eine Nachfrage ohne Namen (eigener kleiner Aufruf), „Nestor, Sofie übernimmt
  die Statusseite bis Freitag“ (Premium: Realtime-Werkzeug `artefakt_eintragen`, Basis: `AKTION: eintragen`),
  oder Klick und Bearbeiten im Dashboard.

Im Modus „Nur auf Knopfdruck“ erkennt Nestor nichts von selbst – nur der Protokoll-Knopf (und die Fünf-Minuten-
Rückfrage, deren Ja wie der Knopf wirkt) schickt Text an das Modell.
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

SPRACHE_SEKUNDEN = {"premium": 60.0, "basis": 120.0}  # so viel neue Sprache, dann ein Erkennungslauf; Basis seltener,
#   weil mistral-medium je Token doppelt so viel kostet wie gpt-5.4-mini (Rechnung in docs/gespraechsregeln.md, Regel 10)
SPAETESTENS_SEKUNDEN = 180.0  # mit wenig neuer Sprache spätestens nach dieser Zeit
MIN_SPRACHE = 12.0        # darunter lohnt kein Aufruf (ein „Gut.“)
KONTEXT_SEKUNDEN = 40.0   # Gesprochenes vor den neuen Sätzen als Kontext
MAX_ZEICHEN = 9000        # größere Mengen (Knopfdruck nach 30 min) in mehreren Aufrufen
MIN_KONFIDENZ = 0.4       # darunter wird nichts festgehalten
FRAGE_KONFIDENZ = 0.5     # darunter fragt Nestor nicht nach (die Karte bleibt sichtbar)
FUENF_MINUTEN = 300.0
ANTWORT_SEKUNDEN = 30.0   # so lange nach einer Nachfrage gilt ein Satz ohne Namen als Antwort
MAX_NACHFRAGEN = 2        # je Punktwechsel gesprochen (kurz und gebündelt); der Rest steht im Dashboard


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

    def luecken(self) -> list[str]:
        """Fehlende Pflichtfelder in Anzeigereihenfolge. Leer = vollständig."""
        aus: list[str] = []
        if self.erledigt:
            return aus
        if self.typ == "aufgabe":
            if self.vage:
                aus.append("was")
            if not self.wer or kollektiv(self.wer):
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
"konfidenz": 0.8, "zeit": "mm:ss", "zitat": "…"}]}. Leere Liste, wenn die neuen Sätze nichts davon enthalten."""

ANTWORT_SYSTEM = """\
Der Moderationsassistent Nestor hat die Runde eben zu diesen festgehaltenen Artefakten gefragt (Nummer, Felder,
was fehlt). Danach kommt, was jemand gesagt hat. Trag nur ein, was ausdrücklich gesagt wurde: „Sofie, bis Freitag“
→ wer und bis; „mach ich“ → wer ist der Sprecher; „ja, so festhalten“ bei einer Entscheidung → status "endgueltig".
Sagt die Runde, die Nachfrage sei nicht nötig oder es bleibe offen („brauchen wir nicht“, „lassen wir so“, „nein“),
gehört die Nummer in abgelehnt. Ist der Satz gar keine Antwort darauf, gib leere Listen zurück.
Antworte nur mit JSON: {"eintraege": [{"nummer": 1, "was": null, "wer": "…", "bis": "…", "status": null,
"reaktion": null}], "abgelehnt": []}"""


def _artefakte_text(liste: list[Artefakt], n: int = 30) -> str:
    return "\n".join(a.kurz() for a in liste[-n:]) or "(noch keine)"


def nachricht(meeting, liste: list[Artefakt], neu: list, kontext: list) -> str:
    agenda = "\n".join(f"{i + 1}. {p.titel}" + (f" – {p.ziel}" if p.ziel else "") for i, p in enumerate(meeting.agenda))
    zeile = lambda s: f"[{mmss(s.start)}] {s.sprecher}: {s.text}"  # noqa: E731
    return (f"Meeting: {meeting.titel or '-'} · Ziel: {meeting.ziel or '-'}\nAgenda:\n{agenda or '(keine)'}\n\n"
            f"Schon festgehalten:\n{_artefakte_text(liste)}\n\n"
            + (f"Kontext (schon ausgewertet):\n" + "\n".join(zeile(s) for s in kontext) + "\n\n" if kontext else "")
            + "NEUE Sätze:\n" + "\n".join(zeile(s) for s in neu))


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
            "konfidenz": konf, "zeit": sekunden(e.get("zeit")), "zitat": _text(e.get("zitat"), 140)}


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


def nachfrage_text(punkt_titel: str | None, fragen: list[Artefakt], weitere: int = 0) -> str:
    kopf = f"Kurz zu „{punkt_titel}“: " if punkt_titel else "Kurz noch: "
    text = kopf + " ".join(frage_zu(a) for a in fragen)
    if weitere:
        text += f" {'Eine weitere Lücke steht' if weitere == 1 else f'{weitere} weitere Lücken stehen'} im Dashboard."
    return text


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
@dataclass
class Rueckfrage:
    """Offene Frage von Nestor im Nestor-Feld (mit Knöpfen) – Fünf-Minuten-Frage oder Nachfrage beim Punktwechsel."""
    art: str             # fuenf_minuten | nachfrage
    text: str
    ids: list[int] = field(default_factory=list)
    seit: float = 0.0
    bis: float = 0.0     # so lange gilt ein Satz ohne Namen als Antwort


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
        self.rueckfrage: Rueckfrage | None = None
        self.fuenf_gefragt = False
        self.verlauf: list[dict] = []  # Nachfragen, Antworten, Ablehnungen (ohne Inhalte der Sätze) für den Bericht

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

    def uebernehmen(self, e: dict, quelle_zeit: float, saetze: list | None = None) -> Artefakt | None:
        """Ein normalisierter Eintrag aus der Erkennung: neues Artefakt oder Ergänzung eines bestehenden."""
        m = self.coach.meeting if self.coach else None
        a = self.holen(e["nummer"]) if e.get("nummer") else None
        if a is None and e.get("typ") and e.get("was"):
            a = next((x for x in self.liste if x.typ == e["typ"] and aehnlich(x.was, e["was"])), None)
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
                         konfidenz=konf, zeit=zeit, zitat=e.get("zitat") or (quelle.text[:140] if quelle else ""),
                         sprecher=quelle.sprecher if quelle is not None and quelle.start == zeit else None,
                         punkt=punkt_an(m, zeit) if m is not None else None)
        if a.typ == "entscheidung" and a.status is None:
            a.status = "vorschlag"
        return a

    def _ergaenzen(self, a: Artefakt, e: dict) -> None:
        """Neue Felder eintragen. Was die Runde selbst gesetzt hat (Stimme, Klick), überschreibt die Erkennung nicht."""
        geaendert = False
        for k in ("wer", "bis", "status", "reaktion", "was"):
            v = e.get(k)
            if not v or v == getattr(a, k):
                continue
            if a.herkunft != "erkannt" and getattr(a, k):
                continue
            if k == "was" and getattr(a, k):
                continue  # der Wortlaut bleibt, sonst springt die Anzeige
            if k == "status" and a.status == "endgueltig" and v == "vorschlag":
                continue
            setattr(a, k, v)
            geaendert = True
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

    def verwerfen(self, seit: float) -> None:
        """Knopfdruck „verwerfen“: was in dem Zeitraum gesagt wurde, fliegt raus; das Transkript wird dort neu gelesen."""
        self.liste = [a for a in self.liste if a.zeit < seit or a.herkunft == "hand"]
        self.bis = min(self.bis, seit)
        self.rueckfrage = None
        self.ableiten()

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
        r = self.rueckfrage
        return {"liste": [a.bild() for a in self.liste],
                "luecken": sum(1 for a in self.liste if a.luecken() and not a.abgelehnt),
                "laeuft": self.laeuft,
                "rueckfrage": ({"art": r.art, "text": r.text, "ids": r.ids, "seit": round(r.seit, 1)} if r else None)}

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

    # --- Erkennung im Lauf -----------------------------------------------------------------------------------
    def _neue_saetze(self) -> list:
        return [s for s in self.coach.meeting.transkript if s.text and s.ende > self.bis]

    def takt(self) -> None:
        """Vom Coach-Takt: genug neue Sprache → ein Lauf im Hintergrund; Fünf-Minuten-Frage; Antwortfenster."""
        c = self.coach
        m = c.meeting
        if not m.laeuft:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # Takt ohne Ereignisschleife (Tests): keine Hintergrundaufgaben
        if self.rueckfrage and m.jetzt() > self.rueckfrage.bis + 90:
            self.rueckfrage = None  # unbeantwortet: Pop-up verschwindet nach einer Weile von selbst
        if not c.knopfdruck and c._client is not None and not self.laeuft:
            neu = self._neue_saetze()
            sprache = sum(s.dauer for s in neu)
            from .config import EINST

            if sprache >= SPRACHE_SEKUNDEN.get(EINST.stufe, 60.0) or (sprache >= MIN_SPRACHE
                                               and m.jetzt() - self.letzter_lauf >= SPAETESTENS_SEKUNDEN):
                from .pipeline import hintergrund

                self.laeuft = True
                hintergrund(self.erkennen())
        self._fuenf_pruefen()

    async def erkennen(self, bis: float | None = None) -> int:
        """Alle noch nicht ausgewerteten Sätze auswerten (in Stücken). Liefert die Zahl neuer/ergänzter Artefakte."""
        from .config import EINST
        from .pipeline import fehlertext, nutzung_loggen

        c = self.coach
        self.laeuft = True
        n = 0
        try:
            async with self.sperre:
                while True:
                    neu = [s for s in self._neue_saetze() if bis is None or s.start <= bis]
                    if not neu or c._client is None:
                        break
                    stueck, zeichen = [], 0
                    for s in neu:
                        if stueck and zeichen + len(s.text) > MAX_ZEICHEN:
                            break
                        stueck.append(s)
                        zeichen += len(s.text) + 20
                    kontext, dauer = [], 0.0
                    for s in reversed([x for x in c.meeting.transkript if x.text and x.ende <= self.bis]):
                        if dauer >= KONTEXT_SEKUNDEN:
                            break
                        kontext.insert(0, s)
                        dauer += s.dauer
                    try:
                        roh, nutzung = await _json_aufruf(c._client, EINST.analyse_modell, SYSTEM,
                                                          nachricht(c.meeting, self.liste, stueck, kontext),
                                                          EINST.analyse_aufwand)
                    except Exception as e:  # noqa: BLE001 – nicht abstürzen; beim nächsten Lauf noch einmal
                        log.warning("Artefakt-Erkennung fehlgeschlagen: %s", fehlertext(e))
                        break
                    nutzung_loggen({"art": "artefakte", "modell": EINST.analyse_modell, **nutzung})
                    for e in roh.get("artefakte") or []:
                        e = normalisieren(e)
                        if e and self.uebernehmen(e, stueck[0].start, stueck):
                            n += 1
                    self.bis = max(self.bis, max(s.ende for s in stueck))
                    self.letzter_lauf = c.meeting.jetzt()
                    c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "artefakte", "saetze": len(stueck),
                                        "anzahl": len(self.liste)})
        finally:
            self.laeuft = False
            self.ableiten()
            await c.melden()
        return n

    # --- Prüfung beim Punktwechsel (Regel 10) ---------------------------------------------------------------
    async def punkt_abgeschlossen(self, i: int, fragen: bool = True) -> list[Artefakt]:
        """Restliche Sätze auswerten; mit Regel „Ergebnisse festhalten“ eine gebündelte Nachfrage – bei
        Vollständigkeit Schweigen. Liefert die Artefakte, nach denen gefragt wurde."""
        c = self.coach
        m = c.meeting
        if c._client is None or c.knopfdruck:
            return []
        await self.erkennen()
        if not fragen or "ergebnisse" not in m.regel_ids or not m.laeuft:
            return []
        alle = [a for a in self.luecken_liste(n=99, punkt=i) if not a.nachgefragt]
        if not alle:
            return []
        fragen_jetzt = alle[:MAX_NACHFRAGEN]
        for a in alle:
            a.nachgefragt = True  # je Artefakt nur einmal, auch die im Dashboard gezeigten
        titel = m.agenda[i].titel if 0 <= i < len(m.agenda) else None
        text = nachfrage_text(titel, fragen_jetzt, len(alle) - len(fragen_jetzt))
        await self._fragen("nachfrage", text, [a.id for a in alle])
        c.protokoll.append({"zeit": m.jetzt(), "art": "artefakt_nachfrage", "punkt": i,
                            "ids": [a.id for a in alle], "text": text})
        return fragen_jetzt

    async def _fragen(self, art: str, text: str, ids: list[int]) -> None:
        """Rückfrage ins Nestor-Feld und gesprochen; danach gilt ein Satz ohne Namen eine Weile als Antwort."""
        c = self.coach
        jetzt = c.meeting.jetzt()
        self.rueckfrage = Rueckfrage(art, text, ids, jetzt, jetzt + ANTWORT_SEKUNDEN)
        self.verlauf.append({"zeit": round(jetzt, 1), "art": art, "ids": ids})
        await c.melden()
        dauer = await c.assistent.sagen(text)
        if self.rueckfrage and self.rueckfrage.text == text:
            self.rueckfrage.bis = c.meeting.jetzt() + ANTWORT_SEKUNDEN + (dauer or 0)
        await c.melden()

    # --- Fünf Minuten vor Schluss --------------------------------------------------------------------------
    def geplantes_ende(self) -> float | None:
        m = self.coach.meeting
        geplant = sum(p.minuten for p in m.agenda) * 60
        return geplant if geplant > 0 else None

    def _fuenf_pruefen(self) -> None:
        """Immer, auch ohne Regel 10: 5 min vor dem geplanten Ende (bei kurzen Meetings zur Hälfte)."""
        ende = self.geplantes_ende()
        m = self.coach.meeting
        if self.fuenf_gefragt or ende is None or not m.laeuft:
            return
        if m.jetzt() >= max(ende - FUENF_MINUTEN, ende / 2):
            from .pipeline import hintergrund

            self.fuenf_gefragt = True
            hintergrund(self.fuenf_minuten_fragen())

    async def fuenf_minuten_fragen(self) -> None:
        c = self.coach
        text = "Noch fünf Minuten. Soll ich zusammenfassen und die letzten Aufgaben verteilen?"
        rest = (self.geplantes_ende() or 0) - c.meeting.jetzt()
        if rest < FUENF_MINUTEN - 30:
            text = f"Noch etwa {max(1, round(rest / 60))} Minuten. Soll ich zusammenfassen und die letzten Aufgaben verteilen?"
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "fuenf_minuten"})
        if c.knopfdruck:
            # Nur auf Knopfdruck: Nestor spricht nicht – das Pop-up allein, Ja wirkt wie der Protokoll-Knopf
            self.rueckfrage = Rueckfrage("fuenf_minuten", text, [], c.meeting.jetzt(), c.meeting.jetzt() + 120)
            await c.melden()
            return
        await self._fragen("fuenf_minuten", text, [])

    async def zusammenfassen(self) -> str:
        """Bei Ja: Zusammenfassung plus höchstens drei Lücken in der festgelegten Reihenfolge – gesprochen und als
        Karte. Aus den Artefakten gebaut, nicht frei formuliert: nichts kommt dazu, was nicht festgehalten ist."""
        c = self.coach
        self.rueckfrage = None
        if c.knopfdruck:
            from . import knopfdruck

            try:
                knopfdruck.reservieren(c, "protokoll")
                await knopfdruck.ausfuehren(c, "protokoll")
            except knopfdruck.KnopfFehler as e:
                log.info("Zusammenfassen auf Knopfdruck nicht möglich: %s", e)
        else:
            await self.erkennen()
        text, karte, luecken = self.zusammenfassung()
        c._karte_ablegen(karte)
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "zusammenfassung", "luecken": [a.id for a in luecken]})
        if not c.knopfdruck:
            for a in luecken:
                a.nachgefragt = True
            jetzt = c.meeting.jetzt()
            if luecken:
                self.rueckfrage = Rueckfrage("nachfrage", " ".join(frage_zu(a) for a in luecken),
                                             [a.id for a in luecken], jetzt, jetzt + ANTWORT_SEKUNDEN)
            await c.melden()
            dauer = await c.assistent.sagen(text)
            if self.rueckfrage and luecken:
                self.rueckfrage.bis = c.meeting.jetzt() + ANTWORT_SEKUNDEN + (dauer or 0)
        await c.melden()
        return text

    def zusammenfassung(self) -> tuple[str, dict, list[Artefakt]]:
        m = self.coach.meeting
        beschl = [a for a in self.liste if a.typ == "entscheidung" and a.status != "vorschlag"]
        aufgaben = [a for a in self.liste if a.typ == "aufgabe"]
        luecken = self.luecken_liste(3)
        teile = ["Kurz zusammengefasst:"]
        if beschl:
            teile.append("Entschieden habt ihr " + _liste_sprechen([a.was.rstrip(".") for a in beschl[-3:]]) + ".")
        if aufgaben:
            fertig = sum(1 for a in aufgaben if not a.luecken())
            teile.append(f"{len(aufgaben)} Aufgabe{'n' if len(aufgaben) > 1 else ''} notiert, "
                         f"{fertig} davon mit Wer und Termin.")
        if not beschl and not aufgaben:
            teile = ["Bisher habe ich keine Entscheidung und keine Aufgabe notiert."]
        if luecken:
            teile.append("Offen sind noch: " + " ".join(frage_zu(a) for a in luecken))
            teile.append("Sagt einfach, wer was übernimmt – ich trag's ein.")
        text = " ".join(teile)
        punkte = [f"Entschieden: {a.was}" for a in beschl[-4:]]
        punkte += [f"Aufgabe: {a.was} – {a.wer if a.wer and not kollektiv(a.wer) else 'wer?'} · "
                   f"{('bis ' + a.bis) if a.bis else 'bis wann?'}" for a in aufgaben[-5:]]
        if luecken:  # die Lücken selbst stehen in der Rückfrage darüber – hier nicht noch einmal (Ticket #21)
            n = sum(1 for a in self.liste if a.luecken() and not a.abgelehnt)
            punkte.append(f"{n} Lücke{'n' if n > 1 else ''} offen – rot markiert unter „Festgehalten“")
        karte = {"art": "zusammenfassung", "frage": "Zusammenfassen", "titel": f"Zusammenfassung · Stand {mmss(m.jetzt())}",
                 "punkte": punkte[:10] or ["Noch nichts festgehalten."]}
        return text, karte, luecken

    # --- Antworten der Runde ---------------------------------------------------------------------------------
    def wartet_auf_antwort(self, t: float) -> bool:
        r = self.rueckfrage
        return r is not None and r.seit <= t <= r.bis

    async def satz(self, seg) -> bool:
        """Ein fertiger Satz, während Nestor auf eine Antwort wartet (ohne Namen). True = als Antwort verarbeitet."""
        from .assistent import angesprochen

        r = self.rueckfrage
        if r is None or not self.wartet_auf_antwort(seg.ende) or angesprochen(seg.text):
            return False
        if r.art == "fuenf_minuten":
            if JA_RE.search(seg.text):
                self.verlauf.append({"zeit": round(seg.ende, 1), "art": "fuenf_minuten_ja", "durch": "stimme"})
                await self.zusammenfassen()
                return True
            if NEIN_RE.search(seg.text):
                self.verlauf.append({"zeit": round(seg.ende, 1), "art": "fuenf_minuten_nein", "durch": "stimme"})
                self.rueckfrage = None
                await self.coach.melden()
                return True
            return False
        return await self.antwort_deuten(seg.text, seg.sprecher)

    async def antwort_deuten(self, text: str, sprecher: str | None = None) -> bool:
        """Antwort auf eine Nachfrage: ein kleiner Aufruf trägt Wer/Bis ein oder merkt sich die Ablehnung."""
        from .config import EINST
        from .pipeline import fehlertext, nutzung_loggen

        c, r = self.coach, self.rueckfrage
        gefragt = [a for a in (self.holen(i) for i in (r.ids if r else [])) if a is not None]
        if not gefragt or c._client is None:
            return False
        uebrige = [a for a in self.luecken_liste(n=12) if a not in gefragt][:12 - len(gefragt)]
        zeile = lambda a: a.kurz() + " · fehlt: " + ", ".join(FELD_NAME[x] for x in a.luecken())  # noqa: E731
        nutzer = ("Gefragt:\n" + "\n".join(zeile(a) for a in gefragt)
                  + ("\n\nWeitere Lücken (falls die Antwort eher dazu passt):\n" + "\n".join(zeile(a) for a in uebrige)
                     if uebrige else "")
                  + f"\n\nAntwort von {sprecher or 'jemandem'}: {text}")
        try:
            roh, nutzung = await _json_aufruf(c._client, EINST.analyse_modell, ANTWORT_SYSTEM, nutzer,
                                              EINST.analyse_aufwand)
        except Exception as e:  # noqa: BLE001
            log.warning("Antwort auf Nachfrage nicht gedeutet: %s", fehlertext(e))
            return False
        nutzung_loggen({"art": "artefakte", "zweck": "antwort", "modell": EINST.analyse_modell, **nutzung})
        ids = {a.id for a in gefragt + uebrige}
        bestaetigt = []
        for e in roh.get("eintraege") or []:
            e = normalisieren({**e, "typ": e.get("typ") or "aufgabe"}) if isinstance(e, dict) else None
            if not e or e["nummer"] not in ids:
                continue
            felder = {k: e[k] for k in ("wer", "bis", "status", "reaktion") if e.get(k)}
            if not felder:
                continue
            a = self.bearbeiten(e["nummer"], felder, herkunft="stimme")
            if a:
                bestaetigt.append((a, felder))
        abgelehnt = []
        for nr in roh.get("abgelehnt") or []:
            try:
                a = self.holen(int(nr))
            except (TypeError, ValueError):
                a = None
            if a is not None and a.id in ids:
                a.abgelehnt = True
                abgelehnt.append(a.id)
        if not bestaetigt and not abgelehnt:
            return False
        self.verlauf.append({"zeit": round(c.meeting.jetzt(), 1), "art": "antwort", "ids": [a.id for a, _ in bestaetigt],
                             "abgelehnt": abgelehnt})
        offen = [a.id for a in gefragt if a.luecken() and not a.abgelehnt]
        if r is not None:
            if offen:
                r.ids = offen
                r.bis = c.meeting.jetzt() + ANTWORT_SEKUNDEN
            else:
                self.rueckfrage = None
        self.ableiten()
        await c.melden()
        satz = " ".join(bestaetigung_text(a, f) for a, f in bestaetigt) or "Okay, frag ich nicht mehr."
        await c.assistent.sagen(satz)
        return True

    def ablehnen(self, nr: int) -> bool:
        """Knopf „nicht nötig“ an einer Lücke: nie wieder nachfragen."""
        a = self.holen(nr)
        if a is None:
            return False
        a.abgelehnt = True
        if self.rueckfrage and nr in self.rueckfrage.ids:
            self.rueckfrage.ids = [i for i in self.rueckfrage.ids if i != nr]
            if not self.rueckfrage.ids and self.rueckfrage.art == "nachfrage":
                self.rueckfrage = None
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
        if self.rueckfrage and a.id in self.rueckfrage.ids and not a.luecken():
            self.rueckfrage.ids = [i for i in self.rueckfrage.ids if i != a.id]
            if not self.rueckfrage.ids:
                self.rueckfrage = None
        return a, bestaetigung_text(a, felder)


JA_RE = re.compile(r"^\W*(ja|jo|jep|gerne?|bitte|klar|okay|ok|mach (das|mal)|fass (zusammen|mal))\b", re.IGNORECASE)
NEIN_RE = re.compile(r"^\W*(nein|nee|ne|nö|danke,? nein|lass mal|nicht nötig|brauchen wir nicht)\b", re.IGNORECASE)


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
