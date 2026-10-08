r"""Nachfrage-Fenster messen (Ticket #27, Nachtrag C): wird der erste Satz nach Nestors Bogen richtig eingeordnet,
und wie schnell? Stufen wie live (coach/assistent.py: nachfrage_einordnen) – drei Regeln (seit #28 auch „knüpft an
die Runde an“), sonst der Klassifikator (gpt-5.4-mini). Kostet ~1 Cent je Durchgang.

    ~/.venvs/lmc/bin/python scripts/einordnen_messen.py [--aufwand low,minimal,none] [--wiederholen 3]

Ticket #28: dazu die Sätze aus dem Premium-Abendlauf 08.10. mit ihrer echten Frage und Antwort – „Heißt das, selbst ein
schneller Application Rollback hätte uns nicht gerettet“ (an die Kollegen, Nestor antwortete) muss still bleiben,
„Und reicht das noch für alle Punkte?“ und „Und wer übernimmt das?“ müssen antworten.
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
KARTE = ("Was fehlt?", ANTWORT, ["Anna: Wir haben jetzt die Maßnahmen gesammelt.", "Tarek: Nestor, was fehlt noch?"])
# Ticket #28: (Satz, erwartet, Frage an Nestor, seine Antwort, die Sätze davor) – wörtlich aus logs/cloudtest/abend_premium
URSACHE = ["Jonas: Gut, die Zeitlinie ist damit belastbar.", "Person ?: Kommen wir zur Ursache:",
           "Jonas: Wir müssen klären, warum die Migration den Ausfall ausgelöst hat und weshalb kein vollständiger "
           "Rollback möglich war."]
ZEIT_1 = ("Wie viel Zeit haben wir noch?", "Ihr habt für diesen Punkt noch knapp zwei Minuten.",
          URSACHE + ["Person 2: Wie viel Zeit haben wir noch, Nestor?"])
ZEIT_2 = ("Und reicht das noch für alle Punkte?", "Ihr habt für alles zusammen noch knapp drei Minuten.",
          URSACHE[1:] + ["Person 2: Wie viel Zeit haben wir noch, Nestor?", "Person 2: Und reicht das noch für alle Punkte?"])
BESCHLUSS = ("Was haben wir zu Punkt eins beschlossen?",
             "Zu Punkt eins habt ihr beschlossen, die Migration künftig nur mit getestetem Down-Pfad zu fahren.",
             ["Person 2: Ich frage wegen des Postmortems: Wir sollten nicht so formulieren, als sei nur das "
              "Kubernetes-Rollback zu spät gekommen", "Person ?: Nestor,", "Person 2: Was haben wir zu Punkt eins beschlossen?"])
FAELLE_28 = [
    ("Heißt das, selbst ein schneller Application Rollback hätte uns nicht gerettet", False, *ZEIT_2),
    ("Heißt das, selbst ein schneller Application Rollback hätte uns nicht gerettet?", False, *ZEIT_2),
    ("Denn das alte Image konnte ja ebenfalls nicht sinnvoll mit den blockierten Tabellen arbeiten.", False, *ZEIT_2),
    ("Und reicht das noch für alle Punkte?", True, *ZEIT_1),
    # ähnliche Gruppenfragen in der Wir-/Uns-Sicht (Leitlinie des Koordinators zu #28) – still
    ("Heißt das, wir hätten den Down-Pfad vorher testen müssen?", False, *ZEIT_2),
    ("Hätte uns ein Alarm auf die Lock-Wartezeit nicht früher gewarnt?", False, *ZEIT_2),
    ("Sollten wir dann nicht lieber das Gegen-Skript ins Repository legen?", False, *ZEIT_2),
    ("Heißt das, das Deployment-Rollback war für uns gar nicht das Problem?", False, *ZEIT_2),
    ("Und wer übernimmt das?", True, *BESCHLUSS),
    ("Und wer übernimmt das", True, *BESCHLUSS),
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aufwand", default="none")
    ap.add_argument("--wiederholen", type=int, default=1, help="jeden Modell-Fall so oft (Streuung)")
    args = ap.parse_args()
    from openai import AsyncOpenAI

    from coach import bogen as BG
    from coach.config import EINST

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    for aufwand in args.aufwand.split(","):
        object.__setattr__(EINST, "einordnen_aufwand", "" if aufwand == "standard" else aufwand)
        richtig, zeiten, tokens = 0, [], [0, 0]
        faelle = [(s, e, *KARTE) for s, e in FAELLE] + FAELLE_28
        gesamt = richtig_28 = gesamt_28 = 0
        for satz, erwartet, frage, antwort, vorher in faelle:
            for _ in range(args.wiederholen):
                t0 = time.monotonic()
                if BG.jemand_anderes(satz, NAMEN):
                    ergebnis, weg = "nicht_an_nestor", "Regel"
                elif BG.klar_an_nestor(satz, NAMEN):
                    ergebnis, weg = "frage_an_nestor", "Regel"
                elif BG.knuepft_an_runde(satz, vorher, frage, antwort):
                    ergebnis, weg = "nicht_an_nestor", "Regel"
                else:
                    ergebnis, nutzung = await BG.einordnen(client, satz, antwort, frage, vorher)
                    weg = "Modell"
                    zeiten.append(time.monotonic() - t0)
                    tokens[0] += nutzung.get("tokens_rein") or 0
                    tokens[1] += nutzung.get("tokens_raus") or 0
                ok = (ergebnis == "frage_an_nestor") == erwartet
                richtig += ok
                gesamt += 1
                if (satz, erwartet, frage, antwort, vorher) in FAELLE_28:
                    richtig_28 += ok
                    gesamt_28 += 1
                print(f"  [{aufwand}] {'✅' if ok else '❌'} {weg:6} {ergebnis:24} {satz}"
                      + (f"  ({zeiten[-1]:.2f} s)" if weg == "Modell" else ""))
                if weg == "Regel":
                    break
        zeiten.sort()
        print(f"{aufwand}: {richtig}/{gesamt} richtig (Ticket #28: {richtig_28}/{gesamt_28}); Modell {len(zeiten)}× – Median {zeiten[len(zeiten) // 2]:.2f} s, "
              f"längste {zeiten[-1]:.2f} s; {tokens[0]} Tokens rein, {tokens[1]} raus")


if __name__ == "__main__":
    asyncio.run(main())
