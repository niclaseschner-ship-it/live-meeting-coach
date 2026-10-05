r"""Benchmark „Wer spricht“ auf der Testbibliothek – mit genau dem Code, der live läuft.

    .venv\Scripts\python scripts\bench_sprecher.py [probe ...]

Jede Probe mit Sprecher-Referenz läuft durch Pausenerkennung und Stimmen.analysieren (Modell und Schwelle
aus der Konfiguration, also auch über LMC_STIMM_MODELL / LMC_STIMM_SCHWELLE änderbar). Bewertet wird in
0,25-s-Schritten, nur wo die Referenz eine Person nennt:
- richtig: Anteil der Zeit, in der die angezeigte Person der Referenzperson entspricht (beste 1:1-Zuordnung)
- Personen: angelegte Personen mit ≥ 10 s Sprechzeit (Soll = Personen in der Referenz)
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.config import EINST  # noqa: E402
from coach.hoeren import nach_16k  # noqa: E402
from coach.stimmen import Stimmen  # noqa: E402
from coach.vad import Pausenerkennung  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
PROBEN = WURZEL / "testbibliothek" / "proben"
AUDIO = WURZEL / "testbibliothek" / "audio"
RASTER = 0.25


def bewerten(probe: dict) -> tuple[float, int, int, float]:
    with wave.open(str(AUDIO / f"{probe['name']}.wav")) as w:
        a = nach_16k(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768)
    vad, stimmen = Pausenerkennung(), Stimmen()
    if "--anzahl" in sys.argv:  # Teilnehmerzahl bekannt (Einrichtung oder Vorstellungsrunde)
        stimmen.register.max_personen = len({r["person"] for r in probe["referenz"]["sprecher"]})
    erkannt = []  # (von, bis, person)
    for start, _, proben in vad.zufuehren(a) + vad.ende():
        erg = stimmen.analysieren(proben)
        erkannt += [(start + x, start + y, p) for x, y, p in erg["abschnitte"]]
    ref = probe["referenz"]["sprecher"]
    paare: dict[tuple, int] = {}
    for r in ref:
        for t in np.arange(r["von"], r["bis"], RASTER):
            p = next((p for x, y, p in erkannt if x <= t < y), None)  # None: „Person ?“ oder nichts erfasst
            paare[(p, r["person"])] = paare.get((p, r["person"]), 0) + 1
    gesamt = sum(paare.values())
    richtig, frei_p, frei_r = 0, set(), set()
    for (p, r), n in sorted(paare.items(), key=lambda x: -x[1]):
        if p is not None and p not in frei_p and r not in frei_r:
            richtig += n; frei_p.add(p); frei_r.add(r)
    personen = sum(s >= 10 for s in stimmen.register.sekunden)
    unsicher = sum(n for (p, _), n in paare.items() if p is None)  # „Person ?“ oder gar nicht erfasst
    return richtig / gesamt, personen, len({r["person"] for r in ref}), unsicher / gesamt


def main() -> None:
    namen = [a for a in sys.argv[1:] if not a.startswith("--")] or [p.parent.name for p in sorted(PROBEN.glob("*/probe.json"))]
    print(f"Modell {EINST.stimm_modell}, Schwelle {EINST.stimm_schwelle}")
    for name in namen:
        probe = json.loads((PROBEN / name / "probe.json").read_text(encoding="utf-8"))
        if not probe.get("referenz", {}).get("sprecher") or not (AUDIO / f"{name}.wav").exists():
            continue
        richtig, n, soll, unsicher = bewerten(probe)
        print(f"  {name:14} richtig {richtig:5.1%}   falsch {1 - richtig - unsicher:5.1%}   „?“/nicht erfasst "
              f"{unsicher:5.1%}   Personen {n} (Soll {soll})", flush=True)


if __name__ == "__main__":
    main()
