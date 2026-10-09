"""Überblick als Text (Ticket #13, beide Stufen): der Stand des Meetings als strukturierte Dashboard-Ansicht – ohne
Bildmodell. In Nestor Basis ersetzt er das Live-Bild (auch auf Zuruf „zeig uns die Übersicht“ → AKTION: bild),
in Premium ist er umschaltbar neben dem Live-Bild.

Aufbau wie die Zonen des Live-Bilds (onepager.py, Strukturanalyse Schritt 1):
    Kopf          Titel, Laufzeit, aktueller Punkt, Agenda mit Status          – aus dem Meeting-Zustand, ohne Modell
    ✅ Entschieden  nur ausdrücklich Beschlossenes, mit Ergebnis
    🟡 Offen        ausdrücklich genannte offene Fragen
    📌 Aufgaben     was, wer, bis wann (nur wenn gesagt)
    ↪ Außerhalb    Gesprächsteile ohne Bezug zur Agenda
    Neu seit dem letzten Stand

Inhalte kommen aus einem Textaufruf (JSON) über Agenda, festgestellte Ergebnisse je Punkt (Regel 10) und Transkript.
Damit nichts „gemalt“ wird: jede Zahl im Überblick muss im Material vorkommen, sonst fliegt der Eintrag raus
(`zahlen_pruefen`) – die Bildprobe mit FLUX hatte aus 25.000 € 55.000 € gemacht.
"""

from __future__ import annotations

import json
import re
import time

from .analyse import mmss
from .config import EINST
from .onepager import meeting_text

AUFTRAG = """\
Du bereitest für eine Besprechungsrunde den Überblick über ihr laufendes Meeting vor. Er steht auf dem Bildschirm
und zeigt auf einen Blick, was entschieden ist, was offen ist und wer was bis wann übernimmt.

Antworte ausschließlich mit einem JSON-Objekt mit genau diesen Schlüsseln:
{{"kernaussage": "ein Satz, höchstens 15 Wörter: wo steht das Meeting gerade",
 "entschieden": [{{"punkt": Nummer des Agendapunkts oder null, "was": "Beschluss in höchstens 12 Wörtern"}}],
 "offen": [{{"punkt": Nummer oder null, "was": "offene Frage in höchstens 12 Wörtern"}}],
 "aufgaben": [{{"was": "Aufgabe in höchstens 10 Wörtern", "wer": "Name oder null", "bis": "Termin oder null"}}],
 "ausserhalb": [{{"zeit": "m:ss", "was": "Thema in höchstens 6 Wörtern"}}],
 "neu": ["1 bis 3 kurze Zeilen: was seit dem letzten Stand dazukam"]}}

Regeln:
- Nur, was im Material steht. Zahlen, Beträge, Termine und Namen genau so wie dort – nichts runden, nichts ergänzen.
- „entschieden“ nur, wenn die Gruppe es ausdrücklich beschlossen hat; ein Vorschlag bleibt „offen“.
- Die festgestellten Ergebnisse je Agendapunkt unten sind geprüft – übernimm sie, statt sie neu zu formulieren.
- Aufgaben: „wer“ und „bis“ nur, wenn gesagt, sonst null. Personen heißen im Transkript „Person N“; nenne sie nicht
  so (dann null). Keine Bewertung von Personen.
- „ausserhalb“: Gesprächsteile ohne Bezug zur Agenda (z. B. Fußball, Urlaub), mit Startzeit; sonst leere Liste.
- Leere Listen sind erlaubt. Deutsch.
{fokus}{vorher}
MATERIAL:
{material}
"""

FOKUS = "\nFOKUS (Wunsch der Runde): {fokus} – nimm nur auf, was dazu gehört.\n"
VORHER = "\nLETZTER STAND (für „neu“ – vergleiche damit, was dazukam):\n{vorher}\n"


def zahlen(text: str) -> set[str]:
    """Zahlen in vergleichbarer Form: „25.000“, „25000“ und „25 000“ werden zu „25000“; Uhrzeiten/Daten bleiben Ziffern."""
    roh = re.findall(r"\d[\d.\s]*\d|\d", text)
    return {re.sub(r"[.\s]", "", z) for z in roh}


def zahlen_pruefen(eintraege: list[dict], quelle: set[str], felder=("was", "wer", "bis")) -> list[dict]:
    """Einträge mit einer Zahl, die im Material nicht vorkommt, verwerfen (lieber weglassen als falsch zeigen)."""
    aus = []
    for e in eintraege:
        text = " ".join(str(e.get(f) or "") for f in felder)
        if zahlen(text) <= quelle:
            aus.append(e)
    return aus


def _liste(roh, felder: tuple[str, ...], n: int) -> list[dict]:
    aus = []
    for e in roh if isinstance(roh, list) else []:
        if isinstance(e, str):
            e = {felder[0]: e}
        if not isinstance(e, dict) or not str(e.get(felder[0]) or "").strip():
            continue
        d = {f: (str(e[f]).strip()[:160] if e.get(f) not in (None, "", "null") else None) for f in felder}
        for f, v in d.items():  # „Person N“ nicht auf den Bildschirm: als Zuständige weglassen, im Text „jemand“
            if v and re.fullmatch(r"Person \d+", v):
                d[f] = None
            elif v:
                d[f] = re.sub(r"\bPerson \d+\b", "jemand", v)
        aus.append(d)
    return aus[:n]


def kopf(meeting) -> dict:
    m = meeting
    i = m.aktiver_punkt
    return {
        "titel": m.titel or "Meeting", "laufzeit": mmss(m.jetzt()), "stand": round(m.jetzt(), 1),
        "punkt": f"{i + 1}. {m.agenda[i].titel}" if 0 <= i < len(m.agenda) else None,
        "agenda": [{"nr": k + 1, "titel": p.titel, "status": m.status(k)} for k, p in enumerate(m.agenda)],
    }


def material(meeting, fokus: str | None = None) -> str:
    """Meeting-Text wie beim Live-Bild plus die festgestellten Ergebnisse je Punkt (Regel 10)."""
    aktuell = bool(fokus and re.search(r"aktuell|aktueller|aktuellen|dieser|laufend", fokus, re.I))
    i = meeting.aktiver_punkt
    if aktuell and 0 <= i < len(meeting.agenda):
        p = meeting.agenda[i]
        teile = [f"Titel: {meeting.titel}\nAgendapunkt {i + 1}: {p.titel}\nZiel: {p.ziel or '-'}",
                 "Transkript:", "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}"
                                           for s in meeting.punkt_transkript(i) if s.text)]
    else:
        teile = [meeting_text(meeting)]
    erg = []
    for i, e in sorted(meeting.ergebnisse.items()):
        if aktuell and i != meeting.aktiver_punkt:
            continue
        if not (0 <= i < len(meeting.agenda)):
            continue
        zeile = f"{i + 1}. {meeting.agenda[i].titel}: Ergebnis: {e.get('ergebnis') or 'keins ausgesprochen'}"
        zeile += "".join(f"; Entscheidung: {d['was']}" + (f" ({d['ergebnis']})" if d.get("ergebnis") else "")
                         for d in e.get("entscheidungen") or [])
        zeile += "".join(f"; Aufgabe: {a['was']} (wer: {a.get('wer') or 'offen'}, bis: {a.get('bis') or 'offen'})"
                         for a in e.get("aufgaben") or [])
        erg.append(zeile)
    if erg:
        teile += ["", "Festgestellte Ergebnisse je Agendapunkt (geprüft):"] + erg
    return "\n".join(teile)


async def erstellen(client, meeting, vorher: dict | None = None, fokus: str | None = None) -> tuple[dict, dict]:
    """Liefert (überblick, nutzung). `vorher`: der letzte Überblick (für „neu seit dem letzten Stand“)."""
    t0 = time.monotonic()
    stoff = material(meeting, fokus)
    alt = ""
    if vorher and vorher.get("fokus") == fokus:
        alt = json.dumps({k: vorher.get(k) for k in ("entschieden", "offen", "aufgaben", "ausserhalb")},
                         ensure_ascii=False)
    auftrag = AUFTRAG.format(fokus=FOKUS.format(fokus=fokus) if fokus else "",
                             vorher=VORHER.format(vorher=alt) if alt else "", material=stoff)
    r = await client.chat.completions.create(
        model=EINST.analyse_modell, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": auftrag}],
        **({"reasoning_effort": EINST.analyse_aufwand} if EINST.analyse_aufwand else {}))
    try:
        roh = json.loads(r.choices[0].message.content or "{}")
    except ValueError:
        roh = {}
    roh = roh if isinstance(roh, dict) else {}
    quelle = zahlen(stoff)
    u = getattr(r, "usage", None)
    nutzung = {"tokens_rein": getattr(u, "prompt_tokens", None), "tokens_raus": getattr(u, "completion_tokens", None),
               "sekunden": round(time.monotonic() - t0, 1)}
    ueberblick = {
        **kopf(meeting),
        "kernaussage": str(roh.get("kernaussage") or "").strip()[:200] or None,
        "entschieden": zahlen_pruefen(_liste(roh.get("entschieden"), ("was", "punkt"), 8), quelle, ("was",)),
        "offen": zahlen_pruefen(_liste(roh.get("offen"), ("was", "punkt"), 6), quelle, ("was",)),
        "aufgaben": zahlen_pruefen(_liste(roh.get("aufgaben"), ("was", "wer", "bis"), 8), quelle),
        "ausserhalb": _liste(roh.get("ausserhalb"), ("was", "zeit"), 4),
        # „Person N“ gehört nicht auf den Bildschirm (Lastenheft: keine Personenbewertung) – auch nicht in „neu“
        "neu": [re.sub(r"\bPerson \d+\b", "jemand", str(x).strip())[:140] for x in (roh.get("neu") or [])
                if str(x).strip()][:3] if vorher
        else ["erster Stand"],
        "fokus": fokus,
    }
    return ueberblick, nutzung


def als_markdown(u: dict) -> str:
    """Für die Meeting-Ablage und die Karte im Verlauf."""
    z = [f"# Überblick: {u['titel']}", "", f"Stand {u['laufzeit']}" + (f" · jetzt {u['punkt']}" if u.get("punkt") else "")]
    if u.get("fokus"):
        z.append(f"Fokus: {u['fokus']}")
    if u.get("kernaussage"):
        z += ["", u["kernaussage"]]
    for titel, schluessel in (("✅ Entschieden", "entschieden"), ("🟡 Offen", "offen")):
        z += ["", f"## {titel}"] + ([f"- {e['was']}" for e in u[schluessel]] or ["- –"])
    z += ["", "## 📌 Aufgaben"] + ([f"- {a['was']} (wer: {a['wer'] or 'offen'}, bis: {a['bis'] or 'offen'})"
                                   for a in u["aufgaben"]] or ["- –"])
    z += ["", "## ↪ Außerhalb der Agenda"] + ([f"- {a['zeit'] or ''} {a['was']}".replace("-  ", "- ")
                                              for a in u["ausserhalb"]] or ["- keine Abschweifung"])
    z += ["", "## Neu seit dem letzten Stand"] + [f"- {n}" for n in u["neu"]]
    return "\n".join(z) + "\n"


def punkte(u: dict) -> list[str]:
    """Kurzfassung als Stichpunkte für die Karte (Handy, Verlauf)."""
    aus = [f"Entschieden: {e['was']}" for e in u["entschieden"][:3]]
    aus += [f"Offen: {e['was']}" for e in u["offen"][:2]]
    aus += [f"Aufgabe: {a['was']}" + (f" ({a['wer']}" + (f", bis {a['bis']}" if a["bis"] else "") + ")" if a["wer"] else "")
            for a in u["aufgaben"][:3]]
    return aus or [u.get("kernaussage") or "Noch nichts festgehalten."]
