r"""Synthetische Meetings auswerten: eingebaute Ereignisse (Referenz) gegen das, was der Coach erkannt hat.

    .venv\Scripts\python scripts\synthetisch_auswerten.py docs\testlauf_synthetisch.md teamweekly vereinsrunde …

Liest testbibliothek/synthetisch/<name>.referenz.json und logs/bericht_<name>.json (scripts/abspielen.py).
Je Ereignisart: gefunden / eingebaut, mit Verzug; dazu Fehlalarme (Hinweise ohne passendes Ereignis), die
Sprecherzuordnung gegen die Referenzpersonen und Nestors Antworten.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent
SYN = WURZEL / "testbibliothek" / "synthetisch"

# Ereignis im Drehbuch -> was der Coach dazu melden sollte
ERWARTET = {"kraftausdruck": "ton", "angriff": "ton", "monolog": "monolog", "abschweifung": "fokus",
            "unterbrechung": "unterbrechung"}


def mmss(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def auswerten(name: str) -> tuple[list[str], dict]:
    ref = json.loads((SYN / f"{name}.referenz.json").read_text(encoding="utf-8"))
    b = json.loads((WURZEL / "logs" / f"bericht_{name}.json").read_text(encoding="utf-8"))
    d = json.loads((SYN / f"{name}.json").read_text(encoding="utf-8"))
    prot = b["protokoll"]
    z = [f"## {d['titel']}", "", f"{len(ref)} Äußerungen, {len(d['personen'])} Personen, Aufnahme {mmss(ref[-1]['bis'])} min. "
         f"Live-Text „{b['einstellungen'].get('live_art')}“, Nestor „{b['einstellungen'].get('modus')}“, Tempo {b.get('tempo')}.", ""]

    # Sprecher: Referenzperson je 0,25 s gegen Transkript-Sprecher (beste 1:1-Zuordnung)
    T = np.arange(0, ref[-1]["bis"], 0.25)
    soll = np.full(len(T), -1)
    for r in ref:
        soll[(T >= r["von"]) & (T < r["bis"])] = r["person"]
    ist = np.full(len(T), "", dtype=object)
    for s in b["transkript"]:
        ist[(T >= s["start"]) & (T < s["ende"])] = s["sprecher"]
    paare = Counter((ist[i], soll[i]) for i in range(len(T)) if soll[i] >= 0 and ist[i] and ist[i] != "Person ?")
    zu, fi, fs = {}, set(), set()
    for (a, c), n in paare.most_common():
        if a not in fi and c not in fs:
            zu[a] = c
            fi.add(a)
            fs.add(c)
    gesprochen = soll >= 0
    richtig = np.mean([zu.get(ist[i]) == soll[i] for i in np.where(gesprochen)[0]])
    unsicher = np.mean([ist[i] in ("", "Person ?") for i in np.where(gesprochen)[0]])
    z += [f"**Sprecher:** {richtig:.0%} der Sprechzeit richtig, {unsicher:.0%} „?“ oder nicht erfasst, "
          f"{1 - richtig - unsicher:.0%} falsch; {len([k for k, v in b['redeanteile'].items() if v >= 10 and k != 'Person ?'])} "
          f"Personen erkannt (Soll {len(d['personen'])}).", ""]

    # Ereignisse
    hinweise = b["hinweise"]
    unterbr = [e["zeit"] for e in prot if e["art"] == "unterbrechung"]
    z += ["| Ereignis | eingebaut | erkannt | Verzug | erkannt als |", "|---|---|---|---|---|"]
    erg: dict = {"name": name}
    benutzt: set = set()
    for art, meldung in ERWARTET.items():
        stellen = [r for r in ref if art in r["ereignisse"]]
        if not stellen:
            continue
        treffer, verzug = 0, []
        for r in stellen:
            if meldung == "unterbrechung":
                t = next((x for x in unterbr if r["von"] - 3 <= x <= r["von"] + 8), None)
            else:
                h = next((h for h in hinweise if h["art"] == meldung and r["von"] - 5 <= h["zeit"] <= r["bis"] + 90
                          and id(h) not in benutzt), None)
                t = h["zeit"] if h else None
                if h:
                    benutzt.add(id(h))
            if t is not None:
                treffer += 1
                verzug.append(t - r["bis"])
        z.append(f"| {art} | {len(stellen)} | {treffer} | {np.median(verzug):+.0f} s |" if verzug else
                 f"| {art} | {len(stellen)} | 0 | – |")
        z[-1] += f" {meldung} |"
        erg[art] = (treffer, len(stellen))
    # Agenda-Wechsel: erste Äußerung eines neuen Punkts
    wechsel_ref, aktiv = [], 0
    for r in ref:
        if r.get("punkt") is not None and r["punkt"] > aktiv:
            wechsel_ref.append((r["von"], r["punkt"], "wechsel_ansage" in r["ereignisse"]))
            aktiv = r["punkt"]
    wechsel = [e for e in prot if e["art"] == "wechsel"]
    for t, p, ansage in wechsel_ref:
        w = next((e for e in wechsel if e["nach"] == p and e["zeit"] >= t - 10), None)
        z.append(f"| Wechsel zu Punkt {p + 1} ({'mit' if ansage else 'ohne'} Ansage) | 1 | {1 if w else 0} | "
                 + (f"{w['zeit'] - t:+.0f} s | {w.get('durch', 'Themen-Zuordnung')} |" if w else "– | – |"))
    # Beschlüsse
    beschl = [r for r in ref if "beschluss" in r["ereignisse"]]
    gefunden = sum(len(e.get("entscheidungen", [])) for e in b.get("ergebnisse", {}).values())
    z.append(f"| beschluss | {len(beschl)} | {gefunden} Entscheidungen festgehalten | – | Regel 10 |")
    ohne = [r for r in ref if "aufgabe_ohne_zustaendig" in r["ereignisse"]]
    if ohne:
        z.append(f"| aufgabe ohne Zuständigen | {len(ohne)} | {sum(1 for h in hinweise if h['art'] == 'ergebnisse')} Hinweise | – | Regel 10 |")
    # Nestor
    fragen = [r for r in ref if "nestor_frage" in r["ereignisse"]]
    antworten = [e for e in prot if e["art"] == "assistent"]
    beantwortet = sum(1 for r in fragen if any(r["von"] <= a["zeit"] <= r["bis"] + 40 for a in antworten))
    z.append(f"| Frage an Nestor | {len(fragen)} | {beantwortet} beantwortet | – | Nestor |")
    erg["nestor"] = (beantwortet, len(fragen))
    # Fehlalarme: Hinweise, die keinem eingebauten Ereignis zugeordnet wurden (ohne Zeit/Ergebnisse)
    # Keine Fehlalarme: Fokus-Hinweise, die einen Agenda-Wechsel vorschlagen (im Abspielmodus sofort übernommen),
    # und Überlappungs-Hinweise an eingebauten Unterbrechungen (dort sprechen zwei gleichzeitig)
    w_zeiten = [e["zeit"] for e in wechsel]
    u_zeiten = [r["von"] for r in ref if "unterbrechung" in r["ereignisse"]]
    rest = [h for h in hinweise if id(h) not in benutzt and h["art"] not in ("zeit", "ergebnisse")
            and not (h["art"] == "fokus" and any(abs(h["zeit"] - t) <= 5 for t in w_zeiten))
            and not (h["art"] == "ueberlappung" and any(-2 <= h["zeit"] - t <= 15 for t in u_zeiten))]
    z += ["", f"**Weitere Hinweise ohne eingebautes Ereignis:** {len(rest)} – "
          + (", ".join(f"{k} {v}" for k, v in Counter(h["art"] for h in rest).most_common()) or "keine"), ""]
    for h in rest[:8]:
        z.append(f"- {mmss(h['zeit'])} [{h['art']}] {h['text'][:130]}")
    dyn = b.get("dynamik") or {}
    z += ["", f"**Gesprächsdynamik:** {dyn.get('ueberlappungen')}× gleichzeitig, {dyn.get('unterbrechungen')}× ins Wort; "
          f"Klima am Ende „{(dyn.get('klima') or {}).get('stufe')}“; Klima-Verlauf: "
          + ", ".join(f"{k} {v}" for k, v in Counter((x.get('klima') or {}).get('stufe') for x in b['zeitreihe']).most_common()) + ".",
          f"**Kosten:** {b['kosten']['meeting']:.2f} $.", ""]
    erg.update(fehlalarme=len(rest), sprecher=richtig, kosten=b["kosten"]["meeting"])
    return z, erg


def main() -> None:
    ziel = Path(sys.argv[1])
    teile, uebersicht = [], []
    for name in sys.argv[2:]:
        z, e = auswerten(name)
        teile += z
        uebersicht.append(e)
    kopf = ["# Synthetische Meetings: eingebaute Ereignisse gegen Erkennung", "",
            "Drehbuch über das ChatGPT-Abo (Codex), Vertonung über Teachbuddys Azure (Stimmen onyx, nova, echo, "
            "shimmer, fable), Durchlauf mit `scripts/abspielen.py`. Synthetische Stimmen sind sich ähnlicher als echte; "
            "die Sprecherzahlen hier sind deshalb kein Maß für den Raum.", ""]
    ziel.write_text("\n".join(kopf + teile) + "\n", encoding="utf-8")
    for e in uebersicht:
        print(e)


if __name__ == "__main__":
    main()
