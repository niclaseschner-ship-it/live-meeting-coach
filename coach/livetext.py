"""Strom 1 Live-Text: OpenAI Realtime-Transkription (gpt-live-transcribe) über WebSocket.

Das Modell streamt Teiltext schon während des Sprechens. Äußerungsgrenzen setzt unsere lokale
Pausenerkennung: am Ende jeder Äußerung schicken wir `input_audio_buffer.commit` und bekommen den
fertigen Satz. Das Modell liefert weder Zeitstempel noch Sprecher – beides kommt aus unseren
eigenen Strömen; die Zuordnung läuft über die Reihenfolge der Commits.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time

import numpy as np

from .config import EINST, openai_schluessel

log = logging.getLogger("coach.livetext")
URL = "wss://api.openai.com/v1/realtime?intent=transcription"
RATE = 24000


class Zuordnung:
    """Verknüpft Ereignisse der API (item_id) mit unseren Äußerungen – ohne Netzwerk testbar.

    Reihenfolge: Teiltext kann vor dem Commit kommen; der Commit verrät die item_id der Äußerung;
    der fertige Text kann vor oder nach dem Commit-Ereignis eintreffen.
    """

    def __init__(self) -> None:
        self._wartend: list[dict] = []  # Äußerungen, für die commit gesendet, aber item_id noch unbekannt
        self._item_zu_meta: dict[str, dict] = {}
        self._fertig_ohne_meta: dict[str, str] = {}

    def commit_gesendet(self, meta: dict) -> None:
        self._wartend.append(meta)

    def commit_bestaetigt(self, item_id: str) -> tuple[dict, str] | None:
        """Liefert (meta, text), falls der fertige Text schon vorher eingetroffen war."""
        if not self._wartend:
            return None
        meta = self._wartend.pop(0)
        self._item_zu_meta[item_id] = meta
        if item_id in self._fertig_ohne_meta:
            return meta, self._fertig_ohne_meta.pop(item_id)
        return None

    def fertig(self, item_id: str, text: str) -> tuple[dict, str] | None:
        meta = self._item_zu_meta.pop(item_id, None)
        if meta is None:
            self._fertig_ohne_meta[item_id] = text
            return None
        return meta, text


class LiveText:
    def __init__(self, bei_teiltext, bei_satz, prompt: str = "", stichwoerter: list[str] | None = None) -> None:
        self._bei_teiltext = bei_teiltext  # async (text) – laufender Teiltext der aktuellen Äußerung
        self._bei_satz = bei_satz  # async (meta, text) – fertiger Satz zu unserer Äußerung
        self._prompt = prompt
        self._stichwoerter = [s for s in (stichwoerter or []) if s and "<" not in s and ">" not in s][:50]
        self._ws = None
        self._empfang: asyncio.Task | None = None
        self._zuordnung = Zuordnung()
        self._teil: dict[str, str] = {}
        self.gesendete_sekunden = 0.0
        self.fehler: str | None = None

    async def verbinden(self) -> None:
        import websockets

        kopf = {"Authorization": f"Bearer {openai_schluessel()}"}
        self._ws = await websockets.connect(URL, additional_headers=kopf, max_size=None)
        transkription = {"model": EINST.live_modell, "languages": [EINST.sprache], "delay": EINST.live_delay}
        if self._prompt:
            transkription["prompt"] = self._prompt[:1000]
        if self._stichwoerter:
            transkription["keywords"] = self._stichwoerter
        await self._ws.send(json.dumps({"type": "session.update", "session": {
            "type": "transcription",
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": RATE},
                                "transcription": transkription, "turn_detection": None}}}}))
        self._empfang = asyncio.create_task(self._empfangen())

    async def audio(self, pcm24k: bytes) -> None:
        if self._ws is None:
            return
        self.gesendete_sekunden += len(pcm24k) / 2 / RATE
        await self._ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm24k).decode()}))

    async def commit(self, meta: dict) -> None:
        if self._ws is None:
            return
        self._zuordnung.commit_gesendet(meta)
        await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def schliessen(self, nachlauf: float = 5.0) -> None:
        if self._ws is None:
            return
        await asyncio.sleep(nachlauf)  # letzte fertige Sätze abwarten
        if self._empfang:
            self._empfang.cancel()
        await self._ws.close()
        self._ws = None

    async def _empfangen(self) -> None:
        try:
            async for roh in self._ws:
                e = json.loads(roh)
                typ = e.get("type", "")
                if typ == "error":
                    # Nur die Meldung, keine Kopfdaten – kann sonst Kennungen enthalten
                    self.fehler = str(e.get("error", {}).get("message", "unbekannt"))[:200]
                    log.warning("Live-Text: %s", self.fehler)
                elif typ == "input_audio_buffer.committed":
                    treffer = self._zuordnung.commit_bestaetigt(e["item_id"])
                    if treffer:
                        await self._bei_satz(*treffer)
                elif typ.endswith("input_audio_transcription.delta"):
                    self._teil[e["item_id"]] = self._teil.get(e["item_id"], "") + e.get("delta", "")
                    await self._bei_teiltext(self._teil[e["item_id"]])
                elif typ.endswith("input_audio_transcription.completed"):
                    self._teil.pop(e["item_id"], None)
                    treffer = self._zuordnung.fertig(e["item_id"], e.get("transcript", "").strip())
                    if treffer:
                        await self._bei_satz(*treffer)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001 – Verbindungsabbruch sichtbar machen
            self.fehler = f"Verbindung getrennt: {type(e).__name__}"
            log.warning("Live-Text: %s", self.fehler)


# --- Nestor Basis: Voxtral Realtime (Mistral) ----------------------------------------------------------------------
MISTRAL_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime?model={modell}"
MISTRAL_RATE = 16000  # Voxtral arbeitet mit 16 kHz; das Mikro liefert 24 kHz → hier umgerechnet
NACHLAUF_TEXT = 1.0  # s Audiozeit nach Äußerungsende: bis dahin gehört ankommender Text noch zur Äußerung
STILLE_EMIT = 0.12  # s ohne neuen Text, wenn der Satz mit Satzzeichen endet → sofort ausgeben
WANDUHR_FRIST = 1.6  # s nach dem Commit: spätestens dann ausgeben (falls kein Audio mehr nachkommt, z. B. stumm)


class TextZuordnung:
    """Voxtral Realtime kennt keine Äußerungen: es streamt Text ohne Zeitstempel und ohne Commit. Unsere
    Pausenerkennung kennt die Äußerungsgrenzen. Jedes Textstück bekommt deshalb die Audiozeit, zu der es ankam;
    zu einer Äußerung (Ende e) gehört alles, was bis e + NACHLAUF_TEXT ankam. Die nächste Äußerung beginnt frühestens
    eine Pause (0,5 s) später, und ihr Text kommt mit ~0,5 s Verzug – die Grenze trennt also sauber.

    Ausgegeben wird, sobald der Text mit einem Satzzeichen endet und kurz nichts mehr kam (typisch ~0,6 s nach
    Sprechende), sonst nach NACHLAUF_TEXT Audiozeit bzw. WANDUHR_FRIST Wanduhrzeit. Ohne Netzwerk testbar."""

    def __init__(self) -> None:
        self.stuecke: list[tuple[float, str]] = []  # (Audiozeit bei Ankunft, Text)
        self.wartend: list[tuple[dict, float, float]] = []  # (meta, Äußerungsende, Wanduhr beim Commit)
        self.letzte_ankunft = 0.0  # Wanduhr

    def text(self, pos: float, stueck: str, wand: float) -> None:
        self.stuecke.append((pos, stueck))
        self.letzte_ankunft = wand

    def teiltext(self) -> str:
        return "".join(t for _, t in self.stuecke).strip()

    def commit(self, meta: dict, ende: float, wand: float) -> None:
        self.wartend.append((meta, ende, wand))

    def faellig(self, pos: float, wand: float, alles: bool = False) -> list[tuple[dict, str]]:
        aus = []
        while self.wartend:
            meta, ende, t_commit = self.wartend[0]
            grenze = ende + NACHLAUF_TEXT
            dazu = [s for s in self.stuecke if s[0] <= grenze]
            text = "".join(t for _, t in dazu).strip()
            satz_fertig = bool(text) and text[-1] in ".?!…" and wand - self.letzte_ankunft >= STILLE_EMIT
            if not (alles or pos >= grenze or wand - t_commit >= WANDUHR_FRIST or satz_fertig):
                break
            self.wartend.pop(0)
            self.stuecke = self.stuecke[len(dazu):]
            aus.append((meta, text))
        return aus


class LiveTextMistral:
    """Strom 1 Live-Text in Nestor Basis: Voxtral Realtime über WebSocket (gleiche Schnittstelle wie LiveText).

    `target_streaming_delay_ms=240`: Text der Frage ~0,6 s nach Sprechende (Probe 08.10.). Kontext (Name, Agenda)
    und Sprachvorgabe unterstützt das Echtzeitmodell nicht (API-Fehler 3051, geprüft 08.10.) – laut Probe kam
    „Nestor“ in der Demo trotzdem 3/3 richtig an, und die Namenserkennung akzeptiert ähnliche Schreibweisen
    (LMC_ASSISTENT_MUSTER). Bricht die Verbindung ab, wird neu verbunden; dazwischen geht kurz Text verloren.
    """

    def __init__(self, bei_teiltext, bei_satz, prompt: str = "", stichwoerter: list[str] | None = None) -> None:
        self._bei_teiltext = bei_teiltext
        self._bei_satz = bei_satz
        self._ws = None
        self._empfang: asyncio.Task | None = None
        self._wache: asyncio.Task | None = None
        self._z = TextZuordnung()
        self._rest = np.zeros(0, dtype=np.float32)
        self.pos = 0.0  # Audiozeit (s), die schon zugeführt ist
        self.gesendete_sekunden = 0.0
        self.fehler: str | None = None
        self._zu = False

    async def verbinden(self) -> None:
        import websockets

        from .mistral import schluessel

        ws = await websockets.connect(MISTRAL_URL.format(modell=EINST.live_modell), max_size=None,
                                      additional_headers={"Authorization": f"Bearer {schluessel()}"})
        await ws.send(json.dumps({"type": "session.update", "session": {
            "audio_format": {"encoding": "pcm_s16le", "sample_rate": MISTRAL_RATE},
            "target_streaming_delay_ms": EINST.basis_live_delay_ms}}))
        self._ws = ws
        self._empfang = asyncio.create_task(self._empfangen(ws))
        if self._wache is None:
            self._wache = asyncio.create_task(self._wachen())

    async def audio(self, pcm24k: bytes) -> None:
        a24 = np.concatenate([self._rest, np.frombuffer(pcm24k, dtype="<i2").astype(np.float32)])
        n = len(a24) // 3 * 3
        self._rest = a24[n:]
        self.pos += len(pcm24k) / 2 / RATE
        ws = self._ws
        if ws is not None and n:
            a16 = np.interp(np.arange(0, n - 1e-9, 1.5), np.arange(n), a24[:n])
            try:
                await ws.send(json.dumps({"type": "input_audio.append",
                                          "audio": base64.b64encode(a16.astype("<i2").tobytes()).decode()}))
                self.gesendete_sekunden += len(pcm24k) / 2 / RATE
            except Exception as e:  # noqa: BLE001 – Verbindung weg: neu verbinden, das Meeting läuft weiter
                self._getrennt(ws, e)
        await self._ausgeben()

    def luecke(self, sekunden: float) -> None:
        """Stumm oder Pause: nichts senden, aber die Audiozeit mitlaufen lassen (sie muss zur Pausenerkennung passen)."""
        self.pos += sekunden

    async def commit(self, meta: dict) -> None:
        self._z.commit(meta, float(meta.get("ende", self.pos)), time.monotonic())
        await self._ausgeben()

    async def schliessen(self, nachlauf: float = 2.0) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):  # beendet die Sitzung; der restliche Text kommt noch
                await self._ws.send(json.dumps({"type": "input_audio.flush"}))
            for _ in range(int(nachlauf * 10)):
                if not self._z.wartend:
                    break
                await asyncio.sleep(0.1)
        self._zu = True
        await self._ausgeben(alles=True)
        for t in (self._empfang, self._wache):
            if t:
                t.cancel()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        self._ws = None

    # --- intern ------------------------------------------------------------------------------------------------------
    async def _ausgeben(self, alles: bool = False) -> None:
        for meta, text in self._z.faellig(self.pos, time.monotonic(), alles):
            await self._bei_satz(meta, text)

    async def _wachen(self) -> None:
        while not self._zu:
            await asyncio.sleep(0.1)
            try:
                await self._ausgeben()
            except Exception:  # noqa: BLE001
                log.exception("Live-Text (Mistral): Ausgabe fehlgeschlagen")

    def _getrennt(self, ws, e: Exception | None) -> None:
        if self._zu or ws is not self._ws:
            return
        self.fehler = f"Verbindung getrennt: {type(e).__name__}" if e else "Verbindung getrennt"
        log.warning("Live-Text (Mistral): %s – verbinde neu", self.fehler)
        self._ws = None
        asyncio.ensure_future(self._neu_verbinden())

    async def _neu_verbinden(self) -> None:
        for versuch in range(5):
            if self._zu:
                return
            await asyncio.sleep(0.5 * (versuch + 1))
            try:
                await self.verbinden()
                self.fehler = None
                return
            except Exception as e:  # noqa: BLE001
                self.fehler = f"Neu verbinden fehlgeschlagen: {type(e).__name__}"
        log.warning("Live-Text (Mistral): %s", self.fehler)

    async def _empfangen(self, ws) -> None:
        try:
            async for roh in ws:
                e = json.loads(roh)
                typ = e.get("type", "")
                if typ == "transcription.text.delta":
                    self._z.text(self.pos, e.get("text", ""), time.monotonic())
                    await self._bei_teiltext(self._z.teiltext())
                    await self._ausgeben()
                elif typ == "error":
                    f = e.get("error") or {}
                    # Nur die Meldung, keine Kopfdaten
                    self.fehler = str(f.get("message", "unbekannt") if isinstance(f, dict) else f)[:200]
                    log.warning("Live-Text (Mistral): %s", self.fehler)
                elif typ == "transcription.done":
                    return
        except asyncio.CancelledError:
            return
        except Exception as e:  # noqa: BLE001
            self._getrennt(ws, e)
            return
        self._getrennt(ws, None)  # Server hat die Sitzung beendet (z. B. Höchstdauer) – weiter mit einer neuen
