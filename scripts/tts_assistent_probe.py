r"""Synthetische Proben für den Sprachassistenten (Ende-zu-Ende über den Abspielmodus).

    .venv\Scripts\python scripts\tts_assistent_probe.py

Erzeugt testbibliothek/audio/assistent_dialog.wav (Begrüßung ohne Einwand, Gespräch, vier Fragen an Nestor)
und assistent_nein.wav (jemand sagt nach der Begrüßung „Nein“) und assistent_recherche.wav (Überblick per Websuche). Die Begrüßung des Coaches selbst ist nicht in
der Aufnahme – am Anfang steht deshalb Stille, in der sie im Raum zu hören wäre. Kosten: ~1,5 min
Sprachausgabe, wenige Cent.
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import coach.config  # noqa: E402,F401  – lädt .env
from openai import OpenAI  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
AUDIO = WURZEL / "testbibliothek" / "audio"
RATE = 24000
MEETING = {
    "titel": "Planung Sommerfest", "ziel": "Termin, Budget und Aufgaben für das Sommerfest festlegen",
    "agenda": [{"titel": "Termin und Ort", "ziel": "Datum festlegen", "minuten": 3},
               {"titel": "Budget", "ziel": "Obergrenze beschließen", "minuten": 3},
               {"titel": "Aufgaben verteilen", "ziel": "Wer macht was bis wann", "minuten": 3}],
    "regeln": [], "regel_ids": ["ausreden", "thema", "zeit"], "teilnehmende": [], "assistent": True,
}
# (Startzeit in s, Stimme, Text) – die Startzeiten lassen Raum für Begrüßung und Antworten
DIALOG = [
    (30, "onyx", "Gut, dann fangen wir mit dem Termin an. Ich schlage Samstag, den zwölften Juli vor."),
    (37, "nova", "Der zwölfte passt mir gut. Als Ort hätte ich den Innenhof vom Bürogebäude vorgeschlagen."),
    (45, "onyx", "Einverstanden. Dann halten wir fest: zwölfter Juli im Innenhof. Bei Regen weichen wir in die Kantine aus."),
    (54, "nova", "Nestor, wo stehen wir gerade?"),
    (72, "onyx", "Nestor, kannst du den aktuellen Agendapunkt kurz zusammenfassen?"),
    (92, "nova", "Danke. Nestor, wir kommen jetzt zum nächsten Punkt."),
    (108, "onyx", "Beim Budget würde ich mit höchstens zweitausend Euro planen, inklusive Essen."),
    (116, "nova", "Das klingt realistisch. Für Getränke brauchen wir aber noch ein Angebot."),
    (124, "onyx", "Nestor, kannst du uns zeigen, was noch ansteht?"),
]
NEIN = [(20, "nova", "Nein."), (30, "onyx", "Dann lass uns trotzdem mit dem Termin anfangen.")]
RECHERCHE = [(30, "nova", "Nestor, gib uns bitte einen kurzen Überblick zum aktuellen Stand beim gesetzlichen Mindestlohn."),
             (65, "onyx", "Danke, das reicht uns.")]
ENDE = {"assistent_dialog": 150, "assistent_nein": 40, "assistent_recherche": 90}


def bauen(client, name: str, plan: list) -> None:
    audio = np.zeros(int(ENDE[name] * RATE), dtype="<i2")
    wahrheit = []
    for t, stimme, text in plan:
        roh = client.audio.speech.create(model="gpt-4o-mini-tts", voice=stimme, input=text, response_format="pcm",
                                         instructions="Sprich natürlich auf Deutsch, wie in einer Besprechung.").content
        a = np.frombuffer(roh, dtype="<i2")
        i = int(t * RATE)
        audio[i:i + len(a)] = a[:len(audio) - i]
        wahrheit.append({"von": t, "bis": round(t + len(a) / RATE, 2), "text": text})
    with wave.open(str(AUDIO / f"{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(audio.tobytes())
    (AUDIO / f"{name}.json").write_text(json.dumps(MEETING, ensure_ascii=False, indent=1), encoding="utf-8")
    ziel = WURZEL / "testbibliothek" / "proben" / name
    ziel.mkdir(exist_ok=True)
    (ziel / "probe.json").write_text(json.dumps({
        "name": name, "titel": f"Sprachassistent: {name.split('_')[1]}",
        "synthetisch": "scripts/tts_assistent_probe.py", "setting": "TTS, Stille am Anfang für die Begrüßung",
        "meeting": MEETING, "referenz": {"aeusserungen": wahrheit}, "eignung": ["sprachassistent"]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}.wav: {ENDE[name]} s, {len(plan)} Äußerungen")


def main() -> None:
    client = OpenAI()
    bauen(client, "assistent_dialog", DIALOG)
    bauen(client, "assistent_nein", NEIN)
    bauen(client, "assistent_recherche", RECHERCHE)


if __name__ == "__main__":
    main()
