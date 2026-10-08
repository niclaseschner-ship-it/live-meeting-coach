r"""Wie schnell kann Nestor einen Auftrag bestätigen? (Ticket #21 Punkt 3)

    OPENAI_API_KEY=… ~/.venvs/lmc/bin/python scripts/bestaetigung_messen.py --premium [--laeufe 3]
    MISTRAL_API_KEY=… ~/.venvs/lmc/bin/python scripts/bestaetigung_messen.py --basis

Gemessen wird ab dem Moment, in dem der Coach den Satz mit „Nestor“ hat (der Verzug des Live-Texts davor ist für
alle Wege gleich):

- **Floskel aus dem Zwischenspeicher:** erzeugt die Floskeln der Stimme (coach/bestaetigung.py), falls sie fehlen,
  und misst dann im echten Assistenten den Weg Auslöser → erstes Tonstück an das Dashboard.
- **Premium, Realtime selbst:** neue Sitzung öffnen, Frage als Text, response.create → erster Ton. Dazu in der offenen
  Sitzung eine zweite Frage → erster Ton (Rückfragen, „Nestor, …“ im laufenden Gespräch). Die Antwort wird nach dem
  ersten Ton abgebrochen (response.cancel), damit es wenig kostet.
- **Basis, Text-Weg:** mistral-medium gestreamt bis zum ersten fertigen Satz, Voxtral (Thorsten) bis zum ersten Ton.

Kosten aus der Nutzung (logs/nutzung.jsonl, coach/kosten.py). Ergebnis auf der Konsole und als JSON unter
logs/messung_bestaetigung_<zeit>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import config, kosten  # noqa: E402
from coach.config import EINST, WURZEL  # noqa: E402

FRAGEN = ["Nestor, wo stehen wir gerade?", "Nestor, was ist beim Budget noch offen?",
          "Nestor, fass den Punkt kurz zusammen."]


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def _coach():
    from coach.pipeline import Coach

    c = Coach()
    c._einrichten({"titel": "Messeplanung 2027", "ziel": "Entscheidung über den Stand",
                   "agenda": [{"titel": "Budget", "minuten": 10}, {"titel": "Standort", "minuten": 10}],
                   "regel_ids": ["ausreden", "zeit"]})
    c.meeting.starten(virtuell=True)
    return c


async def floskel_messen(c, n: int = 5) -> dict:
    """Floskeln erzeugen (falls nötig) und Auslöser → erstes Tonstück im Assistenten messen."""
    from coach import bestaetigung as b

    a = c.assistent
    t0 = time.monotonic()
    neu = await a.floskeln.vorbereiten(c._client)
    erzeugt = round(time.monotonic() - t0, 2)
    zeiten = []
    for _ in range(n):
        erstes = asyncio.get_running_loop().create_future()

        async def senden(nachricht, erstes=erstes):
            if nachricht.get("typ") == "stimme" and not erstes.done():
                erstes.set_result(time.monotonic())
        c.direkt.append(senden)
        t = time.monotonic()
        aufgabe = asyncio.ensure_future(a.floskel_sagen(a.floskeln.kurz()))
        zeiten.append(round(await asyncio.wait_for(erstes, 5) - t, 4))
        await aufgabe
        c.direkt.remove(senden)
    fehlt = [t for t in b.ALLE if a.floskeln.da(t) is None]
    return {"neu_erzeugt": neu, "erzeugen_s": erzeugt, "fehlt": fehlt, "bis_erstes_tonstueck_s": zeiten}


async def realtime_messen(c, laeufe: int) -> dict:
    import websockets

    from coach.gespraech import URL, Gespraech

    kopf = {"Authorization": f"Bearer {config.openai_schluessel()}"}
    erg = []
    for i in range(laeufe):
        g = Gespraech(c.assistent)
        frage = FRAGEN[i % len(FRAGEN)].replace("Nestor, ", "")
        t0 = time.monotonic()
        ws = await websockets.connect(URL.format(modell=EINST.realtime_modell), additional_headers=kopf, max_size=None)
        t_verb = time.monotonic() - t0
        await ws.send(json.dumps({"type": "session.update", "session": g.sitzung()}))
        lauf = {"verbindung_s": round(t_verb, 2)}

        async def antwort(text: str, t_start: float) -> dict:
            await ws.send(json.dumps({"type": "conversation.item.create", "item": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}))
            await ws.send(json.dumps({"type": "response.create"}))
            r = {"ton_s": None, "text_s": None, "erstes_wort": "", "werkzeuge": [], "usd": 0.0}
            aufruf = None
            async for roh in ws:
                e = json.loads(roh)
                typ = e.get("type", "")
                if typ == "response.function_call_arguments.done":
                    aufruf = (e.get("name"), e.get("call_id"))
                    r["werkzeuge"].append(round(time.monotonic() - t_start, 2))
                    continue
                if typ == "response.done" and r["ton_s"] is None and aufruf:
                    # wie im Gespräch: Werkzeug beantworten (status_abfragen), dann spricht das Modell
                    nutzung = e.get("response", {}).get("usage") or {}
                    r["usd"] += kosten.dollar({"art": "gespraech", "details_rein": nutzung.get("input_token_details"),
                                               "details_raus": nutzung.get("output_token_details"),
                                               "tokens_rein": nutzung.get("input_tokens"),
                                               "tokens_raus": nutzung.get("output_tokens")})
                    await ws.send(json.dumps({"type": "conversation.item.create", "item": {
                        "type": "function_call_output", "call_id": aufruf[1],
                        "output": json.dumps(c.status_kurz(), ensure_ascii=False)}}))
                    await ws.send(json.dumps({"type": "response.create"}))
                    aufruf = None
                    continue
                if typ in ("response.output_audio.delta", "response.audio.delta") and r["ton_s"] is None:
                    r["ton_s"] = round(time.monotonic() - t_start, 2)
                    await ws.send(json.dumps({"type": "response.cancel"}))
                elif typ in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
                    if r["text_s"] is None:
                        r["text_s"] = round(time.monotonic() - t_start, 2)
                    if len(r["erstes_wort"]) < 40:
                        r["erstes_wort"] += e.get("delta", "")
                elif typ == "response.done":
                    nutzung = e.get("response", {}).get("usage") or {}
                    from coach.pipeline import nutzung_loggen
                    eintrag = {"art": "gespraech", "zweck": "messung_bestaetigung", "modell": EINST.realtime_modell,
                               "tokens_rein": nutzung.get("input_tokens"), "tokens_raus": nutzung.get("output_tokens"),
                               "details_rein": nutzung.get("input_token_details"),
                               "details_raus": nutzung.get("output_token_details")}
                    nutzung_loggen(eintrag)
                    r["usd"] = round(r["usd"] + kosten.dollar(eintrag), 4)
                    if r["ton_s"] is None and not aufruf:
                        r["fehler"] = r.get("fehler") or "Antwort ohne Ton"
                    return r
                elif typ == "error":
                    msg = str(e.get("error", {}).get("message", ""))[:120]
                    if "no active response" not in msg.lower() and "cancel" not in msg.lower():
                        r["fehler"] = msg
            return r

        lauf["neu"] = await antwort(frage, t0)
        await asyncio.sleep(1.0)
        lauf["in_sitzung"] = await antwort("Und was ist beim Standort noch offen?", time.monotonic())
        await ws.close()
        erg.append(lauf)
        print(json.dumps(lauf, ensure_ascii=False))
    return {"laeufe": erg,
            "median_neu_ton_s": _median([l["neu"]["ton_s"] for l in erg]),
            "median_in_sitzung_ton_s": _median([l["in_sitzung"]["ton_s"] for l in erg]),
            "usd": round(sum(l["neu"].get("usd", 0) + l["in_sitzung"].get("usd", 0) for l in erg), 4)}


async def basis_messen(c, laeufe: int) -> dict:
    from coach import assistent as A

    erg = []
    for i in range(laeufe):
        frage = A.frage_aus(FRAGEN[i % len(FRAGEN)])
        t0 = time.monotonic()
        strom = await c._client.chat.completions.create(
            model=EINST.assistent_modell, stream=True,
            messages=[{"role": "system", "content": A.system_text()}, {"role": "user", "content": c.assistent.kontext(frage)}])
        puffer, satz_s, satz = "", None, ""
        async for teil in strom:
            d = teil.choices[0].delta.content if teil.choices else None
            if not d:
                continue
            puffer += d
            if "\n" in puffer:
                fertig, _ = A.saetze_teilen(puffer.split("\n", 1)[1])
                if fertig:
                    satz_s, satz = round(time.monotonic() - t0, 2), fertig[0]
                    break
        t1 = time.monotonic()
        tts_s = None
        async with c._client.audio.speech.with_streaming_response.create(
                model=EINST.stimme_modell, voice=EINST.stimme, input=satz or "Ihr seid bei Punkt eins.",
                response_format="pcm") as antwort:
            async for _ in antwort.iter_bytes(9600):
                tts_s = round(time.monotonic() - t1, 2)
                break
        lauf = {"erster_satz_s": satz_s, "tts_erster_ton_s": tts_s,
                "bis_ton_s": round((satz_s or 0) + (tts_s or 0), 2)}
        print(json.dumps(lauf, ensure_ascii=False))
        erg.append(lauf)
    return {"laeufe": erg, "median_bis_ton_s": _median([l["bis_ton_s"] for l in erg])}


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--premium", action="store_true")
    p.add_argument("--basis", action="store_true")
    p.add_argument("--laeufe", type=int, default=3)
    args = p.parse_args()
    ergebnis = {}
    if args.basis:
        config.stufe_setzen("basis")
        c = _coach()
        ergebnis["basis"] = {"floskel": await floskel_messen(c), "text_weg": await basis_messen(c, args.laeufe)}
    if args.premium:
        config.stufe_setzen("premium")
        c = _coach()
        ergebnis["premium"] = {"floskel": await floskel_messen(c), "realtime": await realtime_messen(c, args.laeufe)}
    print(json.dumps(ergebnis, ensure_ascii=False, indent=1))
    ziel = WURZEL / "logs" / f"messung_bestaetigung_{time.strftime('%Y%m%d_%H%M%S')}.json"
    ziel.parent.mkdir(exist_ok=True)
    ziel.write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {ziel}")


if __name__ == "__main__":
    asyncio.run(main())
