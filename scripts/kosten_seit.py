r"""Kosten laut logs/nutzung.jsonl seit einem Zeitpunkt (für Testläufe mit Budget).

    .venv\Scripts\python scripts\kosten_seit.py 2026-10-05T17:30:00
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

seit = sys.argv[1]
summe, je = 0.0, defaultdict(float)
for zeile in (Path(__file__).resolve().parent.parent / "logs" / "nutzung.jsonl").open(encoding="utf-8"):
    try:
        e = json.loads(zeile)
    except ValueError:
        continue  # parallele Läufe können Zeilen vermischen
    if e.get("zeit", "") >= seit:
        summe += e.get("usd") or 0
        je[e["art"]] += e.get("usd") or 0
print(f"{summe:.3f} $ seit {seit}: " + ", ".join(f"{k} {v:.3f}" for k, v in sorted(je.items(), key=lambda x: -x[1])))
