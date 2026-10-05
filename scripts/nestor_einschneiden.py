r"""Fragen an Nestor in eine Probe einschneiden – für Ende-zu-Ende-Tests mit echten Sitzungen.

    .venv\Scripts\python scripts\nestor_einschneiden.py koblenz_rat [weitere …]

Liest testbibliothek/proben/<name>/probe.json (Liste „nestor“: Zeitpunkt in der Quelle, Text) und
testbibliothek/audio/<name>.wav. Schreibt <name>_nestor.wav mit
- 20 s Stille am Anfang (Nestors Begrüßung und das Zeitfenster für ein „Nein“),
- je Frage: in die leiseste Stelle ±8 s um den Zeitpunkt eine synthetische Stimme (gpt-4o-mini-tts) und
  danach Stille für Nestors Antwort (Recherche 35 s, Bild 10 s, sonst 22 s).
Dazu <name>_nestor.json (Einrichtung) und <name>_nestor.einschuebe.json: wo jede Frage tatsächlich liegt und
wie sich Zeitpunkte der Quelle auf die neue Aufnahme abbilden (für die Auswertung gegen die Referenz).
Kosten: Sprachausgabe für ein paar Sätze, unter 1 Cent je Probe.
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.config import openai_schluessel  # noqa: E402
from openai import OpenAI  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
PROBEN = WURZEL / "testbibliothek" / "proben"
AUDIO = WURZEL / "testbibliothek" / "audio"
RATE = 24000
VORLAUF = 20.0
STIMMEN = ["nova", "verse", "coral", "onyx"]


def leiseste_stelle(a: np.ndarray, mitte: float, spanne: float = 8.0) -> float:
    """Sekunde mit der geringsten Lautstärke (300-ms-Fenster) im Bereich mitte ± spanne."""
    f = int(0.3 * RATE)
    von, bis = max(0, int((mitte - spanne) * RATE)), min(len(a) - f, int((mitte + spanne) * RATE))
    if bis <= von:
        return mitte
    x = a[von:bis + f].astype(np.float32)
    energie = np.convolve(x * x, np.ones(f, dtype=np.float32), mode="valid")[::RATE // 100]
    return (von + int(np.argmin(energie)) * (RATE // 100) + f // 2) / RATE


def einschneiden(client, name: str) -> None:
    probe = json.loads((PROBEN / name / "probe.json").read_text(encoding="utf-8"))
    with wave.open(str(AUDIO / f"{name}.wav")) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    von = probe["quelle"]["von"]
    teile, einschuebe, versatz, pos = [np.zeros(int(VORLAUF * RATE), dtype="<i2")], [], VORLAUF, 0
    for k, e in enumerate(probe["nestor"]):
        schnitt = leiseste_stelle(a, e["nach"] - von)
        i = int(schnitt * RATE)
        if i <= pos:
            i = pos  # zwei Fragen direkt hintereinander (z. B. „ja, mach eine Folie“)
        teile.append(a[pos:i])
        roh = client.audio.speech.create(model="gpt-4o-mini-tts", voice=STIMMEN[k % len(STIMMEN)], input=e["text"],
                                         response_format="pcm",
                                         instructions="Sprich natürlich auf Deutsch, wie jemand in einer Sitzung.").content
        frage = np.frombuffer(roh, dtype="<i2")
        pause = 35.0 if e.get("recherche") else 10.0 if e.get("bild") else 22.0
        start = i / RATE + versatz
        teile += [np.zeros(int(0.5 * RATE), dtype="<i2"), frage, np.zeros(int(pause * RATE), dtype="<i2")]
        einschuebe.append({"text": e["text"], "quelle_s": round(e["nach"], 1), "start": round(start + 0.5, 2),
                           "frage_ende": round(start + 0.5 + len(frage) / RATE, 2),
                           "art": "recherche" if e.get("recherche") else "bild" if e.get("bild") else "frage"})
        versatz += 0.5 + len(frage) / RATE + pause
        pos = i
    teile.append(a[pos:])
    neu = np.concatenate(teile)
    ziel = AUDIO / f"{name}_nestor.wav"
    with wave.open(str(ziel), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(neu.tobytes())
    (AUDIO / f"{name}_nestor.json").write_text(json.dumps(probe["meeting"], ensure_ascii=False, indent=1), encoding="utf-8")
    # Abbildung Quelle -> neue Aufnahme: t_neu = t_quelle - von + VORLAUF + alles, was davor eingeschoben wurde
    schnitte = [{"ab_quelle": round(e["quelle_s"], 1), "versatz": 0.0} for e in einschuebe]
    v = VORLAUF
    for s, e in zip(schnitte, einschuebe):
        v += 0.5 + (e["frage_ende"] - e["start"]) + (35.0 if e["art"] == "recherche" else 10.0 if e["art"] == "bild" else 22.0)
        s["versatz"] = round(v, 2)
    (AUDIO / f"{name}_nestor.einschuebe.json").write_text(json.dumps(
        {"probe": name, "quelle_von": von, "vorlauf": VORLAUF, "einschuebe": einschuebe, "schnitte": schnitte},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ziel.name}: {len(neu) / RATE / 60:.1f} min, {len(einschuebe)} Fragen an Nestor")


def main() -> None:
    client = OpenAI(api_key=openai_schluessel())
    for name in sys.argv[1:]:
        einschneiden(client, name)


if __name__ == "__main__":
    main()
