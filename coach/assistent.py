"""Sprachassistent: der Coach lässt sich mit Namen ansprechen und antwortet mit Sprache (docs/sprachassistent.md).

Ablauf
- Begrüßung zu Beginn: Name, gewünschte Regeln, Hinweis „ich höre mit“ – wer das nicht möchte, sagt „Nein“.
  Kein Nein → Start mit Agendapunkt 1. Ein Nein → der Coach hört nicht mit (Pause, Transkript verworfen).
- Danach hört der Assistent nur auf seinen Namen (im Live-Text, der ohnehin mitläuft – kein zweiter
  Audiostrom) oder auf den Knopf „fragen“. Kurz nach einer Antwort geht eine Rückfrage auch ohne Namen.
- Antwort: ein gestreamter Aufruf an ein Sprachmodell mit dem Meeting-Zustand als Kontext. Erste Zeile
  ist eine Aktion (Bild zeichnen, Agendapunkt wechseln, Pause), danach der gesprochene Text. Jeder fertige
  Satz geht sofort an die Sprachausgabe; der Ton wird als PCM-Stücke an das Dashboard gestreamt.
  Gemessen 05.10.2026: erster Satz nach ~1,2 s, erster Ton ~0,5 s später.
- Eigene Sprache filtert der Coach aus Transkript und Sprecherspur (Zeitfenster, in denen er spricht),
  damit er sich nicht selbst zuhört oder als Person zählt.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time

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
antwortest nur, wenn man dich anspricht. Deine Antwort wird vorgelesen.

So antwortest du:
- Gesprochene Sprache: kurz (meist 1–3 Sätze, höchstens 5), natürlich, freundlich, auf Deutsch, per „ihr“.
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
                            Sag dazu, dass das Bild etwa eine bis zwei Minuten dauert.
AKTION: weiter <nummer>   – zum Agendapunkt mit dieser Nummer wechseln (oder „weiter naechster“),
                            nur wenn die Gruppe das ausdrücklich will.
AKTION: recherche <frage> – im Internet recherchieren („gib uns einen Überblick zu …“, aktuelle Fakten).
                            Sag dazu nur kurz, dass du nachschaust; das Ergebnis liest du danach vor.
                            Frage ohne Namen und ohne Interna aus dem Meeting formulieren.
AKTION: folie             – das letzte Rechercheergebnis mit Quellen als Folie ins Dashboard stellen,
                            wenn die Gruppe das möchte („ja, mach eine Folie“). Sag, dass sie gleich erscheint.
AKTION: pause             – die Gruppe möchte, dass du nicht mehr zuhörst. Sag, dass man dich über den
                            Knopf im Dashboard wieder einschaltet.

Beispiel:
AKTION: keine
Ihr seid bei Punkt zwei, dem Budget. Entschieden ist noch nichts, offen ist die Frage nach dem Puffer.
"""


BILD_ZEILE = "                            Sag dazu, dass das Bild etwa eine bis zwei Minuten dauert.\n"
# Nestor Basis (und Überblick als Text): „AKTION: bild“ zeigt den Überblick als Text – er steht nach wenigen Sekunden
BILD_ZEILE_TEXT = "                            Sag dazu, dass die Übersicht gleich im Dashboard erscheint.\n"
UEBERLAST = "Ich komme gerade nicht durch, versucht es gleich nochmal."


def system_text() -> str:
    """Systemanweisung für die gewählte Stufe: in Basis entsteht auf „AKTION: bild“ der Überblick als Text."""
    s = SYSTEM.format(name=EINST.assistent_name)
    if EINST.bild_anbieter == "text":
        s = s.replace("visuelle Übersicht zeichnen lassen", "Übersicht ins Dashboard stellen").replace(
            BILD_ZEILE, BILD_ZEILE_TEXT)
    return s


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


def begruessungstext(meeting, basis: bool | None = None) -> tuple[str, str]:
    """(Begrüßung mit Einwilligung, Startsatz).

    Die Begrüßung ist fest formuliert – sie trägt die Einwilligung, da darf nichts frei formuliert sein. Danach geht
    es ohne Wartepause weiter (Niclas, 07.10.: das Warten auf ein Nein war ein toter Moment); ein Nein ist kurz nach
    der Begrüßung als einfaches „Nein“ möglich und später jederzeit als „Nestor, nein“ (`spaetes_nein`).
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
    if basis:
        # Nestor Basis: keine Rückfragen ohne Namen, kein Ins-Wort-Fallen (Text + Sprachausgabe) – dafür die Knöpfe
        wie = (f"Ganz kurz, wie ihr mit mir klarkommt: Sagt einfach „{name}“ und eure Frage – jedes Mal mit meinem "
               "Namen. Oder ihr nehmt die Knöpfe auf dem Bildschirm oder am Handy.")
    else:
        wie = (f"Ganz kurz, wie ihr mit mir klarkommt: Sagt einfach „{name}“ und eure Frage. Nachfragen geht dann "
               "auch ohne Namen, und wenn ich zu viel rede, redet einfach rein.")
    start = f"{wie}{agenda_bitte(meeting)}{agenda_kommentar(meeting)}{erster}"
    return gruss, start


# Ton für die Begrüßung: locker und zugewandt, nicht vorgelesen. Ob ein Lachen hörbar wird, entscheidet das Modell.
STIL_START = ("Sprich warm, locker und zugewandt auf Deutsch, wie eine sympathische Moderatorin, die sich auf das "
              "Meeting freut – mit einem Lächeln in der Stimme und einem kurzen, leisen Lachen nach dem ersten Satz. "
              "Natürliches Tempo, kleine Pausen zwischen den Gedanken.")


VORSTELLUNG_BITTE = ("Damit ich euch auseinanderhalten kann: Sagt bitte reihum kurz euren Namen, zum Beispiel: "
                     "Ich bin Lea.")


def vorstellung_start(meeting) -> str:
    _, start = begruessungstext(meeting)
    return "Danke! " + start


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


class Assistent:
    def __init__(self, coach) -> None:
        self.coach = coach
        self.aktiv = True  # in der Einrichtung abschaltbar
        self.zustand = "bereit"  # bereit | begruessung | einwand | angesprochen | denkt | spricht | pausiert
        self.letzte: dict | None = None  # {frage, antwort, zeit}
        self.verlauf: list[tuple[str, str]] = []  # (Frage, Antwort) für Rückfragen
        self.sprechzeiten: list[tuple[float, float]] = []  # Meetingzeit, in der der Coach spricht
        self.messung: dict | None = None  # laufende Zeitmessung Auslöser -> erster Ton
        self._angesprochen_bis = -1e9
        self._nachfrage_bis = -1e9
        self._einwand_bis: float | None = None
        self.vorstellung_bis: float | None = None  # Meetingzeit, bis zu der Namen gesammelt werden
        self._aufgabe: asyncio.Task | None = None
        self._ton_id = 0
        self._bild_ansage = False
        self.gespraech = None  # offene Realtime-Sitzung (coach/gespraech.py)
        self.letzte_aktion: dict | None = None
        self.halten: tuple[float, float] | None = None  # „Nestor fragen“ gehalten: (von, bis) Meetingzeit
        self.letzte_quellen: list[dict] = []  # Quellen der letzten Recherche fürs Dashboard

    # --- Zustand nach außen ------------------------------------------------
    def schnappschuss(self) -> dict:
        return {"aktiv": self.aktiv, "name": EINST.assistent_name, "zustand": self.zustand,
                "letzte": self.letzte}

    @property
    def pausiert(self) -> bool:
        return self.zustand == "pausiert"

    @property
    def ansprache_aus(self) -> bool:
        """Modus „Auf Knopfdruck“ (Lastenheft 3): Nestor hört nicht auf seinen Namen und spricht nicht – Fragen
        gehen über die Knopfleiste und kommen als Text-Karte zurück (coach/knopfdruck.py)."""
        return self.coach.modus == "knopfdruck"

    def spricht_um(self, t: float) -> bool:
        return any(a - 0.2 <= t <= b for a, b in self.sprechzeiten)

    def eigene_sprache(self, start: float, ende: float) -> bool:
        """Überwiegend in einem Zeitfenster, in dem der Coach selbst sprach (nur live mit Lautsprecher)."""
        if self.coach.simulation_laeuft:
            return False
        ueber = sum(max(0.0, min(ende, b) - max(start, a)) for a, b in self.sprechzeiten)
        return ueber >= 0.5 * max(0.1, ende - start)

    # --- Begrüßung mit Einwilligung ----------------------------------------
    async def begruessen(self) -> None:
        if not self.aktiv or self.coach._client is None or self.ansprache_aus:
            return
        gruss, start = begruessungstext(self.coach.meeting)
        self.zustand = "begruessung"
        await self.coach.melden()
        await self._sprechen_texte([gruss], danach="begruessung")
        # Kein Warten auf das Nein: es geht gleich weiter, ein einfaches „Nein“ zählt aber noch eine Weile
        ende = self.sprechzeiten[-1][1] if self.sprechzeiten else self.coach.meeting.jetzt()
        self._einwand_bis = ende + EINST.einwand_sekunden
        if EINST.vorstellung_sekunden > 0:  # Vorstellungsrunde: Namen und Stimmen kennenlernen
            await self._sprechen_texte([VORSTELLUNG_BITTE])
            ende = self.sprechzeiten[-1][1] if self.sprechzeiten else self.coach.meeting.jetzt()
            self.vorstellung_bis = ende + EINST.vorstellung_sekunden
            self._einwand_bis = max(self._einwand_bis, ende + EINST.einwand_sekunden)
        else:
            await self._sprechen_texte([start], stil=STIL_START)

    def takt(self) -> None:
        """Vom Coach-Takt: Ende der Vorstellungsrunde → Start ansagen; Ende des Fensters für ein einfaches Nein."""
        jetzt = self.coach.meeting.jetzt()
        if self._einwand_bis is not None and jetzt > self._einwand_bis:
            self._einwand_bis = None
        if self.vorstellung_bis is not None and jetzt > self.vorstellung_bis:
            self.vorstellung_bis = None
            self._starten(self._sprechen_texte([vorstellung_start(self.coach.meeting)], stil=STIL_START))

    # --- Eingang: fertige Sätze und Teiltext --------------------------------
    def teiltext(self, text: str) -> None:
        if self.aktiv and self.zustand in ("bereit", "spricht") and angesprochen(text):
            self.zustand = "angesprochen"  # sofortige Rückmeldung im Dashboard, bevor der Satz fertig ist

    def messen(self, ausloeser: str, verzug_text: float = 0.0) -> None:
        """Zeitmessung bis zum ersten Ton (logs/nestor_zeiten.jsonl, Raumtest 06.10.: „Nestor stark verzögert“).
        verzug_text: wie lange der Satz nach seinem Ende brauchte, bis er als Text ankam."""
        self.messung = {"ausloeser": ausloeser, "modus": EINST.assistent_modus, "t0": time.monotonic(),
                        "verzug_text": round(max(0.0, verzug_text), 2)}

    def knopf(self) -> None:
        """Knopf „fragen“: wie Ansprechen mit Namen – die nächste Äußerung gilt als Frage."""
        if self.ansprache_aus:
            return
        self.messen("knopf")
        if EINST.assistent_modus == "gespraech":
            if not (self.gespraech and self.gespraech.offen):
                self._starten(self._gespraech_starten(None))
            return
        self._angesprochen_bis = self.coach.meeting.jetzt() + 10
        if self.zustand in ("bereit", "spricht"):
            self.zustand = "angesprochen"

    def halten_start(self) -> None:
        """Knopf „Nestor fragen“ wird gehalten (Handy): was jetzt gesagt wird, ist die Frage – sie kommt als Aufnahme
        (frage_beantworten), nicht über den Live-Text; dort wird sie ignoriert, sonst antwortete Nestor doppelt."""
        jetzt = self.coach.meeting.jetzt()
        self.halten = (jetzt, jetzt + 120)
        if self.zustand in ("bereit", "spricht"):
            self.zustand = "angesprochen"

    def halten_ende(self) -> None:
        if self.halten:
            self.halten = (self.halten[0], self.coach.meeting.jetzt() + 2.5)  # Nachlauf: Pause + Live-Text-Verzug

    def frage_beantworten(self, frage: str, ausloeser: str = "halten") -> None:
        """Eine Frage, die nicht über den Namen kam (gehalten, getippt): gesprochen + Karte wie bei „Nestor, …“."""
        if not self.aktiv or self.pausiert or self.coach._client is None:
            return
        self.messen(ausloeser)
        self._angesprochen_bis = -1e9
        if EINST.assistent_modus == "gespraech" and not (self.gespraech and self.gespraech.offen):
            self._starten(self._gespraech_starten(frage))
        else:
            self._starten(self._antworten(frage))

    async def satz(self, text: str, ende: float) -> None:
        if not self.aktiv or self.pausiert or self.ansprache_aus:
            return
        if self.halten and self.halten[0] - 0.5 <= ende <= self.halten[1]:
            return  # gehört zur gehaltenen Frage – die kommt als Aufnahme
        jetzt = self.coach.meeting.jetzt()
        frisch = self._einwand_bis is not None and jetzt <= self._einwand_bis
        if (frisch and einwand(text)) or spaetes_nein(text):
            await self._einwand_erhalten()
            return
        if self.gespraech and self.gespraech.offen:
            await self.gespraech.satz(text, ende)  # das Modell hört mit; antworten nur, wenn gemeint
            return
        direkt = angesprochen(text)
        if direkt:
            self.messen("ansprache", jetzt - ende)
        if direkt and EINST.assistent_modus == "gespraech":
            frage = frage_aus(text)
            self._starten(self._gespraech_starten(frage if len(frage.split()) >= 3 else None))
            return
        knopf = jetzt <= self._angesprochen_bis
        if knopf and not direkt:
            self.messen("frage_nach_knopf", jetzt - ende)
        nachfrage = jetzt <= self._nachfrage_bis and text.rstrip().endswith("?")
        if not (direkt or knopf or nachfrage):
            if self.zustand == "angesprochen" and jetzt > self._angesprochen_bis:
                self.zustand = "bereit"
            return
        frage = frage_aus(text) if direkt else text.strip()
        if len(frage.split()) < 3:  # nur der Name („Nestor?“) – auf die eigentliche Frage warten
            self._angesprochen_bis = jetzt + 10
            self.zustand = "angesprochen"
            self._starten(self._sprechen_texte(["Ja?"], danach="angesprochen"))
            await self.coach.melden()
            return
        self._angesprochen_bis = -1e9
        self._starten(self._antworten(frage))

    async def _einwand_erhalten(self) -> None:
        self._einwand_bis = None
        await self.coach.einwand_umsetzen()
        self.zustand = "pausiert"
        self._starten(self._sprechen_texte([
            "Verstanden, dann höre ich heute nicht mit. Was ich bisher gehört habe, ist gelöscht. "
            "Über den Knopf im Dashboard könnt ihr mich wieder einschalten."], danach="pausiert"))

    def fortsetzen(self) -> None:
        if self.pausiert:
            self.zustand = "bereit"

    def stoppen(self) -> None:
        if self._aufgabe and not self._aufgabe.done():
            self._aufgabe.cancel()
        if self.gespraech:
            asyncio.ensure_future(self.gespraech.schliessen())
        self.zustand = "pausiert" if self.pausiert else "bereit"

    def ansagen(self, text: str) -> None:
        """Kurze Ansage, die eine laufende Antwort nicht abbricht (z. B. „Das Bild ist fertig“).

        Ist ein Gespräch offen, spricht Nestor sie dort – sonst gäbe es zwei Stimmen gleichzeitig (Test 05.10.).
        """
        if not self.aktiv or self.pausiert or self.ansprache_aus:
            return
        if self.gespraech and self.gespraech.offen:
            asyncio.ensure_future(self.gespraech.ansagen(text))
        else:
            asyncio.ensure_future(self._sprechen_texte([text]))

    def _starten(self, coro) -> None:
        if self._aufgabe and not self._aufgabe.done():
            self._aufgabe.cancel()  # eine neue Ansprache unterbricht die laufende Antwort
        self._aufgabe = asyncio.ensure_future(coro)

    # --- Gespräch (Realtime) ---------------------------------------------------
    async def _gespraech_starten(self, frage: str | None) -> None:
        from .gespraech import Gespraech

        self.zustand = "angesprochen"
        await self.coach.melden()
        g = Gespraech(self)
        try:
            await g.starten(frage)
            self.gespraech = g
        except Exception as e:  # noqa: BLE001 – Rückfall auf den Text-Weg, damit die Runde eine Antwort bekommt
            log.warning("Gespräch nicht gestartet (%s) – Antwort über den Text-Weg", type(e).__name__)
            if frage:
                await self._antworten(frage)
            else:
                self._angesprochen_bis = self.coach.meeting.jetzt() + 10
                await self._sprechen_texte(["Ja?"], danach="angesprochen")

    async def recherche_vorlesen(self, frage: str) -> None:
        """Textmodus: Recherche ausführen und das Ergebnis vorlesen."""
        from .pipeline import nutzung_loggen
        from .recherche import recherchieren

        c = self.coach
        self.zustand = "recherchiert"
        await c.melden()
        try:
            erg = await recherchieren(c._client, frage, c.meeting.titel)
        except Exception as e:  # noqa: BLE001
            from .mistral import ist_ueberlast

            log.warning("Recherche fehlgeschlagen: %s", type(e).__name__)
            await self._sprechen_texte([UEBERLAST if ist_ueberlast(e) else "Die Recherche hat leider nicht geklappt."])
            return
        nutzung_loggen({"art": "recherche", "modell": EINST.recherche_modell, "tokens_rein": erg["tokens_rein"],
                        "tokens_raus": erg["tokens_raus"], "sekunden": erg["sekunden"], "suchen": erg.get("suchen")})
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "recherche", "frage": frage, "quellen": erg["quellen"],
                            "sekunden": erg["sekunden"]})
        c.recherche_merken(frage, erg)
        c.antwort_karte(frage, erg["text"], None, erg["quellen"])
        self.letzte = {"frage": frage, "antwort": erg["text"], "zeit": c.meeting.jetzt(), "aktion": None,
                       "quellen": erg["quellen"]}
        saetze, rest = saetze_teilen(erg["text"] + " ")
        await self._sprechen_texte(saetze + ([rest] if rest.strip() else [])
                                   + ["Soll ich das mit den Quellen auf einer Folie zusammenstellen?"])

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
                if erg:
                    zeile += f" – Ergebnis: {erg['ergebnis'] or 'keins ausgesprochen'}"
                    zeile += "".join(f"; Aufgabe: {a['was']} (wer: {a['wer'] or 'offen'}, bis: {a['bis'] or 'offen'})"
                                     for a in erg["aufgaben"])
                z.append(zeile)
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
        transkript = "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in m.transkript if s.text)
        z += ["", "Transkript (neuester Teil):", transkript[-9000:] or "(noch nichts)"]
        for f, a in self.verlauf[-2:]:
            z += ["", f"Frühere Frage an dich: {f}", f"Deine Antwort: {a}"]
        z += ["", f"Frage an dich: {frage}"]
        return "\n".join(z)

    async def _antworten(self, frage: str) -> None:
        c = self.coach
        self.zustand = "denkt"
        await c.melden()
        t0 = time.monotonic()
        aktion, gesprochen, puffer, erste_zeile = None, [], "", None
        saetze: asyncio.Queue = asyncio.Queue()
        sprecher = asyncio.ensure_future(self._sprechen_warteschlange(saetze))
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
                    aktion = aktion_lesen(erste_zeile)
                    if not AKTION_RE.match(erste_zeile):  # Aktionszeile vergessen – dann ist sie schon Text
                        puffer = erste_zeile + " " + puffer
                fertig, puffer = saetze_teilen(puffer)
                for s in fertig:
                    gesprochen.append(s)
                    await saetze.put(s)
            if erste_zeile is None:  # sehr kurze Antwort ohne Zeilenumbruch
                aktion = aktion_lesen(puffer)
                puffer = re.sub(r"^\s*AKTION:\s*keine\b", "", puffer, flags=re.IGNORECASE) if aktion is None else ""
            if puffer.strip():
                gesprochen.append(puffer.strip())
                await saetze.put(puffer.strip())
            await saetze.put(None)
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
            satz = UEBERLAST if ist_ueberlast(e) else "Entschuldigung, das hat gerade nicht geklappt."
            if not gesprochen:
                gesprochen.append(satz)
            await saetze.put(satz)
            await saetze.put(None)
        antwort = " ".join(gesprochen)
        self.letzte = {"frage": frage, "antwort": antwort, "zeit": c.meeting.jetzt(), "aktion": aktion}
        self.verlauf.append((frage, antwort))
        c.antwort_karte(frage, antwort, aktion, [])
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "assistent", "frage": frage, "antwort": antwort,
                            "aktion": aktion, "sekunden": round(time.monotonic() - t0, 1)})
        await c.melden()
        if aktion:
            await c.assistent_aktion(aktion)
        await sprecher
        self._nachfrage_bis = c.meeting.jetzt() + EINST.nachfrage_sekunden

    # --- Sprachausgabe --------------------------------------------------------
    async def _sprechen_warteschlange(self, saetze: asyncio.Queue) -> float:
        dauer = 0.0
        while (s := await saetze.get()) is not None:
            dauer += await self._sprechen(s)
        if not self.pausiert:
            self.zustand = "bereit"
        await self.coach.melden()
        return dauer

    async def _sprechen_texte(self, texte: list[str], danach: str = "bereit", stil: str | None = None) -> float:
        """Feste Texte sprechen (Begrüßung, „Ja?“, Ansagen); danach den angegebenen Zustand setzen."""
        dauer = 0.0
        for t in texte:
            dauer += await self._sprechen(t, stil)
        self.zustand = danach
        await self.coach.melden()
        return dauer

    async def _sprechen(self, text: str, stil: str | None = None) -> float:
        """Einen Satz synthetisieren und gestreamt ans Dashboard schicken. Liefert die Tondauer in Sekunden."""
        c = self.coach
        if c._client is None or not text.strip() or self.ansprache_aus:
            return 0.0
        if EINST.stimme_aus:  # Tests: keine Sprachausgabe, Dauer grob geschätzt (~14 Zeichen je Sekunde)
            return len(text) / 14
        if self.zustand not in ("begruessung", "pausiert"):
            self.zustand = "spricht"
            await c.melden()
        self._ton_id += 1
        ton_id, n_bytes, rest = self._ton_id, 0, b""
        beginn = c.meeting.jetzt() + VORLAUF_SEKUNDEN
        if self.sprechzeiten and self.sprechzeiten[-1][1] > beginn:
            beginn = self.sprechzeiten[-1][1]  # schließt an den vorigen Satz an
        self.sprechzeiten.append((beginn, beginn + 30))  # vorläufig, wird unten genau gesetzt
        try:
            async with c._client.audio.speech.with_streaming_response.create(
                    model=EINST.stimme_modell, voice=EINST.stimme, input=text, response_format="pcm",
                    instructions=stil or "Sprich ruhig, freundlich und klar auf Deutsch, wie eine erfahrene Moderation. "
                                         "Natürliches Tempo, nicht zu langsam.") as antwort:
                async for stueck in antwort.iter_bytes(9600):
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
        self.sprechzeiten[-1] = (beginn, beginn + dauer + NACHLAUF_SEKUNDEN)
        from .pipeline import nutzung_loggen
        nutzung_loggen({"art": "stimme", "modell": EINST.stimme_modell, "zeichen": len(text),
                        "sekunden_audio": round(dauer, 1)})
        return dauer
