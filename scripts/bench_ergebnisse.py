r"""Benchmark Regel 10 „Ergebnisse festhalten“ auf dem Stadtrat-Transkript (vorhandener Bericht, keine Transkription).

    .venv\Scripts\python scripts\bench_ergebnisse.py

Das Transkript (logs/bericht_stadtrat_fremd.json, ohne die zwei gemischten Äußerungen des Audio-Einschnitts)
wird an den Kapitelmarken in Agendapunkte geteilt; je Punkt ein Aufruf (7 Aufrufe, unter 1 Cent).
Referenz: Abstimmungsergebnisse aus testbibliothek/proben/stadtrat/probe.json („beschluesse“).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import ergebnisse  # noqa: E402
from coach.config import EINST  # noqa: E402
from coach.pipeline import Coach, nutzung_loggen  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
GEMISCHT = {7, 8}


async def main() -> None:
    probe = json.loads((WURZEL / "testbibliothek" / "proben" / "stadtrat" / "probe.json").read_text(encoding="utf-8"))
    agenda = probe["meeting"]["agenda"]
    ref = probe["referenz"]
    beginne = [r["von"] + (40 if r["von"] >= 250 else 0) for r in ref["agenda"]] + [1e9]
    saetze = [s for i, s in enumerate(json.loads((WURZEL / "logs" / "bericht_stadtrat_fremd.json")
                                                 .read_text(encoding="utf-8"))["transkript"]) if i not in GEMISCHT]
    client = Coach()._client
    for k, r in enumerate(ref["agenda"]):
        p = agenda[r["punkt"] - 1]
        text = "\n".join(f"{s['sprecher']}: {s['text']}" for s in saetze if beginne[k] <= s["start"] < beginne[k + 1])
        if not text:
            continue
        erg, nutzung = await ergebnisse.pruefen(client, EINST.analyse_modell, p["titel"], p["ziel"], text,
                                                EINST.analyse_aufwand)
        nutzung_loggen({"art": "bench-ergebnisse", "modell": EINST.analyse_modell, **nutzung})
        soll = ref["beschluesse"].get(str(r["punkt"]), "kein Ergebnis im Ausschnitt")
        print(f"TOP {r['punkt']}  Soll: {soll}")
        print(f"        Ist:  {erg['ergebnis'] or '– kein Ergebnis –'}")
        for e in erg["entscheidungen"]:
            print(f"              • {e['was']}: {e['ergebnis']}")
        for h in ergebnisse.hinweise(p["titel"], erg):
            print(f"        Hinweis: {h}")


if __name__ == "__main__":
    asyncio.run(main())
