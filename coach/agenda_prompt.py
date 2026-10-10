"""Agenda per Prompt (Lastenheft 4.1): aus freier Eingabe, Einfügungen oder Sprache wird eine Tabelle.

Ein Aufruf reicht für beides: eine neue Agenda aus Fließtext oder einer eingefügten Tabelle, oder eine
Änderung an einer bestehenden (`bisher`). Benutzt denselben Client-Weg wie `coach/themen.py`
(`coach._client`, Modell aus der Anbieterwahl des Meetings, coach/anbieter.py).
"""

from __future__ import annotations

import json

MAX_PUNKTE = 15
MAX_MINUTEN = 240
MAX_TEILNEHMENDE = 20
FEHLERANTWORT = "Nestor konnte die Antwort nicht lesen – bitte noch einmal versuchen."

SYSTEM = (
    "Du hilfst, aus einer freien Eingabe eine Meeting-Agenda zu machen. Die Eingabe kann Fließtext, eine "
    "eingefügte Tabelle (z. B. tab-getrennt aus Outlook oder Excel, oder als HTML) oder eine abgetippte "
    "Spracheingabe sein – auch eine ganze Einladungsmail mit Betreff, Anrede, Uhrzeit, Teilnehmerliste, "
    "Agenda (als Liste oder Tabelle) und Signatur. Gibt es bereits eine Tabelle (\"bisher\"), ist die neue "
    "Eingabe meist ein Änderungswunsch dazu – ändere nur, was verlangt wird, der Rest bleibt wie er war.\n"
    "Du bist ein Planungsassistent, kein reiner Feld-Extraktor. Eine freie Beschreibung eines Vorhabens "
    "reicht: entwickle daraus selbst einen konkreten, sinnvoll geordneten Agenda-ENTWURF mit 3–8 passenden "
    "Punkten und einem Ziel pro Punkt. Nicht nur das Gesamtziel befüllen! Beispiel: Hausbau mit einer WG "
    "von Keller bis Dach besprechen und klären, wer was macht → gemeinsame Anforderungen, Keller/Fundament, "
    "Wohngeschosse, Dach, Budget/Zeitplan und Aufgabenverteilung. Das ist ein Vorschlag, keine bereits "
    "getroffene Entscheidung. Erfinde keine Namen, Zusagen oder baulichen Fakten. Fehlende Dauer oder "
    "Teilnehmernamen blockieren den Entwurf nicht; Zeiten schätzen und als Schätzung benennen.\n"
    "Nur wenn Thema oder beabsichtigtes Ergebnis wirklich unklar sind oder eine Änderung mehrdeutig ist, "
    "stelle in antwort 1–3 konkrete Rückfragen. Setze dann status auf rueckfrage und lasse ALLE bisherigen "
    "Felder unverändert; ohne bisherigen Stand bleiben sie leer. Der bisherige Dialog enthält die "
    "Rückfrage und die Antwort darauf: nutze diesen Kontext, damit eine kurze Folgeantwort genügt.\n"
    "Aus einer Einladungsmail: der Betreff wird zum Titel, der einleitende Satz mit Zweck oder Anlass zum "
    "Ziel, eine genannte Teilnehmerliste zu \"teilnehmende\". Eine Uhrzeit \"von–bis\" ergibt die "
    "Gesamtdauer des Meetings; haben die Agendapunkte dann keine eigene Minutenangabe, verteile die "
    "Gesamtdauer gleichmäßig auf sie. Uhrzeiten an einzelnen Punkten (\"10:00–10:20\") werden zu Minuten; "
    "Dauerangaben (\"20 min\", \"0,5 h\") auch. Fehlt jede Dauerangabe (auch keine Uhrzeit von–bis), schätze "
    "die Minuten je Punkt passend zum Thema und erwähne das kurz in \"antwort\".\n"
    "\"titel\", \"ziel\" und \"teilnehmende\" nur ändern, wenn die Eingabe sie eindeutig liefert (eine neue "
    "Einladung, eine erste Eingabe ohne \"bisher\") oder wenn sie ausdrücklich genau dieses Feld ändern will "
    "(z. B. \"Ziel ist eigentlich …\", \"Teilnehmer ergänzen: …\"); sonst unverändert den bisherigen Wert "
    "übernehmen.\n"
    "Antworte ausschließlich mit einem JSON-Objekt mit den Schlüsseln:\n"
    '"status": "entwurf" bei einem brauchbaren Entwurf bzw. erledigten Änderungswunsch, sonst "rueckfrage";\n'
    '"titel": kurzer Meeting-Titel, oder der bisherige, wenn sich keiner aus der Eingabe ergibt;\n'
    '"ziel": kurzer Satz zum Zweck/Anlass des Meetings, oder der bisherige, wenn sich keiner ergibt;\n'
    '"punkte": Liste von {"titel": str, "minuten": ganze Zahl 1–240, "ziel": str oder leer}, höchstens 15 '
    "Einträge;\n"
    '"teilnehmende": Liste von Namen ohne Anrede und ohne Mailadresse, oder die bisherigen, wenn sich keine '
    "aus der Eingabe ergeben;\n"
    '"antwort": ein kurzer Satz an den Nutzer (z. B. Anzahl Punkte und Gesamtdauer), oder eine Rückfrage, '
    "wenn sich aus der Eingabe keine brauchbare Agenda ergibt – dann bleiben \"punkte\" leer oder wie zuvor."
)


def nachricht(eingabe: str, bisher: dict | None) -> str:
    if bisher and any(bisher.get(k) for k in ("punkte", "titel", "ziel", "teilnehmende")):
        return (f"Bisherige Tabelle:\n{json.dumps(bisher, ensure_ascii=False)}\n\n"
                f"Änderungswunsch bzw. neue Eingabe:\n{eingabe}")
    return f"Eingabe:\n{eingabe}"


def _minuten(wert) -> int:
    try:
        m = int(round(float(wert)))
    except (TypeError, ValueError):
        m = 10
    return min(MAX_MINUTEN, max(1, m))


def _namen(werte, bisherige) -> list[str]:
    """Teilnehmenden-Liste: aus der Antwort, sonst die bisherige – wie beim Titel (einziger Wert, kein
    Feld pro Punkt, daher kein eigener Normalisierer nötig)."""
    if isinstance(werte, list) and any(str(w).strip() for w in werte):
        return [str(w).strip()[:100] for w in werte if str(w).strip()][:MAX_TEILNEHMENDE]
    return [str(w).strip()[:100] for w in (bisherige or []) if str(w).strip()][:MAX_TEILNEHMENDE]


def normalisieren(roh: dict, bisher: dict | None) -> dict:
    bisher = bisher if isinstance(bisher, dict) else {}
    rueckfrage = roh.get("status") == "rueckfrage" or not any(
        isinstance(p, dict) and str(p.get("titel", "")).strip()
        for p in (roh.get("punkte") or [])
    )
    if rueckfrage:
        roh = {**bisher, "antwort": roh.get("antwort"), "status": "rueckfrage"}
    punkte = [
        {"titel": str(p.get("titel", "")).strip()[:200], "minuten": _minuten(p.get("minuten")),
         "ziel": str(p.get("ziel") or "").strip()[:300]}
        for p in (roh.get("punkte") or [])
        if isinstance(p, dict) and str(p.get("titel", "")).strip()
    ][:MAX_PUNKTE]
    titel = str(roh.get("titel") or bisher.get("titel") or "").strip()[:200]
    ziel = str(roh.get("ziel") or bisher.get("ziel") or "").strip()[:300]
    teilnehmende = _namen(roh.get("teilnehmende"), bisher.get("teilnehmende"))
    antwort = str(roh.get("antwort") or "").strip()[:1000]
    if not punkte and not rueckfrage:
        rueckfrage = True
        if "?" not in antwort:
            antwort = "Worum soll es im Meeting gehen und was möchtet ihr am Ende geklärt haben?"
    if rueckfrage and "?" not in antwort:
        antwort = "Welche Themen oder Entscheidungen soll ich für die Agenda berücksichtigen?"
    return {"titel": titel, "ziel": ziel, "punkte": punkte, "teilnehmende": teilnehmende,
            "antwort": antwort, "status": "rueckfrage" if rueckfrage else "entwurf"}


def dialog_nachrichten(verlauf) -> list[dict]:
    """Nur kurze Textbeiträge aus diesem Vorbereitungsdialog, keine Modell-/Systemrollen."""
    if not isinstance(verlauf, list):
        return []
    return [{"role": n["role"], "content": n["content"][:2000]}
            for n in verlauf[-8:] if isinstance(n, dict)
            and n.get("role") in ("user", "assistant") and isinstance(n.get("content"), str)
            and n["content"].strip()]


async def agenda_vorschlagen(client, modell: str, eingabe: str, bisher: dict | None, verlauf=None) -> dict:
    """Bei kaputter Antwort ein Wiederholungsversuch; bleibt sie kaputt, eine Fehlermeldung in "antwort"
    und die bisherige Tabelle unverändert (nichts geht verloren)."""
    nachr = nachricht(eingabe, bisher)
    for _ in range(2):
        antwort = await client.chat.completions.create(
            model=modell,
            messages=[{"role": "system", "content": SYSTEM}, *dialog_nachrichten(verlauf),
                      {"role": "user", "content": nachr}],
            response_format={"type": "json_object"},
        )
        inhalt = antwort.choices[0].message.content or "{}"
        try:
            roh = json.loads(inhalt)
        except json.JSONDecodeError:
            roh = None
        if isinstance(roh, dict):
            return normalisieren(roh, bisher)
    bisher = bisher or {}
    return {"titel": str(bisher.get("titel", "")), "ziel": str(bisher.get("ziel", "")),
            "punkte": bisher.get("punkte", []), "teilnehmende": list(bisher.get("teilnehmende", [])),
            "antwort": FEHLERANTWORT, "status": "fehler"}
