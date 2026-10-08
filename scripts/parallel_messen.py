"""Parallele Meetings (Ticket #13, Schritt 0.2): ab wie vielen gleichzeitigen Meetings kommen 429 oder spürbar
längere Antwortzeiten – für Nestor Basis (Mistral) und Premium (OpenAI)?

    python scripts/parallel_messen.py --stufe basis [--anzahl 1 2 4 8] [--sekunden 120]

Jedes simulierte Meeting erzeugt dieselbe API-Last wie ein echtes (Abspielmodus der Messe-Demo, Echtzeit):
- Live-Text: Demo-Audio (ab 0:27) in 100-ms-Stücken an den Live-Text der Stufe (LiveTextMistral bzw. LiveText),
  Äußerungsgrenzen aus der lokalen Pausenerkennung wie im Coach,
- Zuordnung: alle ~15 s Gesprochenes ein Aufruf themen.zuordnen (mit Ton-Prüfung), wie im Coach,
- Nestor: eine Frage pro Minute („Nestor, wo stehen wir gerade?“): Antwort gestreamt, erster Satz an die
  Sprachausgabe, gemessen bis zum ersten Ton. In beiden Stufen über den Text-Weg (Premium nutzt im Betrieb das
  Realtime-Gespräch – dessen Grenze steht nur aus der Recherche im Bericht).
Lokale Modelle für Sprecher (CAM++) laufen nicht mit – sie belasten keine API, nur den Rechner.

429 werden gezählt (jede Wiederholung von coach/mistral.mit_wiederholung, auch für OpenAI genutzt) und als
Ausfall, wenn auch die Wiederholungen nicht reichen. Schlüssel nur aus der Umgebung. Ergebnis: logs/basis/parallel_<stufe>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import assistent as A  # noqa: E402
from coach import config, themen  # noqa: E402
from coach.config import EINST, WURZEL  # noqa: E402
from coach.mistral import mit_wiederholung, ist_ueberlast  # noqa: E402
from coach.zustand import Agendapunkt, Meeting, Segment  # noqa: E402

AUSGABE = WURZEL / "logs" / "basis"


class Zaehler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.n429 = 0

    def emit(self, record) -> None:
        if "429" in record.getMessage():
            self.n429 += 1


ZAEHLER = Zaehler()


class OpenAIMitZaehler:
    """OpenAI ohne eigene Wiederholung (max_retries=0), 429 über dieselbe Wiederholung wie bei Mistral – so zählen wir."""

    def __init__(self, key: str) -> None:
        from types import SimpleNamespace

        from openai import AsyncOpenAI

        self._oa = AsyncOpenAI(api_key=key, max_retries=0)
        self.audio = self._oa.audio
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        return await mit_wiederholung(lambda: self._oa.chat.completions.create(**kw), "chat")


def demo_einrichtung() -> Meeting:
    d = json.loads((WURZEL / "demo" / "messeplanung.json").read_text(encoding="utf-8"))
    m = Meeting(titel=d["titel"], ziel=d["ziel"], agenda=[Agendapunkt(p["titel"], p["ziel"], p["minuten"]) for p in d["agenda"]],
                regel_ids=d["regel_ids"])
    m.starten(virtuell=True)
    return m


NUR_API = False  # --nur-api: keine lokale Pausenerkennung (Commit alle 4 s) – trennt API-Grenzen von der Rechnerlast


async def ein_meeting(nr: int, stufe: str, client, audio: np.ndarray, sekunden: float, erg: dict) -> None:
    from coach.hoeren import nach_16k
    from coach.livetext import LiveText, LiveTextMistral
    from coach.vad import Pausenerkennung

    m = demo_einrichtung()
    abschnitt: list[str] = []
    aufgaben: list[asyncio.Task] = []
    ich = {"zuordnung": [], "frage": [], "fehler": [], "saetze": 0}
    erg["meetings"].append(ich)

    async def bei_satz(meta, text) -> None:
        if text:
            ich["saetze"] += 1
            m.transkript.append(Segment("Person 1", text, meta.get("ende", 0) - 2, meta.get("ende", 0)))
            abschnitt.append(text)

    async def bei_teil(_t) -> None:
        pass

    async def zuordnen(text: str) -> None:
        t0 = time.monotonic()
        try:
            await themen.zuordnen(client, EINST.analyse_modell, m, text, EINST.analyse_aufwand, ton=True)
            ich["zuordnung"].append(round(time.monotonic() - t0, 2))
        except Exception as e:  # noqa: BLE001
            ich["fehler"].append(("zuordnung", "ueberlast" if ist_ueberlast(e) else type(e).__name__))

    async def fragen() -> None:
        t0 = time.monotonic()
        try:
            strom = await client.chat.completions.create(
                model=EINST.assistent_modell, stream=True,
                messages=[{"role": "system", "content": A.system_text()},
                          {"role": "user", "content": "Transkript:\n" + "\n".join(s.text for s in m.transkript[-40:])
                           + "\n\nFrage an dich: wo stehen wir gerade?"}],
                **({"reasoning_effort": EINST.assistent_aufwand} if EINST.assistent_aufwand else {}))
            puffer, erste, satz = "", None, None
            async for teil in strom:
                d = teil.choices[0].delta.content if teil.choices else None
                if not d:
                    continue
                puffer += d
                if erste is None:
                    if "\n" not in puffer:
                        continue
                    erste, puffer = puffer.split("\n", 1)
                fertig, puffer = A.saetze_teilen(puffer)
                if fertig:
                    satz = fertig[0]
                    break
            t_satz = time.monotonic() - t0
            async with client.audio.speech.with_streaming_response.create(
                    model=EINST.stimme_modell, voice=EINST.stimme, input=satz or puffer or "Ja.", response_format="pcm",
                    instructions="Sprich ruhig und klar auf Deutsch.") as r:
                async for _ in r.iter_bytes(9600):
                    break
            ich["frage"].append({"satz": round(t_satz, 2), "ton": round(time.monotonic() - t0, 2)})
        except Exception as e:  # noqa: BLE001
            ich["fehler"].append(("frage", "ueberlast" if ist_ueberlast(e) else f"{type(e).__name__}"))

    klasse = LiveTextMistral if stufe == "basis" else LiveText
    live = klasse(bei_teil, bei_satz, "Besprechung auf Deutsch. Der Moderationsassistent heißt Nestor.", ["Nestor"])
    try:
        await live.verbinden()
    except Exception as e:  # noqa: BLE001
        ich["fehler"].append(("live-verbinden", f"{type(e).__name__}: {str(e)[:80]}"))
        return
    vad = None if NUR_API else Pausenerkennung()
    rest = np.zeros(0, np.float32)
    naechster_commit = 4.0
    t0 = time.monotonic()
    naechste_zuordnung, naechste_frage = 15.0, 25.0 + 5 * nr % 20  # Fragen versetzt, eine pro Minute
    for i in range(0, int(sekunden * 24000), 2400):
        await asyncio.sleep(max(0.0, t0 + (i + 2400) / 24000 - time.monotonic()))
        pos = (i + 2400) / 24000
        stueck = audio[i % len(audio):i % len(audio) + 2400]
        await live.audio(stueck.tobytes())
        if vad is None:
            if pos >= naechster_commit:
                naechster_commit += 4.0
                await live.commit({"id": i, "ende": pos})
        else:
            a24 = np.concatenate([rest, stueck.astype(np.float32) / 32768])
            k = len(a24) // 3 * 3
            rest = a24[k:]
            for _s, ende, _p in vad.zufuehren(nach_16k(a24[:k])):
                await live.commit({"id": i, "ende": ende})
        m.virtuelle_zeit = pos
        if pos >= naechste_zuordnung and abschnitt:
            naechste_zuordnung = pos + 15
            text, abschnitt[:] = "\n".join(f"Person 1: {t}" for t in abschnitt), []
            aufgaben.append(asyncio.ensure_future(zuordnen(text)))
        if pos >= naechste_frage:
            naechste_frage += 60
            aufgaben.append(asyncio.ensure_future(fragen()))
    await live.schliessen(nachlauf=1.0)
    if live.fehler:
        ich["fehler"].append(("live", live.fehler))
    if aufgaben:
        await asyncio.wait(aufgaben, timeout=30)
    ich["live_sekunden"] = round(live.gesendete_sekunden, 1)


async def lauf(stufe: str, n: int, sekunden: float) -> dict:
    import wave

    with wave.open(str(WURZEL / "demo" / "messeplanung.wav")) as w:
        demo = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")[27 * 24000:]
    if stufe == "basis":
        from coach.mistral import MistralClient
        client = MistralClient(config.mistral_schluessel())
    else:
        client = OpenAIMitZaehler(config.openai_schluessel())
    vorher = ZAEHLER.n429
    erg: dict = {"stufe": stufe, "meetings_gleichzeitig": n, "meetings": [], "nur_api": NUR_API}
    t0 = time.monotonic()
    verzug: list[float] = []  # Verzug der Ereignisschleife: misst, ob der Rechner selbst der Engpass ist
    fertig = False

    async def schleife_messen() -> None:
        while not fertig:
            t = time.monotonic()
            await asyncio.sleep(0.1)
            verzug.append(time.monotonic() - t - 0.1)

    messer = asyncio.ensure_future(schleife_messen())
    await asyncio.gather(*(ein_meeting(k, stufe, client, np.roll(demo, -k * 24000 * 7), sekunden, erg) for k in range(n)))
    fertig = True
    await messer
    verzug.sort()
    erg["schleife_verzug_p50"] = round(verzug[len(verzug) // 2], 3) if verzug else None
    erg["schleife_verzug_p95"] = round(verzug[int(len(verzug) * 0.95)], 3) if verzug else None
    erg["dauer"] = round(time.monotonic() - t0, 1)
    erg["n429"] = ZAEHLER.n429 - vorher
    zu = [x for mm in erg["meetings"] for x in mm["zuordnung"]]
    ton = [f["ton"] for mm in erg["meetings"] for f in mm["frage"]]
    erg["zuordnung_median"] = round(statistics.median(zu), 2) if zu else None
    erg["zuordnung_max"] = max(zu) if zu else None
    erg["frage_ton_median"] = round(statistics.median(ton), 2) if ton else None
    erg["frage_ton_max"] = max(ton) if ton else None
    erg["ausfaelle"] = [f for mm in erg["meetings"] for f in mm["fehler"]]
    erg["saetze"] = [mm["saetze"] for mm in erg["meetings"]]
    if hasattr(client, "schliessen"):
        await client.schliessen()
    return erg


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for laut in ("httpx", "httpx2", "httpcore", "httpcore2", "openai", "websockets"):
        logging.getLogger(laut).setLevel(logging.WARNING)
    logging.getLogger("coach").addHandler(ZAEHLER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--stufe", choices=["basis", "premium"], required=True)
    ap.add_argument("--anzahl", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--sekunden", type=float, default=120)
    ap.add_argument("--nur-api", action="store_true")
    ap.add_argument("--datei", default="")
    a = ap.parse_args()
    global NUR_API
    NUR_API = a.nur_api
    config.stufe_setzen(a.stufe)
    if a.stufe == "premium":
        object.__setattr__(EINST, "assistent_modus", "text")
    alle = []
    for n in a.anzahl:
        erg = await lauf(a.stufe, n, a.sekunden)
        alle.append(erg)
        print(json.dumps({k: erg[k] for k in ("stufe", "meetings_gleichzeitig", "nur_api", "schleife_verzug_p50",
                                                "schleife_verzug_p95", "n429", "zuordnung_median", "zuordnung_max",
                                                "frage_ton_median", "frage_ton_max", "ausfaelle", "saetze")},
                         ensure_ascii=False), flush=True)
        (AUSGABE / (a.datei or f"parallel_{a.stufe}.json")).write_text(json.dumps(alle, ensure_ascii=False, indent=1), encoding="utf-8")
        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
