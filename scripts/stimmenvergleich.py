#!/usr/bin/env python3
"""Erzeugt kurze, inhaltlich identische TTS-Hörproben für Nestor.

Zugangsdaten werden ausschließlich aus der Umgebung gelesen. Die Ausgabe liegt
unter logs/stimmenvergleich/ und ist absichtlich kein Produktbestandteil.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import urllib.error
import urllib.request


TEXT = (
    "Ich höre zwei unterschiedliche Prioritäten. Lasst uns kurz festhalten: "
    "Was muss heute entschieden werden, und was können wir später klären? "
    "Anna, möchtest du beginnen?"
)
ZIEL = pathlib.Path(__file__).resolve().parents[1] / "logs" / "stimmenvergleich"


def post(url: str, headers: dict[str, str], payload: dict, ziel: pathlib.Path) -> None:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            ziel.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"{exc.code} von {url}: {detail}") from exc


def azure() -> None:
    endpoint = os.environ["HOERSPIEL_AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ["HOERSPIEL_AZURE_OPENAI_DEPLOYMENT"]
    key = os.environ["HOERSPIEL_AZURE_OPENAI_KEY"]
    url = f"{endpoint}/openai/deployments/{deployment}/audio/speech?api-version=2024-10-01-preview"
    for voice in ("nova", "shimmer", "alloy"):
        post(url, {"api-key": key}, {
            "model": deployment, "voice": voice, "input": TEXT,
            "response_format": "mp3", "speed": 1.0,
        }, ZIEL / f"azure-{voice}.mp3")


def mistral_thorsten() -> None:
    key = os.environ["MISTRAL_API_KEY"]
    stimmen = {
        "01-thorsten-mistral.f32le": "01a1188b-54f4-71a8-86df-df69e318948c",
        "06-mistral-marie-happy.f32le": "49d024dd-981b-4462-bb17-74d381eb8fd7",
        "07-mistral-marie-excited.f32le": "2f62b1af-aea3-4079-9d10-7ca665ee7243",
        "08-mistral-marie-curious.f32le": "e0580ce5-e63c-4cbe-88c8-a983b80c5f1f",
        "09-mistral-jane-confident.f32le": "cbe96cf0-85ec-4a10-accb-0b35c93b6dfd",
        "10-mistral-jane-curious.f32le": "5de47977-6e47-4266-a938-3bc1d76b4676",
    }
    for datei, voice_id in stimmen.items():
        req = urllib.request.Request("https://api.mistral.ai/v1/audio/speech", data=json.dumps({
        "model": "voxtral-mini-tts-latest", "voice_id": voice_id,
        "input": TEXT, "response_format": "wav", "stream": False,
        }).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=90) as response:
            antwort = json.load(response)
        (ZIEL / datei.replace(".f32le", ".wav")).write_bytes(base64.b64decode(antwort["audio_data"]))


if __name__ == "__main__":
    ZIEL.mkdir(parents=True, exist_ok=True)
    (ZIEL / "text.txt").write_text(TEXT + "\n", encoding="utf-8")
    azure()
    mistral_thorsten()
    print(ZIEL)
