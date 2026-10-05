"""Recherche auf Zuruf („Nestor, gib uns einen Überblick zu …“): Websuche über die OpenAI-Responses-API.

In die Suche geht nur das Thema (vom Sprachmodell formuliert) und der Meetingtitel als Einordnung –
kein Transkript, keine Namen. Ergebnis: eine vorlesbare Zusammenfassung plus Quellen fürs Dashboard.
Kosten je Recherche ~1–2 Cent (Suchaufruf + Tokens), Dauer typisch 5–15 s.
"""

from __future__ import annotations

import re
import time

from .config import EINST

AUFTRAG = """\
Recherchiere im Web und gib einer Besprechungsrunde einen kurzen Überblick zum Thema unten.
- 4 bis 6 kurze Sätze, gut vorlesbar, Deutsch, ohne Aufzählungszeichen, ohne URLs und ohne Klammern.
- Aktueller Stand mit Jahreszahl, wo es darauf ankommt; Zahlen nur, wenn sie aus den Quellen stammen.
- Wenn die Lage unklar oder umstritten ist, sag das.
Thema: {frage}
Einordnung (Meeting): {titel}
"""


def vorlesbar(text: str) -> str:
    """Eingebettete Quellen „([bmas.de](https://…))“ und Markdown-Links entfernen – die Quellen zeigt das Dashboard."""
    text = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


async def recherchieren(client, frage: str, titel: str = "") -> dict:
    t0 = time.monotonic()
    antwort = await client.responses.create(
        model=EINST.recherche_modell,
        tools=[{"type": "web_search"}],
        input=AUFTRAG.format(frage=frage, titel=titel or "-"),
        **({"reasoning": {"effort": EINST.recherche_aufwand}} if EINST.recherche_aufwand else {}),
    )
    quellen, gesehen = [], set()
    for teil in antwort.output or []:
        if getattr(teil, "type", "") != "message":
            continue
        for inhalt in teil.content or []:
            for a in getattr(inhalt, "annotations", None) or []:
                url = getattr(a, "url", None)
                if getattr(a, "type", "") == "url_citation" and url and url not in gesehen:
                    gesehen.add(url)
                    quellen.append({"titel": (getattr(a, "title", "") or url)[:120], "url": url})
    nutzung = getattr(antwort, "usage", None)
    return {"text": vorlesbar(antwort.output_text or ""), "quellen": quellen[:5],
            "sekunden": round(time.monotonic() - t0, 1),
            "tokens_rein": getattr(nutzung, "input_tokens", None), "tokens_raus": getattr(nutzung, "output_tokens", None)}
