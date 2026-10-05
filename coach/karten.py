"""Nestor-Karten: was Nestor sagt, erscheint zusätzlich als kurze Karte (Pop-up) im Dashboard und bleibt im
Verlauf abrufbar. Antworten werden in wenigen Sekunden zu Titel und Stichpunkten verdichtet; dauert das zu
lange oder ist nichts zu zeigen (Bestätigung, Rückfrage), gibt es keine Karte bzw. die Sätze selbst.
"""

from __future__ import annotations

import asyncio
import json
import re

from .config import EINST

AUFTRAG = """\
Du bist {name} und hast der Besprechungsrunde gerade gesprochen geantwortet. Mach daraus eine Karte für den
Bildschirm. Antworte nur mit JSON:
{{"zeigen": true, "titel": "Thema in höchstens 6 Wörtern", "punkte": ["2 bis 4 Stichpunkte, je höchstens 10 Wörter"]}}
"zeigen": false, wenn die Antwort nur eine Bestätigung, Rückfrage, Begrüßung oder Smalltalk ist.
Nur Inhalte aus der Antwort, nichts ergänzen. Deutsch.

Frage der Runde: {frage}
Antwort: {antwort}
"""
FRIST = 6.0  # Sekunden – länger soll die Karte nicht hinter der Stimme herhinken
MIN_WOERTER = 12


def saetze(text: str, n: int = 4) -> list[str]:
    teile = [t.strip() for t in re.split(r"(?<=[.!?])\s+", text) if t.strip()]
    return teile[:n]


async def verdichten(client, frage: str, antwort: str) -> tuple[dict | None, dict]:
    """Liefert (karte oder None, nutzung). Ohne Modell oder nach Fristablauf: die ersten Sätze."""
    if len(antwort.split()) < MIN_WOERTER:
        return None, {}
    ersatz = {"titel": frage or "Nestor", "punkte": saetze(antwort)}
    if client is None:
        return ersatz, {}
    try:
        r = await asyncio.wait_for(client.chat.completions.create(
            model=EINST.assistent_modell,
            messages=[{"role": "user", "content": AUFTRAG.format(name=EINST.assistent_name, frage=frage or "-",
                                                                antwort=antwort)}],
            response_format={"type": "json_object"},
            **({"reasoning_effort": EINST.assistent_aufwand} if EINST.assistent_aufwand else {})),
            FRIST if EINST.ki != "codex" else 40)  # über das Abo dauert ein Aufruf ~5–10 s
    except (asyncio.TimeoutError, Exception):  # noqa: BLE001 – lieber die Sätze zeigen als nichts
        return ersatz, {}
    nutzung = {"tokens_rein": getattr(r.usage, "prompt_tokens", None),
               "tokens_raus": getattr(r.usage, "completion_tokens", None)}
    try:
        roh = json.loads(r.choices[0].message.content or "{}")
    except ValueError:
        return ersatz, nutzung
    if roh.get("zeigen") is False:
        return None, nutzung
    punkte = [str(p)[:140] for p in (roh.get("punkte") or [])][:4]
    return ({"titel": str(roh.get("titel") or ersatz["titel"])[:80], "punkte": punkte or ersatz["punkte"]}, nutzung)
