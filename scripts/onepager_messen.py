r"""Live-Bild auf einem gespeicherten Transkript erzeugen und die Zeit je Schritt messen.

    .venv\Scripts\python scripts\onepager_messen.py logs\bericht_<name>.json <einrichtung.json> <bis_sekunden> <ausgabeordner> [<ordner des letzten bildes>]

Mit letztem Bild wird fortgeschrieben (wie im Dashboard ab dem zweiten Bild).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import onepager  # noqa: E402
from coach.pipeline import Coach  # noqa: E402
from coach.zustand import Segment  # noqa: E402


async def main() -> None:
    bericht = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    einrichtung = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    bis, ziel = float(sys.argv[3]), Path(sys.argv[4])
    vorher = Path(sys.argv[5]) if len(sys.argv) > 5 else None
    coach = Coach()
    coach._einrichten(einrichtung)
    m = coach.meeting
    m.starten(virtuell=True)
    m.virtuelle_zeit = bis
    m.transkript = [Segment(s["sprecher"], s["text"], s["start"], s["ende"])
                    for s in bericht["transkript"] if s["start"] < bis]
    # Agendastand aus dem Protokoll des Berichts nachstellen
    for e in bericht.get("protokoll", []):
        if e.get("art") == "wechsel" and e["zeit"] <= bis:
            m.punkt_wechseln(e["nach"])
    alt = None
    if vorher:
        alt = {"analyse": (vorher / "analyse.md").read_text(encoding="utf-8"),
               "svg": (vorher / "grafik.svg").read_text(encoding="utf-8")}
    t0 = time.monotonic()
    erg = await onepager.erzeugen(m, alt)
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "grafik.svg").write_text(erg["svg"], encoding="utf-8")
    (ziel / "analyse.md").write_text(erg["analyse"], encoding="utf-8")
    messung = {"gesamt_s": round(time.monotonic() - t0, 1), "schritte": erg["messung"]}
    (ziel / "messung.json").write_text(json.dumps(messung, indent=1), encoding="utf-8")
    print(json.dumps(messung, indent=1))


asyncio.run(main())
