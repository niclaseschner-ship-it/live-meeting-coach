#!/usr/bin/env python3
"""Welche Stufen muss Stufe C (Staging, echte Anbieter) für einen Deploy geprüft haben – und braucht es Stufe D?

Ticket #62, Gate in deploy/deploy.sh. Grundlage ist der Git-Diff zwischen dem zuletzt ausgerollten Stand (jüngster
`deploy-*`-Tag, oder `--seit REF`) und HEAD. Einfach gehalten, im Zweifel streng:

- nur Basis:   coach/mistral.py, coach/knopfdruck.py, coach/api_knopfdruck.py (Mistral-Client, Modus Knopfdruck)
- nur Premium: coach/gespraech.py, coach/bild_gpt.py (Realtime-Gespräch, Live-Bild – gibt es nur bei OpenAI)
- ohne Laufzeitwirkung: docs/, tests/, scripts/, deploy/, szenarien/, testbibliothek/, demo/, *.md, .gitignore,
  Worker-Tests (cloudflare/src/*.test.ts)
- alles andere (übriges coach/, static/, cloudflare/, Dockerfile, requirements*) → **beide**
- kein Vergleichsstand (noch nie über deploy.sh ausgerollt) → beide und Stufe D

Stufe D (Handy von Hand, docs/abnahme_manuell.md) ist zusätzlich nötig bei Änderungen an static/handy*, static/sw.js
und der Audio-Wiedergabe/-Aufnahme (static/basis.js, coach/stimmen.py, coach/stimmen/).

Ausgabe: eine Zeile JSON, z. B. {"stufen": ["basis", "premium"], "d": true, "basis": "deploy-20261010-1200", ...}

    scripts/betroffene_stufen.py [--seit REF]
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys

NUR_BASIS = ("coach/mistral.py", "coach/knopfdruck.py", "coach/api_knopfdruck.py")
NUR_PREMIUM = ("coach/gespraech.py", "coach/bild_gpt.py")
OHNE_WIRKUNG = ("docs/*", "tests/*", "scripts/*", "deploy/*", "szenarien/*", "testbibliothek/*", "demo/*", "*.md",
                ".gitignore", "LICENSE", "Nestor starten.cmd", "cloudflare/src/*.test.ts", "cloudflare/README.md")
FUER_D = ("static/handy*", "static/sw.js", "static/basis.js", "coach/stimmen.py", "coach/stimmen/*")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def einordnen(dateien: list[str] | None) -> dict:
    """dateien=None heißt: kein Vergleichsstand – dann alles streng."""
    if dateien is None:
        return {"stufen": ["basis", "premium"], "d": True, "grund": "kein Vergleichsstand (noch kein deploy-*-Tag)"}
    stufen: set[str] = set()
    gruende: dict[str, list[str]] = {"basis": [], "premium": [], "beide": [], "d": []}
    passt = lambda pfad, muster: any(fnmatch.fnmatch(pfad, m) for m in muster)  # noqa: E731
    for pfad in dateien:
        if passt(pfad, FUER_D):
            gruende["d"].append(pfad)
        if pfad in NUR_BASIS:
            stufen.add("basis")
            gruende["basis"].append(pfad)
        elif pfad in NUR_PREMIUM:
            stufen.add("premium")
            gruende["premium"].append(pfad)
        elif passt(pfad, OHNE_WIRKUNG) and pfad != "scripts/modelle_laden.py":  # das eine Skript im Image
            continue
        else:
            stufen |= {"basis", "premium"}
            gruende["beide"].append(pfad)
    return {"stufen": sorted(stufen), "d": bool(gruende["d"]),
            "grund": {k: v[:8] for k, v in gruende.items() if v} or "nur Dateien ohne Laufzeitwirkung"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seit", help="Vergleichsstand (Tag/Commit); Standard: jüngster deploy-*-Tag vor HEAD")
    args = p.parse_args()
    basis = args.seit
    if not basis:
        try:
            basis = _git("describe", "--tags", "--match", "deploy-*", "--abbrev=0", "HEAD")
        except subprocess.CalledProcessError:
            basis = None
    dateien = _git("diff", "--name-only", f"{basis}..HEAD").splitlines() if basis else None
    ergebnis = einordnen(dateien)
    ergebnis["basis"] = basis
    print(json.dumps(ergebnis, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
