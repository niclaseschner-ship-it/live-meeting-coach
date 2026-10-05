r"""Synthetische Probe „ton_tts“: Sätze aus dem Ton-Testset, gesprochen von OpenAI-Stimmen (TTS).

    .venv\Scripts\python scripts\tts_probe.py

Zweck: Ende-zu-Ende-Test für Regel 7 – kommt ein Kraftausdruck durch die Live-Texterkennung wörtlich an,
und meldet der Coach ihn? Kosten: ~1 min Sprachausgabe (gpt-4o-mini-tts), wenige Cent. Ergebnis landet in
testbibliothek/audio/ton_tts.wav (+ .json mit Regelauswahl) und die Wahrheit in proben/ton_tts/probe.json.
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
RATE = 24000
STIMMEN = ["onyx", "nova", "echo", "shimmer"]
SAETZE = [  # (Text, Klasse) – Kontrollsätze ohne Hinweis dazwischen
    ("Gut, dann schauen wir uns jetzt die Zahlen für das dritte Quartal an.", "neutral"),
    ("Das ist doch alles Scheiße mit diesem Termin.", "kraftausdruck"),
    ("Diesen Vorschlag halte ich für völlig unrealistisch.", "sachkritik"),
    ("Sie haben doch überhaupt keine Ahnung, wovon Sie reden.", "angriff"),
    ("Verdammt noch mal, warum klappt das schon wieder nicht?", "kraftausdruck"),
    ("Kannst du die Folie bitte noch mal einen Schritt zurück machen?", "neutral"),
    ("Du Vollpfosten hast die ganze Präsentation gelöscht!", "angriff"),
    ("Was für ein Bullshit-Prozess ist das denn?", "kraftausdruck"),
    ("Der Kunde hat am Telefon wörtlich gesagt, unser Angebot sei Scheiße.", "zitat"),
    ("Halt doch einfach mal die Klappe!", "angriff"),
    ("Das ist doch komplett im Arsch, das ganze System.", "kraftausdruck"),
    ("Mit diesem Zeitplan fahren wir das Projekt gegen die Wand.", "sachkritik"),
    ("Mit so einem Idioten kann man nicht zusammenarbeiten.", "angriff"),
    ("Danke, das hilft mir sehr weiter.", "neutral"),
]


def main() -> None:
    client = OpenAI()
    teile, wahrheit, t = [], [], 0.0
    pause = np.zeros(int(1.5 * RATE), dtype="<i2")
    for i, (text, klasse) in enumerate(SAETZE):
        stimme = STIMMEN[i % len(STIMMEN)]
        roh = client.audio.speech.create(model="gpt-4o-mini-tts", voice=stimme, input=text,
                                         response_format="pcm",
                                         instructions="Sprich natürlich auf Deutsch, wie in einer Besprechung.").content
        a = np.frombuffer(roh, dtype="<i2")
        wahrheit.append({"von": round(t, 2), "bis": round(t + len(a) / RATE, 2), "person": stimme,
                         "klasse": klasse, "text": text})
        teile += [a, pause]
        t += (len(a) + len(pause)) / RATE
    audio = WURZEL / "testbibliothek" / "audio"
    with wave.open(str(audio / "ton_tts.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(np.concatenate(teile).tobytes())
    meeting = {"titel": "Teambesprechung (synthetisch)", "ziel": "Projektstand",
               "agenda": [{"titel": "Projektstand", "ziel": "", "minuten": 5}],
               "regeln": [], "regel_ids": ["ton", "thema"], "teilnehmende": []}
    (audio / "ton_tts.json").write_text(json.dumps(meeting, ensure_ascii=False, indent=1), encoding="utf-8")
    probe = {"name": "ton_tts", "titel": "Synthetische Sätze für Regel 7 (Sprachausgabe, 4 Stimmen)",
             "synthetisch": "scripts/tts_probe.py", "setting": "TTS, 1,5 s Pause zwischen den Sätzen",
             "meeting": meeting, "referenz": {"saetze": wahrheit,
                                               "sprecher": [{"von": w["von"], "bis": w["bis"], "person": w["person"]}
                                                            for w in wahrheit]},
             "eignung": ["ton", "transkription_kraftausdruecke"]}
    ziel = WURZEL / "testbibliothek" / "proben" / "ton_tts"
    ziel.mkdir(exist_ok=True)
    (ziel / "probe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ton_tts.wav: {t:.0f} s, {len(SAETZE)} Sätze")


if __name__ == "__main__":
    main()
