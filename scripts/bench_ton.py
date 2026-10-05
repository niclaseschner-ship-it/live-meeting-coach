r"""Benchmark Regel 7 „Respektvoller Ton“ auf dem Text-Testset (testbibliothek/texte/ton.json).

    .venv\Scripts\python scripts\bench_ton.py

Die Sätze werden gemischt zu Abschnitten mit je 6 Sätzen zusammengefasst – wie im Betrieb – und mit
genau dem Aufruf der Themen-Zuordnung (ton=True) bewertet. Kosten: ~20 kurze Aufrufe, unter 1 Cent.
Erwartet: Hinweis bei „kraftausdruck“ und „angriff“, kein Hinweis bei neutral, sachkritik, zitat.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import themen  # noqa: E402
from coach.config import EINST  # noqa: E402
from coach.pipeline import Coach, nutzung_loggen  # noqa: E402
from coach.zustand import Agendapunkt, Meeting  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
GRUPPE = 6


def woerter(t: str) -> set[str]:
    return set(re.findall(r"\w+", t.lower()))


async def main() -> None:
    saetze = json.loads((WURZEL / "testbibliothek" / "texte" / "ton.json").read_text(encoding="utf-8"))["saetze"]
    random.Random(7).shuffle(saetze)
    client = Coach()._client
    if client is None:
        sys.exit("kein OPENAI_API_KEY")
    m = Meeting(titel="Teambesprechung", ziel="Projektstand und nächste Schritte",
                agenda=[Agendapunkt("Projektstand"), Agendapunkt("Nächste Schritte")])
    for s in saetze:
        s["vorhersage"] = None
    for i in range(0, len(saetze), GRUPPE):
        gruppe = saetze[i:i + GRUPPE]
        text = "\n".join(f"Person {j % 3 + 1}: {s['text']}" for j, s in enumerate(gruppe))
        erg, nutzung = await themen.zuordnen(client, EINST.analyse_modell, m, text, EINST.analyse_aufwand, ton=True)
        nutzung_loggen({"art": "bench-ton", "modell": EINST.analyse_modell, **nutzung})
        for t in erg["ton"]:
            z = woerter(t["zitat"])
            beste = max(gruppe, key=lambda s: len(z & woerter(s["text"])) / (len(z) or 1))
            if z & woerter(beste["text"]) and beste["vorhersage"] != "angriff":
                beste["vorhersage"] = t["art"]

    def auswerten(auswahl: list[dict], name: str) -> None:
        soll = [s["klasse"] in ("kraftausdruck", "angriff") for s in auswahl]
        ist = [s["vorhersage"] is not None for s in auswahl]
        rp = sum(a and b for a, b in zip(soll, ist))
        print(f"{name} ({len(auswahl)} Sätze): erkannt {rp}/{sum(soll)} · Fehlalarme "
              f"{sum(b and not a for a, b in zip(soll, ist))}/{len(soll) - sum(soll)}")

    klar = [s for s in saetze if not s.get("grenzfall")]
    auswerten(klar, "Eindeutige Sätze")
    auswerten([s for s in saetze if s.get("grenzfall")], "Grenzfälle")
    print("\nJe Klasse (eindeutig): Anteil mit Hinweis")
    for k in ("neutral", "sachkritik", "zitat", "kraftausdruck", "angriff"):
        a = [s for s in klar if s["klasse"] == k]
        print(f"  {k:13} {sum(s['vorhersage'] is not None for s in a)}/{len(a)}")
    print("\nAbweichungen:")
    for s in saetze:
        soll = s["klasse"] in ("kraftausdruck", "angriff")
        if soll != (s["vorhersage"] is not None):
            print(f"  {'(Grenzfall) ' if s.get('grenzfall') else ''}{s['klasse']:13} → "
                  f"{s['vorhersage'] or 'kein Hinweis':13} {s['text'][:80]}")


if __name__ == "__main__":
    asyncio.run(main())
