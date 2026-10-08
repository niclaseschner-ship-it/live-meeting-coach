"""Sofort bestätigen und sichtbar arbeiten (Ticket #21 Punkte 3 und 4).

Bestätigung: Jeden Auftrag bestätigt Nestor sofort kurz („Okay, kleinen Moment“, „Schau ich mir an“). Bei langen
Aufgaben (Bild, Folie, Recherche, Überblick) sagt er, dass es dauert und die Runde weitermachen kann. Die Sätze
sind feste Floskeln, je Stimme einmal erzeugt und auf der Platte zwischengespeichert (Premium: gpt-4o-mini-tts mit
der gewählten Stimme, Basis: Voxtral mit Thorsten). Abgespielt kosten sie nichts und sind ohne Wartezeit da –
gemessen in scripts/bestaetigung_messen.py, Ergebnis in docs/sprachassistent.md.

Aufträge: Was länger dauert, steht als Auftrag in einer Warteschlange („läuft“ / „wartet“) im mittleren Feld des
Dashboards. Jeder Auftrag lässt sich per ✕ oder per Stimme abbrechen („Nestor, lass die Recherche“).
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
KURZ = ["Okay, kleinen Moment.", "Schau ich mir an.", "Moment, ich schau kurz.", "Klar, einen Augenblick.",
        "Alles klar, Moment."]
LANG = ("Mach ich, braucht ein bisschen. Macht ruhig schon weiter, ich zeig's euch hier gleich. "
        "Wenn ihr noch was braucht, sprecht mich einfach an.")
JA = "Ja?"
ABGEBROCHEN = "Okay, lass ich."
NICHTS_OFFEN = "Da läuft gerade nichts."
ALLE = KURZ + [LANG, JA, ABGEBROCHEN, NICHTS_OFFEN]

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


def bestaetigen(frage: str) -> bool:
    """Braucht diese Äußerung eine Bestätigung? Danke, Stopp und Nein nicht."""
    return bool(frage and frage.strip()) and not KEIN_AUFTRAG_RE.match(frage)


class Floskeln:
    """Vorab erzeugte Sätze je Stimme, auf der Platte zwischengespeichert (PCM 24 kHz, 16 bit, mono)."""

    def __init__(self, ordner: str | Path | None = None) -> None:
        self.ordner = Path(ordner or EINST.floskel_ordner)
        self._mem: dict[Path, bytes] = {}
        self._erzeugen: dict[Path, asyncio.Task] = {}
        self._letzte_kurz: str | None = None

    def pfad(self, text: str) -> Path:
        schluessel = f"{EINST.stufe}|{EINST.stimme_modell}|{EINST.stimme}|{STIL if EINST.stufe != 'basis' else ''}|{text}"
        name = hashlib.sha1(schluessel.encode("utf-8")).hexdigest()[:20]
        return self.ordner / f"{EINST.stufe}_{re.sub(r'[^A-Za-z0-9]', '', EINST.stimme)[:12]}_{name}.pcm"

    def da(self, text: str) -> bytes | None:
        """Aus dem Speicher oder von der Platte – ohne Netz, ohne Warten."""
        p = self.pfad(text)
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
        wahl = [k for k in KURZ if k != self._letzte_kurz]
        self._letzte_kurz = random.choice(wahl)
        return self._letzte_kurz

    async def erzeugen(self, client, text: str) -> bytes | None:
        """Einmal per Sprachausgabe erzeugen und ablegen. Mehrere gleichzeitige Wünsche teilen sich einen Aufruf."""
        p = self.pfad(text)
        if (pcm := self.da(text)) is not None:
            return pcm
        if p not in self._erzeugen:
            self._erzeugen[p] = asyncio.ensure_future(self._synthese(client, text, p))
        try:
            return await asyncio.shield(self._erzeugen[p])
        finally:
            if self._erzeugen.get(p) is not None and self._erzeugen[p].done():
                self._erzeugen.pop(p, None)

    async def _synthese(self, client, text: str, p: Path) -> bytes | None:
        t0, teile = time.monotonic(), []
        try:
            async with client.audio.speech.with_streaming_response.create(
                    model=EINST.stimme_modell, voice=EINST.stimme, input=text, response_format="pcm",
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
        nutzung_loggen({"art": "stimme", "zweck": "floskel", "modell": EINST.stimme_modell, "zeichen": len(text),
                        "sekunden_audio": round(len(pcm) / 2 / RATE, 1), "sekunden": round(time.monotonic() - t0, 2)})
        return pcm

    async def vorbereiten(self, client) -> int:
        """Alle fehlenden Floskeln der aktuellen Stimme erzeugen (beim Meetingstart, im Hintergrund). Liefert die
        Zahl neu erzeugter."""
        neu = 0
        for text in ALLE:
            if self.da(text) is None and await self.erzeugen(client, text) is not None:
                neu += 1
        return neu


# --- Aufträge und Warteschlange -----------------------------------------------------------------------------
ARTEN = {"recherche": "Recherche", "bild": "Live-Bild", "folie": "Folie", "ueberblick": "Überblick"}
# Coroutinen, in denen der Coach (coach/pipeline.py) die langen Aufgaben ausführt – darüber findet der Assistent die
# laufende Aufgabe, ohne dass die Pipeline davon wissen muss
PIPELINE_CORO = {"bild": "_onepager_zeichnen", "folie": "_folie_bauen", "ueberblick": "ueberblick_bauen"}

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


def coro_name(task: asyncio.Task) -> str:
    coro = task.get_coro()
    return getattr(getattr(coro, "cr_code", None), "co_name", "") or getattr(coro, "__name__", "")


def pipeline_aufgaben(art: str, ausser: set | None = None) -> list[asyncio.Task]:
    """Laufende Aufgaben des Coaches für eine Art (Bild, Folie, Überblick), die noch keinem Auftrag gehören."""
    name = PIPELINE_CORO.get(art)
    if not name:
        return []
    try:
        alle = asyncio.all_tasks()
    except RuntimeError:
        return []
    return [t for t in alle if not t.done() and coro_name(t) == name and t not in (ausser or set())]
