"""Sofort bestätigen und sichtbar arbeiten (Ticket #21, seit Ticket #27 Teil des Antwortbogens).

Bestätigung: Jeden Auftrag bestätigt Nestor sofort kurz – bei Zuruf, Sprechtaste und Knopf gleich, mit zwei bis drei
Varianten je Art, damit es nicht maschinell klingt („Bin dran.“, „Moment, kommt gleich.“). Lange Aufträge (Bild,
Recherche) sagen stattdessen, dass es dauert und die Runde weitermachen kann; ein zweiter langer Auftrag wartet
(„Ich bin noch am Bild, die Recherche mache ich danach.“), ein dritter wird abgewehrt. Die Sätze sind feste Floskeln,
je Stimme einmal erzeugt und auf der Platte zwischengespeichert (Premium: gpt-4o-mini-tts mit der gewählten Stimme,
Basis: Voxtral mit Thorsten). Abgespielt kosten sie nichts und sind ohne Wartezeit da – gemessen in
scripts/bestaetigung_messen.py, Ergebnis in docs/sprachassistent.md.

Aufträge: Was länger dauert (Bild, Recherche), steht als Auftrag im Arbeitsring oben rechts („1 läuft · 1 wartet“).
Jeder Auftrag lässt sich per ✕ oder per Stimme abbrechen („Nestor, lass die Recherche“).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import EINST

log = logging.getLogger("coach.bestaetigung")

RATE = 24000

# --- Floskeln ---------------------------------------------------------------------------------------------
# Ticket #27: zwei bis drei Varianten je Art, für Knopf, Zuruf und Sprechtaste gleich.
# Kurze Bögen sind meist nach ein bis drei Sekunden fertig. Die Bestätigung darf deshalb
# keinen längeren Arbeitsgang versprechen; dafür gibt es ausschließlich LANGE.
KURZ = ["Mhm.", "Moment.", "Bin dran."]
LANGE = ["Nehme ich mit, dauert ein bisschen. Macht ruhig weiter.",
         "Mach ich, das dauert einen Moment. Redet ruhig weiter."]
LANG = LANGE[0]
# Stau (höchstens zwei lange Aufträge): (läuft, neu) -> Satz; ein dritter wird abgewehrt
STAU = {("bild", "recherche"): "Ich bin noch am Bild, die Recherche mache ich danach.",
        ("recherche", "bild"): "Ich bin noch an der Recherche, das Bild mache ich danach.",
        ("recherche", "recherche"): "Ich bin noch an der Recherche, die nächste mache ich danach.",
        ("bild", "bild"): "Ich bin noch am Bild, das nächste mache ich danach."}
ABWEHR = "Ich hab gerade zwei Sachen auf dem Zettel. Fragt mich gleich nochmal."
NOTIERT = ["Notiert.", "Ist notiert."]
# Seh-Inhalt (Folie, Überblick, Liste): kein Inhalt gesprochen, nur der Hinweis, dass die Karte da ist
HIER = {"folie": "Hier ist die Folie.", "ueberblick": "Hier ist der Überblick.", "festgehalten": "Hier ist die Liste.",
        "karte": "Hier ist sie."}
JA = "Ja?"
ABGEBROCHEN = "Okay, lass ich."
NICHTS_OFFEN = "Da läuft gerade nichts."
ALLE = KURZ + LANGE + list(STAU.values()) + [ABWEHR] + NOTIERT + list(HIER.values()) + [JA, ABGEBROCHEN,
                                                                                       NICHTS_OFFEN]

STIL = ("Sprich locker, freundlich und zügig auf Deutsch, wie ein Kollege, der kurz Bescheid gibt. "
        "Natürliches Tempo, keine langen Pausen.")

# Woran man vor der Antwort erkennt, dass es länger dauert (Bild, Folie, Recherche, Überblick als Text).
LANG_RE = re.compile(
    r"recherch|\bschau\w* (?:mal |kurz )?nach\b|\bsuch\w* (?:mal |kurz )?(?:raus|nach|im netz)|im (?:inter)?netz"
    r"|\büberblick (?:zu|über)\b|\bueberblick (?:zu|ueber)\b|aktuelle[nr]? (?:stand|fakten|zahlen) (?:zu|bei|von)"
    r"|\bfolie\b|\bbild\b|zeichn|visuell|\bübersicht\b|\buebersicht\b|aufmal", re.IGNORECASE)
# Kein Auftrag – nichts zu bestätigen („Nestor, danke“, „Nestor, stopp“, ein spätes Nein)
KEIN_AUFTRAG_RE = re.compile(r"^\W*(?:danke|dankeschön|vielen dank|passt|gut|okay|ok|super|stopp|stop|still|ruhe|"
                             r"nein|tschüss|das war'?s|das wars)\b", re.IGNORECASE)


def stille_kuerzen(pcm: bytes, schwelle: int = 500, vorne: float = 0.03, hinten: float = 0.12) -> bytes:
    """Stille am Anfang und Ende abschneiden: gpt-4o-mini-tts hängt bis zu 1,3 s an (gemessen 08.10.), und Stille
    vorn verzögert die Bestätigung, Stille hinten das, was danach kommt."""
    import numpy as np

    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2")
    laut = np.flatnonzero(np.abs(x.astype(np.int32)) > schwelle)
    if not len(laut):
        return pcm
    a = max(0, int(laut[0] - vorne * RATE))
    b = min(len(x), int(laut[-1] + hinten * RATE))
    return x[a:b].tobytes()


def ist_lang(frage: str) -> bool:
    return bool(LANG_RE.search(frage or ""))


RECHERCHE_AUFTRAG_RE = re.compile(
    r"\b(?:recherchier\w*|such\w*\s+(?:bitte\s+|mal\s+|kurz\s+)*(?:im\s+(?:inter)?netz\s+)?(?:nach\s+)?|"
    r"schau\w*\s+(?:bitte\s+|mal\s+|kurz\s+)*(?:im\s+(?:inter)?netz\s+)?nach\b)",
    re.IGNORECASE,
)


def recherche_auftrag(frage: str) -> bool:
    """Explizite Suchaufträge vor dem Sprachmodell erkennen.

    Reine Wissensfragen bleiben normale Fragen; nur Verben wie „recherchier“, „such … nach“
    oder „schau … nach“ starten sicher die Websuche.
    """
    return bool(RECHERCHE_AUFTRAG_RE.search(frage or ""))


def bestaetigen(frage: str) -> bool:
    """Braucht diese Äußerung eine Bestätigung? Danke, Stopp und Nein nicht."""
    return bool(frage and frage.strip()) and not KEIN_AUFTRAG_RE.match(frage)


class Floskeln:
    """Vorab erzeugte Sätze je Stimme, auf der Platte zwischengespeichert (PCM 24 kHz, 16 bit, mono)."""

    def __init__(self, ordner: str | Path | None = None, wahl=None) -> None:
        """`wahl`: liefert die Anbieterwahl des Meetings (coach/anbieter.py) – Stufe und Stimme gehören zum Schlüssel."""
        self.ordner = Path(ordner or EINST.floskel_ordner)
        self._wahl = wahl or (lambda: None)
        self._mem: dict[Path, bytes] = {}
        self._erzeugen: dict[Path, asyncio.Task] = {}
        self._letzte: dict[int, str] = {}

    def wahl(self, wahl=None):
        w = wahl or self._wahl()
        if w is None:
            from .anbieter import AnbieterFehler

            raise AnbieterFehler("Floskeln ohne Anbieterwahl")
        return w

    def pfad(self, text: str, wahl=None) -> Path:
        w = self.wahl(wahl)
        schluessel = f"{w.stufe}|{w.stimme_modell}|{w.stimme}|{STIL if not w.basis else ''}|{text}"
        name = hashlib.sha1(schluessel.encode("utf-8")).hexdigest()[:20]
        return self.ordner / f"{w.stufe}_{re.sub(r'[^A-Za-z0-9]', '', w.stimme)[:12]}_{name}.pcm"

    def da(self, text: str, wahl=None) -> bytes | None:
        """Aus dem Speicher oder von der Platte – ohne Netz, ohne Warten."""
        p = self.pfad(text, wahl)
        if p in self._mem:
            return self._mem[p]
        try:
            pcm = p.read_bytes()
        except OSError:
            return None
        if not pcm:
            return None
        pcm = stille_kuerzen(pcm)
        self._mem[p] = pcm
        return pcm

    def kurz(self) -> str:
        """Wechselnde kurze Floskel, nie zweimal hintereinander dieselbe."""
        return self.variante(KURZ)

    def variante(self, liste: list[str]) -> str:
        """Eine der Varianten, nie zweimal hintereinander dieselbe (je Liste)."""
        letzte = self._letzte.get(id(liste))
        wahl = [k for k in liste if k != letzte] or list(liste)
        self._letzte[id(liste)] = random.choice(wahl)
        return self._letzte[id(liste)]

    async def erzeugen(self, client, text: str, *, wahl=None) -> bytes | None:
        """Einmal per Sprachausgabe erzeugen und ablegen. Mehrere gleichzeitige Wünsche teilen sich einen Aufruf."""
        w = self.wahl(wahl)
        p = self.pfad(text, w)
        if (pcm := self.da(text, w)) is not None:
            return pcm
        if p not in self._erzeugen:
            self._erzeugen[p] = asyncio.ensure_future(self._synthese(client, text, p, w))
        try:
            return await asyncio.shield(self._erzeugen[p])
        finally:
            if self._erzeugen.get(p) is not None and self._erzeugen[p].done():
                self._erzeugen.pop(p, None)

    async def _synthese(self, client, text: str, p: Path, w) -> bytes | None:
        t0, teile = time.monotonic(), []
        try:
            async with client.audio.speech.with_streaming_response.create(
                    model=w.stimme_modell, voice=w.stimme, input=text, response_format="pcm",
                    instructions=STIL) as antwort:
                async for stueck in antwort.iter_bytes(9600):
                    teile.append(stueck)
        except Exception as e:  # noqa: BLE001
            log.warning("Floskel nicht erzeugt (%s)", type(e).__name__)
            return None
        pcm = stille_kuerzen(b"".join(teile))
        if not pcm:
            return None
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(pcm)
            tmp.replace(p)
        except OSError as e:
            log.warning("Floskel nicht gespeichert (%s)", type(e).__name__)
        self._mem[p] = pcm
        from .pipeline import nutzung_loggen
        nutzung_loggen({"art": "stimme", "zweck": "floskel", "modell": w.stimme_modell, "zeichen": len(text),
                        "sekunden_audio": round(len(pcm) / 2 / RATE, 1), "sekunden": round(time.monotonic() - t0, 2)})
        return pcm

    async def vorbereiten(self, client, *, wahl=None) -> int:
        """Alle fehlenden Floskeln der aktuellen Stimme erzeugen (beim Meetingstart, im Hintergrund). Liefert die
        Zahl neu erzeugter."""
        neu = 0
        for text in ALLE:
            w = self.wahl(wahl)
            if self.da(text, w) is None and await self.erzeugen(client, text, wahl=w) is not None:
                neu += 1
        return neu


# --- Aufträge und Warteschlange -----------------------------------------------------------------------------
ARTEN = {"recherche": "Recherche", "bild": "Live-Bild", "folie": "Folie", "ueberblick": "Überblick"}
ART_RE = {
    "recherche": re.compile(r"recherch|such|nachschau|\bnetz\b", re.IGNORECASE),
    "folie": re.compile(r"\bfolie", re.IGNORECASE),
    "bild": re.compile(r"\bbild|zeichn|übersicht|uebersicht|visuell", re.IGNORECASE),
    "ueberblick": re.compile(r"überblick|ueberblick|übersicht|uebersicht", re.IGNORECASE),
}
_ART_WORT = r"(?:recherche|suche|folie|bild|zeichnung|übersicht|uebersicht|überblick|ueberblick)"
ABBRUCH_RE = re.compile(
    rf"\b(?:lass|vergiss|stopp|stoppe|stop|streich|cancel)\w*\s+(?:die|das|den|deine|mal die|mal das)?\s*{_ART_WORT}"
    rf"|{_ART_WORT}\w*\s+(?:abbrechen|stoppen|canceln|vergessen|lassen|brauchen wir nicht|nicht mehr)"
    rf"|\bbrich\s+(?:die|das|den)?\s*(?:{_ART_WORT}\w*\s+)?ab\b"
    r"|\b(?:abbrechen|lass das|lass es|vergiss das|vergiss es)\b",
    re.IGNORECASE)


def abbruch_wunsch(text: str) -> bool:
    return bool(ABBRUCH_RE.search(text or ""))


def abbruch_art(text: str) -> str | None:
    """Welche Art ist gemeint? None = keine genannt (dann der jüngste Auftrag)."""
    for art in ("folie", "recherche", "bild", "ueberblick"):
        if ART_RE[art].search(text):
            return art
    return None


@dataclass
class Auftrag:
    id: int
    art: str
    titel: str
    seit: float
    zustand: str = "laeuft"  # laeuft | wartet
    task: asyncio.Task | None = None
    beim_abbruch: list = field(default_factory=list)

    def bild(self) -> dict:
        return {"id": self.id, "art": self.art, "name": ARTEN.get(self.art, self.art), "titel": self.titel,
                "zustand": self.zustand, "seit": round(self.seit, 1)}


class Auftraege:
    def __init__(self) -> None:
        self.liste: list[Auftrag] = []
        self._n = 0
        self.melden = None  # Rückruf (async), wenn sich die Liste von selbst ändert (Aufgabe fertig)

    def neu(self, art: str, titel: str, seit: float, task: asyncio.Task | None = None,
            zustand: str = "laeuft") -> Auftrag:
        self._n += 1
        a = Auftrag(self._n, art, (titel or "").strip()[:120], seit, zustand)
        self.liste.append(a)
        if task is not None:
            self.verbinden(a, task)
            a.zustand = zustand
        return a

    def verbinden(self, a: Auftrag, task: asyncio.Task) -> None:
        a.task, a.zustand = task, "laeuft"
        task.add_done_callback(lambda _t, a=a: self._fertig(a))

    def _fertig(self, a: Auftrag) -> None:
        if a in self.liste:
            self.liste.remove(a)
            if self.melden is not None:
                try:
                    asyncio.ensure_future(self.melden())
                except RuntimeError:
                    pass

    def entfernen(self, a: Auftrag) -> None:
        if a in self.liste:
            self.liste.remove(a)

    def offen(self, art: str | None = None) -> list[Auftrag]:
        return [a for a in self.liste if art is None or a.art == art]

    def holen(self, nr: int) -> Auftrag | None:
        return next((a for a in self.liste if a.id == nr), None)

    def ziel(self, text: str) -> Auftrag | None:
        """Den Auftrag zu einem Abbruchwunsch: die genannte Art (der jüngste davon), sonst der jüngste überhaupt.
        „Übersicht“ meint in Premium das Bild, in Basis den Überblick – deshalb beide prüfen."""
        art = abbruch_art(text)
        kandidaten = self.offen(art) if art else list(self.liste)
        if not kandidaten and art in ("bild", "ueberblick"):
            kandidaten = self.offen("ueberblick" if art == "bild" else "bild")
        return kandidaten[-1] if kandidaten else None

    def abbrechen(self, a: Auftrag) -> None:
        self.entfernen(a)
        for f in a.beim_abbruch:
            try:
                f()
            except Exception as e:  # noqa: BLE001
                log.warning("Abbruch: Aufräumen fehlgeschlagen (%s)", type(e).__name__)
        if a.task is not None and not a.task.done():
            a.task.cancel()

    def schnappschuss(self) -> list[dict]:
        return [a.bild() for a in self.liste]
