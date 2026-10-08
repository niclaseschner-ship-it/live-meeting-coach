"""Sprachassistent Nestor (docs/sprachassistent.md, Ticket #27: Antwortbogen).

Grundregel: Nestor spricht nur in einem **Antwortbogen**, den die Runde ausgelöst hat – Ausnahme ist die Begrüßung.
Was er von sich aus merkt, kommt still (Band oben, Karte im Verlauf).

- **Begrüßung** mit Einwilligung („ich höre mit“, Nein jetzt oder später als „Nestor, nein“), endet mit der Bitte
  um die Namen; danach ordnet Nestor still zu („Erkannt: …“ im Band).
- **Auslöser** (coach/bogen.py): Premium wie ein Telefon – „Nestor, …“ im Live-Text, danach eine Nachfrage ohne
  Namen (nur der erste Satz, und nur wenn er an Nestor gerichtet ist). Basis wie ein Funkgerät – Sprechtaste
  halten, sprechen, loslassen; auf den Namen reagiert Basis nicht. In beiden: Knöpfe und getippte Fragen.
- **Ein Bogen zur Zeit:** sofort eine Floskel, dann die Karte, dann ein bis zwei Sätze zu dem, was auffällt. Knöpfe
  sind währenddessen gesperrt; ein neuer Zuruf bzw. die Sprechtaste unterbricht die Stimme des laufenden Bogens –
  seine Karte kommt trotzdem still in den Verlauf.
- **Lange Aufträge** (Bild, Recherche) sind kein Bogen: „Nehme ich mit …“, das Ergebnis kommt still in den
  Verlauf. Höchstens zwei (einer läuft, einer wartet), ein dritter wird abgewehrt.
- Eigene Sprache filtert der Coach aus Transkript und Sprecherspur (Zeitfenster, in denen er spricht),
  damit er sich nicht selbst zuhört oder als Person zählt.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from dataclasses import dataclass, field

from . import bestaetigung as B
from . import bogen as BG
from .analyse import mmss
from .config import EINST
from .regeln import NACH_ID

log = logging.getLogger("coach.assistent")

RATE = 24000  # PCM der Sprachausgabe: 24 kHz, 16 bit, mono
NAME_RE = re.compile(rf"\b(?:{EINST.assistent_muster})\b", re.IGNORECASE)
NEIN_RE = re.compile(r"\bnein\b|nicht einverstanden|(möchte|will|wollen|möchten) (ich |wir )?(das )?nicht", re.IGNORECASE)
SATZENDE_RE = re.compile(r"(?<=[.!?])\s+")
AKTION_RE = re.compile(r"^\s*AKTION:\s*(\w+)\s*(.*)$", re.IGNORECASE)
VORLAUF_SEKUNDEN = 0.4  # bis der Ton im Browser wirklich zu hören ist
NACHLAUF_SEKUNDEN = 0.8  # Hall und Verzögerung nach dem letzten Ton

SYSTEM = """\
Du bist {name}, der Moderationsassistent eines Präsenzmeetings. Du hörst über ein Raummikrofon zu und
antwortest nur, wenn man dich anspricht. Deine Antwort wird vorgelesen; Einzelheiten erscheinen danach als Karte.

So antwortest du:
- Gesprochene Sprache: kurz – ein Satz, höchstens zwei. Natürlich, freundlich, auf Deutsch, per „ihr“, nie „Sie“.
  Keine Aufzählungszeichen, kein Markdown, keine Klammern. Das Wichtigste zuerst.
- Neutral: Du bewertest keine Personen, ergreifst keine Partei und erfindest nichts. Was nicht im Kontext
  steht, weißt du nicht – dann sag das. Personen heißen im Transkript „Person N“; nenne sie nicht so,
  sondern sprich von „jemandem“ oder der Gruppe.
- Agendapunkte nennst du mit der Nummer und dem Titel aus der Agenda unten, nicht mit Nummern, die im
  Gespräch fallen – sprechbar geschrieben: „Punkt zwei, Budget“, nicht „2. Budget“.
- Bei „wo stehen wir“, „fass zusammen“ oder „was kommt als Nächstes“: Stand, Festgehaltenes, Offenes –
  aus Agenda, Ergebnissen und Transkript, ohne etwas dazuzuerfinden. „Festgehalten“ oder „entschieden“ sagst
  du nur, wenn die Gruppe es ausdrücklich so beschlossen hat; ein Vorschlag bleibt ein Vorschlag.

Erste Zeile deiner Antwort ist IMMER genau eine Aktion, danach folgt der gesprochene Text:
AKTION: keine
AKTION: bild <fokus>      – visuelle Übersicht zeichnen lassen; <fokus> in eigenen Worten, z. B.
                            „gesamt“, „Agendapunkt 2“, „was noch ansteht“, „wo Entscheidungen fehlen“.
                            Nicht, wenn die Runde nur ein vorhandenes Bild erklärt haben möchte.
AKTION: weiter <nummer>   – zum Agendapunkt mit dieser Nummer wechseln (oder „weiter naechster“),
                            nur wenn die Gruppe das ausdrücklich will.
AKTION: recherche <frage> – im Internet recherchieren („gib uns einen Überblick zu …“, aktuelle Fakten).
                            Das Ergebnis erscheint später still als Karte mit Quellen.
                            Frage ohne Namen und ohne Interna aus dem Meeting formulieren.
AKTION: folie             – das letzte Rechercheergebnis mit Quellen als Folie ins Dashboard stellen,
                            wenn die Gruppe das möchte („ja, mach eine Folie“).
AKTION: karte <art>       – eine Karte zeigen, wenn die Runde genau das möchte: zusammenfassen (Zusammenfassung),
                            fehlt (was noch fehlt), stand (wo stehen wir), festgehalten (Protokoll, Liste).
AKTION: pause             – die Gruppe möchte, dass du nicht mehr zuhörst. Sag, dass man dich über den
                            Knopf im Dashboard wieder einschaltet.
AKTION: eintragen <nummer>; wer=…; bis=…     – Aufgabe, Entscheidung, offenen Punkt oder Risiko ergänzen, wenn
AKTION: eintragen neu <typ>; was=…; wer=…; bis=…   die Gruppe es dir sagt („Sofie übernimmt die Statusseite bis
                            Freitag“). Nummer aus „Festgehaltene Artefakte“ unten; typ ist aufgabe, entscheidung,
                            offen oder risiko; weitere Felder: status=endgueltig|vorlaeufig, reaktion=….

Beispiel:
AKTION: keine
Ihr seid bei Punkt zwei, dem Budget. Entschieden ist noch nichts, offen ist die Frage nach dem Puffer.
"""


BILD_ZEILE = "                            Nicht, wenn die Runde nur ein vorhandenes Bild erklärt haben möchte.\n"
# Nestor Basis (und Überblick als Text): „AKTION: bild“ zeigt den Überblick als Text – er steht nach wenigen Sekunden
BILD_ZEILE_TEXT = "                            Er erscheint nach wenigen Sekunden im Verlauf.\n"
BILD_TEXT = ("Übersicht über das Meeting (Entschiedenes, Offenes,\n"
             "                            Aufgaben) ins Dashboard stellen – auch bei „visuelle Übersicht“, „Bild“ oder\n"
             "                            „zeig uns die Übersicht“")
FOLIE_ZEILE = "                            wenn die Gruppe das möchte („ja, mach eine Folie“).\n"
FOLIE_ZEILE_KLAR = ("                            nur wenn ausdrücklich eine Folie gewünscht ist („ja, mach eine Folie“).\n"
                    "                            Eine Übersicht über das Meeting ist keine Folie.\n")
UEBERLAST = "Ich komme gerade nicht durch, versucht es gleich nochmal."
FEHLER = "Entschuldigung, das hat gerade nicht geklappt."
# Aktionen, nach denen das System spricht (Floskel bzw. Karten-Bogen) – der Text des Modells entfällt dann
STILLE_AKTIONEN = ("bild", "recherche", "folie", "karte", "eintragen")
# Ticket #21/#27: Bestätigung und Wartezeit spricht das System selbst (coach/bestaetigung.py)
BESTAETIGUNG_HINWEIS = """
Eine kurze Bestätigung („Bin dran“) hat das System schon gesprochen, bevor deine Antwort kommt. Fang deshalb nicht
mit „Okay“, „Moment“, „Klar“ oder „Gern“ an, sondern direkt mit dem Inhalt.
"""
STILLE_HINWEIS = """
Bei bild, recherche, folie, karte und eintragen spricht das System selbst – schreib nach der Aktionszeile dann nichts
mehr.
"""


def system_text() -> str:
    """Systemanweisung für die gewählte Stufe: in Basis entsteht auf „AKTION: bild“ der Überblick als Text."""
    s = SYSTEM.format(name=EINST.assistent_name)
    if EINST.bild_anbieter == "text":
        s = s.replace("visuelle Übersicht zeichnen lassen", BILD_TEXT).replace(BILD_ZEILE, BILD_ZEILE_TEXT)
    s = s.replace(FOLIE_ZEILE, FOLIE_ZEILE_KLAR)
    return s + (BESTAETIGUNG_HINWEIS if EINST.bestaetigung else "") + STILLE_HINWEIS


def aktion_pruefen(aktion: dict | None, frage: str) -> dict | None:
    """Folie und Übersicht nicht verwechseln: Mistral machte aus „Nestor, mach uns die visuelle Übersicht“ nach einer
    Recherche eine Folie (Cloud-Lauf 08.10., Ticket #15). Wer „Übersicht“/„Bild“ sagt und keine Folie, meint das
    Meeting – dann die Übersicht (bzw. das Live-Bild)."""
    if aktion and aktion["typ"] == "folie" and not re.search(r"folie", frage, re.IGNORECASE) \
            and re.search(r"übersicht|uebersicht|bild|aufmal|visuell", frage, re.IGNORECASE):
        return {"typ": "bild", "fokus": "gesamt"}
    return aktion


def _woerter(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3]


def echo(gehoert: str, gesagt: str) -> bool:
    """Klingt der gehörte Satz nach dem, was Nestor gesagt hat? Mindestens die Hälfte seiner Wörter (ab drei
    Buchstaben) kommt in Nestors Text vor. Ein Satz ohne solche Wörter („Ja.“) zählt als Echo – zu wenig, um ihn
    gegen Nestors Stimme zu behaupten."""
    woerter = _woerter(gehoert)
    if not woerter:
        return True
    bekannt = set(_woerter(gesagt))
    return sum(w in bekannt for w in woerter) >= 0.5 * len(woerter)


def angesprochen(text: str) -> bool:
    return bool(NAME_RE.search(text))


def einwand(text: str) -> bool:
    return bool(NEIN_RE.search(text))


def frage_aus(text: str) -> str:
    """Den Namen entfernen; was bleibt, ist die Frage (Anrede am Anfang oder am Ende)."""
    rest = NAME_RE.sub(" ", text)
    rest = re.sub(r"^\W*(hey|hallo|ok|okay|du)?\W*", "", rest, flags=re.IGNORECASE)
    rest = re.sub(r"[\s,]+([?.!])", r"\1", rest)  # „Was kommt als Nächstes, ?“ → „…Nächstes?“
    rest = re.sub(r",\s*,", ",", rest)  # „Danke, , wir …“ → „Danke, wir …“
    return re.sub(r"\s+", " ", rest).strip(" ,")


def aktion_lesen(zeile: str) -> dict | None:
    m = AKTION_RE.match(zeile)
    if not m:
        return None
    typ, rest = m[1].lower(), m[2].strip()
    if typ == "bild":
        return {"typ": "bild", "fokus": rest or "gesamt"}
    if typ == "weiter":
        return {"typ": "weiter", "ziel": rest.lower()}
    if typ == "pause":
        return {"typ": "pause"}
    if typ == "recherche":
        return {"typ": "recherche", "frage": rest}
    if typ == "folie":
        return {"typ": "folie"}
    if typ == "karte":
        wort = rest.lower().split()[0] if rest else ""
        art = {"zusammenfassung": "zusammenfassen", "protokoll": "festgehalten", "liste": "festgehalten",
               "luecken": "fehlt", "lücken": "fehlt"}.get(wort, wort)
        return {"typ": "karte", "art": art} if art in ("zusammenfassen", "fehlt", "stand", "festgehalten") else None
    if typ == "eintragen":  # Ticket #26: Lücke per Stimme schließen (Basis/Text-Weg)
        from .artefakte import aktion_lesen as eintrag_lesen

        return eintrag_lesen(rest)
    return None


def saetze_teilen(puffer: str) -> tuple[list[str], str]:
    """Fertige Sätze aus dem Puffer lösen; der unfertige Rest bleibt stehen."""
    teile = SATZENDE_RE.split(puffer)
    return [t.strip() for t in teile[:-1] if t.strip()], teile[-1]


def agenda_bitte(meeting) -> str:
    """Den Agendawechsel ohne Ansage erkennt Nestor nur unsicher (Lastenheft 4.3) – deshalb gleich zu Beginn
    darum bitten, ihn anzusagen oder anzuklicken. Bei nur einem Punkt gibt es nichts zu wechseln."""
    if len(meeting.agenda) < 2:
        return ""
    # Das Zusammenfassen läuft über die normale Ansprache („Nestor, fass zusammen“) – kein eigener Ablauf nötig.
    return " Wenn ihr zum nächsten Punkt geht, sagt kurz Bescheid oder klickt ihn an – auf Wunsch fasse ich vorher zusammen."


def _weitere_regeln_satz(meeting) -> str:
    """Freitext-Regeln (coach/zustand.py: Meeting.regeln, Oberfläche-Kachel „Weitere Regeln“, Ticket #10) nach
    den gewählten Katalog-Regeln: höchstens drei wörtlich, sonst zusammengefasst. Nestor liest sie nur vor,
    er prüft sie nicht – das steht auch so auf der Kachel."""
    weitere = [r.strip() for r in meeting.regeln if r.strip()]
    if not weitere:
        return ""
    if len(weitere) <= 3:
        liste = ", ".join(weitere[:-1]) + (" und " if len(weitere) > 1 else "") + weitere[-1]
    else:
        rest = len(weitere) - 3
        liste = f"{', '.join(weitere[:3])} und {rest} weitere, die ihr auf dem Bildschirm seht"
    return f" Außerdem habt ihr euch vorgenommen: {liste}."


def agenda_kommentar(meeting) -> str:
    """Ein menschlicher Halbsatz zur Agenda – zeigt, dass Nestor das Meeting kennt (Niclas, 07.10.: „Aha-Moment“)."""
    punkte = meeting.agenda
    if not punkte:
        return ""
    minuten = round(sum(p.minuten for p in punkte))
    je_punkt = minuten / len(punkte)
    zahl = {1: "Ein Punkt", 2: "Zwei Punkte", 3: "Drei Punkte", 4: "Vier Punkte", 5: "Fünf Punkte",
            6: "Sechs Punkte"}.get(len(punkte), f"{len(punkte)} Punkte")
    if je_punkt < 10:
        wertung = "das ist sportlich"
    elif je_punkt >= 20:
        wertung = "da habt ihr euch Zeit genommen"
    else:
        wertung = "das passt gut"
    return f" {zahl} in {minuten} Minuten – {wertung}."


NAMEN_BITTE = "Wenn ihr mögt, sagt kurz eure Namen, dann schreibe ich das Protokoll mit Namen."


def wie_text(basis: bool) -> str:
    """Wie man mit Nestor spricht – Telefon (Premium) oder Funkgerät (Basis), Ticket #27."""
    name = EINST.assistent_name
    if basis:
        return ("Ich funktioniere wie ein Funkgerät: Taste halten, sprechen, loslassen – ich rede dann aus. Die Taste "
                "ist auf dem Bildschirm und am Handy, am Laptop geht auch die Leertaste.")
    return (f"Ich funktioniere wie ein Telefon: Sagt „{name}“ und eure Frage. Direkt danach könnt ihr ohne Namen "
            "nachfragen, und wenn ich zu viel rede, redet einfach rein.")


def begruessungstext(meeting, basis: bool | None = None, namen: bool | None = None) -> tuple[str, str]:
    """(Begrüßung mit Einwilligung, Rest der Begrüßung).

    Feste Fassung: Rückfall der freien Begrüßung (coach/begruessung.py, Ticket #23) und Standard in Basis. Nestor sagt
    in der Begrüßung alles (Ticket #27) und endet mit der Bitte um die Namen – danach kein Startsatz mehr. Ein Nein ist
    kurz nach der Begrüßung als einfaches „Nein“ möglich und später jederzeit als „Nestor, nein“ (`spaetes_nein`).
    """
    name = EINST.assistent_name
    regeln = [NACH_ID[r].titel.split(" – ")[0] for r in meeting.regel_ids if r in NACH_ID]
    teil_regeln = ""
    if regeln:
        liste = ", ".join(regeln[:-1]) + (" und " if len(regeln) > 1 else "") + regeln[-1]
        teil_regeln = f" Ihr habt euch diese Regeln vorgenommen: {liste}."
    teil_regeln += _weitere_regeln_satz(meeting)
    gruss = (f"Hallo zusammen, ich bin {name} und begleite heute euer Meeting.{teil_regeln} Dafür höre ich mit. "
             f"Wer nicht einverstanden ist, sagt einfach Nein – das geht auch später noch, dann mit meinem Namen: "
             f"„{name}, nein“. Dann lösche ich alles.")
    erster = f" Los geht's mit Punkt eins: {meeting.agenda[0].titel}." if meeting.agenda else " Los geht's."
    if basis is None:
        basis = EINST.stufe == "basis"
    if namen is None:
        namen = EINST.vorstellung_sekunden > 0
    start = f"{wie_text(basis)}{agenda_bitte(meeting)}{agenda_kommentar(meeting)}{erster}"
    if namen:
        start += f" {NAMEN_BITTE}"
    return gruss, start


# Ton für die Begrüßung: locker und zugewandt, nicht vorgelesen. Ob ein Lachen hörbar wird, entscheidet das Modell.
STIL_START = ("Sprich warm, locker und zugewandt auf Deutsch, wie eine sympathische Moderatorin, die sich auf das "
              "Meeting freut – mit einem Lächeln in der Stimme und einem kurzen, leisen Lachen nach dem ersten Satz. "
              "Natürliches Tempo, kleine Pausen zwischen den Gedanken.")


# Spätes Nein: nur der Name und das Nein, sonst nichts – „Nestor, nein, ich meinte Punkt zwei“ darf nicht alles löschen.
SPAETES_NEIN_RE = re.compile(rf"^\W*(?:{EINST.assistent_muster})\W+(?:nein|wir sind nicht einverstanden)\W*$",
                             re.IGNORECASE)


def spaetes_nein(text: str) -> bool:
    return bool(SPAETES_NEIN_RE.match(text))


VORSTELLUNG_RE = re.compile(r"(?i:ich bin|ich heiße|ich heisse|mein name ist|hier ist|hier spricht)\s+(?i:die |der )?"
                     r"([A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?)")
NUR_NAME_RE = re.compile(r"^\W*([A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?)(?:\s+hier)?\W*$")


def name_aus(text: str, bekannte: list[str] | None = None) -> str | None:
    """Vorname aus einer Vorstellung („Ich bin Lea“, „Mein Name ist Jonas“, „Miriam hier“). Stehen Teilnehmende
    in der Einrichtung, gewinnt der dort eingetragene Name, wenn er im Satz vorkommt."""
    for n in bekannte or []:
        vorname = n.split()[0]
        if re.search(r"\b" + re.escape(vorname) + r"\b", text, re.IGNORECASE):
            return n
    m = VORSTELLUNG_RE.search(text) or NUR_NAME_RE.match(text.strip())
    if m and m.group(1).lower() not in {"nestor", "ja", "nein", "okay", "hallo", "danke", "gut"}:
        return m.group(1)
    return None


class BogenBelegt(RuntimeError):
    """Ein Knopf, während schon ein Bogen läuft (Ticket #27: nie zwei parallel; Knöpfe sind dann gesperrt)."""


@dataclass
class Bogen:
    """Ein Auftrag der Runde, eine Antwort: Bestätigung, Karte, ein bis zwei Sätze (Ticket #27)."""
    id: int
    art: str             # frage | stand | zusammenfassen | fehlt | festgehalten | regeln | ueberblick | folie | bild …
    frage: str
    quelle: str          # stimme | taste | getippt | knopf | nachfrage | band
    t0: float            # monotonic: Auslöser
    sprecher: str | None = None
    fokus: str = ""
    abgeloest: bool = False   # durch einen neuen Bogen unterbrochen: still weiterarbeiten, Karte trotzdem ablegen
    task: asyncio.Task | None = None
    vorher: asyncio.Future | None = None  # Stimme des abgelösten Bogens stoppen, bevor dieser spricht
    zusatz: list = field(default_factory=list)
    zeiten: dict = field(default_factory=dict)

    def merken(self, schritt: str) -> None:
        self.zeiten.setdefault(schritt, round(time.monotonic() - self.t0, 2))


class Assistent:
    def __init__(self, coach) -> None:
        self.coach = coach
        self.aktiv = True  # in der Einrichtung abschaltbar
        # bereit | begruessung | einwand | angesprochen | denkt | spricht | pausiert | recherchiert | gespraech | taste
        self.zustand = "bereit"
        self.letzte: dict | None = None  # {frage, antwort, zeit}
        self.verlauf: list[tuple[str, str]] = []  # (Frage, Antwort) für Rückfragen
        self.sprechzeiten: list[tuple[float, float]] = []  # Meetingzeit, in der der Coach spricht
        self.sprechtexte: list[tuple[float, float, str]] = []  # dasselbe mit dem gesprochenen Text (Textweg)
        self.echo_im_abspielen = False  # Testläufe (scripts/cloudtest_lokal.py): eigene Sprache filtern wie live
        self.messung: dict | None = None  # laufende Zeitmessung Auslöser -> erster Ton
        self._angesprochen_bis = -1e9
        # Rückfrage-Fenster (Premium, Ticket #27 Nachtrag C): nur der erste Satz nach dem Bogen zählt
        self._nachfrage_ab = -1e9
        self._nachfrage_bis = -1e9
        self._fragende: str | None = None  # Sprecher, der den letzten Bogen ausgelöst hat (nur ein Plus-Signal)
        self._einwand_bis: float | None = None
        self.vorstellung_bis: float | None = None  # Meetingzeit, bis zu der Namen gesammelt werden
        self._aufgabe: asyncio.Task | None = None  # Begrüßung, „Ja?“, Abbruch-Bestätigung (kein Bogen)
        self._ton_id = 0
        self.gespraech = None  # offene Realtime-Sitzung (coach/gespraech.py)
        self.letzte_aktion: dict | None = None
        self.halten: tuple[float, float] | None = None  # Sprechtaste gehalten: (von, bis) Meetingzeit
        self.letzte_quellen: list[dict] = []
        # Ticket #21/#27: Floskeln, lange Aufträge (Stau 2/3), Text läuft mit
        self.floskeln = B.Floskeln()
        self.auftraege = B.Auftraege()
        self.auftraege.melden = coach.melden
        self.lang_sperre = asyncio.Lock()  # ein langer Auftrag zur Zeit, der zweite wartet
        self._text_neu: dict | None = None  # die nächste Textnachricht beginnt eine neue Äußerung
        self.bogen: Bogen | None = None
        self._bogen_n = 0

    # --- Zustand nach außen ------------------------------------------------
    def schnappschuss(self) -> dict:
        jetzt = self.coach.meeting.jetzt()
        b = self.bogen
        hoert = self._nachfrage_bis if self.nachfrage_moeglich and self._nachfrage_bis > jetzt else None
        return {"aktiv": self.aktiv, "name": EINST.assistent_name, "zustand": self.zustand,
                "letzte": self.letzte, "auftraege": self.auftraege.schnappschuss(),
                "bogen": {"art": b.art, "name": BG.NAMEN.get(b.art, b.art), "quelle": b.quelle} if b else None,
                "hoert_bis": round(hoert, 1) if hoert else None,
                "funkgeraet": self.funkgeraet, "taste": self.halten is not None}

    @property
    def pausiert(self) -> bool:
        return self.zustand == "pausiert"

    @property
    def ansprache_aus(self) -> bool:
        """Modus „Auf Knopfdruck“ (Lastenheft 3): Nestor hört nicht auf seinen Namen und spricht nicht – Fragen
        gehen über die Knopfleiste und kommen als Text-Karte zurück (coach/knopfdruck.py)."""
        return self.coach.modus == "knopfdruck"

    @property
    def funkgeraet(self) -> bool:
        """Nestor Basis (Ticket #27): Sprechtaste statt Name, kein Rückfrage-Fenster."""
        return EINST.stufe == "basis"

    @property
    def nachfrage_moeglich(self) -> bool:
        return not self.funkgeraet and EINST.nachfrage_sekunden > 0

    def spricht_um(self, t: float) -> bool:
        return any(a - 0.2 <= t <= b for a, b in self.sprechzeiten)

    def eigene_sprache(self, start: float, ende: float, text: str | None = None) -> bool:
        """Überwiegend in einem Zeitfenster, in dem der Coach selbst sprach (nur live mit Lautsprecher).

        Mit `text` (fertiger Satz) zusätzlich: nur dann eigene Sprache, wenn der Satz auch nach Nestors Worten klingt.
        Spricht jemand, während Nestor noch redet, ist das kein Echo – im Cloud-Lauf (Ticket #15) gingen so die Ansage
        „Wir gehen jetzt zu Agendapunkt drei“ und zwei Fragen an Nestor verloren, weil Thorsten noch vorlas."""
        if self.coach.simulation_laeuft and not self.echo_im_abspielen:
            return False
        ueber = sum(max(0.0, min(ende, b) - max(start, a)) for a, b in self.sprechzeiten)
        if ueber < 0.5 * max(0.1, ende - start):
            return False
        if text is None:
            return True
        # Was Nestor in diesem Zeitraum gesagt hat (mit Spielraum für den Verzug des Live-Texts)
        gesagt = " ".join(t for a, b, t in self.sprechtexte if a - 2.0 <= ende and start <= b + 2.0)
        if not gesagt:
            return True  # Text unbekannt (Realtime-Gespräch): nach der Zeit entscheiden wie bisher
        return echo(text, gesagt)

    # --- Begrüßung mit Einwilligung ----------------------------------------
    async def begruessen(self) -> None:
        if not self.aktiv or self.coach._client is None or self.ansprache_aus:
            return
        self.zustand = "begruessung"
        await self.coach.melden()
        self.floskeln_vorbereiten()  # Floskeln der Stimme erzeugen, falls sie fehlen (einmal je Stimme)
        self.text_neu(None)
        if await self._begruessen_frei():
            return
        if self.pausiert:
            return  # Nein schon während des Versuchs – nichts mehr sagen außer der Bestätigung
        self.zustand = "begruessung"
        vorstellung = EINST.vorstellung_sekunden > 0
        gruss, start = begruessungstext(self.coach.meeting)
        frei = None
        if EINST.stufe == "basis" and EINST.basis_begruessung_frei:  # Ticket #23: Mistral formuliert, sonst fest
            from .begruessung import basis_formulieren, in_stuecke

            text = await basis_formulieren(self.coach._client, self.coach.meeting, vorstellung)
            frei = in_stuecke(text) if text else None
        await self._sprechen_texte(frei or [gruss], danach="begruessung")
        # Kein Warten auf das Nein: es geht gleich weiter, ein einfaches „Nein“ zählt aber noch eine Weile
        ende = self.sprechzeiten[-1][1] if self.sprechzeiten else self.coach.meeting.jetzt()
        self._einwand_bis = ende + EINST.einwand_sekunden
        if not frei:
            await self._sprechen_texte([start], stil=STIL_START)
        ende = self.sprechzeiten[-1][1] if self.sprechzeiten else self.coach.meeting.jetzt()
        self._einwand_bis = max(self._einwand_bis, ende + EINST.einwand_sekunden)
        if vorstellung:  # Ticket #27: kein Startsatz mehr danach – Nestor ordnet die Namen still zu
            self.vorstellung_bis = ende + EINST.vorstellung_sekunden

    async def _begruessen_frei(self) -> bool:
        """Premium (Ticket #23): Begrüßung frei im Realtime-Gespräch. False = nicht zustande gekommen, dann spricht
        der Aufrufer die feste Fassung. Fehlt im hörbar Gesagten ein Teil der Einwilligung, folgt der feste Nachsatz."""
        if EINST.stufe == "basis" or EINST.begruessung != "frei" or EINST.assistent_modus != "gespraech":
            return False
        from .begruessung import Begruessung, nachsatz, pflicht_fehlt

        vorstellung = EINST.vorstellung_sekunden > 0
        b = Begruessung(self, vorstellung)
        self._einwand_bis = self.coach.meeting.jetzt() + 3600  # ein einfaches „Nein“ zählt während der Begrüßung
        self.gespraech = b
        try:
            await b.starten()
            warten = [asyncio.ensure_future(b.ton_da.wait()), asyncio.ensure_future(b.fertig.wait())]
            _, offen = await asyncio.wait(warten, timeout=EINST.begruessung_frist_ton,
                                          return_when=asyncio.FIRST_COMPLETED)
            for w in offen:
                w.cancel()
            if not b.ton_da.is_set():
                raise TimeoutError("kein Ton")
        except Exception as e:  # noqa: BLE001 – auch Zeitüberschreitung: feste Fassung
            log.warning("Begrüßung frei nicht gestartet (%s) – feste Fassung", type(e).__name__)
            await b.schliessen()
            if self.gespraech is b:
                self.gespraech = None
            if not self.pausiert:
                self._einwand_bis = None
            return self.pausiert or not self.coach.meeting.laeuft
        try:
            await asyncio.wait_for(b.fertig.wait(), EINST.begruessung_max_sekunden)
        except asyncio.TimeoutError:
            log.warning("Begrüßung frei: kein Ende nach %.0f s", EINST.begruessung_max_sekunden)
            await b._phase_beenden()
        if b.ergebnis == "einwand" or self.pausiert or not self.coach.meeting.laeuft:
            return True  # Nein, oder das Meeting wurde während der Begrüßung beendet: nichts nachschieben
        gesagt = b.gesagt()
        fehlt = pflicht_fehlt(gesagt)
        self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "begruessung_pruefung",
                                     "ergebnis": b.ergebnis, "fehlt": fehlt})
        if b.ergebnis == "fehler" and not gesagt:
            return False
        danach = "gespraech" if b.offen else "bereit"
        if fehlt:
            log.info("Begrüßung frei: Nachsatz (fehlt: %s)", ", ".join(fehlt))
            await self._sprechen_texte([nachsatz()], danach=danach)
        if vorstellung and not re.search(r"\bnamen?\b", gesagt, re.IGNORECASE):
            await self._sprechen_texte([NAMEN_BITTE], danach=danach)
        ende = self.sprechzeiten[-1][1] if self.sprechzeiten else self.coach.meeting.jetzt()
        self._einwand_bis = ende + EINST.einwand_sekunden
        if vorstellung:
            self.vorstellung_bis = ende + EINST.vorstellung_sekunden
        if self.zustand == "begruessung":
            self.zustand = danach
            await self.coach.melden()
        return True

    def takt(self) -> None:
        """Vom Coach-Takt: Ende der Vorstellungsrunde (still, Ticket #27), Ende des Fensters für ein einfaches Nein,
        Ende des Rückfrage-Fensters."""
        jetzt = self.coach.meeting.jetzt()
        if self._einwand_bis is not None and jetzt > self._einwand_bis:
            self._einwand_bis = None
        if self.vorstellung_bis is not None and jetzt > self.vorstellung_bis:
            self.vorstellung_bis = None
        if self._nachfrage_bis > 0 and jetzt > self._nachfrage_bis:
            self._nachfrage_bis = -1e9

    # --- Eingang: fertige Sätze und Teiltext --------------------------------
    def teiltext(self, text: str) -> None:
        if (self.aktiv and not self.funkgeraet and self.zustand in ("bereit", "spricht", "gespraech")
                and angesprochen(text)):
            self.zustand = "angesprochen"  # sofortige Rückmeldung im Dashboard, bevor der Satz fertig ist

    def messen(self, ausloeser: str, verzug_text: float = 0.0) -> None:
        """Zeitmessung bis zum ersten Ton (logs/nestor_zeiten.jsonl, Raumtest 06.10.: „Nestor stark verzögert“).
        verzug_text: wie lange der Satz nach seinem Ende brauchte, bis er als Text ankam."""
        self.messung = {"ausloeser": ausloeser, "modus": EINST.assistent_modus, "t0": time.monotonic(),
                        "verzug_text": round(max(0.0, verzug_text), 2)}

    def knopf(self) -> None:
        """Knopf „Nestor fragen“ (Premium, Laptop): wie Ansprechen mit Namen – die nächste Äußerung gilt als Frage."""
        if self.ansprache_aus:
            return
        self.messen("knopf")
        self._angesprochen_bis = self.coach.meeting.jetzt() + 10
        if self.zustand in ("bereit", "spricht", "gespraech"):
            self.zustand = "angesprochen"

    def halten_start(self) -> None:
        """Sprechtaste gedrückt (Funkgerät, Ticket #27; am Handy auch in Premium): was jetzt gesagt wird, ist die
        Frage – sie kommt als Aufnahme (frage_beantworten), nicht über den Live-Text. Die Taste unterbricht Nestor."""
        jetzt = self.coach.meeting.jetzt()
        self.halten = (jetzt, jetzt + 120)
        if self.bogen is not None:
            self._bogen_abloesen()
        elif self.zustand == "spricht":
            asyncio.ensure_future(self.coach.direkt_senden({"typ": "stimme_stopp"}))
            self._sprechzeit_kappen()
        self._nachfrage_bis = -1e9
        if not self.pausiert and self.zustand != "begruessung":
            self.zustand = "taste"

    def halten_ende(self) -> None:
        if self.halten:
            self.halten = (self.halten[0], self.coach.meeting.jetzt() + 2.5)  # Nachlauf: Pause + Live-Text-Verzug
        if self.zustand == "taste":
            self.zustand = "denkt"

    def frage_beantworten(self, frage: str, ausloeser: str = "taste") -> None:
        """Eine Frage, die nicht über den Namen kam (Sprechtaste, getippt): ein Bogen wie bei „Nestor, …“."""
        if not self.aktiv or self.pausiert or self.coach._client is None:
            return
        self.messen(ausloeser)
        self._angesprochen_bis = -1e9
        self.annehmen(frage, "taste" if ausloeser in ("halten", "taste") else ausloeser)

    async def satz(self, text: str, ende: float, sprecher: str | None = None) -> None:
        if not self.aktiv or self.pausiert or self.ansprache_aus:
            return
        if self.halten and self.halten[0] - 0.5 <= ende <= self.halten[1]:
            return  # gehört zur gehaltenen Frage – die kommt als Aufnahme
        jetzt = self.coach.meeting.jetzt()
        frisch = self._einwand_bis is not None and jetzt <= self._einwand_bis
        if (frisch and einwand(text)) or spaetes_nein(text):
            await self._einwand_erhalten()
            return
        if self.funkgeraet:
            # Basis hört nicht auf den Namen (Ticket #27): still ein Hinweis aufs Funkgerät, höchstens einmal je Minute
            if angesprochen(text):
                self.coach.taste_hinweis()
            return
        direkt = angesprochen(text)
        if direkt:
            self.messen("ansprache", jetzt - ende)
            self._nachfrage_bis = -1e9
            frage = frage_aus(text)
            if len(frage.split()) < 3 and not BG.karten_art(frage) and not B.abbruch_wunsch(frage):
                # nur der Name („Nestor?“) – auf die eigentliche Frage warten
                self._angesprochen_bis = jetzt + 10
                self.zustand = "angesprochen"
                self._starten(self._ja_sagen())
                await self.coach.melden()
                return
            self._angesprochen_bis = -1e9
            self.annehmen(frage, "stimme", sprecher)
            return
        if jetzt <= self._angesprochen_bis:  # nach „Ja?“ oder dem Knopf: der nächste Satz ist die Frage
            self.messen("frage_nach_knopf", jetzt - ende)
            self._angesprochen_bis = -1e9
            self.annehmen(text.strip(), "stimme", sprecher)
            return
        if self._nachfrage_ab <= ende <= self._nachfrage_bis:
            # Follow-up-Modus: nur der erste Satz nach dem Bogen kann eine Nachfrage sein, danach ist das Fenster zu
            self._nachfrage_bis = -1e9
            await self.coach.melden()
            if await self.nachfrage_einordnen(text, sprecher) == "frage_an_nestor":
                self.messen("nachfrage", jetzt - ende)
                self.annehmen(text.strip(), "nachfrage", sprecher)
            return
        if self.zustand == "angesprochen" and jetzt > self._angesprochen_bis and self.bogen is None:
            self.zustand = "gespraech" if self.gespraech and self.gespraech.offen else "bereit"

    async def nachfrage_einordnen(self, text: str, sprecher: str | None = None) -> str:
        """Ticket #27, Nachtrag C: drei Stufen, im Zweifel schweigen. Liefert frage_an_nestor | an_nestor_ohne_antwort |
        nicht_an_nestor."""
        c = self.coach
        namen = list(c.meeting.teilnehmende) + list(c.namen.values())
        if BG.jemand_anderes(text, namen):
            ergebnis, weg = "nicht_an_nestor", "regel"
        elif BG.klar_an_nestor(text, namen):
            ergebnis, weg = "frage_an_nestor", "regel"
        else:
            t0 = time.monotonic()
            letzte = (self.letzte or {}).get("antwort") or ""
            ergebnis, nutzung = await BG.einordnen(c._client, text, letzte)
            weg = f"modell {time.monotonic() - t0:.2f}s"
            if nutzung:
                from .pipeline import nutzung_loggen

                nutzung_loggen({"art": "assistent", "zweck": "einordnen", "modell": EINST.assistent_modell, **nutzung})
        gleich = bool(sprecher and self._fragende and sprecher == self._fragende)
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "nachfrage_einordnung", "ergebnis": ergebnis,
                            "weg": weg, "gleiche_person": gleich})
        log.info("Nachfrage-Fenster: %s (%s%s)", ergebnis, weg, ", gleiche Person" if gleich else "")
        return ergebnis

    # --- Bogen: ein Auftrag, eine Antwort (Ticket #27) ---------------------------------------------------------
    def annehmen(self, frage: str, quelle: str, sprecher: str | None = None) -> Bogen | None:
        """Ein gerichteter Auftrag (Zuruf, Sprechtaste, getippt, Nachfrage): Abbruch, Moderations-Karte oder Frage."""
        if B.abbruch_wunsch(frage) and (self.auftraege.liste or B.abbruch_art(frage)):
            self._starten(self._abbruch_per_stimme(frage))  # „Nestor, lass die Recherche“ (Ticket #21)
            return None
        return self.bogen_starten(BG.karten_art(frage) or "frage", frage, quelle, sprecher)

    def bogen_starten(self, art: str, frage: str = "", quelle: str = "knopf", sprecher: str | None = None,
                      fokus: str = "") -> Bogen:
        """Einen Bogen beginnen. Läuft schon einer: ein Knopf wird abgewiesen (BogenBelegt), Zuruf und Sprechtaste
        unterbrechen dessen Stimme – seine Karte kommt trotzdem still (Nachtrag B)."""
        alt = self.bogen
        vorher = None
        if alt is not None and alt.task is not None and not alt.task.done():
            if quelle in ("knopf", "band"):
                raise BogenBelegt(f"Nestor ist noch bei „{BG.NAMEN.get(alt.art, alt.art)}“ – gleich wieder frei.")
            vorher = self._bogen_abloesen()
        if self._aufgabe and not self._aufgabe.done():
            self._aufgabe.cancel()  # „Ja?“ oder eine Abbruch-Bestätigung
        self._bogen_n += 1
        b = Bogen(self._bogen_n, art, (frage or "").strip(), quelle, time.monotonic(), sprecher, fokus, vorher=vorher)
        if self.messung is None:
            self.messen(quelle)
        self.bogen = b
        self._fragende = sprecher
        self._nachfrage_bis = -1e9
        self.zustand = "denkt"
        b.task = asyncio.ensure_future(self._bogen_lauf(b))
        return b

    def _bogen_abloesen(self) -> asyncio.Future | None:
        """Stimme des laufenden Bogens stoppen; die Arbeit läuft still weiter."""
        b = self.bogen
        if b is None:
            return None
        b.abgeloest = True
        self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "bogen_unterbrochen", "bogen": b.art})
        g = self.gespraech
        if g is not None and g.offen and hasattr(g, "stumm_schalten"):
            g.stumm_schalten()
        self._sprechzeit_kappen()
        return asyncio.ensure_future(self.coach.direkt_senden({"typ": "stimme_stopp"}))

    def _sprechzeit_kappen(self) -> None:
        if self.sprechzeiten:
            a, b = self.sprechzeiten[-1]
            self.sprechzeiten[-1] = (a, min(b, self.coach.meeting.jetzt() + 0.5))

    async def _bogen_lauf(self, b: Bogen) -> None:
        c = self.coach
        if b.vorher is not None:
            await asyncio.gather(b.vorher, return_exceptions=True)
        try:
            if b.art == "frage":
                await self._frage_lauf(b)
            elif b.art in BG.LANG_ARTEN:
                await self.lang_annehmen(b.art, b.frage, b.fokus, b)
            else:
                await self._karten_lauf(b)
            for z in list(b.zusatz):
                await asyncio.gather(z, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 – ehrlich sagen statt zu hängen
            from .mistral import ist_ueberlast

            log.warning("Bogen „%s“ fehlgeschlagen: %s", b.art, type(e).__name__)
            if not b.abgeloest:
                await self._sprechen_texte([UEBERLAST if ist_ueberlast(e) else FEHLER], bogen=b)
        finally:
            b.merken("ende")
            if self.bogen is b:
                self.bogen = None
                if not self.pausiert:
                    self.zustand = "gespraech" if self.gespraech and self.gespraech.offen else "bereit"
                if not b.abgeloest and self.nachfrage_moeglich and self.halten is None:
                    jetzt = c.meeting.jetzt()
                    ende = max(jetzt, self.sprechzeiten[-1][1] if self.sprechzeiten else jetzt)
                    self._nachfrage_ab = ende - 1.0  # ein Satz, der mit Nestors letztem Wort endet, zählt mit
                    self._nachfrage_bis = ende + EINST.nachfrage_sekunden
            from .pipeline import _zeit_loggen

            _zeit_loggen({"ausloeser": "bogen", "art": b.art, "quelle": b.quelle, "stufe": EINST.stufe,
                          "abgeloest": b.abgeloest, **b.zeiten})
            c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "bogen", "bogen": b.art, "quelle": b.quelle,
                                "zeiten": dict(b.zeiten), "abgeloest": b.abgeloest})
            await c.melden()

    async def _karten_lauf(self, b: Bogen, floskel: bool = True) -> None:
        """Karten-Bogen: Floskel sofort, Karte, ein bis zwei Sätze (nie die Karte vorlesen)."""
        c = self.coach
        self.text_neu(b.frage or BG.NAMEN.get(b.art))
        ton = asyncio.ensure_future(self.floskel_sagen(self.floskeln.kurz(), b)) if floskel else None
        await c.melden()
        karte, satz = await BG.BAUER[b.art](c, b)
        if karte is not None:
            c._karte_ablegen({**karte, "frage": karte.get("frage") or b.frage or BG.NAMEN.get(b.art),
                              "still": b.abgeloest, "bogen": b.id})
            b.merken("karte")
            await c.melden()
        if ton is not None:
            await ton
        if satz and not b.abgeloest:
            await self._sprechen_texte([satz], bogen=b)

    async def _frage_lauf(self, b: Bogen) -> None:
        """Frage an Nestor: Premium im Realtime-Gespräch (offen oder neu), sonst Text + Sprachausgabe."""
        if EINST.assistent_modus == "gespraech" and not self.funkgeraet:
            if self.gespraech is not None and self.gespraech.offen and hasattr(self.gespraech, "frage"):
                await self.gespraech.frage(b)
                return
            if await self._gespraech_starten(b):
                return
        await self._antworten(b)

    def zusatz_bogen(self, art: str, fokus: str = "") -> None:
        """Ein Werkzeug des Gesprächs verlangt eine Karte (Folie, Zusammenfassung …) – im laufenden Bogen."""
        b = self.bogen
        if b is None:
            try:
                self.bogen_starten(art, BG.NAMEN.get(art, art), "werkzeug", fokus=fokus)
            except BogenBelegt:
                pass
            return
        teil = Bogen(b.id, art, b.frage, b.quelle, b.t0, b.sprecher, fokus)
        teil.abgeloest = b.abgeloest
        b.zusatz.append(asyncio.ensure_future(self._karten_lauf(teil, floskel=False)))

    # --- Lange Aufträge: Bild und Recherche (Ticket #27: kein Bogen, Stau 2/3) ---------------------------------
    async def lang_annehmen(self, art: str, titel: str, fokus: str = "", bogen: Bogen | None = None) -> bool:
        """„Nehme ich mit …“ und im Hintergrund erledigen; das Ergebnis kommt still in den Verlauf. Läuft schon einer,
        wartet der neue; ein dritter wird abgewehrt."""
        offen = [a for a in self.auftraege.liste if a.art in BG.LANG_ARTEN]
        if bogen is not None:
            self.text_neu(bogen.frage or BG.NAMEN.get(art))
        if len(offen) >= 2:
            await self.floskel_sagen(B.ABWEHR, bogen)
            self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "auftrag_abgewehrt", "auftrag": art})
            return False
        laufend = next((a for a in offen if a.zustand == "laeuft"), offen[0] if offen else None)
        satz = B.STAU.get((laufend.art, art), B.ABWEHR) if laufend else self.floskeln.variante(B.LANGE)
        a = self.auftraege.neu(art, titel or BG.NAMEN.get(art, art), self.coach.meeting.jetzt(),
                               zustand="wartet" if offen else "laeuft")
        a.task = asyncio.ensure_future(self._lang_lauf(a, fokus))
        a.task.add_done_callback(lambda _t, a=a: self._lang_fertig(a))
        self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "auftrag", "auftrag": art,
                                     "zustand": a.zustand})
        await self.coach.melden()
        await self.floskel_sagen(satz, bogen)
        return True

    def _lang_fertig(self, a: B.Auftrag) -> None:
        self.auftraege.entfernen(a)
        try:
            asyncio.ensure_future(self.coach.melden())
        except RuntimeError:
            pass

    async def _lang_lauf(self, a: B.Auftrag, fokus: str) -> None:
        c = self.coach
        async with self.lang_sperre:
            a.zustand = "laeuft"
            await c.melden()
            if a.art == "recherche":
                await self._recherche(a.titel)
            elif a.art == "bild":
                await c.bild_erstellen(fokus or None)

    async def _recherche(self, frage: str) -> None:
        """Recherche im Hintergrund: Ergebnis still als Karte mit Quellen (Ticket #27 – keine „fertig“-Ansage)."""
        from .pipeline import nutzung_loggen
        from .recherche import recherchieren

        c = self.coach
        try:
            erg = await recherchieren(c._client, frage, c.meeting.titel)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            from .mistral import ist_ueberlast

            log.warning("Recherche fehlgeschlagen: %s", type(e).__name__)
            c._karte_ablegen({"art": "recherche", "frage": frage, "titel": frage[:80], "still": True,
                              "punkte": [UEBERLAST if ist_ueberlast(e) else "Die Recherche hat leider nicht geklappt."]})
            await c.melden()
            return
        nutzung_loggen({"art": "recherche", "modell": EINST.recherche_modell, "tokens_rein": erg["tokens_rein"],
                        "tokens_raus": erg["tokens_raus"], "sekunden": erg["sekunden"], "suchen": erg.get("suchen")})
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "recherche", "frage": frage, "quellen": erg["quellen"],
                            "sekunden": erg["sekunden"]})
        c.recherche_merken(frage, erg)
        self.verlauf.append((frage, erg["text"]))
        await c._karte_bauen(frage, erg["text"], erg["quellen"], still=True)

    # --- Sonstige Sprache (kein Bogen) -------------------------------------------------------------------------
    async def _ja_sagen(self) -> None:
        """Nur der Name: „Ja?“ – aus dem Zwischenspeicher, wenn es ihn gibt (sofort da, kostet nichts)."""
        self.text_neu(None)
        if EINST.bestaetigung:
            await self.floskel_sagen(B.JA)
            self.zustand = "angesprochen"
            await self.coach.melden()
        else:
            await self._sprechen_texte(["Ja?"], danach="angesprochen")

    async def _einwand_erhalten(self) -> None:
        self._einwand_bis = None
        if self.gespraech is not None:  # offene Realtime-Sitzung (auch die Begrüßung): sofort still und zu,
            await self.coach.direkt_senden({"typ": "stimme_stopp"})  # ab jetzt geht kein Ton mehr an OpenAI
            await self.gespraech.schliessen()
        if self.bogen is not None:
            self._bogen_abloesen()
        await self.coach.einwand_umsetzen()
        self.zustand = "pausiert"
        for a in list(self.auftraege.liste):  # nichts Gehörtes mehr verarbeiten
            self.auftraege.abbrechen(a)
        self.text_neu(None)
        self._starten(self._sprechen_texte([
            "Verstanden, dann höre ich heute nicht mit. Was ich bisher gehört habe, ist gelöscht. "
            "Über den Knopf im Dashboard könnt ihr mich wieder einschalten."], danach="pausiert"))

    def fortsetzen(self) -> None:
        if self.pausiert:
            self.zustand = "bereit"

    def stoppen(self) -> None:
        """Knopf „Stopp“: Nestor still – ein laufender Bogen arbeitet still weiter (seine Karte kommt trotzdem)."""
        if self.bogen is not None:
            self._bogen_abloesen()
        if self._aufgabe and not self._aufgabe.done():
            self._aufgabe.cancel()
        if self.gespraech:
            asyncio.ensure_future(self.gespraech.schliessen())
        self._nachfrage_bis = -1e9
        self.zustand = "pausiert" if self.pausiert else "bereit"

    def _starten(self, coro) -> None:
        if self._aufgabe and not self._aufgabe.done():
            self._aufgabe.cancel()
        self._aufgabe = asyncio.ensure_future(coro)

    # --- Gespräch (Realtime) ---------------------------------------------------
    async def _gespraech_starten(self, b: Bogen) -> bool:
        """Neue Realtime-Sitzung für eine Frage. False = nicht zustande gekommen (dann der Text-Weg)."""
        from .gespraech import Gespraech

        self.zustand = "angesprochen"
        await self.coach.melden()
        self.text_neu(b.frage)
        floskel = self.bestaetigung_fuer(b.frage)
        ton = None
        if floskel:  # Ticket #21: hörbar, während die Sitzung aufgebaut wird (Messung: docs/sprachassistent.md)
            ton = asyncio.ensure_future(self.floskel_sagen(floskel, b))
        g = Gespraech(self)
        try:
            await g.starten(b.frage, bogen=b)
            self.gespraech = g
        except Exception as e:  # noqa: BLE001 – Rückfall auf den Text-Weg, damit die Runde eine Antwort bekommt
            log.warning("Gespräch nicht gestartet (%s) – Antwort über den Text-Weg", type(e).__name__)
            if ton is not None:
                await ton
            await self._antworten(b, bestaetigt=bool(floskel))
            return True
        await g.warten(b)
        return True

    async def audio(self, pcm24k: bytes) -> None:
        if self.gespraech and self.gespraech.offen:
            await self.gespraech.audio(pcm24k)

    # --- Antworten ----------------------------------------------------------
    def kontext(self, frage: str) -> str:
        c, m = self.coach, self.coach.meeting
        z = [f"Meeting: {m.titel or '-'} · Ziel: {m.ziel or '-'} · Laufzeit {mmss(m.jetzt())} min"]
        if m.agenda:
            z.append("Agenda:")
            for i, p in enumerate(m.agenda):
                zeile = (f"{i + 1}. {p.titel} [{m.status(i)}; {mmss(m.genutzt(i))} von {p.minuten:.0f} min]"
                         + (f" – Ziel: {p.ziel}" if p.ziel else ""))
                erg = m.ergebnisse.get(i)
                if erg and erg.get("ergebnis"):
                    zeile += f" – beschlossen: {erg['ergebnis']}"
                z.append(zeile)
        art = getattr(c, "artefakte", None)
        if art is not None:  # Ticket #26: Aufgaben, Entscheidungen, Offenes, Risiken mit Nummer und Lücken
            z += art.kontext_zeilen()
        if m.regel_ids:
            z.append("Vereinbarte Regeln: " + ", ".join(NACH_ID[r].titel for r in m.regel_ids if r in NACH_ID))
        hinweise = [h for h in m.hinweise[-5:]]
        if hinweise:
            z.append("Letzte Hinweise des Coaches: " + " | ".join(f"[{mmss(h.zeit)}] {h.text}" for h in hinweise))
        if c.onepager_analyse:
            z += ["", "Letzte Strukturanalyse des Live-Bilds (kann veraltet sein):", c.onepager_analyse[:2500]]
        if getattr(c, "ueberblick", None):
            from .ueberblick import als_markdown

            z += ["", "Letzter Überblick im Dashboard (kann veraltet sein):", als_markdown(c.ueberblick)[:2500]]
        if getattr(c, "letzte_recherche", None):  # „Nestor, erklär das“ nach einer Recherche
            r = c.letzte_recherche
            z += ["", f"Letzte Recherche („{r['frage']}“), als Karte im Verlauf:", r["text"][:2000]]
        transkript = "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in m.transkript if s.text)
        z += ["", "Transkript (neuester Teil):", transkript[-9000:] or "(noch nichts)"]
        for f, a in self.verlauf[-2:]:
            z += ["", f"Frühere Frage an dich: {f}", f"Deine Antwort: {a}"]
        z += ["", f"Frage an dich: {frage}"]
        return "\n".join(z)

    async def _antworten(self, b: Bogen, bestaetigt: bool = False) -> None:
        """Text-Weg (Basis, Premium „Kurzantwort“): Sprachmodell gestreamt, Satz für Satz Sprachausgabe. Wird der
        Bogen abgelöst, schweigt die Stimme – die Antwort wird trotzdem fertig und kommt als Karte (Nachtrag B)."""
        c = self.coach
        frage = b.frage
        self.zustand = "denkt"
        await c.melden()
        t0 = time.monotonic()
        aktion, gesprochen, puffer, erste_zeile = None, [], "", None
        saetze: asyncio.Queue = asyncio.Queue()
        if not bestaetigt:
            self.text_neu(frage)
        floskel = None if bestaetigt else self.bestaetigung_fuer(frage)
        if floskel:  # sofort hörbar, während das Sprachmodell noch denkt
            saetze.put_nowait(("floskel", floskel))
        sprecher = asyncio.ensure_future(self._sprechen_warteschlange(saetze, b))
        still = False  # nach bild/recherche/folie/karte/eintragen spricht das System, nicht das Modell
        try:
            strom = await c._client.chat.completions.create(
                model=EINST.assistent_modell, stream=True, stream_options={"include_usage": True},
                messages=[{"role": "system", "content": system_text()},
                          {"role": "user", "content": self.kontext(frage)}],
                **({"reasoning_effort": EINST.assistent_aufwand} if EINST.assistent_aufwand else {}))
            nutzung = None
            async for teil in strom:
                if teil.usage:
                    nutzung = teil.usage
                d = teil.choices[0].delta.content if teil.choices else None
                if not d:
                    continue
                puffer += d
                if erste_zeile is None:
                    if "\n" not in puffer:
                        continue
                    erste_zeile, puffer = puffer.split("\n", 1)
                    aktion = aktion_pruefen(aktion_lesen(erste_zeile), frage)
                    still = bool(aktion and aktion["typ"] in STILLE_AKTIONEN)
                    if not AKTION_RE.match(erste_zeile):  # Aktionszeile vergessen – dann ist sie schon Text
                        puffer = erste_zeile + " " + puffer
                fertig, puffer = saetze_teilen(puffer)
                for s in fertig:
                    if not still:
                        gesprochen.append(s)
                        await saetze.put(s)
            if erste_zeile is None:  # sehr kurze Antwort ohne Zeilenumbruch
                aktion = aktion_pruefen(aktion_lesen(puffer), frage)
                still = bool(aktion and aktion["typ"] in STILLE_AKTIONEN)
                puffer = re.sub(r"^\s*AKTION:\s*keine\b", "", puffer, flags=re.IGNORECASE) if aktion is None else ""
            if puffer.strip() and not still:
                gesprochen.append(puffer.strip())
                await saetze.put(puffer.strip())
            if nutzung:
                from .pipeline import nutzung_loggen
                nutzung_loggen({"art": "assistent", "modell": EINST.assistent_modell,
                                "tokens_rein": nutzung.prompt_tokens, "tokens_raus": nutzung.completion_tokens,
                                "sekunden": round(time.monotonic() - t0, 1)})
        except asyncio.CancelledError:
            sprecher.cancel()
            raise
        except Exception as e:  # noqa: BLE001
            from .mistral import ist_ueberlast

            log.warning("Assistent-Antwort fehlgeschlagen: %s", type(e).__name__)
            # Überlast (HTTP 429 auch nach Wiederholungen): ehrlich sagen, statt zu hängen (Ticket #13)
            satz = UEBERLAST if ist_ueberlast(e) else FEHLER
            if not gesprochen:
                gesprochen.append(satz)
            aktion, still = None, False
            await saetze.put(satz)
        await saetze.put(None)
        await sprecher  # Bestätigung und gesprochene Sätze zu Ende, bevor das System selbst spricht
        antwort = " ".join(gesprochen)
        self.letzte = {"frage": frage, "antwort": antwort, "zeit": c.meeting.jetzt(), "aktion": aktion}
        if antwort:
            self.verlauf.append((frage, antwort))
            c.antwort_karte(frage, antwort, aktion, [], still=b.abgeloest)
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "assistent", "frage": frage, "antwort": antwort,
                            "aktion": aktion, "sekunden": round(time.monotonic() - t0, 1)})
        await c.melden()
        if aktion:
            await self.aktion_ausfuehren(aktion, b)

    async def aktion_ausfuehren(self, aktion: dict, b: Bogen) -> None:
        """Aktion aus der Antwort: lange Aufträge, Karten, Eintragen – das System spricht dazu selbst."""
        c = self.coach
        typ = aktion["typ"]
        if typ == "recherche" and aktion.get("frage"):
            await self.lang_annehmen("recherche", aktion["frage"], bogen=b)
        elif typ == "bild":
            fokus = "" if aktion["fokus"].lower() in ("gesamt", "alles") else aktion["fokus"]
            if EINST.bild_anbieter == "text":  # Basis: kein Bildmodell – der Überblick als Text ist ein kurzer Bogen
                b.fokus = fokus
                await self._karten_lauf(Bogen(b.id, "ueberblick", b.frage, b.quelle, b.t0, b.sprecher, fokus,
                                              abgeloest=b.abgeloest), floskel=False)
            else:
                await self.lang_annehmen("bild", b.frage, fokus, b)
        elif typ in ("folie", "karte"):
            art = "folie" if typ == "folie" else aktion["art"]
            await self._karten_lauf(Bogen(b.id, art, b.frage, b.quelle, b.t0, b.sprecher, abgeloest=b.abgeloest),
                                    floskel=False)
        elif typ == "eintragen":
            a, _ = c.artefakte.eintragen(aktion.get("daten") or {})
            if a is not None:
                c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "artefakt_eingetragen", "id": a.id,
                                    "durch": "stimme"})
                await c.melden()
            await self.floskel_sagen(self.floskeln.variante(B.NOTIERT) if a is not None
                                     else "Das konnte ich keinem Eintrag zuordnen.", b)
        else:
            await c.assistent_aktion(aktion)

    # --- Sofort bestätigen, Text mitlaufen lassen, Aufträge (Ticket #21) ---------------------------------
    def text_neu(self, frage: str | None = None) -> None:
        """Die nächste Textnachricht ans Dashboard beginnt eine neue Äußerung (mit der Frage, auf die sie antwortet)."""
        self._text_neu = {"frage": frage}

    async def text_senden(self, text: str, delta: bool = False) -> None:
        """Was Nestor gleich sagt, als Text ans Dashboard – vor dem Ton, damit es mitläuft (Basis/Text-Weg: der Satz,
        Realtime: die Transkript-Stücke). Das Dashboard zeigt es im Takt der Wiedergabe."""
        if not text or self.ansprache_aus:
            return
        nachricht = {"typ": "nestor_text", "text": text, "delta": delta}
        if self._text_neu is not None:
            nachricht.update(neu=True, frage=self._text_neu["frage"])
            self._text_neu = None
        await self.coach.direkt_senden(nachricht)

    async def floskel_sagen(self, text: str, bogen: Bogen | None = None) -> float:
        """Eine Floskel aus dem Zwischenspeicher abspielen – ohne Sprachausgabe-Aufruf, ohne Wartezeit. Fehlt sie
        noch (erster Lauf mit dieser Stimme), wird sie dieses eine Mal live gesprochen und danach abgelegt."""
        c = self.coach
        if c._client is None or not text or self.ansprache_aus or (bogen is not None and bogen.abgeloest):
            return 0.0
        if bogen is not None:
            bogen.merken("floskel")
        if EINST.stimme_aus:
            return len(text) / 14
        pcm = self.floskeln.da(text)
        if pcm is None:
            asyncio.ensure_future(self.floskeln.erzeugen(c._client, text))
            return await self._sprechen(text, B.STIL, zustand_setzen=False, bogen=bogen)
        self._ton_id += 1
        beginn = c.meeting.jetzt() + VORLAUF_SEKUNDEN
        if self.sprechzeiten and self.sprechzeiten[-1][1] > beginn:
            beginn = self.sprechzeiten[-1][1]
        dauer = len(pcm) / 2 / RATE
        self.sprechzeiten.append((beginn, beginn + dauer + NACHLAUF_SEKUNDEN))
        self.sprechtexte.append((beginn, beginn + dauer + NACHLAUF_SEKUNDEN, text))
        await self.text_senden(text)
        for i in range(0, len(pcm), 9600):
            await c.direkt_senden({"typ": "stimme", "id": self._ton_id, "text": text, "floskel": True,
                                   "pcm": base64.b64encode(pcm[i:i + 9600]).decode("ascii")})
        return dauer

    def bestaetigung_fuer(self, frage: str | None) -> str | None:
        """Welche Floskel bestätigt diesen Auftrag? Eine wechselnde kurze; None, wenn nichts zu bestätigen ist (aus,
        kein Auftrag, „danke“). Lange Aufträge sagen ihre eigene Floskel, sobald das Modell sie wirklich anstößt."""
        if not EINST.bestaetigung or self.ansprache_aus or not B.bestaetigen(frage or ""):
            return None
        return self.floskeln.kurz()

    def floskeln_vorbereiten(self) -> None:
        if EINST.bestaetigung and self.coach._client is not None and not EINST.stimme_aus:
            asyncio.ensure_future(self.floskeln.vorbereiten(self.coach._client))

    def auftrag_abbrechen(self, nr: int) -> bool:
        """✕ im Arbeitsring oder „Nestor, lass die Recherche“."""
        a = self.auftraege.holen(nr)
        if a is None:
            return False
        log.info("Auftrag abgebrochen: %s", a.art)
        self.auftraege.abbrechen(a)
        self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "auftrag_abgebrochen",
                                     "auftrag": a.art})
        return True

    async def _abbruch_per_stimme(self, text: str) -> None:
        a = self.auftraege.ziel(text)
        self.text_neu(None)
        if a is not None:
            self.auftrag_abbrechen(a.id)
            await self.coach.melden()
        await self.floskel_sagen(B.ABGEBROCHEN if a is not None else B.NICHTS_OFFEN)

    # --- Sprachausgabe --------------------------------------------------------
    async def _sprechen_warteschlange(self, saetze: asyncio.Queue, bogen: Bogen | None = None) -> float:
        dauer = 0.0
        while (s := await saetze.get()) is not None:
            if bogen is not None and bogen.abgeloest:
                continue  # unterbrochen: still weiter einsammeln, damit die Antwort fertig wird
            # ("floskel", Text): Bestätigung aus dem Zwischenspeicher, in derselben Reihenfolge wie die Sätze
            dauer += await (self.floskel_sagen(s[1], bogen) if isinstance(s, tuple)
                            else self._sprechen(s, bogen=bogen))
        await self.coach.melden()
        return dauer

    async def _sprechen_texte(self, texte: list[str], danach: str | None = None, stil: str | None = None,
                              bogen: Bogen | None = None) -> float:
        """Feste Texte sprechen (Begrüßung, „Ja?“, Moderationssatz); danach den angegebenen Zustand setzen."""
        dauer = 0.0
        for t in texte:
            dauer += await self._sprechen(t, stil, bogen=bogen)
        if danach is not None:
            self.zustand = danach
        elif self.zustand == "spricht":
            self.zustand = "bereit"
        await self.coach.melden()
        return dauer

    async def _sprechen(self, text: str, stil: str | None = None, zustand_setzen: bool = True,
                        bogen: Bogen | None = None) -> float:
        """Einen Satz synthetisieren und gestreamt ans Dashboard schicken. Liefert die Tondauer in Sekunden."""
        c = self.coach
        if c._client is None or not text.strip() or self.ansprache_aus or (bogen is not None and bogen.abgeloest):
            return 0.0
        if bogen is not None:
            bogen.merken("satz")
        if EINST.stimme_aus:  # Tests: keine Sprachausgabe, Dauer grob geschätzt (~14 Zeichen je Sekunde)
            return len(text) / 14
        await self.text_senden(text)  # Ticket #21: der Satz steht im Dashboard, sobald sein Ton beginnt
        if zustand_setzen and self.zustand not in ("begruessung", "pausiert", "taste"):
            self.zustand = "spricht"
            await c.melden()
        self._ton_id += 1
        ton_id, n_bytes, rest = self._ton_id, 0, b""
        beginn = c.meeting.jetzt() + VORLAUF_SEKUNDEN
        if self.sprechzeiten and self.sprechzeiten[-1][1] > beginn:
            beginn = self.sprechzeiten[-1][1]  # schließt an den vorigen Satz an
        self.sprechzeiten.append((beginn, beginn + 30))  # vorläufig, wird unten genau gesetzt
        self.sprechtexte.append((beginn, beginn + 30, text))
        try:
            async with c._client.audio.speech.with_streaming_response.create(
                    model=EINST.stimme_modell, voice=EINST.stimme, input=text, response_format="pcm",
                    instructions=stil or "Sprich ruhig, freundlich und klar auf Deutsch, wie eine erfahrene Moderation. "
                                         "Natürliches Tempo, nicht zu langsam.") as antwort:
                async for stueck in antwort.iter_bytes(9600):
                    if bogen is not None and bogen.abgeloest:
                        break  # unterbrochen: kein Ton mehr hinterher (stimme_stopp ist schon raus)
                    stueck = rest + stueck
                    gerade = len(stueck) // 2 * 2
                    stueck, rest = stueck[:gerade], stueck[gerade:]
                    n_bytes += len(stueck)
                    await c.direkt_senden({"typ": "stimme", "id": ton_id, "text": text,
                                           "pcm": base64.b64encode(stueck).decode("ascii")})
        except asyncio.CancelledError:
            await c.direkt_senden({"typ": "stimme_stopp"})
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Sprachausgabe fehlgeschlagen: %s", type(e).__name__)
        dauer = n_bytes / 2 / RATE
        i = next((k for k in range(len(self.sprechzeiten) - 1, -1, -1) if self.sprechzeiten[k][0] == beginn), -1)
        self.sprechzeiten[i] = (beginn, beginn + dauer + NACHLAUF_SEKUNDEN)
        self.sprechtexte[i if i >= 0 else -1] = (beginn, beginn + dauer + NACHLAUF_SEKUNDEN, text)
        if bogen is not None and bogen.abgeloest:
            self._sprechzeit_kappen()
        from .pipeline import nutzung_loggen
        nutzung_loggen({"art": "stimme", "modell": EINST.stimme_modell, "zeichen": len(text),
                        "sekunden_audio": round(dauer, 1)})
        return dauer
