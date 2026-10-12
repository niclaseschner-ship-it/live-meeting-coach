"""Sprachassistent Nestor (docs/sprachassistent.md, Ticket #27: Antwortbogen).

Grundregel: Nestor spricht nur in einem **Antwortbogen**, den die Runde ausgelöst hat – Ausnahme ist die Begrüßung.
Was er von sich aus merkt, kommt still (Band oben, Karte im Verlauf).

- **Begrüßung** mit Einwilligung („ich höre mit“, Nein jetzt oder später als „Nestor, nein“), endet mit der Bitte
  um die Namen; danach ordnet Nestor still zu („Erkannt: …“ im Band).
- **Auslöser:** Premium wie ein Telefon – „Nestor, …“ im Live-Text, danach ein Hörfenster für einen Gesprächszug
  ohne Namen (coach/gespraechszug.py). Im Gespräch (Realtime) wird nichts vorsortiert: jede Anfrage geht als EIN
  Aufruf mit Werkzeugen an das Modell, das auch entscheidet, ob ein Zug ohne Namen gemeint war. Basis wie ein
  Funkgerät – Sprechtaste halten, sprechen, loslassen; auf den Namen reagiert Basis nicht. In beiden: Knöpfe und
  getippte Fragen.
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
from . import gespraechszug as GZ
from . import kern
from .analyse import mmss
from .config import EINST
from .regeln import NACH_ID

log = logging.getLogger("coach.assistent")

RATE = 24000  # PCM der Sprachausgabe: 24 kHz, 16 bit, mono
NAME_RE = re.compile(rf"\b(?:{EINST.assistent_muster})\b", re.IGNORECASE)
NEIN_RE = re.compile(r"\bnein\b|nicht einverstanden|(möchte|will|wollen|möchten) (ich |wir )?(das )?nicht", re.IGNORECASE)
VORLAUF_SEKUNDEN = 0.4  # bis der Ton im Browser wirklich zu hören ist
NACHLAUF_SEKUNDEN = 0.8  # Hall und Verzögerung nach dem letzten Ton
# Nach „Nestor?“ → „Ja?“ gilt der nächste Satz sicher als Frage – so lange nach dem Ende von „Ja?“ (Ticket #28; wie vor
# #27). Gezählt ab dem gesprochenen Ende, nicht ab dem Namen: im Cloudlauf 08.10. lief das Fenster ab, während das
# „Ja?“ noch kam bzw. die Runde nachdachte.
JA_FENSTER_SEKUNDEN = 12.0
TEXT_VERZUG_SEKUNDEN = 3.0  # so lange nach Satzende kann der fertige Satz noch als Text ankommen
# Hörfenster: Ein Satz, der rechtzeitig begann, kommt erst nach seinem Ende als Text – so lange bleibt das Fenster
# nach der Frist (Ring weg) noch für ihn offen
SATZ_NACHLAUF_SEKUNDEN = 15.0
TEILTEXT_FRISCH_SEKUNDEN = 2.0  # so frisch muss ein Teiltext sein, damit er als „spricht gerade“ zählt
# Welche Karte ein Werkzeug legt (Kartenart in logs/nestor.jsonl); karte_zeigen nennt sie im Argument
KARTEN_WERKZEUG = {"zusammenfassen": "zusammenfassen", "karte": "antwort", "karte_zeigen": None, "folie_erstellen": "folie",
                   "karte_neu_aufbereiten": "neu_aufbereiten", "recherchieren": "recherche", "bild_zeichnen": "bild"}


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


NAMEN_BITTE = "Sagt gern eure Namen fürs Protokoll."


def wie_text(basis: bool) -> str:
    """Wie man mit Nestor spricht – Telefon (Premium) oder Funkgerät (Basis), Ticket #27."""
    name = EINST.assistent_name
    if basis:
        return "Wie beim Funkgerät: Taste halten, sprechen, loslassen – am Handy oder per Leertaste."
    return (f"Ich funktioniere wie ein Telefon: Sagt „{name}“ und eure Frage. Direkt danach könnt ihr ohne Namen "
            "nachfragen, und wenn ich zu viel rede, redet einfach rein.")


def begruessungstext(meeting, basis: bool = False, namen: bool | None = None) -> tuple[str, str]:
    """(Begrüßung mit Einwilligung, Rest der Begrüßung).

    Feste Fassung: Rückfall der freien Begrüßung (coach/begruessung.py, Ticket #23) und Standard in Basis. Nestor sagt
    in der Begrüßung alles (Ticket #27) und endet mit der Bitte um die Namen – danach kein Startsatz mehr. Ein Nein ist
    kurz nach der Begrüßung als einfaches „Nein“ möglich und später jederzeit als „Nestor, nein“ (`spaetes_nein`).

    Ticket #67: die Begrüßung ist für alle auch die erste Vorstellung des Produkts – deshalb ein kurzer Satz, was
    Nestor tut (Agenda/Zeit, Ergebnisse festhalten, auf Zuruf zusammenfassen/recherchieren), bevor die Einwilligung
    kommt.
    """
    name = EINST.assistent_name
    regeln = [NACH_ID[r].titel.split(" – ")[0] for r in meeting.regel_ids if r in NACH_ID]
    teil_regeln = ""
    if regeln:
        liste = ", ".join(regeln[:-1]) + (" und " if len(regeln) > 1 else "") + regeln[-1]
        teil_regeln = f" Ihr habt euch diese Regeln vorgenommen: {liste}."
    teil_regeln += _weitere_regeln_satz(meeting)
    gruss = (f"Hallo, ich bin {name}, euer Moderationsassistent.{teil_regeln} Ich höre mit, behalte Agenda und Zeit "
             f"im Blick, halte eure Ergebnisse fest und fasse auf Zuruf zusammen oder recherchiere etwas für euch. "
             f"Nicht einverstanden? Sagt Nein – auch später mit "
             f"„{name}, nein“. Dann lösche ich alles.")
    erster = f" Los geht's mit Punkt eins: {meeting.agenda[0].titel}." if meeting.agenda else " Los geht's."
    if namen is None:
        namen = EINST.vorstellung_sekunden > 0
    start = f"{wie_text(basis)}{agenda_bitte(meeting)}{erster}"
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
# „Lea hier, ich mache das Marketing.“ (Ticket #27: in der Namensrunde-Messung nie erkannt)
NAME_HIER_RE = re.compile(r"^\W*([A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?)\s+hier\b")


def name_aus(text: str, bekannte: list[str] | None = None) -> str | None:
    """Vorname aus einer Vorstellung („Ich bin Lea“, „Mein Name ist Jonas“, „Miriam hier“). Stehen Teilnehmende
    in der Einrichtung, gewinnt der dort eingetragene Name, wenn er im Satz vorkommt."""
    m = VORSTELLUNG_RE.search(text) or NUR_NAME_RE.match(text.strip()) or NAME_HIER_RE.match(text.strip())
    if m and m.group(1).lower() not in {"nestor", "ja", "nein", "okay", "hallo", "danke", "gut"}:
        for n in bekannte or []:
            if n.split()[0].casefold() == m.group(1).casefold():
                return n
        # Eine typische Ein-Buchstaben-ASR-Variante (Niclas/Niklas) darf den eingetragenen Namen benutzen.
        # Nur nach tatsächlicher Vorstellung und nur mit genau einem passenden Kandidaten.
        gesagt = m.group(1).casefold()
        def nahe(n):
            n = n.split()[0].casefold()
            if min(len(gesagt), len(n)) < 5:
                return False
            if len(gesagt) == len(n):
                return sum(x != y for x, y in zip(gesagt, n)) == 1
            kurz, lang = sorted((gesagt, n), key=len)
            return len(lang) - len(kurz) == 1 and any(lang[:i] + lang[i + 1:] == kurz for i in range(len(lang)))
        kandidaten = [n for n in bekannte or [] if nahe(n)]
        if len(kandidaten) == 1:
            return kandidaten[0]
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
    gesagt: str = ""     # Karten-Bogen: der Satz zur Karte
    # Nestors Seite (Ticket #83): erkannte Absicht bzw. Werkzeugaufruf mit Argumenten, Fehlertyp – fließen am Ende
    # von _bogen_lauf in EINEN Eintrag in logs/nestor.jsonl (coach/pipeline.py: _zeit_loggen)
    aktion: dict | None = None
    fehler: str | None = None
    gerichtet: bool = True    # False: Gesprächszug ohne Namen im Hörfenster – das Modell entscheidet
    verworfen: bool = False   # nicht_an_mich: nicht gemeint, Nestor schweigt
    werkzeuge: list = field(default_factory=list)  # Werkzeugaufrufe des Modells: {name, argumente, fehler}
    zug: dict | None = None   # Gesprächszug, aus dem die Anfrage kam: Auslöser, Sprecher, Zahl der Sätze
    frist_ueberschritten: bool = False  # kein Ton bis zur Anfrage-Frist – Ergebnis kam still als Karte
    karte: bool = False       # ein Werkzeug hat schon eine Karte gelegt – keine zusätzliche Antwortkarte

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
        # Hörfenster (Premium im Gespräch): ein Gesprächszug ohne Namen, der bis _hoerfenster_bis beginnt
        self._hoerfenster_ab = -1e9
        self._hoerfenster_bis = -1e9
        self.zug: GZ.Zug | None = None  # Gesprächszug, der gerade gesammelt wird
        self._zug_aufgabe: asyncio.Task | None = None
        self._teiltext_zeit = -1e9  # Uhr (monoton) beim letzten Teiltext
        self._einwand_bis: float | None = None
        self.vorstellung_bis: float | None = None  # Meetingzeit, bis zu der Namen gesammelt werden
        self._aufgabe: asyncio.Task | None = None  # Begrüßung, „Ja?“, Abbruch-Bestätigung (kein Bogen)
        self._ton_id = 0
        self.gespraech = None  # offene Realtime-Sitzung (coach/gespraech.py)
        self.letzte_aktion: dict | None = None
        self.halten: tuple[float, float] | None = None  # Sprechtaste gehalten: (von, bis) Meetingzeit
        self._taste_gehalten = False
        self.letzte_quellen: list[dict] = []
        # Ticket #21/#27: Floskeln, lange Aufträge (Stau 2/3), Text läuft mit
        self.floskeln = B.Floskeln(wahl=lambda: self.coach.wahl)
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
        hoert = max(self._hoerfenster_bis, self._angesprochen_bis) if not self.funkgeraet else -1e9
        hoert = hoert if hoert > jetzt and (self.hoerfenster_moeglich or self._angesprochen_bis > jetzt) else None
        return {"aktiv": self.aktiv, "name": EINST.assistent_name, "zustand": self.zustand,
                "letzte": self.letzte, "auftraege": self.auftraege.schnappschuss(),
                "bogen": {"art": b.art, "name": BG.NAMEN.get(b.art, b.art), "quelle": b.quelle} if b else None,
                "hoert_bis": round(hoert, 1) if hoert else None,
                # Länge des Fensters für den Ring (Hörfenster nach einem Bogen, 12 s nach „Ja?“)
                "hoert_dauer": (JA_FENSTER_SEKUNDEN if self._angesprochen_bis > jetzt
                                else self.coach.wahl.nachfrage_sekunden if self.coach.wahl else 0.0)
                if hoert else None,
                "funkgeraet": self.funkgeraet, "taste": self._taste_gehalten}

    @property
    def pausiert(self) -> bool:
        return self.zustand == "pausiert"

    @property
    def funkgeraet(self) -> bool:
        """Nestor Basis (Ticket #27): Sprechtaste statt Name, kein Rückfrage-Fenster."""
        return self.coach.wahl is not None and self.coach.wahl.basis

    @property
    def agent(self) -> bool:
        """Premium im Gespräch (Realtime): jede Anfrage geht ohne Vorsortierung als ein Aufruf mit Werkzeugen an das
        Modell. Basis und Premium-Kurzantwort nehmen den Text-Weg."""
        w = self.coach.wahl
        return not self.funkgeraet and w is not None and w.assistent_modus == "gespraech"

    @property
    def hoerfenster_moeglich(self) -> bool:
        """Ein Zug ohne Namen nach Nestors Antwort – nur im Gespräch, denn nur dort entscheidet das Modell selbst,
        ob er gemeint war."""
        return self.agent and self.coach.wahl.nachfrage_sekunden > 0

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
        if not self.aktiv or self.coach._client is None:
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
        gruss, start = begruessungstext(self.coach.meeting, basis=self.coach.wahl.basis)
        frei = None
        if self.coach.wahl.basis and EINST.basis_begruessung_frei:  # Ticket #23: Mistral formuliert, sonst fest
            from .begruessung import basis_formulieren, in_stuecke

            text = await basis_formulieren(self.coach._client, self.coach.meeting, vorstellung,
                                           wahl=self.coach.wahl)
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
        if self.zustand in ("begruessung", "spricht"):
            self.zustand = "bereit"
            await self.coach.melden()

    async def _begruessen_frei(self) -> bool:
        """Premium (Ticket #23): Begrüßung frei im Realtime-Gespräch. False = nicht zustande gekommen, dann spricht
        der Aufrufer die feste Fassung. Fehlt im hörbar Gesagten ein Teil der Einwilligung, folgt der feste Nachsatz."""
        if (self.coach.wahl.basis or EINST.begruessung != "frei"
                or self.coach.wahl.assistent_modus != "gespraech"):
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
            await self._sprechen_texte([nachsatz(fehlt)], danach=danach)
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
        if self._hoerfenster_bis > 0 and jetzt > self._hoerfenster_bis + SATZ_NACHLAUF_SEKUNDEN:
            self._hoerfenster_zu("abgelaufen")
        if self._angesprochen_bis > 0 and jetzt > self._angesprochen_bis + TEXT_VERZUG_SEKUNDEN:
            # „Ja?“ ohne Frage: wieder zuhören (sonst bliebe „angesprochen“ stehen, bis jemand etwas sagt). Erst nach
            # dem Verzug des Live-Texts – ein Satz, der im Fenster endete, kommt noch als Text an und gilt (satz())
            self._angesprochen_bis = -1e9
            if self.zustand == "angesprochen" and self.bogen is None:
                self.zustand = "gespraech" if self.gespraech and self.gespraech.offen else "bereit"

    # --- Eingang: fertige Sätze und Teiltext --------------------------------
    def teiltext(self, text: str) -> None:
        if text:
            self._teiltext_zeit = time.monotonic()
        if (self.aktiv and not self.funkgeraet and self.zustand in ("bereit", "spricht", "gespraech")
                and angesprochen(text)):
            self.zustand = "angesprochen"  # sofortige Rückmeldung im Dashboard, bevor der Satz fertig ist

    def messen(self, ausloeser: str, verzug_text: float = 0.0) -> None:
        """Zeitmessung bis zum ersten Ton (logs/nestor_zeiten.jsonl, Raumtest 06.10.: „Nestor stark verzögert“).
        verzug_text: wie lange der Satz nach seinem Ende brauchte, bis er als Text ankam."""
        self.messung = {"ausloeser": ausloeser,
                        "modus": self.coach.wahl.assistent_modus if self.coach.wahl else None, "t0": time.monotonic(),
                        "verzug_text": round(max(0.0, verzug_text), 2)}

    def knopf(self) -> None:
        """Knopf „Nestor fragen“ (Premium, Laptop): wie Ansprechen mit Namen – die nächste Äußerung gilt als Frage."""
        self.messen("knopf")
        self._angesprochen_bis = self.coach.meeting.jetzt() + 10
        if self.zustand in ("bereit", "spricht", "gespraech"):
            self.zustand = "angesprochen"

    def halten_start(self) -> None:
        """Sprechtaste gedrückt (Funkgerät, Ticket #27; am Handy auch in Premium): was jetzt gesagt wird, ist die
        Frage – sie kommt als Aufnahme (frage_beantworten), nicht über den Live-Text. Die Taste unterbricht Nestor."""
        jetzt = self.coach.meeting.jetzt()
        self.halten = (jetzt, jetzt + 120)
        self._taste_gehalten = True
        if self.bogen is not None:
            self._bogen_abloesen()
        elif self.zustand == "spricht":
            asyncio.ensure_future(self.coach.direkt_senden({"typ": "stimme_stopp"}))
            self._sprechzeit_kappen()
        self._hoerfenster_zu("sprechtaste")
        self.zug = None  # die Taste ersetzt einen angefangenen Zug
        if not self.pausiert and self.zustand != "begruessung":
            self.zustand = "taste"

    def halten_abbrechen(self) -> None:
        """Sprechtaste ohne brauchbare Frage (zu kurz, nichts verstanden): wieder zuhören. Das Zeitfenster der
        Taste bleibt, damit das Gesagte nicht noch über den Live-Text kommt."""
        self._taste_gehalten = False
        if self.zustand in ("taste", "denkt") and self.bogen is None:
            self.zustand = "gespraech" if self.gespraech and self.gespraech.offen else "bereit"

    def halten_ende(self) -> None:
        self._taste_gehalten = False
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

    async def satz(self, text: str, ende: float, sprecher: str | None = None, start: float | None = None) -> None:
        if not self.aktiv or self.pausiert:
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
        if direkt and B.halt_wunsch(frage_aus(text)):  # Leitplanke „Halt“: sofort still, deterministisch
            self.messen("ansprache", jetzt - ende)
            self.zug = None
            self._hoerfenster_zu("halt")
            await self._halt()
            return
        if self.agent:
            await self._zug_satz(text, ende, sprecher, start, direkt)
            return
        if direkt:  # Text-Weg (Premium-Kurzantwort)
            self.messen("ansprache", jetzt - ende)
            frage = frage_aus(text)
            if not re.search(r"\w", frage):
                self._nur_name()
                await self.coach.melden()
                return
            self._angesprochen_bis = -1e9
            self.annehmen(frage, "stimme", sprecher)
            return
        if ende <= self._angesprochen_bis:  # nach „Ja?“ oder dem Knopf: der nächste Satz ist die Frage
            self.messen("frage_nach_knopf", jetzt - ende)
            self._angesprochen_bis = -1e9
            self.annehmen(text.strip(), "stimme", sprecher)
            return
        self._angesprochen_pruefen(jetzt)

    def _angesprochen_pruefen(self, jetzt: float) -> None:
        if self.zustand == "angesprochen" and jetzt > self._angesprochen_bis and self.bogen is None:
            self.zustand = "gespraech" if self.gespraech and self.gespraech.offen else "bereit"

    def _nur_name(self) -> None:
        """Nur der Name („Nestor?“) – „Ja?“ und auf die eigentliche Frage warten; _ja_sagen setzt das Fenster genau."""
        self._angesprochen_bis = self.coach.meeting.jetzt() + JA_FENSTER_SEKUNDEN + 3.0
        self.zustand = "angesprochen"
        self._starten(self._ja_sagen())

    # --- Gesprächszug (Premium im Gespräch) ---------------------------------------------------------------------
    async def _zug_satz(self, text: str, ende: float, sprecher: str | None, start: float | None,
                        direkt: bool) -> None:
        """Ein fertiger Satz im Gespräch: gehört er zu einem offenen Zug, kommt er dazu; sonst beginnt mit dem Namen,
        nach „Ja?“/Knopf oder im Hörfenster ein neuer Zug. Alles andere hört Nestor nur mit."""
        jetzt = self.coach.meeting.jetzt()
        beginn = start if start is not None else ende
        teil = GZ.Teil(sprecher, frage_aus(text) if direkt else text.strip(), beginn, ende)
        if self.zug is not None:
            self.zug.dazu(teil, time.monotonic(), gerichtet=direkt)
            return
        if direkt:
            ausloeser = "ansprache"
        elif ende <= self._angesprochen_bis:
            ausloeser = "frage_nach_knopf"
        elif self.hoerfenster_moeglich and GZ.im_hoerfenster(beginn, ende, self._hoerfenster_ab,
                                                               self._hoerfenster_bis):
            ausloeser = "hoerfenster"
        else:
            self._angesprochen_pruefen(jetzt)
            return
        self.messen(ausloeser, jetzt - ende)
        self._angesprochen_bis = -1e9
        self._hoerfenster_zu("zug_begonnen" if ausloeser == "hoerfenster" else "angesprochen")
        self.zug = GZ.Zug(ausloeser, ausloeser != "hoerfenster", sprecher, time.monotonic(), [teil])
        if self.zug.gerichtet and self.zustand in ("bereit", "spricht", "gespraech"):
            self.zustand = "angesprochen"
        if self._zug_aufgabe is None or self._zug_aufgabe.done():
            self._zug_aufgabe = asyncio.ensure_future(self._zug_abwarten())
        await self.coach.melden()

    def _hoerfenster_zu(self, grund: str) -> None:
        """Das Hörfenster für einen Zug ohne Namen schließt – mit Grund in logs/nestor.jsonl."""
        if self._hoerfenster_bis > 0:
            from .pipeline import _zeit_loggen

            _zeit_loggen({"ausloeser": "hoerfenster", "ereignis": "nachfrage_zu", "grund": grund})
        self._hoerfenster_bis = -1e9

    def an_nestor(self, ende: float, text: str) -> bool:
        """Gehört der Satz zu einer Anfrage an Nestor (Name oder Sprechtaste)? Dann ist er kein Gesprächsinhalt der
        Runde: Die Themenprüfung wertet ihn nicht als Abschweifung (Datenspende 12.10.: „Sag uns, was wir bei dem
        Punkt machen“ löste „Das Thema passt eher zu Punkt 3“ aus)."""
        if self.halten and self.halten[0] - 0.5 <= ende <= self.halten[1]:
            return True
        return angesprochen(text)

    def zug_offen(self) -> bool:
        """Sammelt Nestor gerade einen Zug? Dann gehören weitere Sätze zur Anfrage (keine feste Ansage-Regel)."""
        return self.zug is not None

    async def _zug_abwarten(self) -> None:
        """Bis zur Pause sammeln, dann den Zug als eine Anfrage schicken."""
        pause, hoechstens = EINST.zug_pause_sekunden, EINST.zug_max_warten
        while self.zug is not None:
            z = self.zug
            spricht = (bool(self.coach.meeting.teiltext)
                       and time.monotonic() - self._teiltext_zeit < TEILTEXT_FRISCH_SEKUNDEN)
            if z.fertig(self.coach.meeting.jetzt(), time.monotonic(), spricht, pause, hoechstens):
                self.zug = None
                await self._zug_senden(z)
                return
            await asyncio.sleep(min(0.1, max(0.01, pause / 4)))

    async def _zug_senden(self, z: GZ.Zug) -> None:
        if not self.aktiv or self.pausiert:
            return
        if z.gerichtet and not re.search(r"\w", z.eigener_text()):
            self._nur_name()
            await self.coach.melden()
            return
        b = self.annehmen(z.anfrage(), "stimme" if z.gerichtet else "nachfrage", z.sprecher, gerichtet=z.gerichtet)
        if b is not None:
            b.zug = {"ausloeser": z.ausloeser, "sprecher": sorted({t.sprecher or "?" for t in z.teile}),
                     "saetze": len(z.teile)}
        await self.coach.melden()

    # --- Bogen: ein Auftrag, eine Antwort (Ticket #27) ---------------------------------------------------------
    def annehmen(self, frage: str, quelle: str, sprecher: str | None = None, gerichtet: bool = True) -> Bogen | None:
        """Eine Anfrage (Zuruf, Sprechtaste, getippt, Gesprächszug). Sie geht unsortiert als Frage an das Modell, das
        versteht, was gemeint ist, und die Werkzeuge wählt (coach/kern.py) – in beiden Stufen."""
        return self.bogen_starten("frage", frage, quelle, sprecher, gerichtet=gerichtet)

    def bogen_starten(self, art: str, frage: str = "", quelle: str = "knopf", sprecher: str | None = None,
                      fokus: str = "", gerichtet: bool = True) -> Bogen:
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
        b = Bogen(self._bogen_n, art, (frage or "").strip(), quelle, time.monotonic(), sprecher, fokus, vorher=vorher,
                  gerichtet=gerichtet)
        if self.messung is None:
            self.messen(quelle)
        self.bogen = b
        self._hoerfenster_zu("neue_anfrage")
        self.zustand = "denkt"
        b.task = asyncio.ensure_future(self._bogen_lauf(b))
        return b

    async def _halt(self) -> None:
        """Nestor verstummt sofort: laufenden Bogen abstoßen oder kurze Aufgabe abbrechen, dann zuhören."""
        bogen = self.bogen
        if bogen is not None and bogen.task is not None and not bogen.task.done():
            self._bogen_abloesen()  # nur die Stimme stoppen, die Arbeit läuft still weiter (Rückgabe ignorieren)
        elif self._aufgabe is not None and not self._aufgabe.done():
            self._aufgabe.cancel()
            self._sprechzeit_kappen()
        self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "halt"})
        self._angesprochen_bis = self.coach.meeting.jetzt() + JA_FENSTER_SEKUNDEN + 3.0
        self.zustand = "angesprochen"
        await self.coach.melden()

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
            b.fehler = b.fehler or type(e).__name__
            if not b.abgeloest:
                await self._sprechen_texte([kern.UEBERLAST if ist_ueberlast(e) else kern.FEHLER], bogen=b)
        finally:
            b.merken("ende")
            if self.bogen is b:
                self.bogen = None
                if not self.pausiert:
                    self.zustand = "gespraech" if self.gespraech and self.gespraech.offen else "bereit"
                if (not b.abgeloest and not b.verworfen and self.hoerfenster_moeglich and not self._taste_gehalten
                        and self.zug is None):
                    jetzt = c.meeting.jetzt()
                    ende = max(jetzt, self.sprechzeiten[-1][1] if self.sprechzeiten else jetzt)
                    self._hoerfenster_ab = ende - 1.0  # ein Satz, der mit Nestors letztem Wort endet, zählt mit
                    self._hoerfenster_bis = ende + self.coach.wahl.nachfrage_sekunden
                    from .pipeline import _zeit_loggen

                    _zeit_loggen({"ausloeser": "hoerfenster", "ereignis": "nachfrage_offen", "grund": "antwort_fertig",
                                  "sekunden": round(self._hoerfenster_bis - jetzt, 1)})
            from .pipeline import _zeit_loggen

            # Nestors Seite (Ticket #83, Entscheidung Niclas 11.10.: darf mitgespendet werden): erkannte Absicht
            # bzw. Werkzeugaufruf mit Argumenten (aktion), Antworttext bzw. Kartentitel (gesagt), Kartenart, Fehler –
            # je Anfrage EIN Eintrag in logs/nestor.jsonl, zusammengetragen aus dem, was im Bogen ohnehin anfällt.
            kartenart = b.art if b.art != "frage" else next(
                (KARTEN_WERKZEUG[w["name"]] if w["name"] != "karte_zeigen" else (w["argumente"] or {}).get("art")
                 for w in b.werkzeuge if w["name"] in KARTEN_WERKZEUG and not w.get("fehler")), None)
            # Im Gespräch zusätzlich: der zusammengeführte Text, der Zug, alle Werkzeugaufrufe mit Argumenten,
            # nicht_an_mich und ob die Frist bis zum ersten Ton überschritten wurde
            gespraech = ({"text": b.frage, "sprecher": b.sprecher, "zug": b.zug, "gerichtet": b.gerichtet,
                          "werkzeuge": list(b.werkzeuge), "nicht_an_mich": b.verworfen,
                          "frist_ueberschritten": b.frist_ueberschritten} if self.agent else
                         {"werkzeuge": list(b.werkzeuge)})
            _zeit_loggen({"ausloeser": "bogen", "art": b.art, "quelle": b.quelle, "stufe": c.stufe,
                          "abgeloest": b.abgeloest, "aktion": b.aktion, "antwort": b.gesagt,
                          "kartenart": kartenart, "fehler": b.fehler, **gespraech, **b.zeiten})
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
        b.gesagt = satz or ""
        if satz and not b.abgeloest:
            await self._sprechen_texte([satz], bogen=b)

    async def _frage_lauf(self, b: Bogen) -> None:
        """Frage an Nestor: Premium im Realtime-Gespräch (offen oder neu), sonst Text + Sprachausgabe."""
        if self.coach.wahl.assistent_modus == "gespraech" and not self.funkgeraet:
            if self.gespraech is not None and self.gespraech.offen and hasattr(self.gespraech, "frage"):
                await self.gespraech.frage(b)
                return
            if await self._gespraech_starten(b):
                return
        await kern.text_antwort(self, b)

    # --- Lange Aufträge: Bild und Recherche (Ticket #27: kein Bogen, Stau 2/3) ---------------------------------
    def lang_starten(self, art: str, titel: str, fokus: str = "") -> dict:
        """Bild oder Recherche im Hintergrund beginnen; das Ergebnis kommt still in den Verlauf. Läuft schon einer,
        wartet der neue; ein dritter wird abgewehrt. Liefert das Ergebnis für das Modell (coach/kern.py)."""
        offen = [a for a in self.auftraege.liste if a.art in BG.LANG_ARTEN]
        if len(offen) >= 2:
            self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "auftrag_abgewehrt", "auftrag": art})
            return {"ok": False, "fehler": "Es laufen schon zwei Aufträge – erst wenn einer fertig ist."}
        laufend = next((a for a in offen if a.zustand == "laeuft"), offen[0] if offen else None)
        a = self.auftraege.neu(art, titel or BG.NAMEN.get(art, art), self.coach.meeting.jetzt(),
                               zustand="wartet" if offen else "laeuft")
        a.task = asyncio.ensure_future(self._lang_lauf(a, fokus))
        a.task.add_done_callback(lambda _t, a=a: self._lang_fertig(a))
        self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "auftrag", "auftrag": art,
                                     "zustand": a.zustand})
        asyncio.ensure_future(self.coach.melden())
        if laufend:
            return {"ok": True, "wartet_auf": f"{B.ARTEN.get(laufend.art, laufend.art)}: {laufend.titel}",
                    "hinweis": "beginnt, sobald der laufende Auftrag fertig ist; das Ergebnis kommt als Karte"}
        return {"ok": True, "hinweis": "läuft im Hintergrund, das Ergebnis kommt in etwa einer halben Minute als Karte"}

    async def lang_annehmen(self, art: str, titel: str, fokus: str = "", bogen: Bogen | None = None) -> bool:
        """Knopf „Bild“ bzw. „Recherche“: wie lang_starten, dazu „Nehme ich mit …“ bzw. warum es warten muss."""
        if bogen is not None:
            self.text_neu(bogen.frage or BG.NAMEN.get(art))
        laufend = next((a for a in self.auftraege.liste if a.art in BG.LANG_ARTEN), None)
        erg = self.lang_starten(art, titel, fokus)
        if not erg["ok"]:
            satz = B.ABWEHR
        elif laufend is not None:
            satz = B.STAU.get((laufend.art, art), B.ABWEHR)
        else:
            satz = self.floskeln.variante(B.LANGE)
        await self.floskel_sagen(satz, bogen)
        return erg["ok"]

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
            erg = await recherchieren(c._client, frage, c.meeting.titel, wahl=c.wahl)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            from .ki_fehler import melden
            from .mistral import ist_ueberlast

            melden(c, "recherche", e, band=False)  # Ticket #72: die Karte zeigt es, Protokoll und Technikbericht auch
            c._karte_ablegen({"art": "recherche", "frage": frage, "titel": frage[:80], "still": True,
                              "punkte": [kern.UEBERLAST if ist_ueberlast(e) else "Die Recherche hat leider nicht geklappt."]})
            await c.melden()
            return
        nutzung_loggen({"art": "recherche", "modell": self.coach.wahl.recherche_modell, "tokens_rein": erg["tokens_rein"],
                        "tokens_raus": erg["tokens_raus"], "sekunden": erg["sekunden"], "suchen": erg.get("suchen")})
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "recherche", "frage": frage, "quellen": erg["quellen"],
                            "sekunden": erg["sekunden"]})
        c.recherche_merken(frage, erg)
        self.verlauf.append((frage, erg["text"]))
        # Recherche nicht wieder auf vier Zehn-Wort-Stichpunkte einkürzen.
        c._karte_ablegen({"art": "recherche", "frage": frage, "titel": frage[:80], "still": True,
                         "details": erg["text"], "quellen": erg["quellen"]})
        await c.melden()

    # --- Sonstige Sprache (kein Bogen) -------------------------------------------------------------------------
    async def _ja_sagen(self) -> None:
        """Nur der Name: „Ja?“ – aus dem Zwischenspeicher, wenn es ihn gibt (sofort da, kostet nichts)."""
        self.text_neu(None)
        if EINST.bestaetigung:
            await self.floskel_sagen(B.JA)
            self.zustand = "angesprochen"
        else:
            await self._sprechen_texte(["Ja?"], danach="angesprochen")
        # Ticket #28: der nächste Satz gilt sicher als Frage – 12 s ab dem Ende von „Ja?“ (Wiedergabe samt Nachlauf)
        ende = max(self.coach.meeting.jetzt(), self.sprechzeiten[-1][1] if self.sprechzeiten else 0.0)
        self._angesprochen_bis = ende + JA_FENSTER_SEKUNDEN
        await self.coach.melden()

    async def _einwand_erhalten(self) -> None:
        self._einwand_bis = None
        if self.gespraech is not None:  # offene Realtime-Sitzung (auch die Begrüßung): sofort still und zu,
            await self.coach.direkt_senden({"typ": "stimme_stopp"})  # ab jetzt geht kein Ton mehr an OpenAI
            await self.gespraech.schliessen("einwand")
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
            asyncio.ensure_future(self.gespraech.schliessen("gestoppt"))
        self._hoerfenster_zu("gestoppt")
        self.zug = None
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
        # Ein Zug ohne Namen bekommt keine Sofortbestätigung – vielleicht war Nestor gar nicht gemeint; dann kommt
        # sie erst mit einem Werkzeugaufruf (coach/gespraech.py)
        floskel = self.bestaetigung_fuer(b.frage) if b.gerichtet else None
        ton = None
        if floskel:  # hörbar, während die Sitzung aufgebaut wird (Messung: docs/sprachassistent.md)
            ton = asyncio.ensure_future(self.floskel_sagen(floskel, b))
        g = Gespraech(self)
        try:
            await g.starten(b.frage, bogen=b)
            self.gespraech = g
        except Exception as e:  # noqa: BLE001 – Rückfall auf den Text-Weg, damit die Runde eine Antwort bekommt
            if ton is not None:
                await ton
            if not b.gerichtet:  # ob ein Zug ohne Namen gemeint war, kann nur das Gespräch entscheiden – schweigen
                log.warning("Gespräch nicht gestartet (%s) – Zug ohne Namen bleibt unbeantwortet", type(e).__name__)
                b.verworfen = True
                return True
            log.warning("Gespräch nicht gestartet (%s) – Antwort über den Text-Weg", type(e).__name__)
            await kern.text_antwort(self, b, bestaetigt=bool(floskel))
            return True
        await g.warten(b)
        return True

    async def audio(self, pcm24k: bytes) -> None:
        if self.gespraech and self.gespraech.offen:
            await self.gespraech.audio(pcm24k)

    # --- Antworten ----------------------------------------------------------
    def lage(self) -> str:
        """Der aktuelle Stand für jede Anfrage im Gespräch: Agenda mit aktivem Punkt und Zeiten, Ergebnisse mit
        Nummern, laufende Aufträge, Bild/Folie, letzte Karten, die letzten fünf Minuten Transkript mit Sprechern."""
        c, m = self.coach, self.coach.meeting
        jetzt = m.jetzt()
        z = [f"Meeting: {m.titel or '-'} · Ziel: {m.ziel or '-'} · Laufzeit {mmss(jetzt)} min"]
        if m.agenda:
            z.append("Agenda (► = aktueller Punkt):")
            for i, p in enumerate(m.agenda):
                z.append(f"{'►' if i == m.aktiver_punkt else ' '} {i + 1}. {p.titel} [{m.status(i)}; "
                         f"{mmss(m.genutzt(i))} von {p.minuten:.0f} min]" + (f" – Ziel: {p.ziel}" if p.ziel else ""))
        art = getattr(c, "artefakte", None)
        if art is not None:
            z += art.kontext_zeilen() or ["Festgehaltene Artefakte: noch keine."]
        if m.regel_ids:
            z.append("Vereinbarte Regeln: " + ", ".join(NACH_ID[r].titel for r in m.regel_ids if r in NACH_ID))
        if m.hinweise:
            z.append("Letzte Hinweise des Coaches: " + " | ".join(f"[{mmss(h.zeit)}] {h.text}" for h in m.hinweise[-3:]))
        stand = c.status_kurz()
        z.append(f"Live-Bild: {stand['live_bild']} · Folie: {stand['folie']}")
        if self.auftraege.liste:
            z.append("Laufende Aufträge: " + "; ".join(f"{B.ARTEN.get(a.art, a.art)} ({a.zustand}): {a.titel}"
                                                         for a in self.auftraege.liste))
        karten = [k for k in c.karten[-3:] if k.get("titel") or k.get("punkte")]
        if karten:
            z.append("Letzte Karten im Verlauf (die jüngste zuletzt):")
            for k in karten:
                punkte = " | ".join(str(p) for p in (k.get("punkte") or [])[:4])
                z.append(f"[{mmss(k.get('zeit', 0))}] {k.get('titel') or k.get('frage') or ''}: {punkte}"[:400])
        if getattr(c, "letzte_recherche", None):
            r = c.letzte_recherche
            z += ["", f"Letzte Recherche („{r['frage']}“):", r["text"][:1500]]
        saetze = [s for s in m.transkript if s.text and s.start >= jetzt - 300]
        transkript = "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in saetze)
        z += ["", "Transkript der letzten fünf Minuten:", transkript[-6000:] or "(noch nichts)"]
        return "\n".join(z)

    def kontext(self, frage: str) -> str:
        c, m = self.coach, self.coach.meeting
        z = [f"Meeting: {m.titel or '-'} · Ziel: {m.ziel or '-'} · Laufzeit {mmss(m.jetzt())} min"]
        if m.agenda:
            z.append("Agenda:")
            for i, p in enumerate(m.agenda):
                zeile = (f"{i + 1}. {p.titel} [{m.status(i)}; {mmss(m.genutzt(i))} von {p.minuten:.0f} min]"
                         + (f" – Ziel: {p.ziel}" if p.ziel else ""))
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
            z += ["", "Beschreibung des letzten Live-Bilds (kann veraltet sein; Ergebnisse gelten nur aus den "
                  "festgehaltenen Artefakten):", c.onepager_analyse[:2500]]
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

    # --- Sofort bestätigen, Text mitlaufen lassen, Aufträge (Ticket #21) ---------------------------------
    def text_neu(self, frage: str | None = None) -> None:
        """Die nächste Textnachricht ans Dashboard beginnt eine neue Äußerung (mit der Frage, auf die sie antwortet)."""
        self._text_neu = {"frage": frage}

    async def text_senden(self, text: str, delta: bool = False) -> None:
        """Was Nestor gleich sagt, als Text ans Dashboard – vor dem Ton, damit es mitläuft (Basis/Text-Weg: der Satz,
        Realtime: die Transkript-Stücke). Das Dashboard zeigt es im Takt der Wiedergabe."""
        if not text:
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
        if c._client is None or not text or (bogen is not None and bogen.abgeloest):
            return 0.0
        if bogen is not None:
            bogen.merken("floskel")
        if EINST.stimme_aus:
            return len(text) / 14
        pcm = self.floskeln.da(text)
        if pcm is None:
            asyncio.ensure_future(self.floskeln.erzeugen(c._client, text, wahl=c.wahl))
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
        if not EINST.bestaetigung or not B.bestaetigen(frage or ""):
            return None
        return self.floskeln.kurz()

    def floskeln_vorbereiten(self) -> None:
        if EINST.bestaetigung and self.coach._client is not None and not EINST.stimme_aus:
            asyncio.ensure_future(self.floskeln.vorbereiten(self.coach._client, wahl=self.coach.wahl))

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
        if c._client is None or not text.strip() or (bogen is not None and bogen.abgeloest):
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
                    model=self.coach.wahl.stimme_modell, voice=self.coach.wahl.stimme, input=text, response_format="pcm",
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
        nutzung_loggen({"art": "stimme", "modell": self.coach.wahl.stimme_modell, "zeichen": len(text),
                        "sekunden_audio": round(dauer, 1)})
        return dauer
