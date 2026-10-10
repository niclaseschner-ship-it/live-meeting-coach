"""Hörstrom (Version 2): Audio rein, Teiltext, Sprecherabschnitte und fertige Sätze heraus.

    24-kHz-Audio ──► Live-Text (OpenAI bzw. Mistral in Basis, Streaming) ─────────────────► Teiltext, fertiger Satz
         │
         └─ 16 kHz ─► Pausenerkennung (lokal) ─► Äußerung ─► commit an Live-Text
                                                      └──► Stimm-Fingerabdruck je Fenster (lokal) ─► Personen, Überlappung

Die Meetinguhr folgt der Audiozeit – live wie im Abspielmodus.

Modus „Auf Knopfdruck“ (Lastenheft 3, 4.2): kein Live-Text und keine Transkription je Äußerung. Jede Äußerung
wartet als WAV in `warteschlange`, bis ein Knopf `nachtranskribieren()` aufruft – dann über denselben Weg wie
„sparsam“ (`_transkribieren`), höchstens vier gleichzeitig, Sätze in der Reihenfolge des Sprechens.
Pausenerkennung, Stimm-Fingerabdruck, Überlappung und Unterbrechung laufen unverändert.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import logging
import time
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .config import EINST
from .livetext import LiveText, LiveTextMistral
from .unterbrechung import Aeusserung, pegel_db
from .stimmen import Stimmen
from .vad import Pausenerkennung
from .zustand import Segment

log = logging.getLogger("coach.hoeren")


def nach_16k(a24: np.ndarray) -> np.ndarray:
    """24 kHz → 16 kHz (Faktor 2/3) per linearer Interpolation; reicht für Pausen und Fingerabdruck."""
    if not len(a24):
        return a24
    ziel = np.arange(0, len(a24) - 1e-9, 1.5)
    return np.interp(ziel, np.arange(len(a24)), a24).astype(np.float32)


def prompt_echo(text: str, prompt: str) -> bool:
    """Bei leisen oder sehr kurzen Äußerungen liefert die Transkription manchmal den Kontext-Prompt zurück
    („Besprechung auf Deutsch. Der Moderationsassistent heißt Nestor …“) – das darf Nestor nie auslösen
    (Testlauf 05.10.2026, Frankfurt 24:34)."""
    def norm(s: str) -> str:
        return " ".join("".join(z.lower() if z.isalnum() else " " for z in s).split())

    t, p = norm(text), norm(prompt)
    if len(t) < 12 or not p:
        return False
    if t in p or t.startswith(("besprechung auf deutsch", "meeting in english")):
        return True
    worte = t.split()
    return len(worte) >= 4 and " ".join(worte[:4]) in p and sum(w in p.split() for w in worte) >= 0.8 * len(worte)


def text_cache_datei(wav: bytes, modell: str):
    """Zwischenspeicher für Tests (LMC_TEXT_CACHE): Schlüssel ist der Inhalt der Äußerung, Abspielen ist
    deterministisch – derselbe Lauf ergibt dieselben Äußerungen und kostet beim zweiten Mal nichts."""
    if not EINST.text_cache:
        return None
    import hashlib
    from pathlib import Path

    h = hashlib.sha1(wav + f"{modell}|{EINST.sprache}|v2".encode()).hexdigest()  # Sprache gehört zum Prompt
    return Path(EINST.text_cache) / h[:2] / f"{h}.txt"


def wav_aus(proben: np.ndarray) -> bytes:
    """Äußerung (16 kHz, float) als WAV, so wie sie an die Transkription geht – auch Schlüssel des Zwischenspeichers."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(proben, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


MIN_TEXT = 0.3  # s – kürzere Äußerungen gehen nicht an die Transkription
KNOPF_GLEICHZEITIG = 4  # Knopfdruck: so viele Äußerungen werden gleichzeitig transkribiert


UNSICHER = "Person ?"


def person_name(index: int | None) -> str:
    return f"Person {index + 1}" if index is not None else UNSICHER


MIN_TEIL = 1.0      # s – kürzere Sprecherabschnitte bekommen keine eigene Transkriptzeile
SATZENDE = ".?!…:"


def text_aufteilen(text: str, abschnitte: list[tuple[float, float, int | None]]) -> list[tuple[int | None, str, float, float]]:
    """Äußerung mit Sprecherwechsel in Zeilen je Person teilen (Raumtest 06.10.: Hörbuch, Stimmen gehen nahtlos
    ineinander über – eine Zeile pro Äußerung zeigte nur die überwiegende Person und nie „Person ?“).

    Der Live-Text liefert keine Wortzeiten; der Text wird deshalb nach Sprechzeit geteilt und die Grenze auf das
    nächste Satzende gelegt (Wechsel fallen meist dorthin), sonst auf die nächste Wortgrenze.
    Gibt (person, text, von, bis) relativ zur Äußerung zurück; ein Element, wenn es nichts zu teilen gibt.
    """
    teile: list[list] = []
    for a, b, p in abschnitte:  # gleiche Person zusammenfassen
        if teile and teile[-1][2] == p:
            teile[-1][1] = b
        else:
            teile.append([a, b, p])
    while len(teile) > 1:  # Splitter dem längeren Nachbarn zuschlagen
        i = min(range(len(teile)), key=lambda k: teile[k][1] - teile[k][0])
        if teile[i][1] - teile[i][0] >= MIN_TEIL:
            break
        j = i - 1 if i == len(teile) - 1 or (i > 0 and teile[i - 1][1] - teile[i - 1][0] >= teile[i + 1][1] - teile[i + 1][0]) else i + 1
        a, b = min(teile[i][0], teile[j][0]), max(teile[i][1], teile[j][1])
        teile[j][0], teile[j][1] = a, b
        del teile[i]
        k = 0
        while k < len(teile) - 1:  # nach dem Zuschlagen erneut gleiche Nachbarn verbinden
            if teile[k][2] == teile[k + 1][2]:
                teile[k][1] = teile[k + 1][1]
                del teile[k + 1]
            else:
                k += 1
    woerter = text.split()
    if len(teile) < 2 or len(woerter) < 2 * len(teile):
        p = teile[0][2] if teile else None
        return [(p, text, abschnitte[0][0] if abschnitte else 0.0, abschnitte[-1][1] if abschnitte else 0.0)]
    t0, t1 = teile[0][0], teile[-1][1]
    # Wortgrenzen: Index des ersten Worts der neuen Zeile; Zeichenposition für den Zeitanteil
    pos, n = [], 0
    for w in woerter:
        pos.append(n)
        n += len(w) + 1
    schnitte, letzter = [], 0
    for k in range(1, len(teile)):
        ziel = n * (teile[k][0] - t0) / max(1e-6, t1 - t0)
        rest = len(teile) - k  # so viele Zeilen brauchen danach noch mindestens ein Wort
        kandidaten = [i for i in range(letzter + 1, len(woerter) - rest + 1)]
        if not kandidaten:
            break
        satz = [i for i in kandidaten if woerter[i - 1][-1] in SATZENDE and abs(pos[i] - ziel) <= 0.2 * n]
        i = min(satz or kandidaten, key=lambda i: abs(pos[i] - ziel))
        schnitte.append(i)
        letzter = i
    grenzen = [0, *schnitte, len(woerter)]
    return [(teile[k][2], " ".join(woerter[grenzen[k]:grenzen[k + 1]]), teile[k][0], teile[k][1])
            for k in range(len(grenzen) - 1)]


class Hoerstrom:
    def __init__(self, coach, mit_text: bool) -> None:
        self.coach = coach
        self.vad = Pausenerkennung()
        self.stimmen = Stimmen()
        self.sekunden = 0.0
        self._rest24 = np.zeros(0, dtype=np.float32)
        self._offen: dict[int, dict] = {}
        self._naechste_id = 0
        self._rechner = ThreadPoolExecutor(max_workers=1)  # Reihenfolge der Zuordnung bleibt erhalten
        self._analysen: list[asyncio.Future] = []
        self.vektoren: deque = deque(maxlen=300)  # (start, ende, Fingerabdruck) je Äußerung – Namen (Ticket #27)
        self.live = None
        # Knopfdruck: nichts geht von selbst an einen KI-Dienst; Äußerungen warten auf den Knopf
        self.knopfdruck = coach.modus == "knopfdruck"
        self.warteschlange: list[dict] = []  # {uid, start, ende, wav, person}: noch nicht transkribiert
        self._verworfen_bis = -1.0  # Meetingzeit: Äußerungen, die davor begannen, bekommen keinen Text mehr
        self.sparsam = mit_text and EINST.live_art == "sparsam" and not self.knopfdruck  # Text je Äußerung statt Streaming
        self._vorlage = None  # Tests: {(start, ende): text} aus einem früheren Bericht (LMC_TEXT_VORLAGE)
        if (self.sparsam or self.knopfdruck) and EINST.text_cache and os.getenv("LMC_TEXT_VORLAGE"):
            import json

            bericht = json.loads(open(os.environ["LMC_TEXT_VORLAGE"], encoding="utf-8").read())
            self._vorlage = {(round(s["start"], 1), round(s["ende"], 1)): s["text"] for s in bericht["transkript"]}
        self._letzter_text: asyncio.Future | None = None
        self.text_sekunden = 0.0
        if mit_text and not self.sparsam and not self.knopfdruck:
            m = coach.meeting
            stichwoerter = [p.titel for p in m.agenda] + m.teilnehmende
            if coach.assistent.aktiv:
                stichwoerter.append(EINST.assistent_name)  # Ansprache: „Mestor“ statt „Nestor“ vermeiden
            # Basis: Voxtral Realtime (Mistral), Premium: OpenAI – gleiche Schnittstelle (Ticket #13); Endpunkt,
            # Schlüssel und Hostwache kommen aus der Anbieterwahl des Meetings (coach/anbieter.py, Ticket #60)
            klasse = LiveTextMistral if coach.wahl.basis else LiveText
            self.live = klasse(self._teiltext, self._satz, coach.vokabel_prompt(), stichwoerter,
                               wahl=coach.wahl, bei_verstoss=coach.anbieter_verstoss)

    async def starten(self) -> None:
        if self.live:
            await self.live.verbinden()

    async def zufuehren(self, pcm24k: bytes) -> None:
        if self.coach.stumm or self.coach.assistent.pausiert:
            # Die Gruppe hat „Nein“ gesagt oder pausiert: nichts geht an den Live-Text, die Pausenerkennung
            # bekommt Stille (damit ihre Zeitachse weiter zur Meetinguhr passt).
            pcm24k = bytes(len(pcm24k))
            if self.live and hasattr(self.live, "luecke"):
                self.live.luecke(len(pcm24k) / 2 / 24000)  # Voxtral: Audiozeit läuft weiter, ohne zu senden
        else:
            if self.live:
                await self.live.audio(pcm24k)
            await self.coach.assistent.audio(pcm24k)  # offenes Gespräch mit Nestor hört direkt mit
        a24 = np.concatenate([self._rest24, np.frombuffer(pcm24k, dtype="<i2").astype(np.float32) / 32768])
        n = len(a24) // 3 * 3  # ganze 3er-Gruppen, damit 24k→16k sauber aufgeht
        self._rest24 = a24[n:]
        self.sekunden += len(pcm24k) / 2 / 24000
        m = self.coach.meeting
        m.virtuelle_zeit = self.sekunden
        for start, ende, proben in self.vad.zufuehren(nach_16k(a24[:n])):
            await self._aeusserung(start, ende, proben)
        if self.vad.spricht:
            self.coach.sprache_melden()

    async def beenden(self) -> None:
        for start, ende, proben in self.vad.ende():
            await self._aeusserung(start, ende, proben)
        if self._analysen:
            await asyncio.gather(*self._analysen, return_exceptions=True)
        if self.live:
            await self.live.schliessen()
            self.coach.live_text_kosten(self.live.gesendete_sekunden)
        # Sätze, deren Text nie kam (z. B. ohne Live-Text), trotzdem mit Sprecher ausgeben
        for uid in list(self._offen):
            self._offen[uid]["text"] = self._offen[uid]["text"] or ""
            await self._ausgeben(uid)
        self._rechner.shutdown(wait=False)

    async def text_abwarten(self, zeitlimit: float = 12.0) -> None:
        """Knopf nach einem Redebeitrag: aktuellen VAD-Block abschließen und auf seinen Text warten.

        Kein Stoppen des Audiostroms; neu eintreffende Äußerungen gehören nicht zur Momentaufnahme.
        Bei Ausfall lieber einen wiederholbaren Fehler als eine scheinbar vollständige alte Antwort.
        """
        if self.knopfdruck:
            return  # dessen Knopf-Pipeline transkribiert selbst
        for start, ende, proben in self.vad.ende():
            await self._aeusserung(start, ende, proben)
        offen = set(self._offen)
        deadline = asyncio.get_running_loop().time() + zeitlimit
        while offen.intersection(self._offen):
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Der letzte Redebeitrag wird noch transkribiert. Bitte gleich erneut versuchen.")
            await asyncio.sleep(0.05)

    # --- intern -------------------------------------------------------------
    async def _aeusserung(self, start: float, ende: float, proben: np.ndarray) -> None:
        uid = self._naechste_id
        self._naechste_id += 1
        self._offen[uid] = {"start": start, "ende": ende, "person": None, "person_fertig": False, "text": None,
                            "pegel": pegel_db(proben)}  # Regel 1: Pegel-Einbruch = Übergabe, kein Unterbrechen
        knopf = None
        if self.live:
            await self.live.commit({"id": uid, "ende": ende})  # Ende: Zuordnung bei Voxtral
        elif self.knopfdruck:
            if len(proben) >= 16000 * MIN_TEXT and start >= self._verworfen_bis:
                # als WAV (16 bit) statt float: halber Speicher, und genau die Bytes für Transkription und Zwischenspeicher
                knopf = {"uid": uid, "start": start, "ende": ende, "dauer": len(proben) / 16000, "wav": wav_aus(proben)}
                self.warteschlange.append(knopf)
            else:
                self._offen[uid]["text"] = ""
        elif self.sparsam:
            vorher, self._letzter_text = self._letzter_text, None
            self._letzter_text = asyncio.ensure_future(self._text_je_aeusserung(uid, proben, vorher))
            self._analysen.append(self._letzter_text)
        else:
            self._offen[uid]["text"] = ""
        loop = asyncio.get_running_loop()
        zukunft = loop.run_in_executor(self._rechner, self.stimmen.analysieren, proben)
        person = asyncio.ensure_future(self._person(uid, zukunft))
        self._analysen.append(person)
        if knopf is not None:
            knopf["person"] = person  # der Knopf wartet darauf, bevor er den Satz ausgibt

    async def _person(self, uid: int, zukunft) -> None:
        try:
            erg = await zukunft
        except Exception:  # noqa: BLE001
            log.exception("Stimmanalyse fehlgeschlagen")
            erg = {"person": None, "abschnitte": [], "mischung": []}
        o = self._offen.get(uid)
        if o is None:
            return
        # Transkriptzeile: überwiegende Person; Sprecherspur: Abschnitte je Person (Wechsel innerhalb der Äußerung)
        o["person"] = person_name(erg["person"])
        o["abschnitte"] = erg["abschnitte"]
        if erg.get("vektor") is not None:
            self.vektoren.append((o["start"], o["ende"], erg["vektor"]))
        o["person_fertig"] = True
        mischung = [o["start"] + x for x in erg["mischung"]]
        abschnitte = [Segment(person_name(p), "", o["start"] + a, o["start"] + b) for a, b, p in erg["abschnitte"]]
        ueber = ([(o["start"] + a, o["start"] + b) for a, b in erg["ueberlappung"]]
                 if "ueberlappung" in erg else None)  # None: ohne Segmentierung keine gezählten Vorfälle
        await self.coach.sprecher_abschnitt(abschnitte, o["ende"], mischung, ueber)
        # Regel 1 nur mit sicher zugeordneten Abschnitten – „Person ?“ ist kein Sprecherwechsel
        sicher = [(a, b, p) for a, b, p in erg["abschnitte"] if p is not None]
        self.coach.aeusserung_merken(Aeusserung(o["start"], o["ende"], sicher, o["pegel"]))
        await self._ausgeben(uid)

    def vektor_an(self, start: float, ende: float):
        """Fingerabdruck der Äußerung, die [start, ende] am meisten überlappt (oder None)."""
        best, beste = None, 0.0
        for a, b, v in reversed(self.vektoren):
            if b < start - 5:
                break
            ueber = min(b, ende) - max(a, start)
            if ueber > beste:
                best, beste = v, ueber
        return best

    async def _text_je_aeusserung(self, uid: int, proben: np.ndarray, vorher) -> None:
        """Sparmodus: die Äußerung als WAV an die Transkription; Sätze bleiben in der Reihenfolge des Sprechens."""
        text = ""
        if self.coach._client is not None and len(proben) >= 16000 * MIN_TEXT:
            text = await self._transkribieren(uid, wav_aus(proben), len(proben) / 16000)
        await self._text_ausgeben(uid, text, vorher)

    async def _transkribieren(self, uid: int, wav: bytes, dauer: float, sperre: asyncio.Semaphore | None = None) -> str:
        """Eine Äußerung transkribieren (Sparmodus und Knopfdruck); `sperre` begrenzt gleichzeitige Aufrufe."""
        from .pipeline import fehlertext, nutzung_loggen

        c = self.coach
        t0 = time.monotonic()
        prompt = c.vokabel_prompt()[-800:]
        cache = text_cache_datei(wav, c.wahl.text_modell)
        if cache is not None and not cache.exists() and self._vorlage is not None:
            # Transkript eines früheren Laufs: gleiche Äußerungsgrenzen -> gleicher Text
            o = self._offen.get(uid) or {}
            treffer = self._vorlage.get((round(o.get("start", -1), 1), round(o.get("ende", -1), 1)))
            if treffer:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(treffer, encoding="utf-8")
        if cache is not None and cache.exists():  # Tests: dieselbe Äußerung wurde schon einmal transkribiert
            text = cache.read_text(encoding="utf-8")
            if prompt_echo(text, prompt):  # auch alte Zwischenspeicher-Einträge filtern
                text = ""
            return text
        text = ""
        try:
            async with sperre or contextlib.nullcontext():
                antwort = await c._client.audio.transcriptions.create(
                    model=c.wahl.text_modell, file=("aeusserung.wav", wav, "audio/wav"),
                    language=EINST.sprache, prompt=prompt or None)
            text = (getattr(antwort, "text", "") or "").strip()
            if prompt_echo(text, prompt):
                log.info("Transkription gab den Kontext-Prompt zurück – verworfen")
                text = ""
        except Exception as e:  # noqa: BLE001
            log.warning("Transkription je Äußerung fehlgeschlagen: %s", fehlertext(e))
        if cache is not None and text:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
        self.text_sekunden += dauer
        nutzung_loggen({"art": "text", "modell": c.wahl.text_modell, "sekunden_audio": round(dauer, 1),
                        "sekunden": round(time.monotonic() - t0, 2)})
        return text

    # --- Knopfdruck -------------------------------------------------------------
    def offen(self) -> dict:
        """Was noch nicht transkribiert ist: Äußerungen, Sprechzeit und Meetingzeit seit der ersten davon."""
        w = self.warteschlange
        return {"aeusserungen": len(w), "sprache_sekunden": round(sum(e["dauer"] for e in w), 1),
                "seit_sekunden": round(max(0.0, self.sekunden - w[0]["start"]), 1) if w else 0.0}

    async def nachtranskribieren(self, fortschritt=None) -> dict:
        """Knopf: genau die offenen Äußerungen transkribieren, höchstens vier gleichzeitig. Fertige Sätze gehen in der
        Reihenfolge des Sprechens über `coach.satz()` ins Transkript; `fortschritt(fertig, gesamt)` nach jeder.
        Was währenddessen gesprochen wird, bleibt für den nächsten Knopf in der Warteschlange."""
        offen, self.warteschlange = self.warteschlange, []
        sperre = asyncio.Semaphore(KNOPF_GLEICHZEITIG)
        gesamt, fertig = len(offen), 0

        async def eins(e: dict, vorher) -> None:
            nonlocal fertig
            text = await self._transkribieren(e["uid"], e["wav"], e["dauer"], sperre)
            await asyncio.gather(e["person"], return_exceptions=True)  # ohne feste Person kein Satz
            await self._text_ausgeben(e["uid"], text, vorher)
            fertig += 1
            if fortschritt is not None:
                await fortschritt(fertig, gesamt)

        aufgaben, vorher = [], None
        for e in offen:
            vorher = asyncio.ensure_future(eins(e, vorher))  # jede wartet vor der Ausgabe auf die vorige
            aufgaben.append(vorher)
        if aufgaben:
            await asyncio.gather(*aufgaben)
        return {"aeusserungen": gesamt, "sprache_sekunden": round(sum(e["dauer"] for e in offen), 1)}

    def verwerfen(self, seit: float) -> int:
        """Alle Äußerungen, die nach `seit` enden, aus der Warteschlange nehmen; auch eine gerade laufende Äußerung
        bekommt keinen Text mehr. Sprecherabschnitte (Redeanteile) bleiben. Liefert die Zahl der verworfenen."""
        weg = [e for e in self.warteschlange if e["ende"] > seit]
        self.warteschlange = [e for e in self.warteschlange if e["ende"] <= seit]
        for e in weg:
            o = self._offen.get(e["uid"])
            if o is not None:
                o["text"] = ""  # der Satz entfällt; die Person zählt trotzdem (_person -> _ausgeben)
        self._verworfen_bis = self.sekunden
        return len(weg)

    async def _text_ausgeben(self, uid: int, text: str, vorher) -> None:
        if vorher is not None:
            await asyncio.gather(vorher, return_exceptions=True)  # Reihenfolge wahren
        o = self._offen.get(uid)
        if o is not None:
            o["text"] = text
            await self._ausgeben(uid)

    async def _teiltext(self, text: str) -> None:
        await self.coach.teiltext(text)

    async def _satz(self, meta: dict, text: str) -> None:
        o = self._offen.get(meta["id"])
        if o is None:
            return
        o["text"] = text
        await self._ausgeben(meta["id"])

    async def _ausgeben(self, uid: int) -> None:
        o = self._offen.get(uid)
        if o is None or not o["person_fertig"] or o["text"] is None:
            return
        del self._offen[uid]
        if o["text"]:
            ganz = Segment(o["person"], o["text"], o["start"], o["ende"])
            teile = text_aufteilen(o["text"], o.get("abschnitte") or [])
            zeilen = ([Segment(person_name(p), tx, o["start"] + a, o["start"] + b) for p, tx, a, b in teile]
                      if len(teile) > 1 else None)
            await self.coach.satz(ganz, zeilen)
