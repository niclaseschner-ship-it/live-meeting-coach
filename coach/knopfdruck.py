"""Die Knöpfe (Lastenheft 4.2, Ticket #6, seit #13 in beiden Stufen gleich): die fünf Kernaktionen plus Bild,
Regelprüfung und freie Frage – unabhängig davon, ob sie über die Knopfleiste, einen Zuruf oder die Sprechtaste
ausgelöst werden (coach/assistent.py, coach/bogen.py). Ein Knopf führt die gewählte Analyse aus – aus vorhandenen
Bausteinen:

   stand     Wo stehen wir? Kontext wie bei Nestors Antworten (Assistent.kontext), Antwort als Karte
   regeln    die Regel-Ampeln zusammengefasst, ohne eigenen KI-Aufruf
   protokoll Meeting-Artefakte erkennen (coach/artefakte.py, Ticket #26), daraus protokoll.md und eine Karte
   bild      das vorhandene Live-Bild (onepager_starten)
   frage     freie Frage, Antwort als Text-Karte über den vorhandenen Karten-Weg
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

from .analyse import mmss

ARTEN = ("stand", "regeln", "ueberblick", "protokoll", "bild", "frage", "zusammenfassen", "fehlt")
NAMEN = {"regeln": "Regeln eingehalten?", "protokoll": "Protokoll"}


class Knopfstand:
    """Zustand der Knopf-Analysen eines Meetings (am Coach: `coach.knopf`)."""

    def __init__(self) -> None:
        self.sperre = asyncio.Lock()  # ein Knopf zur Zeit
        self.protokoll: str | None = None  # Markdown vom Protokoll-Knopf (geht als protokoll.md in die Ablage)
        self.protokoll_zeit: float | None = None

    def schnappschuss(self) -> dict:
        return {"protokoll": self.protokoll is not None}


# --- Analysen -----------------------------------------------------------------
KARTE_FORMAT = ('Antworte ausschließlich mit JSON: {"titel": "höchstens 6 Wörter", '
                '"punkte": ["2 bis 5 Stichpunkte, je höchstens 16 Wörter"]')
GRUNDSATZ = ("Neutral: keine Bewertung von Personen, keine Partei, nichts erfinden – was nicht im Kontext steht, "
             "weißt du nicht, dann sag das. Personen heißen im Transkript „Person N“; nenne sie nicht so, sprich von "
             "„jemandem“ oder der Gruppe. „Entschieden“ nur, wenn ausdrücklich beschlossen. Deutsch, per „ihr“.")

STAND = (f"Du bist {{name}}, der Moderationsassistent eines Präsenzmeetings. Die Runde hat gefragt „Wo stehen "
         f"wir?“. {KARTE_FORMAT}, \"naechster_punkt\": Nummer oder null, \"sagen\": \"ein bis zwei kurze gesprochene "
         f"Sätze, zusammen höchstens 30 Wörter\"}}.\n"
         "Stichpunkte: wo die Runde in der Agenda steht und wie es mit der Zeit aussieht, was festgehalten ist, was "
         "offen ist; der letzte Stichpunkt ist ein Vorschlag für den nächsten Schritt und beginnt mit „Vorschlag:“.\n"
         "Agenda-Titel und Ziele ausschließlich aus den gespeicherten Agendadaten wörtlich übernehmen. "
         "Keine erfundenen Erläuterungen eines Punktes als bestehende Agenda ausgeben. Zusätzliche Ideen immer "
         "ausdrücklich als Vorschlag markieren.\n"
         "naechster_punkt: Nummer des Agendapunkts, zu dem die Runde jetzt wechseln sollte – nur wenn der aktuelle "
         "erledigt ist oder das Gespräch schon beim nächsten ist, sonst null.\n"
         "sagen: was auffällt oder was die Runde jetzt tun sollte – NICHT vorlesen, was auf der Karte steht; beginnt "
         f"mit „Hier ist sie.“\n{GRUNDSATZ}")


async def _karte_vom_modell(coach, system: str, nutzer: str, knopf: str, nutzung_art: str = "assistent") -> dict:
    """Ein Aufruf mit JSON-Antwort; Kosten unter der vorhandenen Art im Nutzungsprotokoll (ohne Inhalte)."""
    from .pipeline import nutzung_loggen

    t0 = time.monotonic()
    r = await coach._client.chat.completions.create(
        model=coach.wahl.assistent_modell, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": nutzer}],
        **({"reasoning_effort": coach.wahl.assistent_aufwand} if coach.wahl.assistent_aufwand else {}))
    try:
        roh = json.loads(r.choices[0].message.content or "{}")
    except ValueError:
        roh = {}
    u = getattr(r, "usage", None)
    nutzung_loggen({"art": nutzung_art, "modell": coach.wahl.assistent_modell, "knopf": knopf,
                    "tokens_rein": getattr(u, "prompt_tokens", None), "tokens_raus": getattr(u, "completion_tokens", None),
                    "sekunden": round(time.monotonic() - t0, 1)})
    return roh if isinstance(roh, dict) else {}


def _punkte(roh: dict, n: int = 5) -> list[str]:
    return [str(p)[:200] for p in (roh.get("punkte") or []) if str(p).strip()][:n]


async def _regeln(coach, frage: str, ablegen: bool = True) -> dict:
    """Fokus, Ton und Ergebnisse prüft Nestor laufend – die Karte fasst die Ampeln zusammen, ohne eigenen
    KI-Aufruf."""
    m = coach.meeting
    punkte = [f"{r['titel']}: " + ("eingehalten" if r["farbe"] in ("gruen", "grau") else "Achtung")
              + (f" – {r['detail']}" if r["detail"] else "") for r in coach.schnappschuss()["regel_status"]]
    karte = {"art": "regeln", "frage": NAMEN["regeln"], "titel": f"Regeln · Stand {mmss(m.jetzt())}",
             "punkte": punkte or ["Für dieses Meeting sind keine Gesprächsregeln gewählt."]}
    if ablegen:
        coach._karte_ablegen(karte)
    return karte


def _protokoll_md(coach, am_ende: bool = False) -> str:
    """Protokoll aus den Meeting-Artefakten (Ticket #26): je Agendapunkt Entscheidungen, Optionen, Kriterien, Aufgaben,
    offene Punkte und Risiken, danach was außerhalb der Agenda festgehalten wurde. Lücken stehen als „fehlt“ dabei."""
    from .artefakte import FELD_NAME, STATUS_NAME

    m, art = coach.meeting, coach.artefakte
    wie = "am Meetingende" if am_ende else "auf Knopfdruck"
    z = [f"# Protokoll: {m.titel or 'Meeting'}", "",
         f"{datetime.now():%d.%m.%Y} · Laufzeit {mmss(m.jetzt())} min · erstellt von Nestor {wie}"]
    if m.ziel:
        z.append(f"Ziel: {m.ziel}")

    def zeile(a) -> str:
        teile = [a.was]
        if a.typ in ("option", "kriterium"):
            return "- " + a.was
        if a.typ == "entscheidung":
            teile.append(STATUS_NAME.get(a.status or "", "nur Vorschlag"))
        if a.typ != "entscheidung" or a.wer:
            teile.append(f"wer: {a.wer or 'offen'}")
        if a.typ in ("aufgabe", "offen") or a.bis:
            teile.append(f"bis: {a.bis or 'offen'}")
        if a.typ == "risiko":
            teile.append(f"Reaktion: {a.reaktion or 'offen'}")
        luecken = a.luecken()
        return "- " + " · ".join(teile) + (f" – **fehlt: {', '.join(FELD_NAME[x] for x in luecken)}**" if luecken else "")

    def block(liste) -> list[str]:
        if not liste:
            return ["_Nichts festgehalten._"]
        aus = []
        for typ, titel in (("entscheidung", "Entscheidungen"), ("option", "Optionen"), ("kriterium", "Kriterien"),
                           ("aufgabe", "Aufgaben"), ("offen", "Offene Punkte"), ("risiko", "Risiken")):
            teil = [a for a in liste if a.typ == typ]
            if teil:
                aus += (["", f"**{titel}**"] if aus else [f"**{titel}**"]) + [zeile(a) for a in teil]
        return aus

    if m.agenda:
        for i, p in enumerate(m.agenda):
            z += ["", f"## {i + 1}. {p.titel}",
                  f"_{m.status(i)} · {mmss(m.genutzt(i))} von {p.minuten:.0f} min_" + (f" · Ziel: {p.ziel}" if p.ziel else ""),
                  ""] + block([a for a in art.liste if a.punkt == i and not a.ausserhalb])
        rest = [a for a in art.liste if a.punkt is None or a.ausserhalb]
        if rest:
            z += ["", "## Außerhalb der Agenda (Parkplatz)", ""] + block(rest)
    else:
        z += ["", "## Ergebnisse", ""] + block(art.liste)
    return "\n".join(z) + "\n"


async def _protokoll(coach, frage: str, am_ende: bool = False) -> dict | None:
    """Protokoll-Knopf; `am_ende`: dasselbe automatisch am Meetingende in Basis (Paket mit protokoll.md, Ticket #15),
    dann ohne Karte. Erkennt die Artefakte aus allem, was noch nicht ausgewertet ist (Ticket #26)."""
    m, k, art = coach.meeting, coach.knopf, coach.artefakte
    await art.erkennen()
    k.protokoll = _protokoll_md(coach, am_ende)
    k.protokoll_zeit = m.jetzt()
    if am_ende:
        return None
    if m.agenda:
        belegt = {a.punkt for a in art.liste if not a.ausserhalb}
        punkte = [f"{i + 1}. {p.titel}: " + (art.beschluss(i) or ("kein Beschluss" if i in belegt else "nichts festgehalten"))
                  for i, p in enumerate(m.agenda)]
    else:
        punkte = [a.kurz().split(". ", 1)[-1] for a in art.liste[-6:]] or ["Noch nichts festgehalten."]
    luecken = sum(1 for a in art.liste if a.luecken() and not a.abgelehnt)
    if luecken:
        punkte.append(f"{luecken} Lücke{'n' if luecken > 1 else ''} – im Dashboard rot markiert")
    karte = {"art": "protokoll", "frage": NAMEN["protokoll"], "titel": "Protokoll", "punkte": punkte[:8]}
    coach._karte_ablegen(karte)
    return karte


# Ticket #27: jeder Knopf läuft als Antwortbogen (coach/assistent.py) – welcher Bogen?
BOGEN = {"stand": "stand", "regeln": "regeln", "ueberblick": "ueberblick", "protokoll": "festgehalten", "bild": "bild",
         "zusammenfassen": "zusammenfassen", "fehlt": "fehlt", "folie": "folie"}
