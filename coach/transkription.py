"""Zuhören: aus einem Audio-Block werden Sprecherspur und deutscher Text.

Ablauf je Block:
1. Pegel angleichen (Laptop-Mikrofon im Raum: entfernte Stimmen sind leise).
2. Sprecherspur mit gpt-4o-transcribe-diarize: wer spricht wann. Dessen Text wird verworfen,
   weil das Modell bei Raumaudio ins Englische übersetzt, auch mit language="de"
   (gemessen 02.10.2026; ohne Sprachvorgabe passiert es schon bei leichtem Rauschen).
3. Die Spur wird zu Sprecherbeiträgen zusammengefasst, jeder Beitrag aus dem Audio geschnitten
   und einzeln von gpt-4o-transcribe auf Deutsch transkribiert (im Vergleich das beste Deutsch).
   Damit stimmt die Zuordnung „wer hat was gesagt“ ohne nachträgliches Raten.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import wave
from array import array

RATE = 16000
STILLE_RMS = 200  # 16-bit-Pegel; darunter wird ein Block gar nicht verschickt
ZIEL_RMS = 3000  # Pegelangleich: Ziel-Effektivwert
MAX_VERSTAERKUNG = 8.0
LUECKE_SEKUNDEN = 1.0  # gleiche Person, kürzere Pause: ein Beitrag
MIN_BEITRAG_SEKUNDEN = 1.0  # kürzere Schnipsel (Zickzack bei Überlappung) gehen im Nachbarbeitrag auf
RAND_SEKUNDEN = 0.25  # Puffer beim Ausschneiden, damit kein Wortanfang fehlt
PARALLEL = 6


# --- Audio-Hilfen ----------------------------------------------------------

def proben_lesen(wav: bytes) -> array:
    with wave.open(io.BytesIO(wav)) as w:
        return array("h", w.readframes(w.getnframes()))


def wav_schreiben(proben: array) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(proben.tobytes())
    return buf.getvalue()


def rms(proben: array) -> float:
    return math.sqrt(sum(p * p for p in proben) / len(proben)) if proben else 0.0


def wav_info(wav: bytes) -> tuple[float, float]:
    """Dauer in Sekunden und RMS-Pegel eines 16-bit-Mono-WAV."""
    p = proben_lesen(wav)
    return len(p) / RATE, rms(p)


def pegel_angleichen(proben: array) -> array:
    """Auf Ziel-Effektivwert verstärken, begrenzt, ohne Übersteuern."""
    aktuell = rms(proben)
    if aktuell <= 0:
        return proben
    faktor = min(MAX_VERSTAERKUNG, ZIEL_RMS / aktuell)
    if faktor <= 1.0:
        return proben
    return array("h", (max(-32768, min(32767, int(x * faktor))) for x in proben))


def ausschneiden(proben: array, start: float, ende: float) -> array:
    a = max(0, int((start - RAND_SEKUNDEN) * RATE))
    b = min(len(proben), int((ende + RAND_SEKUNDEN) * RATE))
    return proben[a:b]


def als_data_url(wav: bytes) -> str:
    return "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")


def _feld(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


# --- Sprecherbeiträge aus der Spur ----------------------------------------

def beitraege(spur: list[dict]) -> list[dict]:
    """Spur → Sprecherbeiträge: gleiche Person mit kurzer Pause zusammen, Kleinstschnipsel in den Nachbarn."""
    zusammen: list[dict] = []
    for s in sorted(spur, key=lambda x: x["start"]):
        if zusammen and zusammen[-1]["sprecher"] == s["sprecher"] and s["start"] - zusammen[-1]["ende"] <= LUECKE_SEKUNDEN:
            zusammen[-1]["ende"] = max(zusammen[-1]["ende"], s["ende"])
        else:
            zusammen.append(dict(s))

    # Kleinstschnipsel (z. B. Zickzack bei gleichzeitigem Sprechen) dem vorherigen Beitrag zuschlagen
    ergebnis: list[dict] = []
    for b in zusammen:
        if ergebnis and b["ende"] - b["start"] < MIN_BEITRAG_SEKUNDEN:
            ergebnis[-1]["ende"] = max(ergebnis[-1]["ende"], b["ende"])
        elif ergebnis and ergebnis[-1]["sprecher"] == b["sprecher"] and b["start"] - ergebnis[-1]["ende"] <= LUECKE_SEKUNDEN:
            ergebnis[-1]["ende"] = max(ergebnis[-1]["ende"], b["ende"])
        else:
            ergebnis.append(dict(b))
    # ein kurzer erster Beitrag geht im zweiten auf
    if len(ergebnis) > 1 and ergebnis[0]["ende"] - ergebnis[0]["start"] < MIN_BEITRAG_SEKUNDEN:
        ergebnis[1]["start"] = ergebnis[0]["start"]
        ergebnis.pop(0)
    return ergebnis


# --- API-Aufrufe -----------------------------------------------------------

async def sprecherspur(client, modell: str, wav: bytes, referenzen: dict[str, str], sprache: str) -> list[dict]:
    extra = None
    if referenzen:
        namen = list(referenzen)[:4]
        extra = {"known_speaker_names": namen, "known_speaker_references": [referenzen[n] for n in namen]}
    antwort = await client.audio.transcriptions.create(
        model=modell,
        file=("block.wav", wav, "audio/wav"),
        language=sprache,
        response_format="diarized_json",
        chunking_strategy="auto",
        extra_body=extra,
    )
    return [
        {
            "sprecher": str(_feld(s, "speaker") or "?"),
            "start": float(_feld(s, "start") or 0.0),
            "ende": float(_feld(s, "end") or 0.0),
        }
        for s in _feld(antwort, "segments") or []
    ]


async def text(client, modell: str, wav: bytes, sprache: str, prompt: str) -> str:
    antwort = await client.audio.transcriptions.create(
        model=modell,
        file=("beitrag.wav", wav, "audio/wav"),
        language=sprache,
        prompt=prompt or None,
    )
    return (_feld(antwort, "text") or "").strip()


async def transkribieren(
    client,
    sprecher_modell: str,
    text_modell: str,
    wav: bytes,
    referenzen: dict[str, str],
    sprache: str = "de",
    prompt: str = "",
) -> tuple[list[dict], list[dict], float]:
    """Liefert (Sprecherspur, Beiträge mit Text, transkribierte Sekunden); Zeiten relativ zum Blockanfang."""
    proben = pegel_angleichen(proben_lesen(wav))
    spur = await sprecherspur(client, sprecher_modell, wav_schreiben(proben), referenzen, sprache)
    teile = beitraege(spur) or [{"sprecher": "?", "start": 0.0, "ende": len(proben) / RATE}]

    grenze = asyncio.Semaphore(PARALLEL)

    async def eins(b: dict) -> str:
        async with grenze:
            return await text(client, text_modell, wav_schreiben(ausschneiden(proben, b["start"], b["ende"])), sprache, prompt)

    texte = await asyncio.gather(*(eins(b) for b in teile))
    ergebnis = [{**b, "text": t} for b, t in zip(teile, texte) if t]
    sekunden = sum(b["ende"] - b["start"] + 2 * RAND_SEKUNDEN for b in teile)
    return spur, ergebnis, sekunden
