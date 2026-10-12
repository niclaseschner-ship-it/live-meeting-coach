"""Überblick als Text (Ticket #13, beide Stufen): der Stand des Meetings als strukturierte Dashboard-Ansicht – ohne
Bildmodell. In Nestor Basis ersetzt er das Live-Bild (auch auf Zuruf „zeig uns die Übersicht“ → Werkzeug bild_zeichnen),
in Premium ist er umschaltbar neben dem Live-Bild.

Aufbau wie die Zonen des Live-Bilds (coach/bild_gpt.py, Strukturanalyse Schritt 1):
    Kopf          Titel, Laufzeit, aktueller Punkt, Agenda mit Status          – aus dem Meeting-Zustand, ohne Modell
    ✅ Entschieden  beschlossene und vorläufige Entscheidungen                    – aus den Artefakten
    🟡 Offen        offene Punkte, Risiken, bloße Vorschläge                      – aus den Artefakten
    📌 Aufgaben     was, wer, bis wann                                            – aus den Artefakten
    ↪ Außerhalb    Gesprächsteile ohne Bezug zur Agenda                          – Modell
    Neu seit dem letzten Stand                                                   – aus den Artefakt-Nummern

Entschieden, Offen und Aufgaben sind eine Ansicht auf die festgehaltenen Ergebnisse (coach/artefakte.py) – dieselben
Einträge mit demselben Wortlaut wie in protokoll.md, meeting.json und tasks.json. Das Modell schreibt nur den
Kernsatz und „außerhalb der Agenda“ (bei einem Fokus wählt es dazu die passenden Ergebnis-Nummern aus). Damit nichts
„gemalt“ wird: eine Zahl, die im Material nicht vorkommt, wirft den Satz raus – die Bildprobe mit FLUX hatte aus
25.000 € 55.000 € gemacht.
"""

from __future__ import annotations

import json
import re
import time

from .analyse import mmss
from .artefakte import TYP_NAME, beschlossen, kollektiv, zahlen

MAX_TRANSKRIPT_ZEICHEN = 30000

AUFTRAG = """\
Du bereitest für eine Besprechungsrunde den Überblick über ihr laufendes Meeting vor. Die Ergebnisse (Entscheidungen,
Aufgaben, offene Punkte) sind schon festgehalten und stehen unten; sie erscheinen unverändert im Überblick. Du
lieferst nur den Kernsatz und die Gesprächsteile außerhalb der Agenda.

Antworte ausschließlich mit einem JSON-Objekt mit genau diesen Schlüsseln:
{{"kernaussage": "ein Satz, höchstens 15 Wörter: wo steht das Meeting gerade",
 "ausserhalb": [{{"zeit": "m:ss", "was": "Thema in höchstens 6 Wörtern"}}]{schluessel}}}

Regeln:
- Nur, was im Material steht. Zahlen, Beträge, Termine und Namen genau so wie dort – nichts runden, nichts ergänzen.
- Personen heißen im Transkript „Person N“; nenne sie nicht so. Keine Bewertung von Personen.
- „ausserhalb“: Gesprächsteile ohne Bezug zur Agenda (z. B. Fußball, Urlaub), mit Startzeit; sonst leere Liste.
- Leere Listen sind erlaubt. Deutsch.
{fokus}
MATERIAL:
{material}
"""

FOKUS = ("\nFOKUS (Wunsch der Runde): {fokus} – der Kernsatz handelt davon; unter „nummern“ stehen die Nummern der "
         "festgehaltenen Ergebnisse, die dazugehören.\n")
FOKUS_SCHLUESSEL = ',\n "nummern": [Nummern der festgehaltenen Ergebnisse, die zum Fokus gehören]'


def _ohne_label(text: str) -> str:
    """„Person N“ nicht auf den Bildschirm (Lastenheft: keine Personenlabels) – in Modelltexten „jemand“."""
    return re.sub(r"\bPerson \d+\b", "jemand", text)


def _liste(roh, felder: tuple[str, ...], n: int) -> list[dict]:
    aus = []
    for e in roh if isinstance(roh, list) else []:
        if isinstance(e, str):
            e = {felder[0]: e}
        if not isinstance(e, dict) or not str(e.get(felder[0]) or "").strip():
            continue
        aus.append({f: (_ohne_label(str(e[f]).strip()[:160]) if e.get(f) not in (None, "", "null") else None)
                    for f in felder})
    return aus[:n]


def meeting_text(meeting) -> str:
    """Meeting als Text für die Live-Bild- und Überblick-Aufträge (coach/bild_gpt.py, coach/ueberblick.py)."""
    zeilen = [f"Titel: {meeting.titel or '-'}", f"Ziel: {meeting.ziel or '-'}",
              f"Laufzeit bisher: {mmss(meeting.jetzt())} Minuten", "", "Agenda:"]
    for i, p in enumerate(meeting.agenda, start=1):
        zeilen.append(f"{i}. {p.titel}" + (f" – {p.ziel}" if p.ziel else "")
                      + f" [{meeting.status(i - 1)}]")
    transkript = "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in meeting.transkript if s.text)
    zeilen += ["", "Transkript:", transkript[-MAX_TRANSKRIPT_ZEICHEN:]]
    return "\n".join(zeilen)


def kopf(meeting) -> dict:
    m = meeting
    i = m.aktiver_punkt
    return {
        "titel": m.titel or "Meeting", "laufzeit": mmss(m.jetzt()), "stand": round(m.jetzt(), 1),
        "punkt": f"{i + 1}. {m.agenda[i].titel}" if 0 <= i < len(m.agenda) else None,
        "agenda": [{"nr": k + 1, "titel": p.titel, "status": m.status(k)} for k, p in enumerate(m.agenda)],
    }


def _aktuell(fokus: str | None) -> bool:
    return bool(fokus and re.search(r"aktuell|aktueller|aktuellen|dieser|laufend", fokus, re.I))


def auswahl(meeting, liste: list, fokus: str | None = None) -> list:
    """Die Ergebnisse, die der Überblick zeigt: alle, beim Fokus „aktueller Punkt“ die dieses Punkts."""
    i = meeting.aktiver_punkt
    if _aktuell(fokus) and 0 <= i < len(meeting.agenda):
        return [a for a in liste if a.punkt == i]
    return list(liste)


def material(meeting, liste: list, fokus: str | None = None) -> str:
    """Meeting-Text wie beim Live-Bild plus die festgehaltenen Ergebnisse mit Nummer."""
    i = meeting.aktiver_punkt
    if _aktuell(fokus) and 0 <= i < len(meeting.agenda):
        p = meeting.agenda[i]
        teile = [f"Titel: {meeting.titel}\nAgendapunkt {i + 1}: {p.titel}\nZiel: {p.ziel or '-'}",
                 "Transkript:", "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}"
                                           for s in meeting.punkt_transkript(i) if s.text)]
    else:
        teile = [meeting_text(meeting)]
    gewaehlt = auswahl(meeting, liste, fokus)
    if gewaehlt:
        teile += ["", "Festgehaltene Ergebnisse (Nummer. Art: was):"] + [a.kurz() for a in gewaehlt]
    return "\n".join(teile)


def _wer(a) -> str | None:
    """Zuständige wie in tasks.json; ein Personenlabel bleibt vom Bildschirm fern."""
    if not a.wer or kollektiv(a.wer) or re.match(r"^Person\b", a.wer):
        return None
    return a.wer


def ergebnisse(liste: list) -> dict[str, list[dict]]:
    """Entschieden / Offen / Aufgaben / Optionen als Ansicht auf die Artefakte: jedes Ergebnis genau einmal, Wortlaut
    unverändert. Entschieden = beschlossene und vorläufige Entscheidungen; Offen = offene Punkte, Risiken und bloße
    Vorschläge; Optionen = Optionen und Kriterien, die die Runde abwägt."""
    nr = lambda a: (a.punkt + 1) if a.punkt is not None else None  # noqa: E731
    aus: dict[str, list[dict]] = {"entschieden": [], "offen": [], "aufgaben": [], "optionen": []}
    for a in liste:
        if a.typ in ("option", "kriterium"):  # das Material der Entscheidung, noch nichts Offenes
            aus["optionen"].append({"id": a.id, "was": a.was, "punkt": nr(a), "typ": a.typ})
        elif a.typ == "aufgabe":
            aus["aufgaben"].append({"id": a.id, "was": a.was, "wer": _wer(a), "bis": a.bis, "punkt": nr(a)})
        elif beschlossen(a):
            aus["entschieden"].append({"id": a.id, "was": a.was, "punkt": nr(a), "status": a.status})
        else:
            aus["offen"].append({"id": a.id, "was": a.was, "punkt": nr(a), "typ": a.typ})
    return aus


def _neu(gewaehlt: list, vorher: dict | None, fokus: str | None) -> list[str]:
    """Was seit dem letzten Stand festgehalten wurde – aus den Nummern, ohne Modell."""
    if not vorher or vorher.get("fokus") != fokus or "ids" not in vorher:
        return ["erster Stand"]
    alt = set(vorher["ids"])
    return [f"{TYP_NAME[a.typ]}: {a.was}"[:140] for a in gewaehlt if a.id not in alt][:3]


async def erstellen(client, meeting, liste: list | tuple = (), vorher: dict | None = None, fokus: str | None = None,
                    *, wahl) -> tuple[dict, dict]:
    """Liefert (überblick, nutzung). `liste`: die Artefakte; `vorher`: der letzte Überblick (für „neu“)."""
    t0 = time.monotonic()
    stoff = material(meeting, liste, fokus)
    frei = bool(fokus) and not _aktuell(fokus)  # freier Fokus: das Modell wählt die passenden Ergebnisse
    auftrag = AUFTRAG.format(schluessel=FOKUS_SCHLUESSEL if frei else "",
                             fokus=FOKUS.format(fokus=fokus) if fokus else "", material=stoff)
    r = await client.chat.completions.create(
        model=wahl.analyse_modell, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": auftrag}],
        **({"reasoning_effort": wahl.analyse_aufwand} if wahl.analyse_aufwand else {}))
    try:
        roh = json.loads(r.choices[0].message.content or "{}")
    except ValueError:
        roh = {}
    roh = roh if isinstance(roh, dict) else {}
    quelle = zahlen(stoff)
    u = getattr(r, "usage", None)
    nutzung = {"tokens_rein": getattr(u, "prompt_tokens", None), "tokens_raus": getattr(u, "completion_tokens", None),
               "sekunden": round(time.monotonic() - t0, 1)}
    gewaehlt = auswahl(meeting, liste, fokus)
    if frei and isinstance(roh.get("nummern"), list):
        nummern = {n for n in roh["nummern"] if isinstance(n, int)}
        gewaehlt = [a for a in gewaehlt if a.id in nummern]
    kern = _ohne_label(str(roh.get("kernaussage") or "").strip()[:200])
    ueberblick = {
        **kopf(meeting),
        "kernaussage": kern if kern and zahlen(kern) <= quelle else None,
        **ergebnisse(gewaehlt),
        "ausserhalb": [e for e in _liste(roh.get("ausserhalb"), ("was", "zeit"), 4) if zahlen(e["was"]) <= quelle],
        "neu": _neu(gewaehlt, vorher, fokus),
        "ids": [a.id for a in gewaehlt],
        "fokus": fokus,
    }
    return ueberblick, nutzung


def _zeile(e: dict) -> str:
    """Begriffe wie im Protokoll: vorläufige Entscheidung, bloßer Vorschlag, Risiko."""
    zusatz = {"vorlaeufig": "vorläufig"}.get(e.get("status") or "") or {"risiko": "Risiko",
                                                                       "entscheidung": "nur Vorschlag"}.get(e.get("typ") or "")
    return e["was"] + (f" ({zusatz})" if zusatz else "")


def als_markdown(u: dict) -> str:
    """Für die Meeting-Ablage und die Karte im Verlauf."""
    z = [f"# Überblick: {u['titel']}", "", f"Stand {u['laufzeit']}" + (f" · jetzt {u['punkt']}" if u.get("punkt") else "")]
    if u.get("fokus"):
        z.append(f"Fokus: {u['fokus']}")
    if u.get("kernaussage"):
        z += ["", u["kernaussage"]]
    for titel, schluessel in (("✅ Entschieden", "entschieden"), ("🟡 Offen", "offen")):
        z += ["", f"## {titel}"] + ([f"- {_zeile(e)}" for e in u[schluessel]] or ["- –"])
    if u.get("optionen"):
        z += ["", "## ⚖ Optionen und Kriterien"] + [f"- {TYP_NAME[e['typ']]}: {e['was']}" for e in u["optionen"]]
    z += ["", "## 📌 Aufgaben"] + ([f"- {a['was']} (wer: {a['wer'] or 'offen'}, bis: {a['bis'] or 'offen'})"
                                   for a in u["aufgaben"]] or ["- –"])
    z += ["", "## ↪ Außerhalb der Agenda"] + ([f"- {a['zeit'] or ''} {a['was']}".replace("-  ", "- ")
                                              for a in u["ausserhalb"]] or ["- keine Abschweifung"])
    z += ["", "## Neu seit dem letzten Stand"] + ([f"- {n}" for n in u["neu"]] or ["- nichts Neues festgehalten"])
    return "\n".join(z) + "\n"


def punkte(u: dict) -> list[str]:
    """Kurzfassung als Stichpunkte für die Karte (Handy, Verlauf)."""
    aus = [f"Entschieden: {_zeile(e)}" for e in u["entschieden"][:3]]
    aus += [f"Offen: {_zeile(e)}" for e in u["offen"][:2]]
    aus += [f"{TYP_NAME[e['typ']]}: {e['was']}" for e in u.get("optionen", [])[:4]]
    aus += [f"Aufgabe: {a['was']}" + (f" ({a['wer']}" + (f", bis {a['bis']}" if a["bis"] else "") + ")" if a["wer"] else "")
            for a in u["aufgaben"][:3]]
    return aus or [u.get("kernaussage") or "Noch nichts festgehalten."]
