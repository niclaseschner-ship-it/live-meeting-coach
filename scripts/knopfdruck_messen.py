r"""Wartezeit und Kosten im Modus „Auf Knopfdruck“ messen (Ticket #7, Lastenheft 3 und 4.2).

    OPENAI_API_KEY=... LMC_KI=codex LMC_CODEX_BEFEHL=codex LMC_STIMME_AUS=1 \
        ~/.venvs/lmc/bin/python scripts/knopfdruck_messen.py [--aufnahme PFAD] [--tempo 10] [--bild] [--budget 0.60]

Spielt eine mindestens 61-minütige deutsche Besprechung im Modus „knopfdruck“ ab (wie `scripts/abspielen.py`,
nur ohne Dashboard) und drückt nach 15, 30 und 60 Minuten Meetingzeit nacheinander „Wo stehen wir?“, „Regeln
eingehalten?“ und „Protokoll“ – „Bild“ nur mit `--bild` und nur, wenn danach noch Budget übrig ist. Je Knopf
werden Transkriptions- und Analysezeit aus `logs/nestor_zeiten.jsonl` gelesen (dieselben Felder, die der Coach
im echten Betrieb schreibt) und die Kosten aus der Differenz von `coach.kosten_stand()["meeting"]` vorher/nachher
gebildet (`coach/kosten.py`, ab `hoeren_starten()` bei null). Die Tabelle landet auf der Konsole und als JSON in
`logs/messung_knopfdruck_<zeit>.json`.

Testmaterial: Auf diesem Rechner (wie in der Hauptkopie) liegt keine ≥60-minütige deutsche Besprechung –
`testbibliothek/` enthält nur die README (Proben sind laut ihr bewusst nicht im Git), und
`scripts/bibliothek_laden.py` bräuchte `yt_dlp` (hier nicht installiert) und eigene `probe.json`, die es nicht
gibt. Ersatz: `demo/messeplanung.wav` (echte deutsche TTS-Sprachausgabe, ~3,2 min, Lastenheft-Demo) wird so oft
hintereinandergehängt, bis die Aufnahme die gewünschte Mindestlänge erreicht (`--aufnahme` überschreibt das mit
einer eigenen Datei). Für die Messung zählt laut Ticket nur die Menge offener Äußerungen seit dem letzten Knopf,
nicht der Inhalt – die Wiederholung verfälscht Transkriptions- und Analysezeit deshalb nicht; wichtig ist nur,
dass echte, zu transkribierende deutsche Sprache läuft (keine Stille, kein Fake-Transkript).

Kosten-Obergrenze: Transkription läuft echt gegen die API (gpt-4o-transcribe, ~0,006 $/min Sprache). Die
Text-KI (Stand, Regeln, Protokoll) läuft über das Codex-Abo (`LMC_KI=codex`), kostet also nichts extra – das
Skript weist ihre Zeit trotzdem getrennt aus (sie steht schon als `analyse_s` im Zeitenlog). Vor jedem Knopf
wird aus der noch offenen Sprachzeit die zu erwartende Transkriptionskosten geschätzt; würde das zusammen mit
dem bisherigen Stand das Budget sprengen, bricht der Lauf vorher ab, statt es zu riskieren.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import knopfdruck  # noqa: E402
from coach.config import WURZEL  # noqa: E402
from coach.pipeline import Coach  # noqa: E402

NESTOR_ZEITEN = WURZEL / "logs" / "nestor_zeiten.jsonl"
PREIS_TRANSKRIPTION_PRO_MIN = 0.006  # gpt-4o-transcribe (Lastenheft 4.2, kosten.py MINUTENPREISE)
BILD_SCHAETZUNG = 0.08  # Richtwert aus dem Ticket (gpt-image-2 medium; kosten.py BILD=0,05 ist der Mindestwert)
MARKEN = (15.0, "stand"), (30.0, "regeln"), (60.0, "protokoll")  # (Meetingminute, Knopf)


# --- Testmaterial: Ersatzaufnahme aus der Demo zusammensetzen ----------------------
def aufnahme_bauen(ziel: Path, mindest_minuten: float) -> Path:
    if ziel.is_file():
        print(f"Aufnahme vorhanden: {ziel}")
        return ziel
    quelle = WURZEL / "demo" / "messeplanung.wav"
    with wave.open(str(quelle)) as r:
        rate, kanaele, breite = r.getframerate(), r.getnchannels(), r.getsampwidth()
        daten = r.readframes(r.getnframes())
    je_schleife_s = len(daten) / breite / kanaele / rate
    wiederholungen = math.ceil(mindest_minuten * 60 / je_schleife_s)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ziel), "wb") as w:
        w.setnchannels(kanaele)
        w.setsampwidth(breite)
        w.setframerate(rate)
        for _ in range(wiederholungen):
            w.writeframes(daten)
    gesamt_min = wiederholungen * je_schleife_s / 60
    print(f"Ersatzaufnahme gebaut: {ziel.name} = {wiederholungen}× {quelle.name} ({gesamt_min:.1f} min) – "
          f"siehe Docstring, warum kein echtes ≥60-min-Meeting vorlag.")
    return ziel


# --- Ein Knopf: Zeiten aus dem Log, Kosten aus der Differenz ----------------------
def _letzte_zeitzeile() -> dict:
    zeilen = NESTOR_ZEITEN.read_text(encoding="utf-8").splitlines()
    return json.loads(zeilen[-1]) if zeilen else {}


async def knopf_druecken(coach, art: str, marke_min: float) -> dict:
    vorher = coach.kosten_stand()["meeting"]
    t0 = time.monotonic()
    await knopfdruck.ausfuehren(coach, art)
    wanduhr_s = round(time.monotonic() - t0, 2)
    zeile = _letzte_zeitzeile()
    nachher = coach.kosten_stand()["meeting"]
    eintrag = {
        "meetingminute": marke_min, "knopf": art,
        "transkription_s": zeile.get("transkription_s", 0.0),
        "analyse_s": zeile.get("analyse_s", 0.0),  # bei LMC_KI=codex: Codex-Zeit, keine API-Zeit
        "gesamt_s": zeile.get("gesamt_s", wanduhr_s),
        "aeusserungen": zeile.get("aeusserungen", 0),
        "kosten_usd": round(nachher - vorher, 5),
        "fehler": coach.knopf.fehler,
    }
    coach.knopf.fehler = None
    print(f"  {marke_min:>5.0f} min  {art:<10} transkription {eintrag['transkription_s']:>5.1f}s  "
          f"analyse {eintrag['analyse_s']:>5.1f}s  gesamt {eintrag['gesamt_s']:>5.1f}s  "
          f"{eintrag['kosten_usd']:.4f} $" + (f"  FEHLER: {eintrag['fehler']}" if eintrag["fehler"] else ""))
    return eintrag


# --- Hauptlauf: Aufnahme füttern, an den Marken drücken ---------------------------
async def hauptlauf(aufnahme: Path, tempo: float, budget: float, mit_bild: bool) -> list[dict]:
    coach = Coach()
    coach.modus = "knopfdruck"
    coach.einrichten({"titel": "Messung Knopfdruck (Ticket #7)", "assistent": False,
                      "agenda": [{"titel": "Besprechung", "minuten": 60}],
                      "regel_ids": ["ausreden", "thema", "zeit", "kurz", "ton", "ergebnisse"]})
    coach.simulation_laeuft = True
    await coach.hoeren_starten()

    ergebnisse: list[dict] = []
    naechste = 0
    try:
        with wave.open(str(aufnahme)) as w:
            if w.getframerate() != 24000 or w.getnchannels() != 1:
                raise ValueError("Aufnahme muss WAV, 24 kHz, mono sein")
            paket = 2400  # 100 ms, wie scripts/abspielen.py
            start = time.monotonic()
            n = 0
            while naechste < len(MARKEN):
                daten = w.readframes(paket)
                if not daten:
                    print("Aufnahme zu Ende, bevor alle Marken erreicht wurden – siehe --mindest-minuten.")
                    break
                await coach.hoeren_zufuehren(daten)
                n += len(daten) // 2
                coach.takt()
                soll = start + n / 24000 / tempo
                await asyncio.sleep(max(0.0, soll - time.monotonic()))

                marke_min, art = MARKEN[naechste]
                if coach.meeting.jetzt() >= marke_min * 60:
                    bisher = coach.kosten_stand()["meeting"]
                    geschaetzt = coach.hoerstrom.offen()["sprache_sekunden"] / 60 * PREIS_TRANSKRIPTION_PRO_MIN
                    if bisher + geschaetzt > budget:
                        print(f"Abbruch vor „{art}“ ({marke_min:.0f} min): {bisher:.3f} $ + geschätzt "
                              f"{geschaetzt:.3f} $ Transkription würde das Budget von {budget:.2f} $ sprengen.")
                        break
                    ergebnisse.append(await knopf_druecken(coach, art, marke_min))
                    naechste += 1

        # Bild nur einmal, am Ende – und solange der Hörstrom noch läuft (reservieren() braucht ein Meeting)
        gesamt = coach.kosten_stand()["meeting"]
        if mit_bild and naechste == len(MARKEN):
            if gesamt + BILD_SCHAETZUNG <= budget:
                ergebnisse.append(await knopf_druecken(coach, "bild", coach.meeting.jetzt() / 60))
            else:
                print(f"Bild-Knopf ausgelassen: {gesamt:.3f} $ + geschätzt {BILD_SCHAETZUNG:.2f} $ würde das "
                      f"Budget von {budget:.2f} $ sprengen.")
    finally:
        await coach.hoeren_beenden()
        coach.simulation_laeuft = False

    print(f"\nGesamtkosten dieses Laufs: {coach.kosten_stand()['meeting']:.4f} $ "
          f"(Budget {budget:.2f} $)")
    return ergebnisse


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aufnahme", type=Path, default=WURZEL / "testbibliothek" / "audio" / "messung_knopfdruck.wav")
    ap.add_argument("--mindest-minuten", type=float, default=61.0, help="Mindestlänge der Ersatzaufnahme")
    ap.add_argument("--tempo", type=float, default=10.0, help="Abspielfaktor; ändert nur die Fütterungs-, nicht "
                   "die Meetingzeit (die folgt der Audiolänge, Lastenheft-Hinweis 4.2)")
    ap.add_argument("--budget", type=float, default=0.60, help="Kosten-Obergrenze in USD für diesen Lauf")
    ap.add_argument("--bild", action="store_true", help="am Ende einmal den Bild-Knopf drücken, wenn Budget übrig")
    args = ap.parse_args()

    aufnahme_bauen(args.aufnahme, args.mindest_minuten)
    ergebnisse = asyncio.run(hauptlauf(args.aufnahme, args.tempo, args.budget, args.bild))

    ziel = WURZEL / "logs" / f"messung_knopfdruck_{time.strftime('%Y%m%d_%H%M%S')}.json"
    ziel.parent.mkdir(exist_ok=True)
    ziel.write_text(json.dumps(ergebnisse, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Bericht: {ziel}")


if __name__ == "__main__":
    main()
