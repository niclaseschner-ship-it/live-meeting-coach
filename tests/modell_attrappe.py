"""Attrappe eines Chat-Modells für den Text-Weg (coach/kern.py): gestreamt, mit Werkzeugaufrufen, ohne Netz.

Jeder Aufruf von `chat.completions.create` bekommt den nächsten Zug: einen Text (wird in Stücken gestreamt) oder
`Zug(werkzeuge=[(name, argumente)], text=…)`. Sind die Züge aufgebraucht, kommt eine leere Antwort. Die Argumente
aller Aufrufe stehen in `client.aufrufe` (z. B. um zu prüfen, dass die zweite Runde ohne Werkzeuge lief).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from types import SimpleNamespace


@dataclass
class Zug:
    werkzeuge: list = field(default_factory=list)  # [(name, argumente)]
    text: str = ""


def _stueck(content=None, tool_calls=None):
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=content,
                                                                                      tool_calls=tool_calls))])


class Strom:
    def __init__(self, zug: Zug | str | list):
        if isinstance(zug, (str, list)):
            zug = Zug(text="".join(zug) if isinstance(zug, list) else zug)
        self.zug = zug

    def __aiter__(self):
        async def gen():
            await asyncio.sleep(0)
            for i, (name, argumente) in enumerate(self.zug.werkzeuge):
                yield _stueck(tool_calls=[SimpleNamespace(index=i, id=f"aufruf{i:03d}", function=SimpleNamespace(
                    name=name, arguments=json.dumps(argumente, ensure_ascii=False)))])
            for satz in re.split(r"(?<=[.!?])\s+", self.zug.text) if self.zug.text else []:
                await asyncio.sleep(0)
                yield _stueck(content=satz + " ")  # satzweise, wie ein echtes Modell in Stücken
        return gen()


class Ton:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *x):
        return False

    async def iter_bytes(self, n):
        yield bytes(24000 * 2)  # 1 s Stille


def chat_attrappe(*zuege):
    """Ein Client mit Chat (Züge der Reihe nach) und Sprachausgabe (je Satz 1 s Stille)."""
    offen = list(zuege)
    aufrufe: list[dict] = []

    async def create(**kw):
        aufrufe.append(kw)
        if not kw.get("stream"):  # Nebenaufrufe (Antwortkarte, Moderationssatz): kein Inhalt
            raise RuntimeError("Attrappe: nur gestreamte Aufrufe")
        return Strom(offen.pop(0) if offen else "")

    return SimpleNamespace(
        aufrufe=aufrufe,
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=lambda **kw: Ton()))),
    )
