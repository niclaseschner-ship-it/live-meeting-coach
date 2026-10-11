"""Recherche auf Zuruf („Nestor, gib uns einen Überblick zu …“): Websuche – Premium über die OpenAI-Responses-API,
Basis über die Mistral-Conversations-API. Welcher Weg, entscheidet die Anbieterwahl (coach/anbieter.py).

In die Suche geht nur das Thema (vom Sprachmodell formuliert) und der Meetingtitel als Einordnung –
kein Transkript, keine Namen. Ergebnis: eine vorlesbare Zusammenfassung plus Quellen fürs Dashboard.
Kosten je Recherche ~1–2 Cent (Suchaufruf + Tokens), Dauer typisch 5–15 s.
"""

from __future__ import annotations

import re
import time


AUFTRAG = """\
Recherchiere im Web und gib einer Besprechungsrunde einen kurzen Überblick zum Thema unten.
- Erster Satz: der Kernsatz – die wichtigste Aussage in einem Satz, ohne Aufzählungszeichen.
- Danach 3 bis 5 Stichpunkte (Zeile beginnt mit „- “), jeder mit einem **fett markierten** Stichwort am Anfang,
  dahinter das Konkrete: Namen, Unterschiede, Nutzen, Einschränkungen.
- Deutsch, höchstens 150 Wörter insgesamt. Jede überprüfbare Empfehlung braucht eine klickbare Quelle.
- Aktueller Stand mit Jahreszahl, wo es darauf ankommt; Zahlen nur, wenn sie aus den Quellen stammen.
- Ist die Lage unklar oder umstritten, sag das im Kernsatz.
- Wenn keine belastbaren Webquellen gefunden wurden, sage ausdrücklich, dass die Recherche nicht belegt ist.
Thema: {frage}
Einordnung (Meeting): {titel}
"""


_LINK = r"\[[^\]]*\]\([^)]*\)"


def ohne_zitate(text: str) -> str:
    """Eingebettete Quellen „([bmas.de](https://…))“ entfernen und Markdown-Links auf ihren Text kürzen, Zeilen
    bleiben erhalten. Die Websuche schreibt jede Quelle zusätzlich in den Fließtext; die Quellen stehen schon
    getrennt in `quellen`, also gehört in den Text nur der Inhalt."""
    text = re.sub(rf"[ \t]*\(\s*{_LINK}(?:\s*[,;]\s*{_LINK})*\s*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    return "\n".join(re.sub(r"[ \t]+", " ", z).rstrip() for z in text.split("\n")).strip()


def vorlesbar(text: str) -> str:
    """Wie ohne_zitate, dazu alles in eine Zeile – zum Vorlesen."""
    return re.sub(r"\s+", " ", ohne_zitate(text)).strip()


MISTRAL_ZUSATZ = "\nNutze dafür die Websuche, auch wenn du die Antwort zu kennen glaubst.\n"


async def recherchieren(client, frage: str, titel: str = "", *, wahl) -> dict:
    t0 = time.monotonic()
    if wahl.anbieter == "mistral":
        # Nestor Basis: Mistral Conversations-API mit web_search (coach/mistral.py) – gleiche Rückgabe wie unten
        erg = await client.websuche(wahl.recherche_modell,
                                    AUFTRAG.format(frage=frage, titel=titel or "-") + MISTRAL_ZUSATZ)
        text = ohne_zitate(erg["text"])
        if not erg["quellen"]:
            text = "Keine überprüfbaren Webquellen gefunden – die folgende Antwort ist nicht als Recherche belegt.\n\n" + text
        return {"text": text, "quellen": erg["quellen"], "sekunden": round(time.monotonic() - t0, 1),
                "tokens_rein": erg["tokens_rein"], "tokens_raus": erg["tokens_raus"], "suchen": erg["suchen"]}
    antwort = await client.responses.create(
        model=wahl.recherche_modell,
        tools=[{"type": "web_search"}],
        input=AUFTRAG.format(frage=frage, titel=titel or "-"),
        **({"reasoning": {"effort": wahl.recherche_aufwand}} if wahl.recherche_aufwand else {}),
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
    text = ohne_zitate(antwort.output_text or "")
    if not quellen:
        text = "Keine überprüfbaren Webquellen gefunden – die folgende Antwort ist nicht als Recherche belegt.\n\n" + text
    return {"text": text, "quellen": quellen[:5],
            "sekunden": round(time.monotonic() - t0, 1),
            "tokens_rein": getattr(nutzung, "input_tokens", None), "tokens_raus": getattr(nutzung, "output_tokens", None)}
