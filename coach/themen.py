"""Themen-Zuordnung per LLM: zu welchem Agendapunkt gehört der neue Abschnitt?"""

from __future__ import annotations

import json

from .zustand import Meeting

ARTEN = ("aktiv", "vorgriff", "zurueck", "neu", "unklar")

SYSTEM = (
    "Du beobachtest als neutraler Prozessbegleiter eine Besprechung. "
    "Du bekommst Ziel und Agenda, den aktiven Agendapunkt und einen neuen Abschnitt aus dem Transkript. "
    "Ordne den Abschnitt inhaltlich zu. Bewerte nicht, ob Aussagen richtig sind.\n"
    "Antworte ausschließlich mit einem JSON-Objekt mit den Schlüsseln:\n"
    '"punkt": Nummer des Agendapunkts, um den es inhaltlich geht, oder null;\n'
    '"art": einer von "aktiv", "vorgriff", "zurueck", "neu", "unklar";\n'
    '"konfidenz": Zahl von 0 bis 1;\n'
    '"begruendung": ein kurzer Satz auf Deutsch.\n'
    "Bedeutung von art: aktiv = gehört zum aktiven Punkt; vorgriff = gehört zu einem späteren Punkt; "
    "zurueck = gehört zu einem früheren Punkt; neu = inhaltliches Gespräch ohne Bezug zur Agenda "
    "(auch wenn es mitten in einem Punkt auftaucht oder wie ein Einschub wirkt); "
    "unklar = NUR wenn der Abschnitt keinen Inhalt hat (Begrüßung, Füllsätze, Organisatorisches, zu kurz). "
    "Ein inhaltlich fremdes Thema ist nie unklar, sondern neu. Mischt der Abschnitt Agenda und Fremdes, "
    "entscheide nach dem größeren Anteil.\n"
    "Wichtig: Im Gespräch genannte Nummern („Tagesordnungspunkt 7“, „TOP 3“) können von der Nummerierung "
    "dieser Agenda abweichen. Ordne immer nach dem Inhalt zu, nie nach einer genannten Nummer."
)


# Regel 7 „Respektvoller Ton“: läuft im selben Aufruf mit – keine Zusatzkosten außer wenigen Ausgabe-Tokens
TON = (
    "\nZusätzlich Schlüssel \"ton\": Liste der Stellen im NEUEN Abschnitt mit Kraftausdruck oder persönlichem "
    "Angriff, je {\"zitat\": wörtlicher Ausschnitt mit höchstens 12 Wörtern, \"art\": \"kraftausdruck\" oder \"angriff\"}. "
    "kraftausdruck = derbes oder vulgäres Wort (z. B. Scheiße, verdammt, Arsch, Bullshit, Schwachsinn), auch wenn "
    "es sich nicht gegen eine Person richtet. angriff = herabsetzende Aussage über eine anwesende Person oder Gruppe "
    "(Beleidigung, Unterstellung, Beschämen, „Sie haben keine Ahnung“). NICHT melden: harte Kritik an der Sache "
    "(„das ist falsch“, „Quatsch“, „unrealistisch“), Titel, Fachbegriffe – und wiedergegebene Äußerungen "
    "anderer: Wer berichtet, was jemand gesagt, geschrieben oder getitelt hat („der Kunde sagte, das sei Mist“, "
    "„in der Mail stand …“, „die Schlagzeile lautete …“, „wir werden als … bezeichnet“), verwendet das Wort nicht "
    "selbst – auch dann nicht melden, wenn das Zitat derb oder beleidigend ist. Leere Liste, wenn nichts davon vorkommt."
    " Ein einzelnes mehrdeutiges Wort oder wahrscheinlich falsch transkribierter Fachbegriff ist kein Tonverstoß. "
    "Bei unsicherem Kontext keinen Alarm; persönliche Angriffe nur mit eindeutiger herabsetzender Aussage."
)
TON_ARTEN = ("kraftausdruck", "angriff")


def nachricht(meeting: Meeting, abschnitt: str, kontext: list[str] | None = None) -> str:
    """`kontext`: was davor gesprochen wurde (ohne Überschneidung mit dem Abschnitt); ohne Angabe die letzten zwei
    gesammelten Abschnitte."""
    zeilen = [f"Ziel des Meetings: {meeting.ziel or '(nicht angegeben)'}", "", "Agenda:"]
    for i, p in enumerate(meeting.agenda, start=1):
        zeilen.append(f"{i}. {p.titel}" + (f" – {p.ziel}" if p.ziel else ""))
    zeilen += ["", f"Aktiver Punkt: {meeting.aktiver_punkt + 1}"]
    kontext = meeting.block_texte[-2:] if kontext is None else kontext
    if kontext:
        zeilen += ["", "Vorheriger Verlauf (nur Kontext):", *kontext]
    zeilen += ["", "Neuer Abschnitt:", abschnitt]
    return "\n".join(zeilen)


def normalisieren(roh: dict, anzahl_punkte: int) -> dict:
    punkt = roh.get("punkt")
    try:
        punkt = int(punkt) - 1 if punkt is not None else None
    except (TypeError, ValueError):
        punkt = None
    if punkt is not None and not 0 <= punkt < anzahl_punkte:
        punkt = None
    art = roh.get("art") if roh.get("art") in ARTEN else "unklar"
    try:
        konfidenz = min(1.0, max(0.0, float(roh.get("konfidenz", 0))))
    except (TypeError, ValueError):
        konfidenz = 0.0
    ton = [{"zitat": str(t.get("zitat", ""))[:160], "art": t["art"]}
           for t in (roh.get("ton") or []) if isinstance(t, dict) and t.get("art") in TON_ARTEN]
    return {"punkt": punkt, "art": art, "konfidenz": konfidenz, "begruendung": str(roh.get("begruendung", ""))[:300],
            "ton": ton}


async def zuordnen(client, modell: str, meeting: Meeting, abschnitt: str, aufwand: str = "",
                   ton: bool = False, kontext: list[str] | None = None) -> tuple[dict, dict]:
    extra = {"reasoning_effort": aufwand} if aufwand else {}
    antwort = await client.chat.completions.create(
        model=modell,
        messages=[{"role": "system", "content": SYSTEM + (TON if ton else "")},
                  {"role": "user", "content": nachricht(meeting, abschnitt, kontext)}],
        response_format={"type": "json_object"},
        **extra,
    )
    inhalt = antwort.choices[0].message.content or "{}"
    try:
        roh = json.loads(inhalt)
    except json.JSONDecodeError:
        roh = {}
    nutzung = {}
    if antwort.usage:
        nutzung = {"tokens_rein": antwort.usage.prompt_tokens, "tokens_raus": antwort.usage.completion_tokens}
    return normalisieren(roh, len(meeting.agenda)), nutzung
