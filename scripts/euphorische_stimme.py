#!/usr/bin/env python3
"""Baut eine fröhliche OpenAI-Referenz und eine daraus abgeleitete Mistral-Teststimme."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs" / "stimmenvergleich"
VERGLEICH = ("Ich höre zwei unterschiedliche Prioritäten. Lasst uns kurz festhalten: "
             "Was muss heute entschieden werden, und was können wir später klären? "
             "Anna, möchtest du beginnen?")
REFERENZ = (
    "Hallo zusammen, schön, dass ihr da seid! Ich freue mich richtig auf unsere gemeinsame Runde. "
    "Heute bringen wir frische Ideen auf den Tisch, hören einander aufmerksam zu und machen aus offenen Fragen "
    "klare nächste Schritte. Das wird gut! Lasst uns mit Energie starten: Was wäre für euch heute ein richtig "
    "starkes Ergebnis?"
)
REGIE = (
    "Sprich auf Deutsch wie eine sympathische, moderne Live-Coachin: fröhlich, warm, euphorisch und mitreißend. "
    "Klinge menschlich und spontan, lächle hörbar, setze lebendige Betonungen und kleine natürliche Pausen. "
    "Nicht werblich, nicht schrill und nicht überdreht. Mittleres, zügiges Sprechtempo."
)


def request(url: str, headers: dict[str, str], body: dict) -> bytes:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    openai_key = os.environ["OPENAI_API_KEY"]
    mistral_key = os.environ["MISTRAL_API_KEY"]
    auth_oa = {"Authorization": f"Bearer {openai_key}"}
    auth_mi = {"Authorization": f"Bearer {mistral_key}"}

    ref = request("https://api.openai.com/v1/audio/speech", auth_oa, {
        "model": "gpt-4o-mini-tts", "voice": "nova", "input": REFERENZ,
        "instructions": REGIE, "response_format": "wav", "speed": 1.0,
    })
    (OUT / "11-openai-nova-euphorisch-referenz.wav").write_bytes(ref)
    direkt = request("https://api.openai.com/v1/audio/speech", auth_oa, {
        "model": "gpt-4o-mini-tts", "voice": "nova", "input": VERGLEICH,
        "instructions": REGIE, "response_format": "wav", "speed": 1.0,
    })
    (OUT / "12-openai-nova-euphorisch.wav").write_bytes(direkt)

    created = json.loads(request("https://api.mistral.ai/v1/audio/voices", auth_mi, {
        "name": "nestor-nova-euphorisch-test", "description": "Synthetische OpenAI-Nova-Testreferenz; AI-generiert",
        "sample_audio": base64.b64encode(ref).decode(), "sample_filename": "nova-euphorisch.wav",
        "languages": ["de"], "gender": "female", "tags": ["synthetic", "cheerful", "coach"],
    }))
    voice_id = created["id"]
    (OUT / "mistral-nova-euphorisch-voice-id.txt").write_text(voice_id + "\n")
    pcm = request("https://api.mistral.ai/v1/audio/speech", auth_mi, {
        "model": "voxtral-mini-tts-latest", "voice_id": voice_id, "input": VERGLEICH,
        "response_format": "pcm", "stream": True,
    })
    (OUT / "13-mistral-aus-nova-euphorisch.f32le").write_bytes(pcm)
    print(voice_id)


if __name__ == "__main__":
    main()
