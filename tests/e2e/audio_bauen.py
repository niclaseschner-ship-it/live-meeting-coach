"""Test-Audio für die Klick-E2E bauen (Ticket #61) – kostenlos, lokal, reproduzierbar.

Sprache aus Piper (lokales TTS, Stimme `de_DE-thorsten-medium`, Thorsten-Voice CC0) aus den Sätzen in
`tests/e2e/drehbuch.json`:

  tests/e2e/audio/meeting_e2e.wav   Handy-Mikro: Stillepolster, die Meeting-Sätze mit Pausen, langes Stillepolster
                                    (Chromium spielt die Datei in Schleife – das Polster verhindert eine Wiederholung
                                    im Testfenster)
  tests/e2e/audio/agenda_e2e.wav    Desktop-Mikro: der Agenda-Satz (Agenda per Sprache, Sprechtaste)
  tests/e2e/audio/*.json            Lage der Sätze in der Datei (Sekunden)

Beide 24 kHz, mono, PCM16. tests/e2e/audio/ ist per .gitignore (*.wav) ausgenommen – dieses Skript erzeugt alles neu.
Die Stimme wird beim ersten Lauf nach ~/.cache/lmc-e2e/piper geladen (Hugging Face, ~60 MB), danach offline.

  .venv/bin/python tests/e2e/audio_bauen.py [--neu]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HIER = Path(__file__).resolve().parent
AUSGABE = HIER / "audio"
STIMMEN = Path.home() / ".cache" / "lmc-e2e" / "piper"
RATE = 24_000


def stimme_laden(name: str):
    from piper import PiperVoice

    modell = STIMMEN / f"{name}.onnx"
    if not modell.exists():
        STIMMEN.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "piper.download_voices", name], cwd=STIMMEN, check=True)
    return PiperVoice.load(str(modell))


def sprechen(stimme, text: str) -> np.ndarray:
    """Ein Satz als float32 in 24 kHz."""
    stuecke = [np.frombuffer(c.audio_int16_bytes, dtype="<i2") for c in stimme.synthesize(text)]
    roh = np.concatenate(stuecke).astype(np.float32) / 32768
    quelle = stimme.config.sample_rate
    if quelle != RATE:
        n = int(len(roh) * RATE / quelle)
        roh = np.interp(np.linspace(0, len(roh) - 1, n), np.arange(len(roh)), roh).astype(np.float32)
    spitze = float(np.max(np.abs(roh))) or 1.0
    return roh * (0.7 / spitze)


def stille(s: float) -> np.ndarray:
    return np.zeros(int(s * RATE), dtype=np.float32)


def schreiben(pfad: Path, audio: np.ndarray, lage: list[dict]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(pfad), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    pfad.with_suffix(".json").write_text(json.dumps({"rate": RATE, "dauer_s": round(len(audio) / RATE, 2),
                                                     "saetze": lage}, ensure_ascii=False, indent=2), encoding="utf-8")


def bauen(neu: bool = False) -> dict[str, Path]:
    d = json.loads((HIER / "drehbuch.json").read_text(encoding="utf-8"))["audio"]
    ziele = {"meeting": AUSGABE / "meeting_e2e.wav", "agenda": AUSGABE / "agenda_e2e.wav"}
    stempel = AUSGABE / "stand.json"
    soll = json.dumps(d, sort_keys=True, ensure_ascii=False)
    if not neu and all(p.exists() for p in ziele.values()) and stempel.exists() and stempel.read_text("utf-8") == soll:
        return ziele
    stimme = stimme_laden(d["stimme"])

    teile, lage, pos = [stille(d["meeting_vorlauf_s"])], [], d["meeting_vorlauf_s"]
    for satz in d["meeting_saetze"]:
        a = sprechen(stimme, satz)
        lage.append({"text": satz, "start": round(pos, 2), "ende": round(pos + len(a) / RATE, 2)})
        teile += [a, stille(d["meeting_pause_s"])]
        pos += len(a) / RATE + d["meeting_pause_s"]
    teile.append(stille(d["meeting_nachlauf_s"]))
    schreiben(ziele["meeting"], np.concatenate(teile), lage)

    a = sprechen(stimme, d["agenda_satz"])
    lage = [{"text": d["agenda_satz"], "start": d["agenda_vorlauf_s"],
             "ende": round(d["agenda_vorlauf_s"] + len(a) / RATE, 2)}]
    schreiben(ziele["agenda"], np.concatenate([stille(d["agenda_vorlauf_s"]), a, stille(d["agenda_nachlauf_s"])]), lage)
    stempel.write_text(soll, encoding="utf-8")
    return ziele


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--neu", action="store_true", help="auch neu bauen, wenn die Dateien zum Drehbuch passen")
    for name, pfad in bauen(p.parse_args().neu).items():
        info = json.loads(pfad.with_suffix(".json").read_text(encoding="utf-8"))
        print(f"{name}: {pfad} ({info['dauer_s']} s, {len(info['saetze'])} Sätze)")


if __name__ == "__main__":
    main()
