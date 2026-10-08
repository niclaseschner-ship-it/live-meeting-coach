r"""Nachlauf Regel 3 „Beim Thema bleiben“ auf einem Cloudtest-Mitschnitt (Ticket #24) – echte Zuordnungsaufrufe.

    OPENAI_API_KEY=… python scripts/nachlauf_fokus.py logs/cloudtest/cloud_premium_grenz2/ws.jsonl \
        [--abschweifung 331.9] [--bis 480]

Keine neue Transkription: Die Sätze kommen aus dem WS-Mitschnitt, jeder zu der Meetingzeit, zu der er im Dashboard
erschien. Dazwischen läuft der Takt jede halbe Sekunde, damit Abschnitte auch nach Zeit schließen. Die Meetinguhr
steht, während die Zuordnung läuft; deren gemessene Dauer wird auf die Hinweiszeit aufgeschlagen.

Die Sprachaktivität (VAD) wird aus den Satzzeiten nachgebildet.

Gemessen: Fokus-Hinweise (Zeit, Text), Verzug Abschweifungsbeginn → erster Hinweis, Hinweise nach der Rückkehr,
Zahl der Zuordnungen, Tokens und Kosten (hochgerechnet je Stunde Meeting).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("LMC_SCHLUESSEL_DATEI", "/nonexistent")  # Schlüssel nur aus der Umgebung
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import kosten, themen  # noqa: E402
from coach.analyse import mmss  # noqa: E402
from coach.config import EINST  # noqa: E402
from coach.pipeline import Coach  # noqa: E402
from coach.zustand import Segment  # noqa: E402


def laden(pfad: Path) -> tuple[dict, list[dict], float]:
    """Einrichtung, Sätze mit Ankunftszeit („da“) und Meetingdauer aus ws.jsonl."""
    einrichtung, gesehen, ende = None, {}, 0.0
    with pfad.open(encoding="utf-8") as f:
        for zeile in f:
            d = json.loads(zeile)
            z = d.get("daten")
            if d.get("richtung") != "empfangen" or not isinstance(z, dict) or "segmente" not in z:
                continue
            if einrichtung is None and z.get("laeuft"):
                einrichtung = {"titel": z["titel"], "ziel": z["ziel"], "teilnehmende": z["teilnehmende"],
                               "regel_ids": z["regel_ids"], "assistent": False,
                               "agenda": [{"titel": p["titel"], "ziel": p.get("ziel", ""), "minuten": p["minuten"]}
                                          for p in z["agenda"]]}
            if z.get("laeuft"):
                ende = max(ende, z.get("zeit", 0.0))
            for s in z["segmente"]:
                gesehen.setdefault((s["start"], s["text"]), {**s, "da": z["zeit"]})
    return einrichtung, sorted(gesehen.values(), key=lambda s: s["da"]), ende


async def lauf(einrichtung: dict, saetze: list[dict], bis: float) -> tuple[Coach, list[dict]]:
    aufrufe: list[dict] = []
    original = themen.zuordnen

    async def gemessen(client, modell, meeting, abschnitt, *a, **k):
        t0 = time.monotonic()
        erg, nutzung = await original(client, modell, meeting, abschnitt, *a, **k)
        aufrufe.append({"zeit": meeting.jetzt(), "latenz": time.monotonic() - t0, "modell": modell,
                        "zuordnung": erg["art"], **nutzung})
        return erg, nutzung

    themen.zuordnen = gemessen
    coach = Coach()
    coach._einrichten(einrichtung)
    coach.assistent.aktiv = False
    coach.meeting.starten(virtuell=True)
    warte = list(saetze)
    t = 0.0
    while t <= bis:
        coach.meeting.virtuelle_zeit = t
        if any(s["start"] <= t <= s["ende"] for s in saetze):
            coach.sprache_melden()  # wie die Sprachaktivität (VAD) im Hörstrom
        while warte and warte[0]["da"] <= t:
            s = warte.pop(0)
            await coach.satz(Segment(s["sprecher"], s["text"], s["start"], s["ende"]))
        coach.takt()
        await asyncio.sleep(0)
        async with coach._themen_sperre:  # laufende Zuordnung abwarten – die Uhr steht so lange
            pass
        await asyncio.sleep(0)
        t = round(t + 0.5, 1)
    themen.zuordnen = original
    return coach, aufrufe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ws", type=Path)
    ap.add_argument("--abschweifung", type=float, default=331.9, help="Beginn der Abschweifung (Meetinguhr)")
    ap.add_argument("--rueckkehr", type=float, default=363.4, help="Ende der Rückkehr-Ansage (Meetinguhr)")
    ap.add_argument("--bis", type=float, default=None, help="nur bis zu dieser Meetingzeit abspielen")
    args = ap.parse_args()
    einrichtung, saetze, ende = laden(args.ws)
    bis = args.bis or ende
    coach, aufrufe = asyncio.run(lauf(einrichtung, saetze, bis))

    latenz = {round(a["zeit"], 1): a["latenz"] for a in aufrufe}
    print(f"Modell {EINST.zuordnung_modell or EINST.analyse_modell}, abgespielt bis {mmss(bis)}")
    print("Fokus-Hinweise (Zeit + Dauer der Zuordnung):")
    fokus = []
    for h in coach.meeting.hinweise:
        if h.art == "fokus":
            t = h.zeit + latenz.get(round(h.zeit, 1), 0.0)
            fokus.append((t, h.text))
            print(f"  {mmss(t)} ({t:.1f}s) {h.text[:100]}")
    a, r = args.abschweifung, args.rueckkehr
    erster = next((t for t, _ in fokus if a - 5 <= t <= a + 90), None)
    print(f"Verzug Abschweifung ({a:.1f}s) → Hinweis: " + (f"{erster - a:.1f} s" if erster else "kein Hinweis"))
    nach = [t for t, text in fokus if r < t <= r + 60 and text.startswith("Bezug")]
    print(f"Hinweise nach der Rückkehr ({r:.1f}s, 60 s): {len(nach)}")
    print("Zuordnungen um die Abschweifung:")
    for e in coach.protokoll:
        if e["art"] == "thema" and a - 40 <= e["zeit"] <= r + 60:
            print(f"  {e['zeit']:6.1f}s {e['zuordnung']:8} {e['konfidenz']:.2f} {e['begruendung'][:80]}")
    rein = sum(x.get("tokens_rein", 0) for x in aufrufe)
    raus = sum(x.get("tokens_raus", 0) for x in aufrufe)
    usd = sum(kosten.dollar({"art": "themen", "modell": x["modell"], "tokens_rein": x.get("tokens_rein"),
                                   "tokens_raus": x.get("tokens_raus")}) for x in aufrufe)
    print(f"Zuordnungen: {len(aufrufe)}, Tokens rein {rein}, raus {raus}, Kosten {usd:.4f} $ "
          f"→ {usd / bis * 3600:.3f} $ je Stunde; Mittel {rein / max(1, len(aufrufe)):.0f}/"
          f"{raus / max(1, len(aufrufe)):.0f} Tokens je Aufruf, Latenz Median "
          f"{sorted(x['latenz'] for x in aufrufe)[len(aufrufe) // 2]:.1f} s" if aufrufe else "keine Zuordnungen")


if __name__ == "__main__":
    main()
