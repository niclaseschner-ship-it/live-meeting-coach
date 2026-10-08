r"""Antwortbögen messen (Ticket #27): wie lange dauert ein Bogen – Bestätigung, Karte, Satz, Ende – in Premium und
Basis, und bleibt „Zusammenfassen“ auch nach 60 Minuten Meeting unter 15 s?

Das Meeting entsteht aus den vertonten Drehbüchern der Testbibliothek (~/arbeit/lmc-vertonung: Vereinsrunde,
Team-Weekly, Kontrollrunde, dazu das Incident-Review aus testbibliothek/cloudtest) – ~7 000 Wörter, auf die
gewünschte Länge gestreckt bzw. wiederholt, drei Agendapunkte à 20 min. Es läuft im Prozess mit den echten
KI-Diensten der Stufe: beim Punktwechsel die stille Zusammenfassung des Abschnitts (wie live), am Ende die Bögen
nacheinander, jeweils wie per Knopf ausgelöst (die Frage wie per Zuruf/Sprechtaste). Gemessen ab dem Auslöser:
erster Ton (Bestätigung aus dem Floskel-Vorrat), Karte im Verlauf, erster Ton des Satzes, Ende des Bogens.

    ~/.venvs/lmc/bin/python scripts/bogen_messen.py --stufe premium [--minuten 60] [--vergleich]

Schlüssel aus der Umgebung (OPENAI_API_KEY bzw. MISTRAL_API_KEY). `--vergleich` misst zusätzlich „Zusammenfassen“,
wenn der ganze Text noch unerkannt ist und nacheinander ausgewertet wird (wie vor Ticket #27: ständige Erkennung
gab es nicht mehr, aber ohne Abschnitte) – nur zur Einordnung, kostet ~2 Cent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
QUELLEN = [Path.home() / "arbeit" / "lmc-vertonung" / n / f"{n}.json" for n in ("vereinsrunde", "teamweekly",
                                                                                   "kontrollrunde")]
QUELLEN.append(WURZEL / "testbibliothek" / "cloudtest" / "drehbuch_grenzfaelle.json")
WOERTER_JE_MINUTE = 140
BOEGEN = ["zusammenfassen", "stand", "fehlt", "festgehalten", "ueberblick", "frage"]
FRAGE = "Wie viel Zeit haben wir noch für den aktuellen Punkt?"


def transkript(minuten: float):
    from coach.zustand import Segment

    aeusserungen = []
    for q in QUELLEN:
        if q.exists():
            aeusserungen += json.loads(q.read_text(encoding="utf-8"))["aeusserungen"]
    woerter = sum(len(a["text"].split()) for a in aeusserungen)
    tempo = max(WOERTER_JE_MINUTE, woerter / minuten)  # bei mehr Text etwas schneller sprechen, sonst wiederholen
    aus, t, i = [], 5.0, 0
    while t < minuten * 60 - 5:
        a = aeusserungen[i % len(aeusserungen)]
        i += 1
        dauer = len(a["text"].split()) / tempo * 60
        aus.append(Segment(f"Person {a['person'] % 4 + 1}", a["text"], t, t + dauer))
        t += dauer + 0.8
    return aus, woerter


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stufe", choices=["premium", "basis"], required=True)
    ap.add_argument("--minuten", type=float, default=60.0)
    ap.add_argument("--vergleich", action="store_true")
    ap.add_argument("--ausgabe", default=None)
    ap.add_argument("--boegen", default=",".join(BOEGEN), help="Komma-Liste, z. B. frage,stand")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    from coach import bogen as BG
    from coach.config import EINST
    from coach.pipeline import Coach, KOSTEN

    c = Coach()
    c.stufe_setzen(args.stufe)
    if c._client is None:
        raise SystemExit("Kein Schlüssel für diese Stufe in der Umgebung.")
    drittel = args.minuten / 3
    c._einrichten({"titel": "Vereins- und Teamrunde", "ziel": "Planung für das nächste Quartal",
                   "agenda": [{"titel": t, "minuten": drittel} for t in ("Sommerfest", "Teamthemen", "Incident")],
                   "regel_ids": ["zeit", "ergebnisse"]})
    gesendet: list[tuple[float, dict]] = []

    async def senden(n):
        gesendet.append((time.monotonic(), {k: v for k, v in n.items() if k != "pcm"}))
    c.direkt.append(senden)
    KOSTEN.neues_meeting()
    t0 = time.monotonic()
    neu = await c.assistent.floskeln.vorbereiten(c._client)
    print(f"Floskeln: {neu} neu erzeugt in {time.monotonic() - t0:.1f} s ({EINST.stufe}, Stimme {EINST.stimme[:12]})")
    c.meeting.starten(virtuell=True)
    segmente, woerter = transkript(args.minuten)
    print(f"Meeting: {len(segmente)} Beiträge, {sum(len(s.text) for s in segmente)} Zeichen, "
          f"{args.minuten:.0f} min (Material {woerter} Wörter)")
    punkt = 0
    abschnitte = []
    for s in segmente:
        ziel = min(2, int(s.start // (drittel * 60)))
        if ziel != punkt:  # Punktwechsel: stille Zusammenfassung des Abschnitts (wie live, nur hier abgewartet)
            c.meeting.virtuelle_zeit = s.start
            t = time.monotonic()
            await c.artefakte.abschnitt_abschliessen(punkt, s.start, "punkt")
            abschnitte.append(round(time.monotonic() - t, 1))
            c.meeting.punkt_wechseln(ziel)
            punkt = ziel
        c.meeting.transkript.append(s)
        c.meeting.segmente.append(s)
    c.meeting.virtuelle_zeit = segmente[-1].ende + 1
    print(f"Abschnitts-Zusammenfassungen (still, im Hintergrund): {abschnitte} s; Artefakte {len(c.artefakte.liste)}")
    offen = [s for s in c.artefakte._neue_saetze()]
    print(f"Noch nicht ausgewertet beim ersten Bogen: {len(offen)} Beiträge, {sum(len(s.text) for s in offen)} Zeichen")

    ergebnisse = []
    for art in args.boegen.split(","):
        gesendet.clear()
        # die Meetinguhr steht hier (kein Ton): bis hinter Nestors letzte Wiedergabe vorstellen, wie im echten Meeting
        if c.assistent.sprechzeiten:
            c.meeting.virtuelle_zeit = max(c.meeting.virtuelle_zeit, c.assistent.sprechzeiten[-1][1] + 1)
        start = time.monotonic()
        if art == "frage":
            b = c.assistent.bogen_starten("frage", FRAGE, "stimme")
        else:
            b = c.assistent.bogen_starten(art, BG.NAMEN[art], "knopf")
        await b.task
        if c.assistent.gespraech is not None:
            await c.assistent.gespraech.schliessen()
        ton = [t - start for t, n in gesendet if n.get("typ") == "stimme"]
        satz_ton = [t - start for t, n in gesendet if n.get("typ") == "stimme" and not n.get("floskel")]
        texte = [n["text"] for _, n in gesendet if n.get("typ") == "nestor_text"]
        e = {"bogen": art, "erster_ton_s": round(ton[0], 2) if ton else None, "karte_s": b.zeiten.get("karte"),
             "satz_ton_s": round(satz_ton[0], 2) if satz_ton else None, "ende_s": b.zeiten.get("ende"),
             "gesagt": " ".join(texte)[:220]}
        ergebnisse.append(e)
        print(f"  {art:15} erster Ton {e['erster_ton_s']} s · Karte {e['karte_s']} s · Satz {e['satz_ton_s']} s · "
              f"Ende {e['ende_s']} s – „{e['gesagt']}“")
        await asyncio.sleep(0.5)
    vergleich = None
    if args.vergleich:
        c.artefakte.bis = -1.0  # alles unerkannt, nacheinander (ohne Abschnitte, ohne parallele Stücke)
        c.artefakte.liste.clear()
        t = time.monotonic()
        await c.artefakte.erkennen(parallel=False)
        vergleich = round(time.monotonic() - t, 1)
        print(f"Vergleich: Erkennung über das ganze Meeting nacheinander {vergleich} s")
    kosten = KOSTEN.stand(live_sekunden=0, live_modell=EINST.live_modell, meeting_sekunden=0,
                          geplant_minuten=args.minuten)
    print(f"Kosten dieses Laufs: {kosten['meeting']:.4f} $")
    if args.ausgabe:
        Path(args.ausgabe).write_text(json.dumps({"stufe": args.stufe, "minuten": args.minuten, "boegen": ergebnisse,
                                                  "abschnitte_s": abschnitte, "vergleich_s": vergleich,
                                                  "kosten_usd": kosten["meeting"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
