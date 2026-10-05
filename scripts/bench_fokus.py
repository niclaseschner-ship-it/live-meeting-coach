r"""Benchmark Regel 3 „Beim Thema bleiben“ (Fokus) – sparsam, auf vorhandenen Transkripten.

    .venv\Scripts\python scripts\bench_fokus.py

Keine neue Transkription: Ganze Talkshow-Äußerungen (logs/bericht_untervier.json) werden an Satzgrenzen
in das Stadtrat-Transkript (logs/bericht_stadtrat_fremd.json, ohne die zwei gemischten Äußerungen des
alten Audio-Einschnitts) eingesetzt – drei Einschübe unterschiedlicher Länge in EINEM Lauf, dazu ein
Kontrolllauf ohne Einschub. Kosten: nur die Themen-Zuordnung (~2 × 45 kurze Aufrufe, wenige Cent).

Gemessen:
- erkannt: Fokus-Hinweis „passt zu keinem Agendapunkt“ zwischen Einschub-Beginn und Ende + 30 s
- eingestuft: mindestens ein Abschnitt im Einschub als „neu“ (fremd) zugeordnet
- Fehlalarme: solche Fokus-Hinweise außerhalb der Einschübe (Kontrolllauf und Einschub-Lauf)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.analyse import mmss  # noqa: E402
from coach.pipeline import Coach  # noqa: E402
from coach.zustand import Segment  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
GEMISCHT = {7, 8}  # Äußerungen mit dem alten Audio-Einschnitt (halb Stadtrat, halb Talkshow)
EINSCHUEBE = [(3, [6]), (14, [9, 10]), (21, [16, 17, 18])]  # (nach Stadtrat-Äußerung, Talkshow-Äußerungen)


REF_AGENDA = json.loads((WURZEL / "testbibliothek" / "proben" / "stadtrat" / "probe.json")
                        .read_text(encoding="utf-8"))["referenz"]["agenda"]


def laden(name: str) -> list[dict]:
    return json.loads((WURZEL / "logs" / f"bericht_{name}.json").read_text(encoding="utf-8"))["transkript"]


def zusammensetzen(mit_einschub: bool) -> tuple[list[dict], list[tuple[float, float, float]]]:
    stadt, talk = laden("stadtrat_fremd"), laden("untervier")
    aus, bereiche, versatz = [], [], 0.0
    plan = dict(EINSCHUEBE) if mit_einschub else {}
    for i, s in enumerate(stadt):
        if i in GEMISCHT:
            continue
        aus.append({**s, "start": s["start"] + versatz, "ende": s["ende"] + versatz})
        if i in plan:
            beginn = t = aus[-1]["ende"] + 0.2
            for j in plan[i]:
                d = talk[j]["ende"] - talk[j]["start"]
                aus.append({"sprecher": "Person 9", "text": talk[j]["text"], "start": t, "ende": t + d})
                t += d + 0.2
            bereiche.append((beginn, t, t - beginn))
            versatz += t - beginn
    return aus, bereiche


async def lauf(saetze: list[dict]) -> Coach:
    einrichtung = json.loads((WURZEL / "testbibliothek" / "proben" / "stadtrat" / "probe.json")
                             .read_text(encoding="utf-8"))["meeting"]
    coach = Coach()
    coach._einrichten(einrichtung | {"regel_ids": ["thema"]})
    coach.auto_wechsel = True
    coach.meeting.starten(virtuell=True)
    for s in saetze:
        coach.meeting.virtuelle_zeit = s["ende"]
        await coach.satz(Segment(s["sprecher"], s["text"], s["start"], s["ende"]))
        await asyncio.sleep(0)
        async with coach._themen_sperre:  # Zuordnung abwarten, damit die Zeitpunkte stimmen
            pass
    await coach._abschnitt_auswerten()
    return coach


def fremd_hinweise(coach: Coach) -> list[float]:
    """Fokus-Hinweise ohne Agendabezug (nicht: Vorgriff auf einen späteren Punkt)."""
    return [h.zeit for h in coach.meeting.hinweise if h.art == "fokus" and h.text.startswith("Bezug zum aktuellen")]


async def main() -> None:
    kontrolle = await lauf(zusammensetzen(False)[0])
    fa = fremd_hinweise(kontrolle)
    print(f"Kontrolllauf ohne Einschub: {len(fa)} Fokus-Hinweise ohne Agendabezug"
          + (f" ({', '.join(mmss(t) for t in fa)})" if fa else ""))
    # Agenda-Wechsel gegen die Kapitelmarken (im Basis-Transkript ab 250 s um 40 s verschoben)
    soll = {r["punkt"]: r["von"] + (40 if r["von"] >= 250 else 0) for r in REF_AGENDA}
    print("  Agenda-Wechsel (Soll → Ist):")
    for e in kontrolle.protokoll:
        if e["art"] == "wechsel":
            p = e["nach"] + 1
            print(f"    TOP {p}: Soll {mmss(soll[p]) if p in soll else '– (nicht im Ausschnitt)'} → Ist {mmss(e['zeit'])}")
    if "--nur-kontrolle" in sys.argv:
        return

    saetze, bereiche = zusammensetzen(True)
    coach = await lauf(saetze)
    hinweise = fremd_hinweise(coach)
    neu = [e for e in coach.protokoll if e["art"] == "thema" and e["zuordnung"] == "neu"]
    print("Einschub-Lauf:")
    for a, b, d in bereiche:
        h = [t for t in hinweise if a <= t <= b + 30]
        n = [e for e in neu if a <= e["zeit"] <= b + 15]
        print(f"  Einschub {mmss(a)}–{mmss(b)} ({d:.0f} s): "
              + (f"erkannt nach {h[0] - a:.0f} s" if h else "NICHT erkannt")
              + f", als fremd eingestuft: {len(n)} Abschnitt(e)")
    fehl = [t for t in hinweise if not any(a <= t <= b + 30 for a, b, _ in bereiche)]
    print(f"  Fehlalarme außerhalb der Einschübe: {len(fehl)}" + (f" ({', '.join(mmss(t) for t in fehl)})" if fehl else ""))
    for h in coach.meeting.hinweise:
        if h.art == "fokus":
            print(f"    {mmss(h.zeit)} {h.text[:110]}")


if __name__ == "__main__":
    asyncio.run(main())
