"""Messungen für Nestor Basis (Ticket #13, docs/messung_basis.md) – echte API-Aufrufe, Kosten wenige Cent.

    python scripts/basis_messen.py zurufe              # die 12 Zurufe der Machbarkeitsprobe als Audio (einmalig)
    python scripts/basis_messen.py kette [--n 10]      # Sprechende → erster Ton (Schritt 0, Stoppregel 2,5 s)
    python scripts/basis_messen.py aktionen [--stufe basis|premium] [--laeufe 1]
                                                       # 12 Zurufe: richtige Aktion? erster Satz nach … s
    python scripts/basis_messen.py hoerproben          # Thorstens Antworten als WAV unter logs/basis/hoerproben/

Schlüssel nur aus der Umgebung (MISTRAL_API_KEY bzw. OPENAI_API_KEY). Alle Ergebnisse unter logs/basis/ (nicht im Git).

Kette: Jeder Zuruf (synthetisch, Stimme „nic-de“ aus dem Mistral-Konto) läuft in Echtzeit in 100-ms-Stücken durch
genau die Bausteine des Coaches – Pausenerkennung (Silero), Live-Text (LiveTextMistral, Voxtral Realtime mit
target_streaming_delay_ms=240), Ansprache-Erkennung, Antwort (mistral-medium, Systemanweisung aus assistent.py,
Kontext der Messe-Demo), erster Satz an die Sprachausgabe (Voxtral TTS, voice_id Thorsten). Gemessen wird ab dem
Sprechende (Ende der Sprache in der Aufnahme) bis das erste Tonstück auf dem Server ankommt – wie
logs/nestor_zeiten.jsonl im Betrieb; der Weg Server → Browser (LAN, wenige ms) und der Abspielpuffer fehlen.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import assistent as A  # noqa: E402
from coach import config  # noqa: E402
from coach.config import EINST, WURZEL  # noqa: E402

AUSGABE = WURZEL / "logs" / "basis"
NIC = "45037c68-ec51-466c-8393-dabaafb73607"  # gespeicherte Stimme „nic-de“ (Fragesteller in den Proben)

# Die 12 Zurufe aus der Machbarkeitsprobe (~/brainstorm/mistral-probe/aktion.py) mit erwarteter Aktion
ZURUFE = [
    ("Nestor, wo stehen wir gerade?", "keine"),
    ("Nestor, zeig uns bitte die Übersicht.", "bild"),
    ("Nestor, kannst du mal aufmalen, was noch offen ist?", "bild"),
    ("Nestor, lass uns zum nächsten Punkt gehen.", "keine|weiter"),  # es gibt keinen nächsten Punkt
    ("Nestor, spring bitte nochmal zurück zu Punkt zwei.", "weiter"),
    ("Nestor, gib uns einen kurzen Überblick, was ein Eckstand auf der Messe Stuttgart pro Quadratmeter kostet.",
     "recherche"),
    ("Nestor, was kosten Hotels in Stuttgart während großer Messen?", "recherche"),
    ("Nestor, hör bitte mal kurz nicht zu, wir müssen was Vertrauliches besprechen.", "pause"),
    ("Nestor, was haben wir zum Budget beschlossen?", "keine"),
    ("Nestor, wer bucht eigentlich die Hotels?", "keine"),
    ("Nestor, wer hat hier am meisten geredet?", "keine"),
    ("Nestor, haben wir schon entschieden, wer die Flyer macht?", "keine"),
]


def demo_kontext() -> str:
    """Meeting-Zustand der Messe-Demo bei 2:45 – derselbe Kontext wie in der Machbarkeitsprobe."""
    zeilen = [z for z in (WURZEL / "demo" / "protokoll.md").read_text(encoding="utf-8").splitlines()
              if re.match(r"- \d:\d\d", z)]
    zeilen = [re.sub(r"^- (\d:\d\d) \*\*(.+?):\*\* ", r"[\1] \2: ", z.strip()).replace("[–]", "") for z in zeilen]
    zeilen = [z for z in zeilen if z[1:5] < "2:44"]
    return ("Meeting: Messeplanung 2027 · Ziel: Stand, Budget und Aufgaben für die Fachmesse im April festlegen · "
            "Laufzeit 2:45 min\nAgenda:\n"
            "1. Termin und Messestand [erledigt; 0:55 von 1 min] – Ziel: Standgröße und Lage entscheiden – Ergebnis: "
            "40 Quadratmeter Eckstand; Aufgabe: Stand buchen (wer: offen, bis: Freitag)\n"
            "2. Budget [erledigt; 1:00 von 1 min] – Ziel: Obergrenze beschließen – Ergebnis: höchstens 25.000 Euro\n"
            "3. Aufgaben verteilen [läuft; 0:24 von 1 min] – Ziel: Wer macht was bis wann\n"
            "Vereinbarte Regeln: Ausreden lassen, Beim Thema bleiben, Zeit im Blick, Kurz fassen, Ton, Ergebnisse "
            "festhalten\n\nTranskript (neuester Teil):\n" + "\n".join(zeilen))


def client_fuer(stufe: str):
    config.stufe_setzen(stufe)
    if stufe == "basis":
        from coach.mistral import MistralClient
        return MistralClient(config.mistral_schluessel())
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=config.openai_schluessel())


def wav_lesen(pfad: Path) -> np.ndarray:
    with wave.open(str(pfad)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def wav_schreiben(pfad: Path, s16: np.ndarray, rate: int = 24000) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(pfad), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(s16.astype("<i2").tobytes())


def sprechende(s16: np.ndarray, rate: int = 24000) -> float:
    """Ende der Sprache: letztes 10-ms-Fenster über -40 dBFS."""
    f = rate // 100
    n = len(s16) // f
    rms = np.sqrt((s16[:n * f].astype(np.float64).reshape(n, f) / 32768) ** 2).mean(axis=1)
    laut = np.nonzero(rms > 0.01)[0]
    return float((laut[-1] + 1) * f / rate) if len(laut) else len(s16) / rate


async def tts(client, text: str, stimme: str) -> np.ndarray:
    teile = []
    async with client.audio.speech.with_streaming_response.create(model=EINST.basis_stimme_modell, voice=stimme,
                                                                  input=text, response_format="pcm") as r:
        async for s in r.iter_bytes(9600):
            teile.append(s)
    return np.frombuffer(b"".join(teile), dtype="<i2")


# --- Zurufe als Audio ---------------------------------------------------------------------------------------------
async def zurufe() -> None:
    c = client_fuer("basis")
    for i, (frage, _) in enumerate(ZURUFE):
        pfad = AUSGABE / "zurufe" / f"{i:02d}.wav"
        if pfad.exists():
            continue
        wav_schreiben(pfad, await tts(c, frage, NIC))
        print("erzeugt", pfad.name, frage)
        await asyncio.sleep(1.0)
    await c.schliessen()


# --- Kette Sprechende → erster Ton ----------------------------------------------------------------------------------
# Die Zurufe stehen mitten im Meeting: Voxtral Realtime erkennt „Nestor“ am Anfang einer frischen Sitzung schlecht
# („Nächstes Tor“, „Nest door“, einmal japanisch – Vorlauf 08.10.), mit deutschem Gespräch davor wie im Meeting gut.
# Darum eine durchgehende Sitzung: 23 s Demo-Gespräch, dann je Zuruf: Frage, 3,5 s Stille, 8 s Demo-Gespräch.
DEMO_VON, DEMO_BIS = 27.0, 116.0  # Messe-Demo ohne „Nestor“ (Punkt 1 bis Ende Budget)


def zuruf_audio(n: int, stille_s: float = 3.5) -> tuple[np.ndarray, list[dict]]:
    """23 s Demo-Gespräch, dann je Zuruf: 1,2 s Pause, Frage, Stille, 8 s Demo-Gespräch (24 kHz, s16)."""
    demo = wav_lesen(WURZEL / "demo" / "messeplanung.wav")
    stuecke, fragen = [demo[int(DEMO_VON * 24000):int(50 * 24000)]], []
    pos, fueller = len(stuecke[0]) / 24000, 50.0
    for k in range(n):
        nr = k % len(ZURUFE)
        roh = wav_lesen(AUSGABE / "zurufe" / f"{nr:02d}.wav")
        vorher = np.zeros(int(1.2 * 24000), "<i2")  # kurze Pause vor dem Zuruf, sonst hängt das Gespräch davor dran
        pos += len(vorher) / 24000
        stuecke.append(vorher)
        fragen.append({"nr": nr, "frage_soll": ZURUFE[nr][0], "start": pos, "ende_audio": round(pos + sprechende(roh), 2)})
        if fueller + 8 > DEMO_BIS:
            fueller = 50.0
        stille = np.zeros(int(stille_s * 24000), "<i2")
        teil = demo[int(fueller * 24000):int((fueller + 8) * 24000)]
        fueller += 8
        stuecke += [roh, stille, teil]
        pos += (len(roh) + len(stille) + len(teil)) / 24000
    return np.concatenate(stuecke), fragen


async def kette_lauf(c, n: int, kontext: str) -> list[dict]:
    from coach.hoeren import nach_16k
    from coach.livetext import LiveTextMistral
    from coach.vad import Pausenerkennung

    audio, fragen = zuruf_audio(n)
    t0 = 0.0
    zustand = {"warte_auf_frage": None}
    laeufe: list[asyncio.Task] = []

    def frage_zu(zeit: float) -> dict | None:
        """Zu welchem Zuruf gehört eine Äußerung, die bei dieser Audiozeit endet?"""
        for f in fragen:
            if f["start"] - 0.5 <= zeit <= f["ende_audio"] + 1.0:
                return f
        return None

    async def antworten(f: dict, text: str, frage: str, ende_ausloeser: float) -> None:
        m = f
        m.update(text=text, frage=frage, ende_ausloeser=round(ende_ausloeser, 2),
                 t_text=time.monotonic() - t0)
        strom = await c.chat.completions.create(
            model=EINST.assistent_modell, stream=True, stream_options={"include_usage": True},
            messages=[{"role": "system", "content": A.system_text()},
                      {"role": "user", "content": kontext + "\n\nFrage an dich: " + frage}])
        puffer, erste, satz = "", None, None
        async for teil in strom:
            d = teil.choices[0].delta.content if teil.choices else None
            if not d:
                continue
            m.setdefault("t_token", time.monotonic() - t0)
            puffer += d
            if erste is None:
                if "\n" not in puffer:
                    continue
                erste, puffer = puffer.split("\n", 1)
                m["aktion"] = erste.strip()
            saetze, puffer = A.saetze_teilen(puffer)
            if saetze:
                satz = saetze[0]
                break
        if satz is None:
            satz = puffer.strip() or "Ja."
        m.update(t_satz=time.monotonic() - t0, satz=satz)
        async with c.audio.speech.with_streaming_response.create(model=EINST.stimme_modell, voice=EINST.stimme,
                                                                 input=satz, response_format="pcm") as r:
            async for _ in r.iter_bytes(9600):
                m["t_ton"] = time.monotonic() - t0
                break
        # bezogen auf das Ende der auslösenden Äußerung (wie im Betrieb) und auf das Ende des ganzen Zurufs
        for k in ("t_text", "t_token", "t_satz", "t_ton"):
            if k in m:
                m[k.replace("t_", "ab_ende_")] = round(m[k] - ende_ausloeser, 3)
                m[k.replace("t_", "ab_zuruf_")] = round(m[k] - m["ende_audio"], 3)
        print(json.dumps({k: m.get(k) for k in ("nr", "text", "ab_ende_text", "ab_ende_satz", "ab_ende_ton",
                                                 "ab_zuruf_ton", "aktion")}, ensure_ascii=False), flush=True)

    async def bei_satz(meta, text) -> None:
        """Wie Assistent.satz im Textmodus: Name mit Frage → antworten; nur der Name → nächste Äußerung ist die Frage."""
        ende = meta["ende"]
        f = frage_zu(ende)
        if f is not None:
            f.setdefault("saetze", []).append([round(ende, 2), round(time.monotonic() - t0, 2), text])
        if f is None or "t_text" in f:
            return
        if A.angesprochen(text):
            frage = A.frage_aus(text)
            if len(frage.split()) < 3:
                zustand["warte_auf_frage"] = f
                f["nur_name"] = text
                return
            laeufe.append(asyncio.ensure_future(antworten(f, text, frage, ende)))
        elif zustand["warte_auf_frage"] is f:
            zustand["warte_auf_frage"] = None
            laeufe.append(asyncio.ensure_future(antworten(f, text, text.strip(), ende)))

    async def bei_teil(_t) -> None:
        pass

    live = LiveTextMistral(bei_teil, bei_satz)
    vad = Pausenerkennung()
    await live.verbinden()
    t0 = time.monotonic()
    rest = np.zeros(0, np.float32)
    for i in range(0, len(audio), 2400):
        await asyncio.sleep(max(0.0, t0 + (i + 2400) / 24000 - time.monotonic()))  # wie ein Mikrofon: erst nach dem Stück
        stueck = audio[i:i + 2400]
        await live.audio(stueck.tobytes())
        a24 = np.concatenate([rest, stueck.astype(np.float32) / 32768])
        k = len(a24) // 3 * 3
        rest = a24[k:]
        for _start, ende, _ in vad.zufuehren(nach_16k(a24[:k])):
            await live.commit({"id": i, "ende": ende})
    await live.schliessen(nachlauf=1.0)
    if laeufe:
        await asyncio.wait(laeufe, timeout=15)
    for f in fragen:
        if "t_ton" not in f:
            f["fehler"] = "nicht beantwortet" if "t_text" not in f else "kein Ton"
    print(f"Live-Text: {live.gesendete_sekunden:.0f} s Audio gesendet")
    return fragen


async def kette(n: int) -> None:
    c = client_fuer("basis")
    ergebnisse = await kette_lauf(c, n, demo_kontext())
    await c.schliessen()
    (AUSGABE / "kette.json").write_text(json.dumps(ergebnisse, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in ergebnisse:
        if "fehler" in m:
            print("FEHLT", m["nr"], m["fehler"], m.get("saetze"))
    tone = [m["ab_ende_ton"] for m in ergebnisse if "ab_ende_ton" in m]
    for k in ("ab_ende_text", "ab_ende_token", "ab_ende_satz", "ab_ende_ton", "ab_zuruf_ton"):
        w = [m[k] for m in ergebnisse if k in m]
        if w:
            print(f"{k:14s} Median {statistics.median(w):.2f} s  min {min(w):.2f}  max {max(w):.2f}  (n={len(w)})")
    if tone:
        med = statistics.median(tone)
        print(f"\nMedian Sprechende → erster Ton: {med:.2f} s – {'STOPP (> 2,5 s)' if med > 2.5 else 'weiter (≤ 2,5 s)'}")


# --- Ganze Pipeline: Zurufe mitten im Meeting, abgespielt durch den Coach -------------------------------------------
async def pipeline(stufe: str, n: int) -> None:
    """Die Zurufe laufen als Aufnahme durch Coach.abspielen – derselbe Weg wie im Dashboard. Gemessen wird mit
    Nestors eigener Zeitmessung (logs/nestor_zeiten.jsonl): Verzug des Satzes nach Sprechende + bis zum ersten Ton."""
    import os

    from coach.pipeline import NESTOR_ZEITEN, NUTZUNG, Coach

    config.stufe_setzen(stufe)
    audio, fragen = zuruf_audio(n, stille_s=8.0)
    pfad = AUSGABE / f"zurufe_meeting_{n}.wav"
    wav_schreiben(pfad, audio)
    einrichtung = json.loads((WURZEL / "demo" / "messeplanung.json").read_text(encoding="utf-8"))
    pfad.with_suffix(".json").write_text(json.dumps(einrichtung, ensure_ascii=False), encoding="utf-8")
    vorher_z = NESTOR_ZEITEN.read_text(encoding="utf-8").count("\n") if NESTOR_ZEITEN.exists() else 0
    vorher_n = NUTZUNG.read_text(encoding="utf-8").count("\n") if NUTZUNG.exists() else 0
    coach = Coach()
    coach.onepager_am_ende = False

    async def beobachten() -> None:
        if coach.assistent.pausiert:  # „hör kurz nicht zu“ – für die Messung gleich wieder einschalten
            await asyncio.sleep(2)
            coach.assistent.fortsetzen()

    coach.beobachter.append(beobachten)
    await coach.abspielen(pfad, tempo=1.0, auto_wechsel=False)
    await asyncio.sleep(12)
    zeiten = [json.loads(z) for z in NESTOR_ZEITEN.read_text(encoding="utf-8").splitlines()[vorher_z:]]
    nutzung = [json.loads(z) for z in NUTZUNG.read_text(encoding="utf-8").splitlines()[vorher_n:]]
    antworten = [e for e in coach.protokoll if e["art"] in ("assistent", "recherche")]
    gesamt = [round(z["verzug_text"] + z["bis_ton"], 2) for z in zeiten if z["ausloeser"] == "ansprache"]
    erg = {"stufe": stufe, "n": n, "zeiten": zeiten, "sprechende_bis_ton": gesamt,
           "antworten": [{k: e.get(k) for k in ("zeit", "art", "frage", "antwort", "aktion", "quellen", "sekunden")}
                         for e in antworten],
           "modelle": sorted({e.get("modell", "") for e in nutzung}),
           "usd": round(sum(e.get("usd", 0) for e in nutzung), 4), "transkript": [s.text for s in coach.meeting.transkript]}
    (AUSGABE / f"pipeline_{stufe}.json").write_text(json.dumps(erg, ensure_ascii=False, indent=1), encoding="utf-8")
    for e in antworten:
        print(f"{e['zeit']:6.1f}s {e['art']:9s} {str(e.get('frage'))[:50]:50s} → {str(e.get('aktion'))[:40]}  {str(e.get('antwort'))[:80]}")
    if gesamt:
        print(f"\n{stufe}: Sprechende → erster Ton (Ansprache) Median {statistics.median(gesamt):.2f} s, "
              f"min {min(gesamt):.2f}, max {max(gesamt):.2f}, n={len(gesamt)}; Modelle {erg['modelle']}; {erg['usd']} $")


# --- Aktionen ------------------------------------------------------------------------------------------------------------
async def aktionen(stufe: str, laeufe: int) -> None:
    c = client_fuer(stufe)
    kontext = demo_kontext()
    erg = []
    for lauf in range(laeufe):
        for frage, soll in ZURUFE:
            t0 = time.monotonic()
            strom = await c.chat.completions.create(
                model=EINST.assistent_modell, stream=True,
                messages=[{"role": "system", "content": A.system_text()},
                          {"role": "user", "content": kontext + "\n\nFrage an dich: " + A.frage_aus(frage)}],
                **({"reasoning_effort": EINST.assistent_aufwand} if EINST.assistent_aufwand else {}))
            text, satz = "", None
            async for t in strom:
                d = t.choices[0].delta.content if t.choices else None
                if d:
                    text += d
                    if satz is None and "\n" in text and A.saetze_teilen(text.split("\n", 1)[1])[0]:
                        satz = time.monotonic() - t0
            ok = bool(re.match(r"\s*AKTION:\s*(" + soll + r")\b", text, re.I))
            person = bool(re.search(r"Person \d", text))
            erg.append({"lauf": lauf, "frage": frage, "soll": soll, "ok": ok, "person_genannt": person,
                        "erster_satz": round(satz or time.monotonic() - t0, 2), "text": text.strip()})
            print(("OK  " if ok else "FALSCH") + f" {erg[-1]['erster_satz']:.2f}s  {frage[:60]}  →  "
                  + text.strip().split("\n")[0], flush=True)
            await asyncio.sleep(1.1 if stufe == "basis" else 0)
    if hasattr(c, "schliessen"):
        await c.schliessen()
    (AUSGABE / f"aktionen_{stufe}.json").write_text(json.dumps(erg, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(e["ok"] for e in erg)
    print(f"\n{stufe}: Aktion richtig {ok}/{len(erg)}, „Person N“ genannt {sum(e['person_genannt'] for e in erg)}×, "
          f"erster Satz Median {statistics.median(e['erster_satz'] for e in erg):.2f} s")


# --- Hörproben -------------------------------------------------------------------------------------------------------------
async def hoerproben() -> None:
    """Thorstens Antworten auf einige Zurufe (aus aktionen_basis.json) plus Begrüßung als WAV."""
    from coach.zustand import Agendapunkt, Meeting

    c = client_fuer("basis")
    m = Meeting(titel="Messeplanung 2027", agenda=[Agendapunkt("Termin und Messestand", "", 1),
                                                   Agendapunkt("Budget", "", 1), Agendapunkt("Aufgaben verteilen", "", 1)],
                regel_ids=["ausreden", "thema", "zeit", "kurz", "ton", "ergebnisse"])
    gruss, start = A.begruessungstext(m, basis=True)
    texte = {"00_begruessung": gruss, "01_start": start}
    datei = AUSGABE / "aktionen_basis.json"
    if datei.exists():
        for e in json.loads(datei.read_text(encoding="utf-8"))[:12]:
            if e["soll"] in ("keine", "pause", "keine|weiter"):
                rumpf = e["text"].split("\n", 1)[-1].strip()
                texte[f"{len(texte):02d}_" + re.sub(r"\W+", "_", A.frage_aus(e["frage"]).lower())[:40]] = rumpf
    texte[f"{len(texte):02d}_ueberlast"] = A.UEBERLAST
    for name, text in texte.items():
        wav_schreiben(AUSGABE / "hoerproben" / f"{name}.wav", await tts(c, text, EINST.basis_stimme))
        print(name, "–", text[:90])
        await asyncio.sleep(1.0)
    await c.schliessen()


def main() -> None:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for laut in ("httpx", "httpx2", "httpcore", "httpcore2", "openai", "websockets"):
        logging.getLogger(laut).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("was", choices=["zurufe", "kette", "aktionen", "hoerproben", "pipeline"])
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--stufe", default="basis", choices=["basis", "premium"])
    ap.add_argument("--laeufe", type=int, default=1)
    a = ap.parse_args()
    AUSGABE.mkdir(parents=True, exist_ok=True)
    if a.was == "zurufe":
        asyncio.run(zurufe())
    elif a.was == "kette":
        asyncio.run(kette(a.n))
    elif a.was == "pipeline":
        asyncio.run(pipeline(a.stufe, a.n))
    elif a.was == "aktionen":
        asyncio.run(aktionen(a.stufe, a.laeufe))
    else:
        asyncio.run(hoerproben())


if __name__ == "__main__":
    main()
