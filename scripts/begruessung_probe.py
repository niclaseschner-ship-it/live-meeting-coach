r"""Probelauf Ticket #23: Nestors freie Begrüßung über gpt-realtime, echt, als WAV nach logs/begruessung/.

Der Schlüssel kommt über die Standardeingabe, nie als Argument oder im Log:

    sudo -n zugang holen openai-api-key | python scripts/begruessung_probe.py --name probe1
    ... | python scripts/begruessung_probe.py --name unterbrochen --zwischenruf 10
    ... | python scripts/begruessung_probe.py --name nein --nein 8

Läuft über den echten Weg (Assistent.begruessen → coach/begruessung.py). Das Dashboard ist eine Attrappe, die den
Ton wie der Browser hintereinander abspielt und bei „stimme_stopp“ verstummt; das Mikrofon bekommt Stille in
Echtzeit, bei --zwischenruf/--nein nach so vielen Sekunden Wiedergabe einen Zuruf (gpt-4o-mini-tts, andere
Stimme, einmal erzeugt und wiederverwendet). Ergebnis: <name>.wav (Lautsprecher + Zuruf gemischt) und
<name>.json (Transkript je Antwort, hörbarer Teil, Prüfung, Dauer, Kosten).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
AUSGABE = WURZEL / "logs" / "begruessung"
RATE = 24000
VORLAUF = 0.4  # wie im Coach angenommen: bis der Ton im Browser zu hören ist

MEETING = {
    "titel": "Messeplanung 2027", "ziel": "Standkonzept und Budget für die Messe festlegen",
    "agenda": [{"titel": "Standkonzept", "minuten": 15}, {"titel": "Budget", "minuten": 20},
               {"titel": "Personal", "minuten": 10}, {"titel": "Zeitplan", "minuten": 15}],
    "regel_ids": ["zeit", "kurz", "ergebnisse"], "regeln": ["Handys bleiben in der Tasche"],
}
ZURUFE = {"zwischenruf": ("Passt, leg los!", "zwischenruf_passt.wav"), "nein": ("Nein.", "zwischenruf_nein.wav")}


class Lautsprecher:
    """Spielt wie static/basis.js: Stücke hintereinander, stimme_stopp bricht ab und leert die Schlange."""

    def __init__(self) -> None:
        self.stuecke: list[list] = []  # [start (monotonic), pcm int16]
        self.naechste = 0.0
        self.erster: float | None = None
        self.stopps: list[float] = []

    async def __call__(self, n: dict) -> None:
        jetzt = time.monotonic()
        if n.get("typ") == "stimme":
            pcm = np.frombuffer(base64.b64decode(n["pcm"]), dtype="<i2")
            t = max(jetzt + VORLAUF, self.naechste)
            self.stuecke.append([t, pcm])
            self.naechste = t + len(pcm) / RATE
            if self.erster is None:
                self.erster = t
        elif n.get("typ") == "stimme_stopp":
            self.stopps.append(jetzt)
            behalten = []
            for t, pcm in self.stuecke:
                if t >= jetzt:
                    continue
                gespielt = int((jetzt - t) * RATE)
                behalten.append([t, pcm[:gespielt]])
            self.stuecke, self.naechste = behalten, 0.0

    def ende(self) -> float:
        return max((t + len(p) / RATE for t, p in self.stuecke), default=0.0)


def zuruf_laden(art: str) -> np.ndarray:
    text, datei = ZURUFE[art]
    pfad = AUSGABE / datei
    if not pfad.exists():
        from openai import OpenAI

        roh = OpenAI().audio.speech.create(model="gpt-4o-mini-tts", voice="ash", input=text, response_format="pcm",
                                           instructions="Locker, freundlich, deutsch, normal laut, wie im Meeting.")
        with wave.open(str(pfad), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(roh.content)
    with wave.open(str(pfad), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


async def lauf(args) -> dict:
    from openai import AsyncOpenAI

    from coach import begruessung as B
    from coach import pipeline
    from coach.config import EINST
    from coach.pipeline import Coach

    kosten: list[dict] = []
    alt_loggen = pipeline.nutzung_loggen

    def loggen(e: dict) -> None:
        from coach.kosten import dollar

        kosten.append({**{k: v for k, v in e.items() if not k.startswith("details")}, "usd": round(dollar(e), 5)})
        alt_loggen(e)

    pipeline.nutzung_loggen = loggen
    instanzen: list = []
    alt_init = B.Begruessung.__init__

    def init(self, *a, **k):
        alt_init(self, *a, **k)
        instanzen.append(self)

    B.Begruessung.__init__ = init

    c = Coach()
    c._einrichten(MEETING)
    c._client = AsyncOpenAI()
    c.meeting.starten()
    ls = Lautsprecher()
    c.direkt.append(ls)
    zuruf = None
    art = "zwischenruf" if args.zwischenruf else ("nein" if args.nein else None)
    if art:
        zuruf = zuruf_laden(art)
    nach = args.zwischenruf or args.nein
    mikro_start: float | None = None
    laeuft = True

    async def mikro():
        nonlocal mikro_start
        pos, schritt = 0, int(RATE * 0.1)
        t_naechst = time.monotonic()
        while laeuft:
            jetzt = time.monotonic()
            stueck = np.zeros(schritt, dtype="<i2")
            if zuruf is not None and ls.erster is not None and jetzt >= ls.erster + nach and pos < len(zuruf):
                if mikro_start is None:
                    mikro_start = jetzt
                teil = zuruf[pos:pos + schritt]
                stueck[:len(teil)] = teil
                pos += schritt
            await c.assistent.audio(stueck.tobytes())
            t_naechst += 0.1
            await asyncio.sleep(max(0.0, t_naechst - time.monotonic()))

    t0 = time.monotonic()
    feeder = asyncio.create_task(mikro())
    await c.assistent.begruessen()
    t_fertig = time.monotonic()
    # Vorstellungsrunde: Takt laufen lassen, bis der Start gesagt ist
    while c.assistent.vorstellung_bis is not None:
        c.assistent.takt()
        await asyncio.sleep(0.5)
    await asyncio.sleep(1.0)
    b0 = instanzen[0] if instanzen else None
    if b0 is not None and b0._einwand_aufgabe is not None:
        await b0._einwand_aufgabe  # Nein: Bestätigung „Verstanden …“ abwarten
    while c.assistent._aufgabe and not c.assistent._aufgabe.done():
        await asyncio.sleep(0.5)
    if c.assistent.gespraech and getattr(c.assistent.gespraech, "_start_laeuft", False):
        while c.assistent.gespraech and c.assistent.gespraech._start_laeuft:
            await asyncio.sleep(0.5)
    while time.monotonic() < ls.ende() + 1.0:
        await asyncio.sleep(0.2)
    laeuft = False
    await feeder
    if c.assistent.gespraech:
        await c.assistent.gespraech.schliessen()

    # Mischung: Lautsprecher + Zuruf (so, wie es im Raum zu hören wäre)
    beginn = min([t for t, _ in ls.stuecke] + ([mikro_start] if mikro_start else []), default=t0)
    ende = max(ls.ende(), (mikro_start + len(zuruf) / RATE) if mikro_start else 0.0)
    mix = np.zeros(int((ende - beginn) * RATE) + RATE // 2, dtype=np.int32)
    for t, pcm in ls.stuecke:
        i = int((t - beginn) * RATE)
        mix[i:i + len(pcm)] += pcm
    if mikro_start:
        i = int((mikro_start - beginn) * RATE)
        mix[i:i + len(zuruf)] += zuruf
    AUSGABE.mkdir(parents=True, exist_ok=True)
    with wave.open(str(AUSGABE / f"{args.name}.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(np.clip(mix, -32768, 32767).astype("<i2").tobytes())

    b = instanzen[0] if instanzen else None
    gespielt = sum(len(p) for _, p in ls.stuecke) / RATE
    return {
        "name": args.name,
        "zwischenruf": {"art": art, "nach_s": nach, "um_s": round(mikro_start - ls.erster, 1) if mikro_start else None},
        "erster_ton_nach_s": round(ls.erster - t0, 2) if ls.erster else None,
        "dauer_ton_s": round(gespielt, 1),
        "dauer_gesamt_s": round(ls.ende() - ls.erster, 1) if ls.erster else None,
        "begruessen_s": round(t_fertig - t0, 1),
        "stopps_nach_s": [round(s - ls.erster, 1) for s in ls.stopps] if ls.erster else [],
        "ergebnis": b.ergebnis if b else None,
        "antworten": [{"status": a.get("status"), "text": a.get("text"), "hoerbar": B.hoerbar(a),
                       "sekunden": round(a.get("bytes", 0) / 2 / RATE, 1), "gekuerzt_bei_s": a.get("gekuerzt")}
                      for a in (b.antworten if b else [])],
        "zwischenrufe_gehoert": b.zwischenrufe if b else [],
        "protokoll": [e for e in c.protokoll if e.get("art") in ("begruessung", "begruessung_pruefung", "einwand")],
        "gesprochen_fest": [t for _, _, t in c.assistent.sprechtexte
                            if t not in [a.get("text") for a in (b.antworten if b else [])]],
        "kosten": kosten, "usd": round(sum(k["usd"] for k in kosten), 4),
        "mikro_sekunden": round(time.monotonic() - t0, 1),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--zwischenruf", type=float, default=0.0, help="„Passt, leg los“ nach so vielen s Wiedergabe")
    p.add_argument("--nein", type=float, default=0.0, help="„Nein“ nach so vielen s Wiedergabe")
    p.add_argument("--vorstellung", type=float, default=0.0, help="Vorstellungsrunde in s (0 = keine)")
    args = p.parse_args()
    schluessel = sys.stdin.readline().strip()
    if not schluessel:
        sys.exit("Kein Schlüssel auf der Standardeingabe.")
    os.environ["OPENAI_API_KEY"] = schluessel
    os.environ["LMC_VORSTELLUNG_SEKUNDEN"] = str(args.vorstellung)
    os.environ.setdefault("LMC_STUFE", "premium")
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for laut in ("httpx", "websockets", "openai"):
        logging.getLogger(laut).setLevel(logging.WARNING)
    erg = asyncio.run(lauf(args))
    (AUSGABE / f"{args.name}.json").write_text(json.dumps(erg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: erg[k] for k in ("name", "ergebnis", "dauer_gesamt_s", "dauer_ton_s", "usd",
                                          "stopps_nach_s")}, ensure_ascii=False))
    for a in erg["antworten"]:
        print(f"[{a['status']}, {a['sekunden']} s{', gekürzt bei ' + str(a['gekuerzt_bei_s']) if a['gekuerzt_bei_s'] is not None else ''}] {a['hoerbar']}")
    print("Zurufe gehört:", erg["zwischenrufe_gehoert"])
    print("Protokoll:", erg["protokoll"])


if __name__ == "__main__":
    main()
