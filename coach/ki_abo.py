"""Text-KI über das ChatGPT-Abo (Codex-Kommandozeile) statt über die API – für Tests ohne API-Kosten.

    LMC_KI=codex  (Standard: openai)

Der Coach bekommt einen Client, der sich wie der OpenAI-Client verhält: `chat.completions.create` geht an
`codex exec` (über ssh auf dem Pi, wo Codex mit dem ChatGPT-Konto angemeldet ist), alles andere –
Transkription, Sprachausgabe, Recherche, Live-Bild – weiter an die API, weil das Abo das nicht abdeckt.
Gemessen 05.10.2026: ~5 s je Aufruf (Standardmodell, Denkaufwand niedrig) statt 1–3 s über die API.
Nur für eigene Tests gedacht, nicht als Schnittstelle für andere.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
from types import SimpleNamespace

from .config import EINST

log = logging.getLogger("coach.ki_abo")
FRIST = 120
_GLEICHZEITIG = asyncio.Semaphore(4)  # nicht mehr als vier Codex-Läufe gleichzeitig auf dem Pi

NULL_NUTZUNG = SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def prompt_aus(messages: list[dict], json_gewuenscht: bool) -> str:
    teile = []
    for m in messages:
        inhalt = m.get("content")
        if isinstance(inhalt, list):  # Inhaltsteile -> nur Text
            inhalt = "\n".join(t.get("text", "") for t in inhalt if isinstance(t, dict))
        rolle = {"system": "ANWEISUNG", "user": "EINGABE", "assistant": "BISHERIGE ANTWORT"}.get(m.get("role"), "EINGABE")
        teile.append(f"### {rolle}\n{inhalt}")
    if json_gewuenscht:
        teile.append("### FORMAT\nAntworte ausschließlich mit gültigem JSON, ohne Erklärung und ohne Codeblock.")
    teile.append("Führe keine Befehle aus und lies keine Dateien – beantworte nur die Eingabe.")
    return "\n\n".join(teile)


def bereinigen(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return m.group(1) if m else text


async def codex(prompt: str, frist: float = FRIST) -> str:
    befehl = shlex.split(EINST.codex_befehl, posix=True) + [
        "exec", "-c", f"model_reasoning_effort={EINST.codex_aufwand}", "--skip-git-repo-check",
        "--sandbox", "read-only", "--ephemeral", "-"]
    async with _GLEICHZEITIG:
        p = await asyncio.create_subprocess_exec(*befehl, stdin=asyncio.subprocess.PIPE,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            raus, fehler = await asyncio.wait_for(p.communicate(prompt.encode("utf-8")), frist)
        except asyncio.TimeoutError:
            p.kill()
            raise
    if p.returncode != 0:
        # Nur der Code, nicht stderr – das kann Kontodetails enthalten
        raise RuntimeError(f"codex exec beendet mit {p.returncode}")
    return bereinigen(raus.decode("utf-8", "replace"))


class _Completions:
    async def create(self, *, messages, response_format=None, stream=False, **_):
        json_gewuenscht = bool(response_format and response_format.get("type") == "json_object")
        text = await codex(prompt_aus(messages, json_gewuenscht))
        if json_gewuenscht:
            try:
                json.loads(text)
            except ValueError:
                m = re.search(r"\{.*\}", text, re.DOTALL)
                text = m.group(0) if m else "{}"
        if stream:
            return _strom(text)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=NULL_NUTZUNG)


async def _strom(text: str):
    """Wie ein OpenAI-Stream: erst der ganze Text als ein Stück, dann die Nutzung (null – Abo)."""
    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=None)
    yield SimpleNamespace(choices=[], usage=NULL_NUTZUNG)


class AboClient:
    """Wie AsyncOpenAI; nur Chat geht über Codex, der Rest an den echten Client."""

    def __init__(self, api_client) -> None:
        self._api = api_client
        self.chat = SimpleNamespace(completions=_Completions())

    def __getattr__(self, name):
        return getattr(self._api, name)
