"""Hörstrom (Version 2): Audio rein, Teiltext, Sprecherabschnitte und fertige Sätze heraus.

    24-kHz-Audio ──► Live-Text (OpenAI, Streaming) ─────────────────► Teiltext, fertiger Satz
         │
         └─ 16 kHz ─► Pausenerkennung (lokal) ─► Äußerung ─► commit an Live-Text
                                                      └──► Stimm-Fingerabdruck je Fenster (lokal) ─► Personen, Überlappung

Die Meetinguhr folgt der Audiozeit – live wie im Abspielmodus.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .config import EINST
from .livetext import LiveText
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


def person_name(index: int | None) -> str:
    return f"Person {index + 1}" if index is not None else "–"


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
        self.live = None
        self.sparsam = mit_text and EINST.live_art == "sparsam"  # Text je Äußerung statt Streaming
        self._letzter_text: asyncio.Future | None = None
        self.text_sekunden = 0.0
        if mit_text and not self.sparsam:
            m = coach.meeting
            stichwoerter = [p.titel for p in m.agenda] + m.teilnehmende
            if coach.assistent.aktiv:
                stichwoerter.append(EINST.assistent_name)  # Ansprache: „Mestor“ statt „Nestor“ vermeiden
            self.live = LiveText(self._teiltext, self._satz, coach.vokabel_prompt(), stichwoerter)

    async def starten(self) -> None:
        if self.live:
            await self.live.verbinden()

    async def zufuehren(self, pcm24k: bytes) -> None:
        if self.coach.stumm or self.coach.assistent.pausiert:
            # Die Gruppe hat „Nein“ gesagt oder pausiert: nichts geht an den Live-Text, die Pausenerkennung
            # bekommt Stille (damit ihre Zeitachse weiter zur Meetinguhr passt).
            pcm24k = bytes(len(pcm24k))
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

    # --- intern -------------------------------------------------------------
    async def _aeusserung(self, start: float, ende: float, proben: np.ndarray) -> None:
        uid = self._naechste_id
        self._naechste_id += 1
        self._offen[uid] = {"start": start, "ende": ende, "person": None, "person_fertig": False, "text": None,
                            "pegel": pegel_db(proben)}  # Regel 1: Pegel-Einbruch = Übergabe, kein Unterbrechen
        if self.live:
            await self.live.commit({"id": uid})
        elif self.sparsam:
            vorher, self._letzter_text = self._letzter_text, None
            self._letzter_text = asyncio.ensure_future(self._text_je_aeusserung(uid, proben, vorher))
            self._analysen.append(self._letzter_text)
        else:
            self._offen[uid]["text"] = ""
        loop = asyncio.get_running_loop()
        zukunft = loop.run_in_executor(self._rechner, self.stimmen.analysieren, proben)
        self._analysen.append(asyncio.ensure_future(self._person(uid, zukunft)))

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
        o["person_fertig"] = True
        mischung = [o["start"] + x for x in erg["mischung"]]
        abschnitte = [Segment(person_name(p), "", o["start"] + a, o["start"] + b) for a, b, p in erg["abschnitte"]]
        await self.coach.sprecher_abschnitt(abschnitte, o["ende"], mischung)
        self.coach.aeusserung_merken(Aeusserung(o["start"], o["ende"], erg["abschnitte"], o["pegel"]))
        await self._ausgeben(uid)

    async def _text_je_aeusserung(self, uid: int, proben: np.ndarray, vorher) -> None:
        """Sparmodus: die Äußerung als WAV an die Transkription; Sätze bleiben in der Reihenfolge des Sprechens."""
        from .pipeline import fehlertext, nutzung_loggen

        c = self.coach
        text = ""
        if c._client is not None and len(proben) >= 16000 * 0.3:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes((np.clip(proben, -1, 1) * 32767).astype("<i2").tobytes())
            t0 = time.monotonic()
            try:
                antwort = await c._client.audio.transcriptions.create(
                    model=EINST.text_modell, file=("aeusserung.wav", buf.getvalue(), "audio/wav"),
                    language=EINST.sprache, prompt=c.vokabel_prompt()[-800:] or None)
                text = (getattr(antwort, "text", "") or "").strip()
            except Exception as e:  # noqa: BLE001
                log.warning("Transkription je Äußerung fehlgeschlagen: %s", fehlertext(e))
            dauer = len(proben) / 16000
            self.text_sekunden += dauer
            nutzung_loggen({"art": "text", "modell": EINST.text_modell, "sekunden_audio": round(dauer, 1),
                            "sekunden": round(time.monotonic() - t0, 2)})
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
            await self.coach.satz(Segment(o["person"], o["text"], o["start"], o["ende"]))
