r"""Testbibliothek: Audio der Proben herstellen (herunterladen, ausschneiden, 24 kHz mono).

    .venv\Scripts\python scripts\bibliothek_laden.py            # alle fehlenden Proben
    .venv\Scripts\python scripts\bibliothek_laden.py stadtrat   # nur diese

Je Probe liegt in testbibliothek/proben/<name>/probe.json, woher sie stammt (öffentliches Video und
Zeitfenster) oder woraus sie zusammengesetzt ist. Das Audio landet in testbibliothek/audio/ (nicht im
Git), daneben <name>.json mit Titel und Agenda für den Abspielmodus im Dashboard. Die vollständigen
Downloads werden nach dem Ausschneiden gelöscht.
"""

from __future__ import annotations

import json
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent
PROBEN = WURZEL / "testbibliothek" / "proben"
AUDIO = WURZEL / "testbibliothek" / "audio"
RATE = 24000


def proben() -> dict[str, dict]:
    return {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(PROBEN.glob("*/probe.json"))}


def schreiben(name: str, a: np.ndarray, probe: dict) -> None:
    with wave.open(str(AUDIO / f"{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(a.astype("<i2").tobytes())
    (AUDIO / f"{name}.json").write_text(json.dumps(probe["meeting"], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {name}: {len(a) / RATE:.0f} s")


def lesen(name: str) -> np.ndarray:
    with wave.open(str(AUDIO / f"{name}.wav")) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def herunterladen(name: str, probe: dict) -> None:
    import av
    import yt_dlp

    q = probe["quelle"]
    with tempfile.TemporaryDirectory() as tmp:
        opts = {"format": "bestaudio[ext=m4a]/bestaudio", "outtmpl": str(Path(tmp) / "roh.%(ext)s"),
                "noplaylist": True, "quiet": True, "no_warnings": True, "noprogress": True}
        if q.get("untertitel"):  # kostenloses Grob-Transkript bzw. Zwischenrufe – ganze Länge, Zeitmarken der Quelle
            (AUDIO / "untertitel").mkdir(exist_ok=True)
            with yt_dlp.YoutubeDL({"skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
                                   "subtitleslangs": ["de.*", "de"], "subtitlesformat": "vtt", "quiet": True,
                                   "no_warnings": True, "noprogress": True,
                                   "outtmpl": str(AUDIO / "untertitel" / "%(id)s.%(ext)s")}) as ydl:
                ydl.download([q["url"]])
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([q["url"]])
        roh = next(Path(tmp).glob("roh.*"))
        c = av.open(str(roh))
        st = c.streams.audio[0]
        rs = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        teile = []
        for frame in c.decode(st):
            if float(frame.pts * st.time_base) > q["bis"] + 1:
                break
            teile.extend(f.to_ndarray().reshape(-1) for f in rs.resample(frame))
        c.close()
    schreiben(name, np.concatenate(teile)[q["von"] * RATE:q["bis"] * RATE], probe)


def zusammensetzen(name: str, probe: dict, alle: dict) -> None:
    teile = []
    for t in probe["abgeleitet"]["teile"]:
        if not (AUDIO / f"{t['probe']}.wav").exists():
            herstellen(t["probe"], alle)
        teile.append(lesen(t["probe"])[int(t["von"] * RATE):int(t["bis"] * RATE)])
    schreiben(name, np.concatenate(teile), probe)


def herstellen(name: str, alle: dict) -> None:
    if (AUDIO / f"{name}.wav").exists():
        print(f"  {name}: vorhanden")
        return
    probe = alle[name]
    if "abgeleitet" in probe:
        zusammensetzen(name, probe, alle)
    else:
        herunterladen(name, probe)


def main() -> None:
    AUDIO.mkdir(parents=True, exist_ok=True)
    alle = proben()
    for name in sys.argv[1:] or alle:
        herstellen(name, alle)


if __name__ == "__main__":
    main()
