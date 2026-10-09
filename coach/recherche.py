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
- Liefere 3 bis 5 konkrete, brauchbare Ergebnisse mit Namen, Unterschieden, Nutzen und Einschränkungen.
- Deutsch, klar gegliedert, etwa 180 bis 300 Wörter. Jede überprüfbare Empfehlung braucht eine klickbare Quelle.
- Aktueller Stand mit Jahreszahl, wo es darauf ankommt; Zahlen nur, wenn sie aus den Quellen stammen.
- Wenn die Lage unklar oder umstritten ist, sag das.
- Wenn keine belastbaren Webquellen gefunden wurden, sage ausdrücklich, dass die Recherche nicht belegt ist.
Thema: {frage}
Einordnung (Meeting): {titel}
"""


def vorlesbar(text: str) -> str:
    """Eingebettete Quellen „([bmas.de](https://…))“ und Markdown-Links entfernen – die Quellen zeigt das Dashboard."""
    text = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


MISTRAL_ZUSATZ = "\nNutze dafür die Websuche, auch wenn du die Antwort zu kennen glaubst.\n"


async def recherchieren(client, frage: str, titel: str = "") -> dict:
    t0 = time.monotonic()
    if hasattr(client, "websuche"):
        # Nestor Basis: Mistral Conversations-API mit web_search (coach/mistral.py) – gleiche Rückgabe wie unten
        erg = await client.websuche(EINST.recherche_modell,
                                    AUFTRAG.format(frage=frage, titel=titel or "-") + MISTRAL_ZUSATZ)
        text = erg["text"]
        if not erg["quellen"]:
            text = "Keine überprüfbaren Webquellen gefunden – die folgende Antwort ist nicht als Recherche belegt.\n\n" + text
        return {"text": text, "quellen": erg["quellen"], "sekunden": round(time.monotonic() - t0, 1),
                "tokens_rein": erg["tokens_rein"], "tokens_raus": erg["tokens_raus"], "suchen": erg["suchen"]}
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
    text = antwort.output_text or ""
    if not quellen:
        text = "Keine überprüfbaren Webquellen gefunden – die folgende Antwort ist nicht als Recherche belegt.\n\n" + text
    return {"text": text, "quellen": quellen[:5],
            "sekunden": round(time.monotonic() - t0, 1),
            "tokens_rein": getattr(nutzung, "input_tokens", None), "tokens_raus": getattr(nutzung, "output_tokens", None)}
