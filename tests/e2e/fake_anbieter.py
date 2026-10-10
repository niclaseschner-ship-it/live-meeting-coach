"""Fake-OpenAI und Fake-Mistral für die lokale Klick-E2E (Ticket #61, Stufe B).

Zwei Server in einem Prozess, auf **verschiedenen Loopback-Hosts** – so ist die Anbietertrennung hostgenau
beweisbar: Premium darf nur 127.0.0.11 (OpenAI) berühren, Basis nur 127.0.0.12 (Mistral).

Oberfläche = genau das, was coach/ heute aufruft (Inventur 10.10.2026):

OpenAI (Premium)                                       Mistral (Basis)
  POST /v1/chat/completions (auch stream=True)           POST /v1/chat/completions (OpenAI-kompatibel, auch stream)
  POST /v1/responses        (Recherche, Bild)            POST /v1/conversations    (Websuche)
  POST /v1/audio/transcriptions (multipart)              POST /v1/audio/transcriptions (multipart, context_bias)
  POST /v1/audio/speech     (PCM s16le 24 kHz, roh)      POST /v1/audio/speech     (SSE, speech.audio.delta, f32le)
  GET  /v1/models           (Schlüsselprüfung)
  WS   /v1/realtime?intent=transcription (Live-Text)     WS /v1/audio/transcriptions/realtime (Voxtral Live-Text)
  WS   /v1/realtime?model=… (Gespräch, Begrüßung)

Jede Anfrage landet als eine Zeile in `<log>/anfragen_<anbieter>.jsonl` (Zeit, Pfad, Modell, Größe, Regel,
Status) – **nie** ein Schlüssel und nie Audio, nur ob eine Authorization-Kopfzeile da war. Antworten kommen aus
`tests/e2e/drehbuch.json`; eine Chat-Anfrage ohne passende Regel gibt HTTP 500 und den Protokolleintrag
`"fehler": "unbekannter_prompt"` mit dem Anfang des Systemprompts (eigener Code, keine Nutzerdaten).

Sprachausgabe trägt einen akustischen Fingerabdruck: OpenAI 440 Hz, Mistral 660 Hz (Drehbuch `tts`).

Start:  python -m tests.e2e.fake_anbieter --log logs/pipeline/<ts>/b/basis/fakes
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import time
from pathlib import Path

import numpy as np
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

HIER = Path(__file__).resolve().parent
DREHBUCH = HIER / "drehbuch.json"
RATE = 24_000
OPENAI_HOST, OPENAI_PORT = "127.0.0.11", 18011
MISTRAL_HOST, MISTRAL_PORT = "127.0.0.12", 18012


# --- Ton ------------------------------------------------------------------------------------------------------------
def ton(hz: float, sekunden: float, rate: int = RATE) -> np.ndarray:
    """Sprachähnlicher Ton (float32, −1..1): feste Grundfrequenz, Silbenhüllkurve 4 Hz, weiche Ränder."""
    n = max(1, int(sekunden * rate))
    t = np.arange(n, dtype=np.float32) / rate
    huelle = 0.55 + 0.45 * np.sin(2 * math.pi * 4.0 * t) ** 2
    rand = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.02)
    return (0.35 * np.sin(2 * math.pi * hz * t) * huelle * rand).astype(np.float32)


def ton_dauer(text: str, tts: dict) -> float:
    return min(tts["max_s"], max(tts["min_s"], len(text) * tts["sekunden_je_zeichen"]))


# --- Drehbuch --------------------------------------------------------------------------------------------------------
class Drehbuch:
    def __init__(self, pfad: Path = DREHBUCH) -> None:
        self.d = json.loads(pfad.read_text(encoding="utf-8"))
        self.saetze = list(self.d["audio"]["meeting_saetze"])

    def chat(self, nachrichten: list[dict]) -> dict | None:
        def text(n: dict) -> str:
            c = n.get("content")
            if isinstance(c, list):
                return " ".join(str(t.get("text", "")) for t in c if isinstance(t, dict))
            return str(c or "")

        if not nachrichten:
            return None
        system, nutzer = text(nachrichten[0]), text(nachrichten[-1])
        for regel in self.d["chat"]:
            if all(s in system for s in regel.get("system_enthaelt", [])) and \
                    all(s in nutzer for s in regel.get("nutzer_enthaelt", [])):
                return regel
        return None

    @staticmethod
    def antwort_text(regel: dict) -> str:
        if "antwort_text" in regel:
            return regel["antwort_text"]
        return json.dumps(regel["antwort"], ensure_ascii=False)


class Anbieter:
    """Zustand und Protokoll eines Fake-Anbieters."""

    def __init__(self, name: str, hz: float, log: Path, drehbuch: Drehbuch) -> None:
        self.name = name
        self.hz = hz
        self.drehbuch = drehbuch
        self.log = log / f"anfragen_{name}.jsonl"
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.satz_nr = 0  # nächster Meeting-Satz (Live-Text und Transkription je Äußerung teilen ihn)
        self.t0 = time.time()

    def protokoll(self, **eintrag) -> None:
        eintrag = {"t": round(time.time(), 3), "anbieter": self.name, **eintrag}
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")

    def naechster_satz(self) -> str:
        if self.satz_nr >= len(self.drehbuch.saetze):
            return ""
        s = self.drehbuch.saetze[self.satz_nr]
        self.satz_nr += 1
        return s

    def transkript(self, dateiname: str) -> str:
        wert = self.drehbuch.d["transkription"].get(dateiname)
        if wert == "@meeting_saetze":
            return self.naechster_satz()
        return wert or ""


def _auth(request) -> bool:
    return bool(request.headers.get("authorization"))


# --- REST, gemeinsam ------------------------------------------------------------------------------------------------
def chat_route(a: Anbieter):
    async def chat(request: Request):
        koerper = await request.json()
        regel = a.drehbuch.chat(koerper.get("messages") or [])
        basis = {"art": "http", "pfad": request.url.path, "modell": koerper.get("model"), "auth": _auth(request),
                 "stream": bool(koerper.get("stream"))}
        if regel is None:
            erste = (koerper.get("messages") or [{}])[0]
            anfang = str(erste.get("content") or "")[:160]
            a.protokoll(**basis, status=500, fehler="unbekannter_prompt", prompt_anfang=anfang)
            return JSONResponse({"error": {"message": "Fake: unbekannter Prompt (Drehbuch ergänzen)",
                                           "type": "fake_drehbuch"}}, status_code=500)
        inhalt = Drehbuch.antwort_text(regel)
        a.protokoll(**basis, status=200, regel=regel["id"])
        nutzung = {"prompt_tokens": 100, "completion_tokens": max(1, len(inhalt) // 4), "total_tokens": 100 + len(inhalt) // 4}
        kennung = f"chatcmpl-fake-{int(time.time() * 1000)}"
        if koerper.get("stream"):
            async def strom():
                for i in range(0, len(inhalt), 24):
                    stueck = {"id": kennung, "object": "chat.completion.chunk", "created": int(time.time()),
                              "model": koerper.get("model"), "choices": [{"index": 0, "delta": {
                                  "role": "assistant", "content": inhalt[i:i + 24]}, "finish_reason": None}]}
                    yield f"data: {json.dumps(stueck, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)
                ende = {"id": kennung, "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": koerper.get("model"), "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                yield f"data: {json.dumps(ende)}\n\n"
                nutz = {"id": kennung, "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": koerper.get("model"), "choices": [], "usage": nutzung}
                yield f"data: {json.dumps(nutz)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(strom(), media_type="text/event-stream")
        return JSONResponse({"id": kennung, "object": "chat.completion", "created": int(time.time()),
                             "model": koerper.get("model"),
                             "choices": [{"index": 0, "finish_reason": "stop",
                                          "message": {"role": "assistant", "content": inhalt}}],
                             "usage": nutzung})
    return chat


def transkription_route(a: Anbieter):
    async def transkription(request: Request):
        form = await request.form()
        datei = form.get("file")
        name = getattr(datei, "filename", "") or ""
        groesse = len(await datei.read()) if datei is not None else 0
        text = a.transkript(name)
        a.protokoll(art="http", pfad=request.url.path, modell=form.get("model"), datei=name, bytes=groesse,
                    response_format=form.get("response_format"), auth=_auth(request), status=200,
                    text_laenge=len(text))
        if form.get("response_format") == "diarized_json":
            return JSONResponse({"text": text, "segments": [{"speaker": "A", "start": 0.0, "end": 1.0, "text": text}]})
        return JSONResponse({"text": text, "usage": {"type": "duration", "seconds": max(1, groesse // 48000)}})
    return transkription


# --- OpenAI ----------------------------------------------------------------------------------------------------------
def openai_app(a: Anbieter, drehbuch: Drehbuch) -> Starlette:
    tts = drehbuch.d["tts"]

    async def speech(request: Request):
        k = await request.json()
        text = str(k.get("input") or "")
        dauer = ton_dauer(text, tts)
        a.protokoll(art="http", pfad=request.url.path, modell=k.get("model"), stimme=k.get("voice"),
                    format=k.get("response_format"), zeichen=len(text), ton_hz=a.hz, ton_s=round(dauer, 2),
                    auth=_auth(request), status=200)
        pcm = (ton(a.hz, dauer) * 32767).astype("<i2").tobytes()

        async def strom():
            for i in range(0, len(pcm), 9600):
                yield pcm[i:i + 9600]
                await asyncio.sleep(0.02)
        return StreamingResponse(strom(), media_type="audio/pcm")

    async def responses(request: Request):
        k = await request.json()
        a.protokoll(art="http", pfad=request.url.path, modell=k.get("model"), auth=_auth(request), status=200)
        text = "Fake-Recherche: Vereinsbusse kosten gebraucht etwa 20.000 bis 40.000 Euro."
        return JSONResponse({"id": "resp-fake", "object": "response", "status": "completed", "model": k.get("model"),
                             "output": [{"type": "message", "role": "assistant", "content": [
                                 {"type": "output_text", "text": text, "annotations": []}]}],
                             "output_text": text,
                             "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70}})

    async def modelle(request: Request):
        a.protokoll(art="http", pfad=request.url.path, auth=_auth(request), status=200)
        return JSONResponse({"object": "list", "data": [{"id": "gpt-5.4-mini", "object": "model"}]})

    async def realtime(ws: WebSocket):
        await ws.accept()
        intent = ws.query_params.get("intent")
        modell = ws.query_params.get("model")
        art = "live_text" if intent == "transcription" else "gespraech"
        a.protokoll(art="ws", pfad="/v1/realtime", ws_art=art, modell=modell, auth=bool(ws.headers.get("authorization")),
                    status=101)
        puffer_bytes, n_item, letzte_frage = 0, 0, ""
        try:
            while True:
                e = json.loads(await ws.receive_text())
                typ = e.get("type", "")
                if typ == "session.update":
                    await ws.send_text(json.dumps({"type": "session.updated", "session": e.get("session", {})}))
                elif typ == "input_audio_buffer.append":
                    puffer_bytes += len(e.get("audio", "")) * 3 // 4
                elif typ == "input_audio_buffer.commit" and art == "live_text":
                    n_item += 1
                    item = f"item_fake_{n_item}"
                    sekunden = puffer_bytes / 2 / RATE
                    puffer_bytes = 0
                    satz = a.naechster_satz() if sekunden >= 0.3 else ""
                    a.protokoll(art="ws_ereignis", pfad="/v1/realtime", ereignis="commit", item=item,
                                audio_s=round(sekunden, 2), text_laenge=len(satz))
                    await ws.send_text(json.dumps({"type": "input_audio_buffer.committed", "item_id": item}))
                    for i in range(0, len(satz), 20):
                        await ws.send_text(json.dumps({"type": "conversation.item.input_audio_transcription.delta",
                                                       "item_id": item, "delta": satz[i:i + 20]}))
                    await ws.send_text(json.dumps({"type": "conversation.item.input_audio_transcription.completed",
                                                   "item_id": item, "transcript": satz}))
                elif typ == "response.create":
                    await _realtime_antwort(ws, a, drehbuch, tts, letzte_frage)
                elif typ == "conversation.item.create":
                    inhalt = (e.get("item") or {}).get("content") or []
                    letzte_frage = " ".join(str(t.get("text", "")) for t in inhalt if isinstance(t, dict))
                elif typ in ("conversation.item.truncate", "response.cancel",
                             "input_audio_buffer.clear"):
                    pass
        except WebSocketDisconnect:
            pass

    return Starlette(routes=[
        Route("/v1/chat/completions", chat_route(a), methods=["POST"]),
        Route("/v1/responses", responses, methods=["POST"]),
        Route("/v1/audio/transcriptions", transkription_route(a), methods=["POST"]),
        Route("/v1/audio/speech", speech, methods=["POST"]),
        Route("/v1/models", modelle, methods=["GET"]),
        WebSocketRoute("/v1/realtime", realtime),
    ])


def realtime_text(drehbuch: Drehbuch, frage: str) -> tuple[str, str]:
    """(Regel, Antworttext) für eine Realtime-Antwort: Begrüßung, eine Drehbuch-Antwort oder der Kartensatz."""
    if "Begrüße" in frage:
        return "begruessung", drehbuch.d["begruessung_premium"]
    for regel in drehbuch.d.get("realtime", []):
        if all(t in frage for t in regel["frage_enthaelt"]):
            return regel["id"], regel["antwort_text"]
    return "realtime_standard", "Hier ist sie. Das Wichtige steht auf der Karte."


async def _realtime_antwort(ws: WebSocket, a: Anbieter, drehbuch: Drehbuch, tts: dict, frage: str = "") -> None:
    """Eine gesprochene Antwort des Realtime-Modells: Transkript-Deltas und 440-Hz-PCM in Stücken."""
    regel, text = realtime_text(drehbuch, frage)
    dauer = ton_dauer(text, {**tts, "max_s": 6.0})
    a.protokoll(art="ws_ereignis", pfad="/v1/realtime", ereignis="response", regel=regel, ton_hz=a.hz,
                ton_s=round(dauer, 2))
    rid, item = f"resp_fake_{time.time_ns()}", f"item_out_{time.time_ns()}"
    await ws.send_text(json.dumps({"type": "response.created", "response": {"id": rid, "status": "in_progress"}}))
    pcm = (ton(a.hz, dauer) * 32767).astype("<i2").tobytes()
    worte = text.split(" ")
    stuecke = [pcm[i:i + 4800] for i in range(0, len(pcm), 4800)]
    for i, s in enumerate(stuecke):
        await ws.send_text(json.dumps({"type": "response.output_audio.delta", "response_id": rid, "item_id": item,
                                       "delta": base64.b64encode(s).decode()}))
        w = worte[i * len(worte) // len(stuecke):(i + 1) * len(worte) // len(stuecke)]
        if w:
            await ws.send_text(json.dumps({"type": "response.output_audio_transcript.delta", "response_id": rid,
                                           "item_id": item, "delta": " ".join(w) + " "}))
        await asyncio.sleep(0.05)
    await ws.send_text(json.dumps({"type": "response.output_audio.done", "response_id": rid, "item_id": item}))
    await ws.send_text(json.dumps({"type": "response.output_audio_transcript.done", "response_id": rid,
                                   "item_id": item, "transcript": text}))
    await ws.send_text(json.dumps({"type": "response.done", "response": {
        "id": rid, "status": "completed",
        "output": [{"id": item, "type": "message", "role": "assistant",
                    "content": [{"type": "output_audio", "transcript": text}]}],
        "usage": {"input_tokens": 200, "output_tokens": 100, "input_token_details": {"text_tokens": 200, "audio_tokens": 0},
                  "output_token_details": {"text_tokens": 20, "audio_tokens": 80}}}}))


# --- Mistral ---------------------------------------------------------------------------------------------------------
def mistral_app(a: Anbieter, drehbuch: Drehbuch) -> Starlette:
    tts = drehbuch.d["tts"]

    async def speech(request: Request):
        k = await request.json()
        text = str(k.get("input") or "")
        dauer = ton_dauer(text, tts)
        a.protokoll(art="http", pfad=request.url.path, modell=k.get("model"), stimme=k.get("voice_id"),
                    format=k.get("response_format"), zeichen=len(text), ton_hz=a.hz, ton_s=round(dauer, 2),
                    auth=_auth(request), status=200)
        f32 = ton(a.hz, dauer).astype("<f4").tobytes()

        async def strom():
            for i in range(0, len(f32), 19200):
                e = {"type": "speech.audio.delta", "audio_data": base64.b64encode(f32[i:i + 19200]).decode()}
                yield f"data: {json.dumps(e)}\n\n"
                await asyncio.sleep(0.02)
            yield f"data: {json.dumps({'type': 'speech.audio.done'})}\n\n"
        return StreamingResponse(strom(), media_type="text/event-stream")

    async def conversations(request: Request):
        k = await request.json()
        a.protokoll(art="http", pfad=request.url.path, modell=k.get("model"), auth=_auth(request), status=200)
        return JSONResponse({"outputs": [
            {"type": "tool.execution", "name": "web_search"},
            {"type": "message.output", "content": [
                {"type": "text", "text": "Fake-Recherche: Vereinsbusse kosten gebraucht etwa 20.000 bis 40.000 Euro."},
                {"type": "tool_reference", "url": "https://example.org/vereinsbus", "title": "Beispielquelle"}]}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "connector_tokens": 0}})

    async def realtime(ws: WebSocket):
        """Voxtral Realtime kennt keine Commits: der Fake erkennt Sprechpausen selbst (Energie) und schickt nach
        jeder Äußerung den nächsten Drehbuchsatz als Text-Deltas."""
        await ws.accept()
        a.protokoll(art="ws", pfad="/v1/audio/transcriptions/realtime", ws_art="live_text",
                    modell=ws.query_params.get("model"), auth=bool(ws.headers.get("authorization")), status=101)
        rate = 16_000
        sprache_s, stille_s, schwelle = 0.0, 0.0, 0.02
        try:
            while True:
                e = json.loads(await ws.receive_text())
                typ = e.get("type", "")
                if typ == "session.update":
                    await ws.send_text(json.dumps({"type": "session.updated"}))
                elif typ == "input_audio.append":
                    roh = np.frombuffer(base64.b64decode(e.get("audio", "")), dtype="<i2").astype(np.float32) / 32768
                    if not len(roh):
                        continue
                    dauer = len(roh) / rate
                    if float(np.sqrt(np.mean(roh * roh))) > schwelle:
                        sprache_s += dauer
                        stille_s = 0.0
                    else:
                        stille_s += dauer
                        if sprache_s >= 0.4 and stille_s >= 0.35:
                            satz = a.naechster_satz()
                            a.protokoll(art="ws_ereignis", pfad="/v1/audio/transcriptions/realtime",
                                        ereignis="aeusserung", audio_s=round(sprache_s, 2), text_laenge=len(satz))
                            for i in range(0, len(satz), 20):
                                await ws.send_text(json.dumps({"type": "transcription.text.delta",
                                                               "text": satz[i:i + 20]}))
                            sprache_s = 0.0
                elif typ == "input_audio.flush":
                    await ws.send_text(json.dumps({"type": "transcription.done"}))
        except WebSocketDisconnect:
            pass

    return Starlette(routes=[
        Route("/v1/chat/completions", chat_route(a), methods=["POST"]),
        Route("/v1/conversations", conversations, methods=["POST"]),
        Route("/v1/audio/transcriptions", transkription_route(a), methods=["POST"]),
        Route("/v1/audio/speech", speech, methods=["POST"]),
        WebSocketRoute("/v1/audio/transcriptions/realtime", realtime),
    ])


# --- Start -----------------------------------------------------------------------------------------------------------
async def starten(log: Path, drehbuch_pfad: Path = DREHBUCH) -> None:
    import uvicorn

    drehbuch = Drehbuch(drehbuch_pfad)
    tts = drehbuch.d["tts"]
    oa = Anbieter("openai", tts["openai_hz"], log, drehbuch)
    mi = Anbieter("mistral", tts["mistral_hz"], log, drehbuch)
    server = [
        uvicorn.Server(uvicorn.Config(openai_app(oa, drehbuch), host=OPENAI_HOST, port=OPENAI_PORT,
                                      log_level="warning", ws="websockets", lifespan="off")),
        uvicorn.Server(uvicorn.Config(mistral_app(mi, drehbuch), host=MISTRAL_HOST, port=MISTRAL_PORT,
                                      log_level="warning", ws="websockets", lifespan="off")),
    ]
    await asyncio.gather(*(s.serve() for s in server))


def umgebung() -> dict[str, str]:
    """Umlenkung des Coachs auf die Fakes – ausschließlich über die Endpunkt-Variablen aus coach/anbieter.py (#60)."""
    oa = f"http://{OPENAI_HOST}:{OPENAI_PORT}"
    mi = f"http://{MISTRAL_HOST}:{MISTRAL_PORT}"
    return {
        "LMC_OPENAI_URL": f"{oa}/v1",
        "LMC_OPENAI_WS_URL": f"ws://{OPENAI_HOST}:{OPENAI_PORT}/v1/realtime",
        "LMC_MISTRAL_URL": f"{mi}/v1",
        "LMC_MISTRAL_WS_URL": f"ws://{MISTRAL_HOST}:{MISTRAL_PORT}/v1/audio/transcriptions/realtime",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--log", required=True, help="Ordner für anfragen_<anbieter>.jsonl")
    p.add_argument("--drehbuch", default=str(DREHBUCH))
    args = p.parse_args()
    asyncio.run(starten(Path(args.log), Path(args.drehbuch)))


if __name__ == "__main__":
    main()
