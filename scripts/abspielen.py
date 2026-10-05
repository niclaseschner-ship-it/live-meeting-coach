"""Aufnahme ohne Browser durch die Pipeline schicken und einen Testbericht schreiben.

    .venv\\Scripts\\python scripts\\abspielen.py <aufnahme.wav> [--tempo 1] [--bis SEKUNDEN]

Neben der WAV (24 kHz mono) liegt optional <aufnahme>.json mit Titel, Agenda, Teilnehmenden.
Der Bericht landet in logs/bericht_<name>.json und als Kurzfassung auf der Konsole.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.analyse import mmss  # noqa: E402
from coach.config import WURZEL  # noqa: E402
from coach.pipeline import Coach  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("aufnahme")
    ap.add_argument("--tempo", type=float, default=1.0)
    ap.add_argument("--bis", type=float, default=None, help="nur die ersten N Sekunden abspielen")
    ap.add_argument("--mit-bild", action="store_true", help="Abschlussbild zeichnen und Live-Bilder speichern")
    args = ap.parse_args()
    pfad = Path(args.aufnahme)

    if args.bis:  # gekürzte Kopie neben dem Original
        kurz = pfad.with_name(pfad.stem + f"_bis{int(args.bis)}.wav")
        with wave.open(str(pfad)) as r, wave.open(str(kurz), "wb") as w:
            w.setparams(r.getparams())
            w.writeframes(r.readframes(int(args.bis * r.getframerate())))
        if pfad.with_suffix(".json").is_file():
            kurz.with_suffix(".json").write_text(pfad.with_suffix(".json").read_text(encoding="utf-8"), encoding="utf-8")
        pfad = kurz

    coach = Coach()
    coach.onepager_am_ende = args.mit_bild  # sonst Bild separat mit scripts/onepager_bauen.py
    bilder_ordner = WURZEL / "logs" / "testlauf" / pfad.stem
    gespeichert: set[int] = set()
    zeitreihe: list[dict] = []
    erste_saetze: dict[float, float] = {}

    async def beobachten() -> None:
        m = coach.meeting
        t = round(m.jetzt())
        if not zeitreihe or zeitreihe[-1]["t"] != t:
            s = coach.schnappschuss()
            zeitreihe.append({"t": t, "punkt": m.aktiver_punkt, "klima": (s.get("dynamik") or {}).get("klima"),
                              "ampeln": {a["name"]: a["farbe"] for a in s["ampeln"]}})
        for seg in m.transkript:
            erste_saetze.setdefault(seg.start, time.monotonic())
        if args.mit_bild and coach.onepager_png and coach.onepager_version not in gespeichert:
            gespeichert.add(coach.onepager_version)
            bilder_ordner.mkdir(parents=True, exist_ok=True)
            (bilder_ordner / f"bild_{coach.onepager_version}_{int(m.jetzt())}s.png").write_bytes(coach.onepager_png)

    coach.beobachter.append(beobachten)
    t0 = time.monotonic()
    await coach.abspielen(pfad, tempo=args.tempo, auto_wechsel=True)
    dauer = time.monotonic() - t0
    # Nachlauf: Abschlussbild, Ergebnisprüfung, letzte Karten
    for _ in range(240):
        if not (coach._onepager_laeuft or coach._folie_laeuft):
            break
        await asyncio.sleep(1)
    await asyncio.sleep(5)
    await beobachten()
    m = coach.meeting

    bericht = {
        "aufnahme": pfad.name,
        "laufzeit_s": round(dauer, 1),
        "personen": sorted({s.sprecher for s in m.segmente}),
        "redeanteile": {k: round(v, 1) for k, v in m.redeanteile().items()},
        "transkript": [{"start": round(s.start, 1), "ende": round(s.ende, 1), "sprecher": s.sprecher, "text": s.text}
                       for s in m.transkript],
        "hinweise": [{"zeit": round(h.zeit, 1), "art": h.art, "text": h.text} for h in m.hinweise],
        "protokoll": coach.protokoll,
        "mischungen": [round(t, 1) for t in m.mischungen],
        "zeitreihe": zeitreihe,
        "onepager_version": coach.onepager_version,
        "karten": coach.karten,
        "folie": coach.folie,
        "ergebnisse": {str(i): e for i, e in m.ergebnisse.items()},
        "agenda": [{"titel": p.titel, "minuten": p.minuten, "genutzt": round(m.genutzt(i), 1)} for i, p in enumerate(m.agenda)],
        "kosten": coach.kosten_stand(),
        "dynamik": coach.dynamik(),
        "namen": coach.namen,
        "ueberlappungen": m.ueberlappungen,
        "tempo": args.tempo,
        "einstellungen": coach.einstellungen(),
        "fehler": coach.fehler,
    }
    ziel = WURZEL / "logs" / f"bericht_{pfad.stem}.json"
    ziel.parent.mkdir(exist_ok=True)
    ziel.write_text(json.dumps(bericht, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{pfad.name}: {dauer:.0f}s Laufzeit, {len(m.transkript)} Sätze, Personen: {', '.join(bericht['personen'])}")
    print("Redeanteile:", bericht["redeanteile"])
    for e in coach.protokoll:
        if e["art"] == "thema":
            punkt = "-" if e["punkt"] is None else e["punkt"] + 1
            print(f"  {mmss(e['zeit'])} Zuordnung {e['zuordnung']:8} Punkt {punkt} (aktiv {e['aktiv'] + 1}) – {e['begruendung'][:90]}")
        elif e["art"] == "wechsel":
            print(f"  {mmss(e['zeit'])} WECHSEL Punkt {e['von'] + 1} → {e['nach'] + 1}")
        elif e["art"] == "ueberlappung":
            print(f"  {mmss(e['zeit'])} Überlappung (Stimmen-Mischung)")
    for h in m.hinweise:
        print(f"  HINWEIS {mmss(h.zeit)} [{h.art}] {h.text[:110]}")
    print("Fehler:", coach.fehler)
    print("Bericht:", ziel)


asyncio.run(main())
