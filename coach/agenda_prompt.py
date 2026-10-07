"""Agenda per Prompt (Lastenheft 4.1): aus freier Eingabe, Einfügungen oder Sprache wird eine Tabelle.

Ein Aufruf reicht für beides: eine neue Agenda aus Fließtext oder einer eingefügten Tabelle, oder eine
Änderung an einer bestehenden (`bisher`). Benutzt denselben Client-Weg wie `coach/themen.py`
(`coach._client`, Modell aus `EINST`), damit `LMC_KI=codex` greift.
"""

from __future__ import annotations

import json

MAX_PUNKTE = 15
MAX_MINUTEN = 240
FEHLERANTWORT = "Nestor konnte die Antwort nicht lesen – bitte noch einmal versuchen."

SYSTEM = (
    "Du hilfst, aus einer freien Eingabe eine Meeting-Agenda zu machen. Die Eingabe kann Fließtext, eine "
    "eingefügte Tabelle (z. B. tab-getrennt aus Outlook oder Excel, oder als HTML) oder eine abgetippte "
    "Spracheingabe sein. Gibt es bereits eine Tabelle (\"bisher\"), ist die neue Eingabe meist ein "
    "Änderungswunsch dazu – ändere nur, was verlangt wird, der Rest bleibt wie er war.\n"
    "Uhrzeiten (\"10:00–10:20\") werden zu Minuten; Dauerangaben (\"20 min\", \"0,5 h\") auch. Fehlt eine "
    "Dauer ganz, schätze sie passend zum Thema und erwähne das kurz in \"antwort\".\n"
    "Antworte ausschließlich mit einem JSON-Objekt mit den Schlüsseln:\n"
    '"titel": kurzer Meeting-Titel, oder der bisherige, wenn sich keiner aus der Eingabe ergibt;\n'
    '"punkte": Liste von {"titel": str, "minuten": ganze Zahl 1–240, "ziel": str oder leer}, höchstens 15 '
    "Einträge;\n"
    '"antwort": ein kurzer Satz an den Nutzer (z. B. Anzahl Punkte und Gesamtdauer), oder eine Rückfrage, '
    "wenn sich aus der Eingabe keine brauchbare Agenda ergibt – dann bleiben \"punkte\" leer oder wie zuvor."
)


def nachricht(eingabe: str, bisher: dict | None) -> str:
    if bisher and bisher.get("punkte"):
        return (f"Bisherige Tabelle:\n{json.dumps(bisher, ensure_ascii=False)}\n\n"
                f"Änderungswunsch bzw. neue Eingabe:\n{eingabe}")
    return f"Eingabe:\n{eingabe}"


def _minuten(wert) -> int:
    try:
        m = int(round(float(wert)))
    except (TypeError, ValueError):
        m = 10
    return min(MAX_MINUTEN, max(1, m))


def normalisieren(roh: dict, bisher: dict | None) -> dict:
    punkte = [
        {"titel": str(p.get("titel", "")).strip()[:200], "minuten": _minuten(p.get("minuten")),
         "ziel": str(p.get("ziel") or "").strip()[:300]}
        for p in (roh.get("punkte") or [])
        if isinstance(p, dict) and str(p.get("titel", "")).strip()
    ][:MAX_PUNKTE]
    titel = str(roh.get("titel") or (bisher or {}).get("titel") or "").strip()[:200]
    return {"titel": titel, "punkte": punkte, "antwort": str(roh.get("antwort") or "").strip()[:500]}


async def agenda_vorschlagen(client, modell: str, eingabe: str, bisher: dict | None) -> dict:
    """Bei kaputter Antwort ein Wiederholungsversuch; bleibt sie kaputt, eine Fehlermeldung in "antwort"
    und die bisherige Tabelle unverändert (nichts geht verloren)."""
    nachr = nachricht(eingabe, bisher)
    for _ in range(2):
        antwort = await client.chat.completions.create(
            model=modell,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": nachr}],
            response_format={"type": "json_object"},
        )
        inhalt = antwort.choices[0].message.content or "{}"
        try:
            roh = json.loads(inhalt)
        except json.JSONDecodeError:
            roh = None
        if isinstance(roh, dict):
            return normalisieren(roh, bisher)
    return {"titel": str((bisher or {}).get("titel", "")), "punkte": (bisher or {}).get("punkte", []),
            "antwort": FEHLERANTWORT}
