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

from . import bestaetigung as B
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
AKTION: eintragen <nummer>; wer=…; bis=…     – Aufgabe, Entscheidung, offenen Punkt oder Risiko ergänzen, wenn
AKTION: eintragen neu <typ>; was=…; wer=…; bis=…   die Gruppe es dir sagt („Sofie übernimmt die Statusseite bis
                            Freitag“). Nummer aus „Festgehaltene Artefakte“ unten; typ ist aufgabe, entscheidung,
                            offen oder risiko; weitere Felder: status=endgueltig|vorlaeufig, reaktion=…. Bestätige
                            danach in einem kurzen Satz, was eingetragen ist.

Beispiel:
AKTION: keine
Ihr seid bei Punkt zwei, dem Budget. Entschieden ist noch nichts, offen ist die Frage nach dem Puffer.
"""


BILD_ZEILE = "                            Sag dazu, dass das Bild etwa eine bis zwei Minuten dauert.\n"
# Nestor Basis (und Überblick als Text): „AKTION: bild“ zeigt den Überblick als Text – er steht nach wenigen Sekunden
BILD_ZEILE_TEXT = ("                            Nur bei dieser Aktion sagst du dazu, dass die Übersicht gleich im\n"
                   "                            Dashboard erscheint.\n")
BILD_TEXT = ("Übersicht über das Meeting (Entschiedenes, Offenes,\n"
             "                            Aufgaben) ins Dashboard stellen – auch bei „visuelle Übersicht“, „Bild“ oder\n"
             "                            „zeig uns die Übersicht“")
FOLIE_ZEILE = ("                            wenn die Gruppe das möchte („ja, mach eine Folie“). Sag, dass sie gleich "
               "erscheint.\n")
FOLIE_ZEILE_KLAR = ("                            nur wenn ausdrücklich eine Folie gewünscht ist („ja, mach eine Folie“).\n"
                    "                            Eine Übersicht über das Meeting ist keine Folie. Sag, dass sie gleich "
                    "erscheint.\n")
UEBERLAST = "Ich komme gerade nicht durch, versucht es gleich nochmal."
LANGE_AKTIONEN = ("bild", "recherche", "folie")
# Ticket #21: Bestätigung und Wartezeit spricht das System vorab (coach/bestaetigung.py)
BESTAETIGUNG_HINWEIS = """
Eine kurze Bestätigung („Okay, kleinen Moment“) hat das System schon gesprochen, bevor deine Antwort kommt. Fang
deshalb nicht mit „Okay“, „Moment“, „Klar“ oder „Gern“ an, sondern direkt mit dem Inhalt. Bei bild, recherche und
folie sagt das System auch schon, dass es ein bisschen dauert und wo es erscheint – schreib nach der Aktionszeile dann
nichts mehr.
"""


def system_text() -> str:
    """Systemanweisung für die gewählte Stufe: in Basis entsteht auf „AKTION: bild“ der Überblick als Text."""
    s = SYSTEM.format(name=EINST.assistent_name)
    if EINST.bild_anbieter == "text":
        s = s.replace("visuelle Übersicht zeichnen lassen", BILD_TEXT).replace(BILD_ZEILE, BILD_ZEILE_TEXT)
    s = s.replace(FOLIE_ZEILE, FOLIE_ZEILE_KLAR)
    return s + BESTAETIGUNG_HINWEIS if EINST.bestaetigung else s


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


def begruessungstext(meeting, basis: bool | None = None) -> tuple[str, str]:
    """(Begrüßung mit Einwilligung, Startsatz).

    Feste Fassung: Rückfall der freien Begrüßung (coach/begruessung.py, Ticket #23) und Standard in Basis. Danach geht
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
        self.sprechtexte: list[tuple[float, float, str]] = []  # dasselbe mit dem gesprochenen Text (Textweg)
        self.echo_im_abspielen = False  # Testläufe (scripts/cloudtest_lokal.py): eigene Sprache filtern wie live
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
        # Ticket #21: Sofort-Bestätigung mit vorab erzeugten Floskeln, Aufträge als Warteschlange, Text läuft mit
        self.floskeln = B.Floskeln()
        self.auftraege = B.Auftraege()
        self.auftraege.melden = coach.melden
        self.recherche_sperre = asyncio.Lock()  # eine Recherche nach der anderen, weitere warten
        self.lang_angesagt = False  # für die laufende Frage ist „braucht ein bisschen“ schon gesagt
        self._text_neu: dict | None = None  # die nächste Textnachricht beginnt eine neue Äußerung

    # --- Zustand nach außen ------------------------------------------------
    def schnappschuss(self) -> dict:
        return {"aktiv": self.aktiv, "name": EINST.assistent_name, "zustand": self.zustand,
                "letzte": self.letzte, "auftraege": self.auftraege.schnappschuss()}

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
        self.floskeln_vorbereiten()  # Ticket #21: Floskeln der Stimme erzeugen, falls sie fehlen (einmal je Stimme)
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
        if vorstellung:  # Vorstellungsrunde: Namen und Stimmen kennenlernen
            if not frei:  # der freie Text enthält die Bitte schon
                await self._sprechen_texte([VORSTELLUNG_BITTE])
            ende = self.sprechzeiten[-1][1] if self.sprechzeiten else self.coach.meeting.jetzt()
            self.vorstellung_bis = ende + EINST.vorstellung_sekunden
            self._einwand_bis = max(self._einwand_bis, ende + EINST.einwand_sekunden)
        elif not frei:
            await self._sprechen_texte([start], stil=STIL_START)

    async def _begruessen_frei(self) -> bool:
        """Premium (Ticket #23): Begrüßung frei im Realtime-Gespräch. False = nicht zustande gekommen, dann spricht
        der Aufrufer die feste Fassung. Fehlt im hörbar Gesagten ein Teil der Einwilligung, folgt der feste Nachsatz."""
        if EINST.stufe == "basis" or EINST.begruessung != "frei" or EINST.assistent_modus != "gespraech":
            return False
        from .begruessung import PUNKT_EINS_RE, Begruessung, nachsatz, pflicht_fehlt

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
            await self._sprechen_texte([VORSTELLUNG_BITTE], danach=danach)
        elif not vorstellung and b.ergebnis == "abgebrochen" and not PUNKT_EINS_RE.search(gesagt):
            _, start = begruessungstext(self.coach.meeting)  # Verbindung weg vor dem Start: fest zu Ende sagen
            await self._sprechen_texte([start], danach="bereit", stil=STIL_START)
        ende = self.sprechzeiten[-1][1] if self.sprechzeiten else self.coach.meeting.jetzt()
        self._einwand_bis = ende + EINST.einwand_sekunden
        if vorstellung:
            self.vorstellung_bis = ende + EINST.vorstellung_sekunden
        if self.zustand == "begruessung":
            self.zustand = danach
            await self.coach.melden()
        return True

    def takt(self) -> None:
        """Vom Coach-Takt: Ende der Vorstellungsrunde → Start ansagen; Ende des Fensters für ein einfaches Nein."""
        jetzt = self.coach.meeting.jetzt()
        if self.auftraege.liste:
            self.auftraege_abgleichen()
        if self._einwand_bis is not None and jetzt > self._einwand_bis:
            self._einwand_bis = None
        if self.vorstellung_bis is not None and jetzt > self.vorstellung_bis:
            self.vorstellung_bis = None
            self._starten(self._start_nach_vorstellung())

    async def _start_nach_vorstellung(self) -> None:
        """Nach der Vorstellungsrunde: frei im noch offenen Begrüßungsgespräch, sonst der feste Startsatz."""
        g = self.gespraech
        if g is not None and g.offen and hasattr(g, "start_sagen") and await g.start_sagen():
            return
        await self._sprechen_texte([vorstellung_start(self.coach.meeting)], stil=STIL_START)

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
        if angesprochen(text) and B.abbruch_wunsch(text) and (self.auftraege.liste or B.abbruch_art(text)):
            await self._abbruch_per_stimme(text)  # „Nestor, lass die Recherche“ (Ticket #21)
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
            self._starten(self._ja_sagen())
            await self.coach.melden()
            return
        self._angesprochen_bis = -1e9
        self._starten(self._antworten(frage))

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
        if self._aufgabe and not self._aufgabe.done():
            self._aufgabe.cancel()
        if self.gespraech:
            asyncio.ensure_future(self.gespraech.schliessen())
        self.zustand = "pausiert" if self.pausiert else "bereit"

    async def sagen(self, text: str) -> float:
        """Wie `ansagen`, wartet aber, bis es gesagt ist (Nachfrage und Zusammenfassung, Ticket #26) – danach beginnt
        das Fenster für die Antwort der Runde. Liefert die ungefähre Dauer in Sekunden (0, wenn Nestor schweigt)."""
        if not self.aktiv or self.pausiert or self.ansprache_aus or self.coach._client is None:
            return 0.0
        g = self.gespraech
        if g is not None and g.offen:
            await g.ansagen(text, woertlich=True)
            for _ in range(60):  # bis das Modell die Ansage gesprochen hat (höchstens ~30 s)
                await asyncio.sleep(0.5)
                if not g._antwort_laeuft:
                    break
            return len(text) / 14
        if self._aufgabe and not self._aufgabe.done():
            for _ in range(60):  # nicht in eine laufende Antwort hinein
                await asyncio.sleep(0.5)
                if self._aufgabe.done():
                    break
        self.text_neu(None)
        return await self._sprechen_texte([text])

    def ansagen(self, text: str) -> None:
        """Kurze Ansage, die eine laufende Antwort nicht abbricht (z. B. „Das Bild ist fertig“).

        Ist ein Gespräch offen, spricht Nestor sie dort – sonst gäbe es zwei Stimmen gleichzeitig (Test 05.10.).
        """
        if not self.aktiv or self.pausiert or self.ansprache_aus:
            return
        if self.gespraech and self.gespraech.offen:
            asyncio.ensure_future(self.gespraech.ansagen(text))
        else:
            self.text_neu(None)
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
        self.text_neu(frage)
        floskel = self.bestaetigung_fuer(frage) if frage else (B.JA if EINST.bestaetigung else None)
        if floskel:  # Ticket #21: hörbar, während die Sitzung aufgebaut wird (Messung: docs/sprachassistent.md)
            asyncio.ensure_future(self.floskel_sagen(floskel))
        g = Gespraech(self)
        try:
            await g.starten(frage, ja_gesagt=floskel == B.JA)
            self.gespraech = g
        except Exception as e:  # noqa: BLE001 – Rückfall auf den Text-Weg, damit die Runde eine Antwort bekommt
            log.warning("Gespräch nicht gestartet (%s) – Antwort über den Text-Weg", type(e).__name__)
            if frage:
                await self._antworten(frage, bestaetigt=bool(floskel))
            else:
                self._angesprochen_bis = self.coach.meeting.jetzt() + 10
                if floskel != B.JA:
                    await self._sprechen_texte(["Ja?"], danach="angesprochen")

    async def recherche_vorlesen(self, frage: str) -> None:
        """Textmodus: Recherche ausführen und das Ergebnis vorlesen."""
        from .pipeline import nutzung_loggen
        from .recherche import recherchieren

        c = self.coach
        auftrag = self.auftraege.neu("recherche", frage, c.meeting.jetzt(), task=asyncio.current_task(),
                                     zustand="wartet" if self.recherche_sperre.locked() else "laeuft")
        self.zustand = "recherchiert"
        await c.melden()
        try:
            async with self.recherche_sperre:
                auftrag.zustand = "laeuft"
                await c.melden()
                erg = await recherchieren(c._client, frage, c.meeting.titel)
        except asyncio.CancelledError:
            self.auftraege.entfernen(auftrag)
            if self.zustand == "recherchiert":
                self.zustand = "bereit"
            await c.melden()
            raise
        except Exception as e:  # noqa: BLE001
            from .mistral import ist_ueberlast

            self.auftraege.entfernen(auftrag)
            log.warning("Recherche fehlgeschlagen: %s", type(e).__name__)
            self.text_neu(frage)
            await self._sprechen_texte([UEBERLAST if ist_ueberlast(e) else "Die Recherche hat leider nicht geklappt."])
            return
        self.auftraege.entfernen(auftrag)  # fertig – das Vorlesen bricht „still“ ab, nicht ✕
        nutzung_loggen({"art": "recherche", "modell": EINST.recherche_modell, "tokens_rein": erg["tokens_rein"],
                        "tokens_raus": erg["tokens_raus"], "sekunden": erg["sekunden"], "suchen": erg.get("suchen")})
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "recherche", "frage": frage, "quellen": erg["quellen"],
                            "sekunden": erg["sekunden"]})
        c.recherche_merken(frage, erg)
        c.antwort_karte(frage, erg["text"], None, erg["quellen"])
        self.letzte = {"frage": frage, "antwort": erg["text"], "zeit": c.meeting.jetzt(), "aktion": None,
                       "quellen": erg["quellen"]}
        saetze, rest = saetze_teilen(erg["text"] + " ")
        self.text_neu(frage)
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
        transkript = "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in m.transkript if s.text)
        z += ["", "Transkript (neuester Teil):", transkript[-9000:] or "(noch nichts)"]
        for f, a in self.verlauf[-2:]:
            z += ["", f"Frühere Frage an dich: {f}", f"Deine Antwort: {a}"]
        z += ["", f"Frage an dich: {frage}"]
        return "\n".join(z)

    async def _antworten(self, frage: str, bestaetigt: bool = False) -> None:
        c = self.coach
        self.zustand = "denkt"
        await c.melden()
        t0 = time.monotonic()
        aktion, gesprochen, puffer, erste_zeile = None, [], "", None
        saetze: asyncio.Queue = asyncio.Queue()
        if not bestaetigt:
            self.text_neu(frage)
        floskel = None if bestaetigt else self.bestaetigung_fuer(frage)
        if floskel:  # Ticket #21: sofort hörbar, während das Sprachmodell noch denkt
            saetze.put_nowait(("floskel", floskel))
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
                    aktion = aktion_pruefen(aktion_lesen(erste_zeile), frage)
                    if aktion and aktion["typ"] in LANGE_AKTIONEN and EINST.bestaetigung and not self.lang_angesagt:
                        self.lang_angesagt = True
                        await saetze.put(("floskel", B.LANG))
                    if not AKTION_RE.match(erste_zeile):  # Aktionszeile vergessen – dann ist sie schon Text
                        puffer = erste_zeile + " " + puffer
                fertig, puffer = saetze_teilen(puffer)
                for s in fertig:
                    gesprochen.append(s)
                    await saetze.put(s)
            if erste_zeile is None:  # sehr kurze Antwort ohne Zeilenumbruch
                aktion = aktion_pruefen(aktion_lesen(puffer), frage)
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
        if antwort:
            c.antwort_karte(frage, antwort, aktion, [])
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "assistent", "frage": frage, "antwort": antwort,
                            "aktion": aktion, "sekunden": round(time.monotonic() - t0, 1)})
        await c.melden()
        if aktion:
            await c.assistent_aktion(aktion)
            self.auftrag_nach_aktion(aktion, frage)
            await c.melden()
        await sprecher
        self._nachfrage_bis = c.meeting.jetzt() + EINST.nachfrage_sekunden

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

    async def floskel_sagen(self, text: str) -> float:
        """Eine Floskel aus dem Zwischenspeicher abspielen – ohne Sprachausgabe-Aufruf, ohne Wartezeit. Fehlt sie
        noch (erster Lauf mit dieser Stimme), wird sie dieses eine Mal live gesprochen und danach abgelegt."""
        c = self.coach
        if c._client is None or not text or self.ansprache_aus:
            return 0.0
        if EINST.stimme_aus:
            return len(text) / 14
        pcm = self.floskeln.da(text)
        if pcm is None:
            asyncio.ensure_future(self.floskeln.erzeugen(c._client, text))
            return await self._sprechen(text, B.STIL, zustand_setzen=False)
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
        kein Auftrag, „danke“). Die lange Ansage („braucht ein bisschen …“) kommt erst, wenn das Modell die lange
        Aufgabe wirklich anstößt (Aktionszeile bzw. Werkzeug, 0,4–1,1 s): Aus der Frage geraten, passte sie im
        Probelauf 08.10. nicht – „Überblick zum Mindestlohn“ angekündigt, das Modell bot dann ein Bild an."""
        if not EINST.bestaetigung or self.ansprache_aus or not B.bestaetigen(frage or ""):
            return None
        self.lang_angesagt = False
        return self.floskeln.kurz()

    async def lang_ansagen(self) -> None:
        """Eine lange Aufgabe beginnt (Werkzeug im Gespräch): die Wartezeit jetzt ansagen, einmal je Frage."""
        if EINST.bestaetigung and not self.lang_angesagt:
            self.lang_angesagt = True
            await self.floskel_sagen(B.LANG)

    def floskeln_vorbereiten(self) -> None:
        if EINST.bestaetigung and self.coach._client is not None and not EINST.stimme_aus:
            asyncio.ensure_future(self.floskeln.vorbereiten(self.coach._client))

    def auftrag_nach_aktion(self, aktion: dict | None, titel: str) -> B.Auftrag | None:
        """Bild, Folie oder Überblick hat der Coach gerade angestoßen (coach/pipeline.py): als Auftrag führen. Läuft
        schon eins und wird nachgeholt (Bild), wartet der neue Auftrag."""
        if not aktion:
            return None
        art = "ueberblick" if aktion["typ"] == "bild" and EINST.bild_anbieter == "text" else aktion["typ"]
        if art not in B.PIPELINE_CORO:
            return None
        c, jetzt = self.coach, self.coach.meeting.jetzt()
        vergeben = {a.task for a in self.auftraege.liste if a.task is not None}
        neu = B.pipeline_aufgaben(art, vergeben)
        if neu:
            a = self.auftraege.neu(art, titel, jetzt, task=neu[0])
        elif art == "bild" and getattr(c, "_onepager_nachholen", False):
            a = self.auftraege.neu(art, titel, jetzt, zustand="wartet")
        else:
            return None
        a.beim_abbruch.append(lambda: self._pipeline_abbruch(a))
        return a

    def _pipeline_abbruch(self, a: B.Auftrag) -> None:
        c = self.coach
        if a.task is not None:  # abgebrochen, bevor die Aufgabe lief, räumt sie selbst nicht auf
            a.task.add_done_callback(lambda _t, art=a.art: self._pipeline_aufraeumen(art))
        if a.art == "bild":
            if a.zustand == "wartet" or not any(x.zustand == "wartet" for x in self.auftraege.offen("bild")):
                c._onepager_nachholen = False
            if not self.auftraege.offen("bild"):
                self._bild_ansage = False
        elif a.art == "ueberblick":
            c._ueberblick_nachholen = False

    def _pipeline_aufraeumen(self, art: str) -> None:
        if B.pipeline_aufgaben(art):
            return  # schon die nächste (nachgeholt) – deren Zustand gilt
        flagge = {"bild": "_onepager_laeuft", "folie": "_folie_laeuft", "ueberblick": "_ueberblick_laeuft"}[art]
        if getattr(self.coach, flagge, False):
            setattr(self.coach, flagge, False)
            asyncio.ensure_future(self.coach.melden())

    def auftraege_abgleichen(self) -> None:
        """Wartende Aufträge an die nächste Aufgabe des Coaches hängen, sobald sie beginnt; verschwundene weg."""
        c = self.coach
        for a in [x for x in self.auftraege.liste if x.zustand == "wartet" and x.art in B.PIPELINE_CORO]:
            if any(x.zustand == "laeuft" for x in self.auftraege.offen(a.art)):
                continue
            vergeben = {x.task for x in self.auftraege.liste if x.task is not None}
            neu = B.pipeline_aufgaben(a.art, vergeben)
            if neu:
                self.auftraege.verbinden(a, neu[0])
            elif not getattr(c, "_onepager_laeuft", False) and not getattr(c, "_onepager_nachholen", False):
                self.auftraege.entfernen(a)

    def auftrag_abbrechen(self, nr: int) -> bool:
        """✕ im Dashboard oder „Nestor, lass die Recherche“."""
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
    async def _sprechen_warteschlange(self, saetze: asyncio.Queue) -> float:
        dauer = 0.0
        while (s := await saetze.get()) is not None:
            # ("floskel", Text): Bestätigung aus dem Zwischenspeicher, in derselben Reihenfolge wie die Sätze
            dauer += await (self.floskel_sagen(s[1]) if isinstance(s, tuple) else self._sprechen(s))
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

    async def _sprechen(self, text: str, stil: str | None = None, zustand_setzen: bool = True) -> float:
        """Einen Satz synthetisieren und gestreamt ans Dashboard schicken. Liefert die Tondauer in Sekunden."""
        c = self.coach
        if c._client is None or not text.strip() or self.ansprache_aus:
            return 0.0
        if EINST.stimme_aus:  # Tests: keine Sprachausgabe, Dauer grob geschätzt (~14 Zeichen je Sekunde)
            return len(text) / 14
        await self.text_senden(text)  # Ticket #21: der Satz steht im Dashboard, sobald sein Ton beginnt
        if zustand_setzen and self.zustand not in ("begruessung", "pausiert"):
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
        self.sprechtexte[-1] = (beginn, beginn + dauer + NACHLAUF_SEKUNDEN, text)
        from .pipeline import nutzung_loggen
        nutzung_loggen({"art": "stimme", "modell": EINST.stimme_modell, "zeichen": len(text),
                        "sekunden_audio": round(dauer, 1)})
        return dauer
