"""Strom 1 Live-Text: OpenAI Realtime-Transkription (gpt-live-transcribe) über WebSocket.

Das Modell streamt Teiltext schon während des Sprechens. Äußerungsgrenzen setzt unsere lokale
Pausenerkennung: am Ende jeder Äußerung schicken wir `input_audio_buffer.commit` und bekommen den
fertigen Satz. Das Modell liefert weder Zeitstempel noch Sprecher – beides kommt aus unseren
eigenen Strömen; die Zuordnung läuft über die Reihenfolge der Commits.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

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
