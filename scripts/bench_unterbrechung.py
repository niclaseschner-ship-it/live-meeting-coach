r"""Benchmark Regel 1 „Ausreden lassen“: Unterbrechungen je 10 min auf der Testbibliothek (ohne KI-Kosten).

    .venv\Scripts\python scripts\bench_unterbrechung.py [probe ...] [--cache ORDNER]

Jede Probe läuft durch Pausenerkennung und Stimmen.analysieren – genau der lokale Teil, der live läuft (wie
bench_sprecher.py, ohne Echtzeit-Abspielen; das Ergebnis ist dasselbe, weil die Stimmanalyse live bei Tempo ≤ 10
Schritt hält). Mit --cache werden die Live-Signale je Probe zwischengespeichert (Neuberechnung ~40 s je Probe).

Varianten (coach/unterbrechung.py):
- V0 Ausgangswert: jede Folge von Stimmen-Mischungen (Cluster, 3 s) als Ereignis
- V1 Wechsel ohne VAD-Pause, A ≥ 3 s, B ≥ 3 s, ohne Pegelprüfung
- V2 wie V1, zusätzlich kein Pegel-Einbruch ≥ 15 dB an der Wechselstelle (empfohlen)
- V3 wie V2, streng: A ≥ 4 s, B ≥ 4 s

Wahrheit:
- Sprecher-Referenz: Kandidaten = Wechsel des Rederechts (Läufe ≥ 2 s → ≥ 3 s) mit Überlappung, d. h. ohne
  Lücke oder mit Zickzack-Schnipseln (< 0,5 s) der Diarisierung an der Stelle; Abschnitte < 1 s bilden
  keinen eigenen Lauf. Treffer: Ereignis ± 2,5 s.
  Fehlalarm: Ereignis ohne Kandidat in der Nähe. In geordneten Proben gibt es keine Kandidaten.
- bundestag_ordnungsrufe: protokollierte Zwischenrufe (Untertitelzeit, ± 3 s). Zwischenrufe sind meist
  Einwürfe (die Rednerin spricht weiter) und nach der Arbeitsdefinition keine Unterbrechung.
"""

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

os.environ.setdefault("LMC_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.unterbrechung import Aeusserung, je_10_min, pegel_db, unterbrechungen  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
PROBEN = WURZEL / "testbibliothek" / "proben"
AUDIO = WURZEL / "testbibliothek" / "audio"
STANDARD = ["untervier", "bundestag_ordnungsrufe", "freital_buergerversammlung", "zoom_inca4d", "stadtrat", "ahaus_rat"]

VARIANTEN = {
    "V1 ohne Pause, 3 s/3 s": {"pause_db": None},
    "V2 + Pegelprüfung (empf.)": {},
    "V3 + streng 4 s/4 s": {"min_vorher": 4.0, "min_nachher": 4.0},
}


def live_signale(name: str, cache: Path | None) -> tuple[list[Aeusserung], list[float], float]:
    """VAD-Äußerungen mit Abschnitten und Pegel, Mischfenster (absolut), Dauer."""
    datei = cache / f"unterbrechung_{name}.json" if cache else None
    if datei and datei.exists():
        d = json.loads(datei.read_text())
        return [Aeusserung(**a) for a in d["aeusserungen"]], d["mischung"], d["dauer"]
    from coach.hoeren import nach_16k
    from coach.stimmen import Stimmen
    from coach.vad import Pausenerkennung

    with wave.open(str(AUDIO / f"{name}.wav")) as w:
        a = nach_16k(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768)
    vad, stimmen = Pausenerkennung(), Stimmen()
    aeusserungen, mischung = [], []
    for start, ende, proben in vad.zufuehren(a) + vad.ende():
        erg = stimmen.analysieren(proben)
        aeusserungen.append(Aeusserung(start, ende, [tuple(x) for x in erg["abschnitte"]], pegel_db(proben)))
        mischung += [start + t for t in erg["mischung"]]
    dauer = len(a) / 16000
    if datei:
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text(json.dumps({"aeusserungen": [vars(x) for x in aeusserungen], "mischung": mischung,
                                     "dauer": dauer}))
    return aeusserungen, mischung, dauer


def mischungs_ereignisse(mischung: list[float], abstand: float = 3.0) -> list[float]:
    ev: list[list[float]] = []
    for t in sorted(mischung):
        if ev and t - ev[-1][1] <= abstand:
            ev[-1][1] = t
        else:
            ev.append([t, t])
    return [a for a, _ in ev]


def ref_kandidaten(ref: list[dict], schnipsel: float = 1.0, zacke: float = 0.5) -> list[float]:
    """Wechsel des Rederechts mit Überlappung aus der Sprecher-Referenz (siehe Kopf)."""
    r = sorted(ref, key=lambda x: x["von"])
    L: list[list] = []
    for x in r:
        if x["bis"] - x["von"] < schnipsel:
            continue
        if L and L[-1][2] == x["person"] and x["von"] - L[-1][1] < 3.0:
            L[-1][1] = x["bis"]
        else:
            L.append([x["von"], x["bis"], x["person"]])
    aus = []
    for a, b in zip(L, L[1:]):
        if a[2] == b[2] or a[1] - a[0] < 2 or b[1] - b[0] < 3:
            continue
        zickzack = any(a[1] - 0.5 <= x["von"] <= b[0] + 0.5 and x["bis"] - x["von"] < zacke for x in r)
        if b[0] - a[1] <= 0.3 or (zickzack and b[0] - a[1] <= 1.0):
            aus.append(b[0])
    return aus


def vergleich(ereignisse: list[float], wahr: list[tuple[float, float]], tol: float) -> tuple[int, int]:
    treffer = sum(any(a - tol <= t <= b + tol for t in ereignisse) for a, b in wahr)
    fehl = sum(not any(a - tol <= t <= b + tol for a, b in wahr) for t in ereignisse)
    return treffer, fehl


def mmss(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def main() -> None:
    args = sys.argv[1:]
    cache = None
    if "--cache" in args:
        i = args.index("--cache")
        cache = Path(args[i + 1])
        del args[i:i + 2]
    namen = args or STANDARD
    print(f"{'Probe':28} {'Variante':27} {'je 10 min':>9}  Wahrheit")
    for name in namen:
        probe = json.loads((PROBEN / name / "probe.json").read_text(encoding="utf-8"))
        if not (AUDIO / f"{name}.wav").exists():
            continue
        ref = probe.get("referenz", {})
        aeusserungen, mischung, dauer = live_signale(name, cache)
        wahr, tol, art = None, 2.5, ""
        if ref.get("zwischenrufe"):
            wahr = [(z["von"], z["bis"]) for z in ref["zwischenrufe"] if z["art"] == "zwischenruf"]
            tol, art = 3.0, "Zwischenrufe"
        elif ref.get("sprecher"):
            wahr = [(t, t) for t in ref_kandidaten(ref["sprecher"])]
            art = "Kandidaten"
        ergebnisse = {"V0 Mischungen (Ausgangswert)": mischungs_ereignisse(mischung)}
        for vn, v in VARIANTEN.items():
            ergebnisse[vn] = [u.zeit for u in unterbrechungen(aeusserungen, **v)]
        for vn, ev in ergebnisse.items():
            zeile = f"{name:28} {vn:27} {len(ev) / dauer * 600:9.1f}"
            if wahr is not None:
                h, f = vergleich(ev, wahr, tol)
                zeile += f"  {h}/{len(wahr)} {art}, {f} ohne"
            print(zeile, flush=True)
        empf = unterbrechungen(aeusserungen)
        print(f"{'':28} Stellen V2: {', '.join(mmss(u.zeit) for u in empf) or '–'}"
              f"  (zweite Hälfte {je_10_min(empf, dauer / 2, dauer):.1f} je 10 min)")


if __name__ == "__main__":
    main()
