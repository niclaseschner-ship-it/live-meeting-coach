"""Regel 10 „Ergebnisse festhalten“: beim Abschluss eines Agendapunkts Ergebnis und Aufgaben herausziehen.

Ein kurzer Aufruf je abgeschlossenem Punkt (nicht laufend). Der Coach meldet, wenn ein Punkt ohne
erkennbares Ergebnis endet oder eine Aufgabe keine Verantwortlichen bzw. keinen Termin hat.
"""

from __future__ import annotations

import json

SYSTEM = (
    "Du bist neutraler Protokollhelfer einer Besprechung. Du bekommst den Agendapunkt und das Transkript des "
    "gerade abgeschlossenen Punkts. Halte nur fest, was ausdrücklich gesagt wurde – nichts ergänzen, nicht bewerten.\n"
    "Antworte ausschließlich mit einem JSON-Objekt:\n"
    '"ergebnis": ein Satz mit dem Ergebnis des Punkts (Beschluss, Einigung, Kenntnisnahme, Vertagung) oder null, '
    "wenn kein Ergebnis ausgesprochen wurde;\n"
    '"entscheidungen": Liste von {"was": kurz, "ergebnis": z. B. „einstimmig“, „mehrheitlich, 1 Enthaltung“, „vertagt“};\n'
    '"aufgaben": Liste von {"was": kurz, "wer": Name oder Rolle oder null, "bis": Termin oder null} – nur '
    "ausdrücklich vereinbarte Aufgaben."
)


def nachricht(titel: str, ziel: str, transkript: str) -> str:
    return f"Agendapunkt: {titel}" + (f" – {ziel}" if ziel else "") + f"\n\nTranskript:\n{transkript[-12000:]}"


def normalisieren(roh: dict) -> dict:
    def liste(k: str, felder: tuple[str, ...]) -> list[dict]:
        return [{f: (str(e[f])[:200] if e.get(f) not in (None, "") else None) for f in felder}
                for e in (roh.get(k) or []) if isinstance(e, dict) and e.get("was")]

    erg = roh.get("ergebnis")
    return {"ergebnis": str(erg)[:300] if erg else None,
            "entscheidungen": liste("entscheidungen", ("was", "ergebnis")),
            "aufgaben": liste("aufgaben", ("was", "wer", "bis"))}


async def pruefen(client, modell: str, titel: str, ziel: str, transkript: str, aufwand: str = "") -> tuple[dict, dict]:
    extra = {"reasoning_effort": aufwand} if aufwand else {}
    antwort = await client.chat.completions.create(
        model=modell,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": nachricht(titel, ziel, transkript)}],
        response_format={"type": "json_object"},
        **extra,
    )
    try:
        roh = json.loads(antwort.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        roh = {}
    nutzung = {}
    if antwort.usage:
        nutzung = {"tokens_rein": antwort.usage.prompt_tokens, "tokens_raus": antwort.usage.completion_tokens}
    return normalisieren(roh), nutzung


def hinweise(titel: str, erg: dict) -> list[str]:
    """Texte für die Gruppe – beobachtend, ohne Wertung."""
    aus = []
    if not erg["ergebnis"] and not erg["entscheidungen"]:
        aus.append(f"„{titel}“ ist abgeschlossen, ein Ergebnis wurde nicht ausgesprochen. Kurz festhalten?")
    for a in erg["aufgaben"]:
        fehlt = [w for w, k in (("Verantwortliche/n", "wer"), ("Termin", "bis")) if not a[k]]
        if fehlt:
            aus.append(f"„{titel}“: Aufgabe „{a['was']}“ ohne {' und '.join(fehlt)}.")
    return aus
