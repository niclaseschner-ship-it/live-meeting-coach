"""Themen-Zuordnung auf einem gespeicherten Transkript neu durchspielen (ohne Audio) – für Modellvergleiche.

    .venv\\Scripts\\python scripts\\themen_vergleich.py logs\\bericht_<name>.json <einrichtung.json> <modell> <aufwand>

Ausgabe: Agenda-Wechsel und Fokus-Hinweise mit Zeitpunkt.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["LMC_ANALYSE"], os.environ["LMC_ANALYSE_AUFWAND"] = sys.argv[3], sys.argv[4]
from coach.analyse import mmss  # noqa: E402
from coach.pipeline import Coach  # noqa: E402
from coach.zustand import Segment  # noqa: E402


async def main() -> None:
    bericht = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    einrichtung = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    coach = Coach()
    coach._einrichten(einrichtung)
    coach.auto_wechsel = True
    coach.meeting.starten(virtuell=True)
    for s in bericht["transkript"]:
        coach.meeting.virtuelle_zeit = s["ende"]
        await coach.satz(Segment(s["sprecher"], s["text"], s["start"], s["ende"]))
        await asyncio.sleep(0)  # gestartete Zuordnung laufen lassen …
        async with coach._themen_sperre:  # … und auf sie warten, damit die Zeitpunkte stimmen
            pass
    await coach._abschnitt_auswerten()
    for e in coach.protokoll:
        if e["art"] == "wechsel":
            print(f"  {mmss(e['zeit'])} WECHSEL {e['von'] + 1} → {e['nach'] + 1}")
        elif e["art"] == "thema" and e["zuordnung"] != "aktiv":
            p = "-" if e["punkt"] is None else e["punkt"] + 1
            print(f"  {mmss(e['zeit'])}   {e['zuordnung']:8} {p} ({e['konfidenz']:.2f}) {e['begruendung'][:70]}")
    for h in coach.meeting.hinweise:
        if h.art == "fokus":
            print(f"  {mmss(h.zeit)} HINWEIS {h.text[:90]}")


asyncio.run(main())
