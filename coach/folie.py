"""Recherche als Folie: Nestor bietet nach einer Recherche an, das Ergebnis mit Quellen auf einer Folie
zusammenzustellen. Die Folie ist eine Dashboard-Ansicht (scharf, Quellen anklickbar), kein generiertes Bild.

Grundlage ist nur das Rechercheergebnis (Text und Quellen) – keine neue Websuche, nichts aus dem Transkript.
Ein Aufruf mit gpt-5.4-mini, ~2–4 s, unter 1 Cent.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlparse

from .config import EINST

AUFTRAG = """\
Mach aus diesem Rechercheergebnis eine Folie für eine Besprechungsrunde. Antworte nur mit JSON:
{{"titel": "kurzer Titel, max. 6 Wörter",
  "kernaussage": "ein Satz, das Wichtigste",
  "punkte": ["3 bis 5 Stichpunkte, je höchstens 12 Wörter, mit Zahlen und Jahreszahlen aus dem Text"],
  "offen": "ein Satz, was unklar oder umstritten ist – leer lassen, wenn nichts"}}
Nur Inhalte aus dem Text unten, nichts ergänzen. Deutsch.

Frage: {frage}
Rechercheergebnis: {text}
"""


def quelle_kurz(q: dict) -> dict:
    host = urlparse(q.get("url", "")).netloc.removeprefix("www.")
    return {"titel": q.get("titel") or host, "url": q.get("url", ""), "seite": host}


async def erstellen(client, recherche: dict) -> tuple[dict, dict]:
    """Liefert (folie, nutzung). recherche: {frage, text, quellen, zeit}."""
    t0 = time.monotonic()
    antwort = await client.chat.completions.create(
        model=EINST.assistent_modell,
        messages=[{"role": "user", "content": AUFTRAG.format(frage=recherche["frage"], text=recherche["text"])}],
        response_format={"type": "json_object"},
        **({"reasoning_effort": EINST.assistent_aufwand} if EINST.assistent_aufwand else {}),
    )
    roh = json.loads(antwort.choices[0].message.content or "{}")
    folie = {
        "frage": recherche["frage"],
        "titel": str(roh.get("titel") or recherche["frage"])[:80],
        "kernaussage": str(roh.get("kernaussage") or "")[:240],
        "punkte": [str(p)[:160] for p in (roh.get("punkte") or [])][:5],
        "offen": str(roh.get("offen") or "")[:240],
        "quellen": [quelle_kurz(q) for q in recherche.get("quellen", [])][:5],
        "zeit": recherche.get("zeit"),
        "datum": time.strftime("%d.%m.%Y"),
    }
    nutzung = {"tokens_rein": getattr(antwort.usage, "prompt_tokens", None),
               "tokens_raus": getattr(antwort.usage, "completion_tokens", None),
               "sekunden": round(time.monotonic() - t0, 1)}
    return folie, nutzung
