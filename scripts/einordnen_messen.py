r"""Nachfrage-Fenster messen (Ticket #27, Nachtrag C): wird der erste Satz nach Nestors Bogen richtig eingeordnet,
und wie schnell? Drei Stufen wie live (coach/assistent.py: nachfrage_einordnen) – zwei Regeln, sonst der
Klassifikator (gpt-5.4-mini). Kostet ~1 Cent je Durchgang.

    ~/.venvs/lmc/bin/python scripts/einordnen_messen.py [--aufwand low,minimal,none]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ANTWORT = ("Hier ist sie. Zwei Aufgaben haben noch niemanden, der sich kümmert – das Runbook und die Kundenmail. "
           "Schaut kurz drauf.")
NAMEN = ["Anna", "Tarek", "Sofie", "Jonas"]
# (Satz, erwartet: True = Nestor antwortet)
FAELLE = [
    ("Anna, das machst du doch, oder?", False),
    ("Ja, passt.", False),
    ("Und bis wann?", True),
    ("Was meinst du mit Wartungsfenster?", True),
    ("Die Migration lief ja schon am Freitag schief.", False),
    ("Danke dir.", False),
    ("Kannst du das Runbook Sofie zuordnen?", True),
    ("Das Runbook übernehme ich, das ist kein Problem.", False),
    ("Welche Kundenmail ist da gemeint?", True),
    ("Okay, dann machen wir weiter mit den Maßnahmen.", False),
    ("Und was ist mit dem Monitoring?", True),
    ("Das übernimmst du, oder Tarek?", False),
    ("Warum steht da noch nichts zum SLA?", True),
    ("Ich finde, wir sollten das Thema vertagen.", False),
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aufwand", default="low")
    args = ap.parse_args()
    from openai import AsyncOpenAI

    from coach import bogen as BG
    from coach.config import EINST

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    for aufwand in args.aufwand.split(","):
        object.__setattr__(EINST, "einordnen_aufwand", "" if aufwand == "standard" else aufwand)
        richtig, zeiten, tokens = 0, [], [0, 0]
        for satz, erwartet in FAELLE:
            t0 = time.monotonic()
            if BG.jemand_anderes(satz, NAMEN):
                ergebnis, weg = "nicht_an_nestor", "Regel"
            elif BG.klar_an_nestor(satz, NAMEN):
                ergebnis, weg = "frage_an_nestor", "Regel"
            else:
                ergebnis, nutzung = await BG.einordnen(client, satz, ANTWORT)
                weg = "Modell"
                zeiten.append(time.monotonic() - t0)
                tokens[0] += nutzung.get("tokens_rein") or 0
                tokens[1] += nutzung.get("tokens_raus") or 0
            ok = (ergebnis == "frage_an_nestor") == erwartet
            richtig += ok
            print(f"  [{aufwand}] {'✅' if ok else '❌'} {weg:6} {ergebnis:24} {satz}"
                  + (f"  ({zeiten[-1]:.2f} s)" if weg == "Modell" else ""))
        zeiten.sort()
        print(f"{aufwand}: {richtig}/{len(FAELLE)} richtig; Modell {len(zeiten)}× – Median {zeiten[len(zeiten) // 2]:.2f} s, "
              f"längste {zeiten[-1]:.2f} s; {tokens[0]} Tokens rein, {tokens[1]} raus")


if __name__ == "__main__":
    asyncio.run(main())
