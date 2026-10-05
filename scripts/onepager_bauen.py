"""One-Pager aus einem Testlauf-Bericht erzeugen (Strukturanalyse + Zeichnung durch Claude).

    .venv\\Scripts\\python scripts\\onepager_bauen.py logs\\bericht_<name>.json <einrichtung.json>

Ergebnis: logs/onepager/<name>/analyse.md, grafik.svg, dauer.txt
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import onepager  # noqa: E402
from coach.config import WURZEL  # noqa: E402
from coach.zustand import Agendapunkt, Meeting, Segment  # noqa: E402


def meeting_aus_bericht(bericht: dict, einrichtung: dict) -> Meeting:
    m = Meeting(titel=einrichtung.get("titel", ""), ziel=einrichtung.get("ziel", ""),
                agenda=[Agendapunkt(p["titel"], p.get("ziel", ""), p.get("minuten", 10)) for p in einrichtung["agenda"]],
                teilnehmende=einrichtung.get("teilnehmende", []))
    m.starten(virtuell=True)
    m.transkript = [Segment(s["sprecher"], s["text"], s["start"], s["ende"]) for s in bericht["transkript"]]
    m.virtuelle_zeit = m.transkript[-1].ende if m.transkript else 0
    for e in bericht["protokoll"]:  # Agenda-Stand am Ende wie im Lauf
        if e["art"] == "wechsel":
            m.punkt_wechseln(e["nach"])
    return m


async def main() -> None:
    bericht = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    einrichtung = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    name = Path(sys.argv[1]).stem.removeprefix("bericht_")
    ziel = WURZEL / "logs" / "onepager" / name
    ziel.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    erg = await onepager.erzeugen(meeting_aus_bericht(bericht, einrichtung))
    (ziel / "analyse.md").write_text(erg["analyse"], encoding="utf-8")
    (ziel / "grafik.svg").write_text(erg["svg"], encoding="utf-8")
    (ziel / "dauer.txt").write_text(f"{time.monotonic() - t0:.0f} s\n", encoding="utf-8")
    print(f"{name}: fertig in {time.monotonic() - t0:.0f} s, SVG {len(erg['svg']) // 1024} KB → {ziel}")


asyncio.run(main())
