"""Läuft auf dem Pi: Drehbuch eines synthetischen Meetings über Teachbuddys Azure-Vertonung sprechen lassen.

Aufruf (vom Laptop über scripts/synthetisch_meeting.py vertonen --azure):
    cd ~/repos/teachbuddy && source bin-zugang.sh && TEACHBUDDY_SPRECHTEMPO=1.0 \
        .venv/bin/python <dieses Skript> <drehbuch.json> <ausgabeordner>

Die Azure-Zugangsdaten bleiben auf dem Pi (zugang.py von Teachbuddy liest sie); heraus gehen nur MP3-Dateien,
eine je Äußerung (0000.mp3, 0001.mp3, …). Bereits vorhandene Dateien werden nicht noch einmal erzeugt.
"""

import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/repos/teachbuddy"))
from podcast import vertonung  # noqa: E402

STIMMEN = ["onyx", "nova", "echo", "shimmer", "fable"]  # Azure-Bereitstellung kennt nur nova, shimmer, echo, onyx, fable, alloy


def main() -> None:
    drehbuch, ziel = sys.argv[1], sys.argv[2]
    os.makedirs(ziel, exist_ok=True)
    d = json.load(open(drehbuch, encoding="utf-8"))
    tts = vertonung.aus_umgebung()
    for i, a in enumerate(d["aeusserungen"]):
        datei = os.path.join(ziel, f"{i:04d}.mp3")
        if os.path.exists(datei):
            continue
        mp3 = tts.synthese(text=a["text"], voice=STIMMEN[a["person"] % len(STIMMEN)])
        with open(datei, "wb") as f:
            f.write(mp3)
    print(f"{len(d['aeusserungen'])} Äußerungen, {tts.zeichen} Zeichen an Azure")


if __name__ == "__main__":
    main()
