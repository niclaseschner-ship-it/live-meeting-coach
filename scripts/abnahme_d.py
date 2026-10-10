#!/usr/bin/env python3
"""Stufe D (Ticket #62): die Handy-Checkliste aus docs/abnahme_manuell.md im Terminal abhaken.

Liest die Tabelle unter `<!-- d-checkliste … -->`, fragt jede Zeile ab (j = erfüllt, n = nicht erfüllt, ü = übersprungen;
danach optional eine Notiz) und schreibt `<Hauptrepo>/logs/pipeline/<sha>/d.json`. `"ok": true` nur, wenn jede Zeile
außer den als „Optional“ markierten mit j beantwortet wurde. Das Gate in deploy/deploy.sh liest genau dieses Feld.

    scripts/pipeline.sh d            (ruft dieses Skript)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
DOKU = WURZEL / "docs" / "abnahme_manuell.md"
STAGING = "https://nestor-staging.niclas-eschner.workers.dev"


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(WURZEL), *args], capture_output=True, text=True).stdout.strip()


def punkte(text: str) -> list[dict]:
    """Zeilen der Checkliste: Minute, Schritt, Prüfung – aus der ersten Tabelle nach dem Marker."""
    teil = text.split("<!-- d-checkliste", 1)[1]
    aus = []
    for zeile in teil.splitlines()[1:]:
        if not zeile.startswith("|"):
            if aus:
                break
            continue
        zellen = [z.strip() for z in zeile.strip().strip("|").split("|")]
        if len(zellen) < 3 or zellen[0] in ("Min", "") or set(zellen[0]) <= {"-"}:
            continue
        aus.append({"min": zellen[0], "schritt": zellen[1], "pruefung": zellen[2],
                    "optional": zellen[1].lower().startswith("optional")})
    return aus


def frage(text: str, erlaubt: tuple[str, ...]) -> str:
    while True:
        antwort = input(text).strip().lower()
        if antwort in erlaubt:
            return antwort
        print(f"  bitte {'/'.join(erlaubt)}")


def main() -> int:
    if not sys.stdin.isatty():
        print("Stufe D fragt im Terminal – bitte interaktiv aufrufen.", file=sys.stderr)
        return 2
    sha = git("rev-parse", "HEAD")
    haupt = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    try:
        with urllib.request.urlopen(STAGING + "/version", timeout=10) as a:
            staging_sha = json.load(a).get("git_sha")
    except Exception:  # noqa: BLE001
        staging_sha = None
    print(f"Stufe D für {sha[:12]} – Staging trägt {staging_sha[:12] if staging_sha else '?'}")
    if staging_sha != sha:
        print("⚠️  Staging trägt nicht diesen Stand. Erst 'deploy/deploy.sh --staging', sonst gilt die Abnahme für einen\n"
              "   anderen Code. Trotzdem fortfahren?")
        if frage("   [j/n] ", ("j", "n")) != "j":
            return 1
    geraet = input("Gerät(e), z. B. „iPhone 15, iOS 18.6, Safari“: ").strip()
    ergebnis = []
    for i, p in enumerate(punkte(DOKU.read_text(encoding="utf-8")), 1):
        print(f"\n{i}. [{p['min']}] {p['schritt']}\n   Prüfung: {p['pruefung']}")
        a = frage("   erfüllt? [j/n/ü] ", ("j", "n", "ü", "u"))
        notiz = input("   Notiz (Enter = keine): ").strip()
        ergebnis.append({**p, "antwort": {"u": "ü"}.get(a, a), "notiz": notiz})
    pflicht_ok = all(e["antwort"] == "j" for e in ergebnis if not e["optional"])
    daten = {"sha": sha, "staging_sha": staging_sha, "geraet": geraet,
             "zeit": datetime.now().astimezone().isoformat(timespec="seconds"), "ok": pflicht_ok and staging_sha == sha,
             "punkte": ergebnis}
    ziel = haupt / "logs" / "pipeline" / sha / "d.json"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    offen = [e for e in ergebnis if e["antwort"] != "j" and not e["optional"]]
    print(f"\n{'Stufe D abgehakt' if daten['ok'] else 'Stufe D NICHT ok'} · {ziel}")
    for e in offen:
        print(f"  – {e['pruefung']}: {e['antwort']} {e['notiz']}")
    return 0 if daten["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
