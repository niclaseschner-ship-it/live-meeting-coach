"""Nestor Basis (Ticket #13): alle KI-Aufrufe über Mistral AI (Frankreich, Verarbeitung in der EU), ein Schlüssel.

Der Coach spricht überall mit einem Client, der sich wie `openai.AsyncOpenAI` verhält. `MistralClient` bildet genau
die Teile nach, die der Coach braucht – dadurch bleibt der Rest des Codes für beide Stufen gleich:

    chat.completions.create        OpenAI-kompatibler Endpunkt von Mistral (nur base_url und Modell getauscht)
    audio.transcriptions.create    Voxtral Transcribe (Batch, Knopfdruck und „sparsam“)
    audio.speech.with_streaming_response.create
                                   Voxtral TTS mit gespeicherter Stimme (voice_id Thorsten), gestreamt; liefert
                                   wie OpenAI PCM 16 bit 24 kHz (Mistral sendet float32 – hier umgewandelt)
    websuche(...)                  Conversations-API mit dem Werkzeug web_search (Recherche)

Live-Text (Voxtral Realtime) steht in `coach/livetext.py` (`LiveTextMistral`).

Überlast: Mistral antwortet bei zu vielen Anfragen mit HTTP 429 (Pay-as-you-go: Grenze je Sekunde, gemessen
schon bei vier gleichzeitigen Anfragen). Jeder Aufruf wird dann mit wachsender Wartezeit wiederholt; erst wenn das
nicht reicht, kommt `Ueberlast` – Nestor sagt das ehrlich (assistent.py), statt zu hängen.

Schlüssel: `LMC_MISTRAL_SCHLUESSEL` oder `MISTRAL_API_KEY` aus der Umgebung – nie in Dateien, Logs oder Antworten.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import random
import time
from types import SimpleNamespace

import numpy as np

try:  # openai 3.x bringt httpx2 mit, ältere Versionen httpx – beide haben dieselbe Schnittstelle
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx  # type: ignore[no-redef]

log = logging.getLogger("coach.mistral")

BASIS_URL = os.getenv("LMC_MISTRAL_URL", "https://api.mistral.ai/v1")
# Gespeicherte Stimme „nestor-thorsten-de“ im Mistral-Konto (aus 23 s Thorsten-Voice, CC0; Referenz im Repo unter
# coach/stimmen/thorsten_ref.wav, damit sie sich neu anlegen lässt). Mit voice_id ~0,5 s bis zum ersten Ton,
# mit mitgeschickter Referenz ~1,1 s (Machbarkeitsprobe 07./08.10.).
THORSTEN = "01a1188b-54f4-71a8-86df-df69e318948c"
WIEDERHOLUNGEN = 4  # 429: so oft erneut versuchen (Wartezeit 0,5 → 1 → 2 → 4 s, mit Zufallsanteil)
TTS_ZWEITER_VERSUCH = 1.6  # s ohne ersten Ton → zweite Anfrage parallel (Ausreißer bis 10 s gemessen)


def schluessel() -> str | None:
    from .config import mistral_schluessel

    return mistral_schluessel()


class Ueberlast(RuntimeError):
    """Mistral oder OpenAI lehnt wegen zu vieler Anfragen ab (HTTP 429), auch nach Wiederholungen."""


def ist_ueberlast(e: BaseException) -> bool:
    if isinstance(e, Ueberlast):
        return True
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    return status == 429 or type(e).__name__ == "RateLimitError"


async def _warten(versuch: int) -> None:
    await asyncio.sleep(min(4.0, 0.5 * 2 ** versuch) * (0.8 + 0.4 * random.random()))


async def mit_wiederholung(aufruf, art: str = ""):
    """`aufruf()` (async, liefert ein Ergebnis) bei 429 wiederholen; danach `Ueberlast`."""
    for versuch in range(WIEDERHOLUNGEN + 1):
        try:
            return await aufruf()
        except Exception as e:  # noqa: BLE001
            if not ist_ueberlast(e):
                raise
            if versuch == WIEDERHOLUNGEN:
                raise Ueberlast(f"{art or 'Aufruf'}: zu viele Anfragen") from None
            log.info("Mistral 429 (%s) – Versuch %d", art, versuch + 1)
            await _warten(versuch)


class HttpFehler(RuntimeError):
    def __init__(self, status: int, text: str = "") -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status
        self.text = text[:200]  # nur zur Fehlersuche im Log, nie an die Oberfläche


# --- Chat (OpenAI-kompatibel) ------------------------------------------------------------------------------------
class _Completions:
    def __init__(self, oa) -> None:
        self._oa = oa

    async def create(self, **kw):
        # OpenAI-Eigenheiten, die Mistral nicht kennt: Denkaufwand „low“ (Mistral Medium kennt nur none/high)
        kw.pop("reasoning_effort", None)
        kw.pop("reasoning", None)
        return await mit_wiederholung(lambda: self._oa.chat.completions.create(**kw), "chat")


# --- Transkription (Batch) ------------------------------------------------------------------------------------
class _Transkriptionen:
    def __init__(self, client: "MistralClient") -> None:
        self._c = client

    async def create(self, *, model: str, file, language: str | None = None, prompt: str | None = None, **_):
        """`file` wie bei OpenAI: (name, bytes, mime). Der OpenAI-„prompt“ (ein Satz Kontext) hat bei Voxtral kein
        Gegenstück; dafür gibt es `context_bias` (Wörter) – die setzt der Coach als `stichwoerter`."""
        name, daten, mime = file
        felder = [("model", model)]
        if language:
            felder.append(("language", language))
        for w in self._c.stichwoerter[:100]:
            felder.append(("context_bias", w))

        async def senden():
            r = await self._c.http.post(f"{BASIS_URL}/audio/transcriptions", headers=self._c.kopf,
                                        data=felder, files={"file": (name, daten, mime)}, timeout=60)
            if r.status_code != 200:
                raise HttpFehler(r.status_code, r.text)
            return r.json()

        roh = await mit_wiederholung(senden, "transkription")
        return SimpleNamespace(text=(roh.get("text") or "").strip(), usage=roh.get("usage"))


# --- Sprachausgabe (gestreamt) -----------------------------------------------------------------------------------
def f32_zu_s16(daten: bytes) -> bytes:
    a = np.frombuffer(daten, dtype="<f4")
    return (np.clip(a, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class _TtsStrom:
    """Wie OpenAIs `with_streaming_response`: `async with … as antwort: async for stueck in antwort.iter_bytes()`.

    Bleibt der erste Ton länger als `TTS_ZWEITER_VERSUCH` aus, geht eine zweite, gleiche Anfrage los; es gewinnt,
    wer zuerst Ton liefert (Ausreißer der Probe: 4,8 s und 10 s statt ~0,5 s).
    """

    def __init__(self, client: "MistralClient", koerper: dict) -> None:
        self._c = client
        self._koerper = koerper
        self._schlange: asyncio.Queue = asyncio.Queue()
        self._aufgaben: list[asyncio.Task] = []
        self._gewinner: int | None = None
        self.zeichen = len(koerper.get("input", ""))
        self._t0 = time.monotonic()
        self.erster_ton: float | None = None

    async def _anfrage(self, nr: int) -> None:
        try:
            for versuch in range(WIEDERHOLUNGEN + 1):
                async with self._c.http.stream("POST", f"{BASIS_URL}/audio/speech", headers=self._c.kopf,
                                               json=self._koerper, timeout=30) as r:
                    if r.status_code == 429 and versuch < WIEDERHOLUNGEN and self._gewinner is None:
                        log.info("Sprachausgabe: 429 (Anfrage %d, Versuch %d)", nr, versuch + 1)
                        await _warten(versuch)
                        continue
                    if r.status_code != 200:
                        raise Ueberlast("Sprachausgabe: zu viele Anfragen") if r.status_code == 429 else \
                            HttpFehler(r.status_code)
                    rest = b""
                    async for zeile in r.aiter_lines():
                        if not zeile.startswith("data:"):
                            continue
                        try:
                            e = json.loads(zeile[5:].strip())
                        except ValueError:
                            continue
                        if e.get("type") == "speech.audio.delta":
                            if self._gewinner is None:
                                self._gewinner = nr
                                self.erster_ton = time.monotonic() - self._t0
                                if nr or self.erster_ton > 1.2:
                                    log.info("Sprachausgabe: erster Ton nach %.2f s (Anfrage %d)", self.erster_ton, nr)
                            if self._gewinner != nr:
                                return  # die andere Anfrage war schneller
                            roh = rest + base64.b64decode(e.get("audio_data") or "")
                            ganz = len(roh) // 4 * 4
                            roh, rest = roh[:ganz], roh[ganz:]
                            if roh:
                                await self._schlange.put(f32_zu_s16(roh))
                        elif e.get("type") == "speech.audio.done":
                            break
                    if self._gewinner in (None, nr):  # auch ohne jeden Ton: Ende melden, sonst wartet iter_bytes ewig
                        await self._schlange.put(None)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            if self._gewinner in (None, nr):
                await self._schlange.put(e)

    async def __aenter__(self):
        self._aufgaben.append(asyncio.ensure_future(self._anfrage(0)))
        return self

    async def __aexit__(self, *_):
        for a in self._aufgaben:
            a.cancel()
        for a in self._aufgaben:
            with contextlib.suppress(BaseException):
                await a

    async def iter_bytes(self, _groesse: int = 0):
        fehler: list[BaseException] = []
        while True:
            try:
                stueck = await asyncio.wait_for(self._schlange.get(), TTS_ZWEITER_VERSUCH)
            except asyncio.TimeoutError:
                if self._gewinner is None and len(self._aufgaben) == 1:
                    log.info("Sprachausgabe: erster Ton bleibt aus – zweite Anfrage")
                    self._aufgaben.append(asyncio.ensure_future(self._anfrage(1)))
                continue
            if stueck is None:
                return
            if isinstance(stueck, BaseException):
                fehler.append(stueck)
                if len(fehler) >= len(self._aufgaben) or self._gewinner is not None:
                    raise stueck
                continue
            yield stueck


class _Sprache:
    def __init__(self, client: "MistralClient") -> None:
        self._c = client
        self.with_streaming_response = self

    def create(self, *, model: str, input: str, voice: str | None = None, response_format: str = "pcm", **_):
        """Die Stil-Anweisung (`instructions`) von OpenAI gibt es bei Voxtral nicht – sie fällt weg."""
        return _TtsStrom(self._c, {"model": model, "input": input, "voice_id": voice or THORSTEN,
                                   "response_format": "pcm", "stream": True})


# --- Client ---------------------------------------------------------------------------------------------------------
class MistralClient:
    """Wie `AsyncOpenAI` für die Teile, die der Coach nutzt – alles geht an api.mistral.ai."""

    anbieter = "mistral"

    def __init__(self, api_key: str) -> None:
        from openai import AsyncOpenAI

        # max_retries=0: 429 behandelt mit_wiederholung selbst (sonst stapeln sich zwei Wartelogiken)
        self._oa = AsyncOpenAI(base_url=BASIS_URL, api_key=api_key, max_retries=0, timeout=60)
        self.kopf = {"Authorization": f"Bearer {api_key}"}
        self.http = httpx.AsyncClient(timeout=60)
        self.stichwoerter: list[str] = []  # context_bias der Batch-Transkription (Name, Agenda, Teilnehmende)
        self.chat = SimpleNamespace(completions=_Completions(self._oa))
        self.audio = SimpleNamespace(transcriptions=_Transkriptionen(self), speech=_Sprache(self))

    async def websuche(self, modell: str, auftrag: str) -> dict:
        """Recherche über die Conversations-API mit web_search. Liefert {text, quellen, tokens_rein, tokens_raus}.

        Das Modell sucht nicht immer von selbst (Probe 08.10.) – der Auftrag verlangt die Suche, und kommt eine Antwort
        ganz ohne Quellen, wird einmal mit erzwungenem Werkzeug (tool_choice „any“) nachgefasst."""
        async def senden(erzwingen: bool):
            koerper = {"model": modell, "inputs": auftrag, "tools": [{"type": "web_search"}], "store": False}
            if erzwingen:
                koerper["completion_args"] = {"tool_choice": "any"}
            r = await self.http.post(f"{BASIS_URL}/conversations", headers=self.kopf, json=koerper, timeout=60)
            if r.status_code != 200:
                raise HttpFehler(r.status_code, r.text)
            return r.json()

        roh = await mit_wiederholung(lambda: senden(False), "recherche")
        erg = websuche_lesen(roh)
        if not erg["quellen"]:
            roh = await mit_wiederholung(lambda: senden(True), "recherche")
            erg2 = websuche_lesen(roh)
            if erg2["text"]:
                erg2["tokens_rein"] = (erg2["tokens_rein"] or 0) + (erg["tokens_rein"] or 0)
                erg2["tokens_raus"] = (erg2["tokens_raus"] or 0) + (erg["tokens_raus"] or 0)
                erg2["suchen"] += erg["suchen"]
                erg = erg2
        return erg

    async def schliessen(self) -> None:
        with contextlib.suppress(Exception):
            await self.http.aclose()


def websuche_lesen(roh: dict) -> dict:
    """Antwort der Conversations-API: Text aus message.output, Quellen aus tool_reference-Stücken."""
    text, quellen, gesehen, suchen = "", [], set(), 0
    for o in roh.get("outputs") or []:
        if o.get("type") == "tool.execution":
            suchen += 1
        if o.get("type") != "message.output":
            continue
        inhalt = o.get("content")
        if isinstance(inhalt, str):
            text += inhalt
            continue
        for teil in inhalt or []:
            if teil.get("type") == "text":
                text += teil.get("text") or ""
            elif teil.get("type") == "tool_reference":
                url = teil.get("url")
                if url and url not in gesehen:
                    gesehen.add(url)
                    quellen.append({"titel": (teil.get("title") or url)[:120], "url": url})
    u = roh.get("usage") or {}
    return {"text": text.strip(), "quellen": quellen[:5], "tokens_rein": u.get("prompt_tokens"),
            "tokens_raus": u.get("completion_tokens"), "suchen": suchen or (1 if quellen else 0)}

