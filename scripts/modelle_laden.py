"""Lädt die lokalen Modelle nach modelle/ (Pausenerkennung und Stimm-Fingerabdruck), ~29 MB.

Quelle: offizielle Releases von k2-fsa/sherpa-onnx auf GitHub.
    .venv\\Scripts\\python scripts\\modelle_laden.py
"""

import urllib.request
from pathlib import Path

ZIEL = Path(__file__).resolve().parent.parent / "modelle"
QUELLEN = {
    "silero_vad.onnx": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
    # Stimm-Fingerabdruck: CAM++ (3D-Speaker, zh/en) – im Benchmark 05.10.2026 klar vor WeSpeaker ResNet34
    "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx":
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
        "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
}

ZIEL.mkdir(exist_ok=True)
for name, url in QUELLEN.items():
    pfad = ZIEL / name
    if pfad.is_file():
        print(f"vorhanden: {name}")
        continue
    print(f"lade {name} …")
    urllib.request.urlretrieve(url, pfad)
print("fertig:", ZIEL)
