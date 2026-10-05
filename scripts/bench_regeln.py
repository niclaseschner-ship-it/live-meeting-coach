r"""Benchmark Gesprächsregeln 5 und 6 auf der Testbibliothek (ohne KI-Kosten, lokaler Teil der Pipeline).

    .venv\Scripts\python scripts\bench_regeln.py [probe ...]

Regel 5 „Sich kurz fassen“: Monologe aus der Sprecher-Referenz (zusammenhängende Rede einer Person
≥ 60 s, Lücken < 2 s überbrückt) gegen die Monolog-Hinweise des Coaches.
- Treffer: Hinweis zwischen Beginn + 50 s und Ende + 15 s; Verzug = Hinweis − (Beginn + 60 s)
- Fehlalarm: Hinweis in einem Referenzabschnitt, dessen Rede bis dahin < 45 s lief
  (Hinweise in Lücken der Referenz zählen nicht – dort ist die Wahrheit unbekannt)
Regel 6 „Alle kommen zu Wort“: Redeanteile gegen die Referenz (größte Abweichung in Prozentpunkten)
und Hinweis auf eine stille Person (angemeldet: Referenzpersonen + 1).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["LMC_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.analyse import mmss  # noqa: E402
from coach.config import EINST  # noqa: E402
from coach.pipeline import Coach  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
PROBEN = WURZEL / "testbibliothek" / "proben"
AUDIO = WURZEL / "testbibliothek" / "audio"


def monologe(ref: list[dict], min_s: float, luecke: float = 2.0) -> list[tuple[float, float]]:
    laeufe: list[list] = []
    for r in sorted(ref, key=lambda r: r["von"]):
        if laeufe and laeufe[-1][2] == r["person"] and r["von"] - laeufe[-1][1] < luecke:
            laeufe[-1][1] = r["bis"]
        else:
            laeufe.append([r["von"], r["bis"], r["person"]])
    return [(a, b) for a, b, _ in laeufe if b - a >= min_s], laeufe


async def lauf(probe: dict) -> Coach:
    ref = probe["referenz"]["sprecher"]
    personen = sorted({r["person"] for r in ref})
    coach = Coach()
    coach.onepager_am_ende = False
    original = coach._einrichten

    def einrichten(daten: dict) -> None:
        original(daten)
        coach.meeting.regel_ids = ["kurz", "alle"]
        coach.meeting.teilnehmende = personen + ["Stille Person"]

    coach._einrichten = einrichten
    await coach.abspielen(AUDIO / f"{probe['name']}.wav", tempo=float(os.getenv("BENCH_TEMPO", "10")), auto_wechsel=False)  # schneller hält die Stimmanalyse nicht Schritt
    return coach


def bewerten(probe: dict, coach: Coach) -> None:
    ref = probe["referenz"]["sprecher"]
    m = coach.meeting
    soll, laeufe = monologe(ref, EINST.monolog_sekunden)
    ist = [h.zeit for h in m.hinweise if h.art == "monolog"]
    treffer, verzug = 0, []
    for a, b in soll:
        passend = [t for t in ist if a + EINST.monolog_sekunden - 10 <= t <= b + 15]
        if passend:
            treffer += 1
            verzug.append(passend[0] - (a + EINST.monolog_sekunden))
    fehl = [t for t in ist if any(a <= t <= b and t - a < 45 for a, b, _ in laeufe)
            and not any(a + EINST.monolog_sekunden - 10 <= t <= b + 15 for a, b in soll)]
    print(f"  Regel 5 Monologe: {treffer}/{len(soll)} erkannt"
          + (f", Verzug {min(verzug):+.0f} … {max(verzug):+.0f} s" if verzug else "")
          + f", Fehlalarme {len(fehl)}" + (f" ({', '.join(mmss(t) for t in fehl)})" if fehl else ""))

    # Regel 6: Anteile (sortiert verglichen – die Zuordnung Person ↔ Referenz prüft bench_sprecher.py)
    ref_anteil: dict[str, float] = {}
    for r in ref:
        ref_anteil[r["person"]] = ref_anteil.get(r["person"], 0) + r["bis"] - r["von"]
    ist_anteil = {k: v for k, v in m.redeanteile().items() if v >= 10}
    a = sorted((v / sum(ref_anteil.values()) for v in ref_anteil.values()), reverse=True)
    b = sorted((v / sum(ist_anteil.values()) for v in ist_anteil.values()), reverse=True)
    n = max(len(a), len(b))
    a, b = a + [0] * (n - len(a)), b + [0] * (n - len(b))
    abw = max(abs(x - y) for x, y in zip(a, b)) * 100
    still = [h for h in m.hinweise if h.art == "alle" and "noch nicht gesprochen" in h.text]
    print(f"  Regel 6 Redeanteile: Referenz {' / '.join(f'{x:.0%}' for x in a)} · erkannt "
          f"{' / '.join(f'{x:.0%}' for x in b)} · größte Abweichung {abw:.0f} Prozentpunkte")
    print(f"  Regel 6 stille Person: " + (f"gemeldet bei {mmss(still[0].zeit)} – „{still[0].text}“"
                                         if still else "NICHT gemeldet"))


async def main() -> None:
    namen = sys.argv[1:] or [p.parent.name for p in sorted(PROBEN.glob("*/probe.json"))]
    for name in namen:
        probe = json.loads((PROBEN / name / "probe.json").read_text(encoding="utf-8"))
        if not probe.get("referenz", {}).get("sprecher") or not (AUDIO / f"{name}.wav").exists():
            continue
        print(name, flush=True)
        bewerten(probe, await lauf(probe))


if __name__ == "__main__":
    asyncio.run(main())
