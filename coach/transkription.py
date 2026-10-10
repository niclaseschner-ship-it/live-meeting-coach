"""Audio-Hilfen und Transkription einzelner Aufnahmen (Agenda per Sprache).

Der frühere Blockweg (Version 1: Sprecherspur mit OpenAI-Diarisierung je Audio-Block, `/api/block`) ist mit
Ticket #60 entfernt – Live-Text und Sprechtaste laufen über die Ströme in `coach/hoeren.py`.
"""

from __future__ import annotations

import base64
import io
import math
import wave
from array import array

RATE = 16000


# --- Audio-Hilfen ----------------------------------------------------------

def proben_lesen(wav: bytes) -> array:
    with wave.open(io.BytesIO(wav)) as w:
        return array("h", w.readframes(w.getnframes()))


def rms(proben: array) -> float:
    return math.sqrt(sum(p * p for p in proben) / len(proben)) if proben else 0.0


def wav_info(wav: bytes) -> tuple[float, float]:
    """Dauer in Sekunden und RMS-Pegel eines 16-bit-Mono-WAV."""
    p = proben_lesen(wav)
    return len(p) / RATE, rms(p)


def als_data_url(wav: bytes) -> str:
    return "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")


def _feld(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


# --- API-Aufruf ------------------------------------------------------------

async def text(client, modell: str, wav: bytes, sprache: str, prompt: str) -> str:
    antwort = await client.audio.transcriptions.create(
        model=modell,
        file=("beitrag.wav", wav, "audio/wav"),
        language=sprache,
        prompt=prompt or None,
    )
    return (_feld(antwort, "text") or "").strip()
