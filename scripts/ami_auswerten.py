r"""AMI-Durchläufe auswerten: Agenda-Wechsel gegen die Themen-Referenz, Überlappungs-Vorfälle gegen die
Sprecher-Referenz, Beschlüsse gegen die Zusammenfassung.

    .venv\Scripts\python scripts\ami_auswerten.py docs\testlauf_ami.md ami_ES2002b ami_ES2002c ami_ES2002d
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent


def mmss(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def ref_ueberlappungen(sprecher: list[dict], min_dauer: float = 1.0) -> list[tuple[float, float]]:
    """Zeiträume, in denen mindestens zwei Personen laut Referenz gleichzeitig sprechen (≥ min_dauer)."""
    T = np.arange(0, max(r["bis"] for r in sprecher), 0.1)
    n = np.zeros(len(T), int)
    for r in sprecher:
        n[(T >= r["von"]) & (T < r["bis"])] += 1
    maske = n >= 2
    d = np.diff(np.concatenate([[0], maske.astype(int), [0]]))
    lauf = list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))
    return [(T[a], T[b - 1] + 0.1) for a, b in lauf if (b - a) * 0.1 >= min_dauer]


def auswerten(name: str) -> list[str]:
    p = json.loads((WURZEL / "testbibliothek" / "proben" / name / "probe.json").read_text(encoding="utf-8"))
    b = json.loads((WURZEL / "logs" / f"bericht_{name}.json").read_text(encoding="utf-8"))
    ref = p["referenz"]
    z = [f"## {p['titel']}", ""]
    # Agenda: je Agendapunkt der erste Themenabschnitt mit diesem Titel
    agenda = [a["titel"] for a in p["meeting"]["agenda"]]
    start = {}
    for t in ref["themen"]:
        if t["thema"] in agenda and t["thema"] not in start:
            start[t["thema"]] = t["start"]
    wechsel = [e for e in b["protokoll"] if e["art"] == "wechsel"]
    z += ["| Agendapunkt | Referenz | erkannt | Verzug |", "|---|---|---|---|"]
    treffer = 0
    for i, titel in enumerate(agenda[1:], 1):
        t = start.get(titel)
        w = next((e for e in wechsel if e["nach"] == i and t is not None and e["zeit"] >= t - 30), None)
        if w and w["zeit"] - t <= 120:
            treffer += 1
        z.append(f"| {i + 1}. {titel} | {mmss(t) if t is not None else '–'} | {mmss(w['zeit']) if w else '–'} | "
                 + (f"{w['zeit'] - t:+.0f} s |" if w else "– |"))
    z += ["", f"{treffer} von {len(agenda) - 1} Wechseln innerhalb von 2 min, {len(wechsel)} Wechsel insgesamt "
          "(AMI-Themen wiederholen sich, der Coach springt dann zurück).", ""]
    # Überlappungs-Vorfälle
    ru = ref_ueberlappungen(ref["sprecher"])
    erk = [u for u in b.get("ueberlappungen", []) if u[1] - u[0] >= 1.0]
    gefunden = sum(1 for a, c in ru if any(x < c + 0.5 and y > a - 0.5 for x, y in erk))
    echt = sum(1 for x, y in erk if any(x < c + 0.5 and y > a - 0.5 for a, c in ru))
    minuten = b["zeitreihe"][-1]["t"] / 60
    z += [f"**Gleichzeitiges Sprechen ≥ 1 s:** Referenz {len(ru)} Vorfälle ({len(ru) / minuten * 10:.1f} je 10 min), "
          f"erkannt {len(erk)}; {gefunden} der echten gefunden ({gefunden / max(1, len(ru)):.0%}), "
          f"{echt} der erkannten echt ({echt / max(1, len(erk)):.0%}).", ""]
    d = b["dynamik"]
    kl = Counter((x.get("klima") or {}).get("stufe") for x in b["zeitreihe"])
    z += [f"**Dynamik laut Coach:** {d['ueberlappungen']}× gleichzeitig, {d['unterbrechungen']}× ins Wort; Klima "
          + ", ".join(f"{k} {v}" for k, v in kl.most_common()) + ".", ""]
    # Beschlüsse
    entsch = [x for e in b.get("ergebnisse", {}).values() for x in e.get("entscheidungen", [])]
    z += [f"**Beschlüsse:** Referenz {len(ref['beschluesse'])}, vom Coach festgehalten {len(entsch)}.", "",
          "| Referenz (AMI-Zusammenfassung) |", "|---|"] + [f"| {s} |" for s in ref["beschluesse"]] + [
          "", "| Coach (Regel 10) |", "|---|"] + [f"| {x['was']} – {x.get('ergebnis') or ''} |" for x in entsch] + [""]
    hw = Counter(h["art"] for h in b["hinweise"])
    z += [f"**Hinweise:** {sum(hw.values())} (" + ", ".join(f"{k} {v}" for k, v in hw.most_common()) + f"). "
          f"**Kosten:** {b['kosten']['meeting']:.2f} $.", ""]
    return z


def main() -> None:
    z = ["# AMI-Besprechungen durch den ganzen Coach", "",
         "Vier Personen, ein Tischmikrofon, englisch, gespieltes Designprojekt (AMI-Korpus, CC BY 4.0). Live-Text "
         "„sparsam“, Text-KI über die API, Tempo 2. Referenz: Themenabschnitte, Sprecher je Satz, Beschlüsse aus der "
         "Zusammenfassung.", ""]
    for name in sys.argv[2:]:
        z += auswerten(name)
    Path(sys.argv[1]).write_text("\n".join(z) + "\n", encoding="utf-8")
    print("\n".join(z))


if __name__ == "__main__":
    main()
