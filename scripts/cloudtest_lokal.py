r"""Cloud-Testmaterial ohne Browser durch den Coach schicken (Ticket #15): Abspielmodus mit echter KI.

    LMC_STUFE=basis ~/.venvs/lmc/bin/python scripts/cloudtest_lokal.py --zugang mistral-api-key \
        [--wav testbibliothek/cloudtest/meeting.wav] [--bis SEKUNDEN] [--ziel logs/cloudtest_lokal/lauf1]

Anders als `scripts/abspielen.py` verhält sich der Coach hier wie im Browser-Lauf (scripts/cloudtest.py):
- keine automatische Übernahme von Agenda-Vorschlägen (`auto_wechsel` aus) – gewechselt wird nur per Ansage,
  Klick oder Nestor;
- `--wie-live` (Standard): Nestors eigene Sprechzeiten werden wie live aus dem Transkript gefiltert (im Abspielmodus
  sonst abgeschaltet, weil kein Lautsprecher mithört) – genau das passiert im Browser-Lauf, wenn die Aufnahme
  weiterläuft, während Nestor noch spricht;
- Einrichtung aus `referenz.json` (Titel, Ziel, Agenda, Teilnehmende aus der Einladung, Standardregeln) wie nach der
  Agenda aus der Einladungsmail;
- Meeting-Ablage an (`archiv_aktiv`), am Ende wird das Paket wie auf der Abschlussseite gebaut.

Ergebnis: `<ziel>/lauf.json` (Wechsel, Überblicke, Karten, Kosten je Art) und `<ziel>/paket.zip`; Kurzfassung auf
der Konsole. Keine Inhalte aus dem Nutzungsprotokoll, nur Mengen.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import types
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import abschluss, regeln  # noqa: E402
from coach.analyse import mmss  # noqa: E402
from coach.config import EINST, WURZEL, mistral_schluessel  # noqa: E402
from coach.pipeline import NUTZUNG, Coach  # noqa: E402

CLOUDTEST = WURZEL / "testbibliothek" / "cloudtest"
TEILNEHMENDE = ["Martina", "Jörg", "Sabine", "Mehmet"]  # aus agenda_prompt.txt


def einrichtung(referenz: dict) -> dict:
    return {"titel": referenz["titel"], "ziel": referenz["ziel"], "agenda": referenz["agenda"],
            "teilnehmende": TEILNEHMENDE, "regel_ids": list(regeln.STANDARD), "assistent": True}


def nutzung_seit(seit: str) -> list[dict]:
    if not NUTZUNG.exists():
        return []
    aus = []
    for zeile in NUTZUNG.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(zeile)
        except ValueError:
            continue
        if e.get("zeit", "") >= seit:
            aus.append(e)
    return aus


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", default=str(CLOUDTEST / "meeting.wav"))
    ap.add_argument("--referenz", default=str(CLOUDTEST / "referenz.json"))
    ap.add_argument("--bis", type=float, default=None, help="nur die ersten N Sekunden")
    ap.add_argument("--ziel", default=str(WURZEL / "logs" / "cloudtest_lokal" / time.strftime("%H%M%S")))
    ap.add_argument("--ohne-eigene-sprache", action="store_true",
                    help="Nestors Sprechzeiten nicht filtern (wie scripts/abspielen.py)")
    ap.add_argument("--zugang", default="", help="Name in der Hausablage (zugang holen), falls kein Schlüssel gesetzt")
    args = ap.parse_args()
    ziel = Path(args.ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LMC_ARCHIV", str(ziel / "ablage"))
    object.__setattr__(EINST, "archiv", str(ziel / "ablage"))

    wav = Path(args.wav)
    if args.bis:
        import wave

        kurz = ziel / f"meeting_bis{int(args.bis)}.wav"
        with wave.open(str(wav)) as r, wave.open(str(kurz), "wb") as w:
            w.setparams(r.getparams())
            w.writeframes(r.readframes(int(args.bis * r.getframerate())))
        wav = kurz

    referenz = json.loads(Path(args.referenz).read_text(encoding="utf-8"))
    if args.zugang and EINST.stufe == "basis" and not mistral_schluessel():
        # Schlüssel aus der Hausablage nur in die Umgebung dieses Prozesses – nie in Dateien oder Logs
        import subprocess

        os.environ["MISTRAL_API_KEY"] = subprocess.run(["sudo", "-n", "zugang", "holen", args.zugang],
                                                       capture_output=True, text=True, check=True).stdout.strip()
    coach = Coach()
    if coach._client is None:
        sys.exit("Kein KI-Client – Schlüssel in der Umgebung? (LMC_STUFE=basis + MISTRAL_API_KEY)")
    coach.archiv_aktiv = True
    coach._einrichten(einrichtung(referenz))
    if not args.ohne_eigene_sprache:
        a = coach.assistent

        def eigene_sprache(self, start: float, ende: float) -> bool:  # wie live: ohne simulation_laeuft-Ausnahme
            ueber = sum(max(0.0, min(ende, b) - max(start, x)) for x, b in self.sprechzeiten)
            return ueber >= 0.5 * max(0.1, ende - start)

        a.eigene_sprache = types.MethodType(eigene_sprache, a)

    beginn = time.strftime("%Y-%m-%dT%H:%M:%S")
    ueberblicke: list[dict] = []
    gesehen = {"ueberblick": 0}

    async def beobachten() -> None:
        if coach.ueberblick_version != gesehen["ueberblick"]:
            gesehen["ueberblick"] = coach.ueberblick_version
            ueberblicke.append({"version": coach.ueberblick_version, "zeit": round(coach.meeting.jetzt(), 1),
                                "stand": coach.ueberblick.get("laufzeit") if coach.ueberblick else None})

    coach.beobachter.append(beobachten)
    t0 = time.monotonic()
    await coach.abspielen(wav, tempo=1.0, auto_wechsel=False)
    dauer = time.monotonic() - t0
    archiv = coach.archiv
    for _ in range(300):  # Ablage wie auf der Abschlussseite abwarten
        if archiv is None or archiv.fertig:
            break
        await asyncio.sleep(1)
    m = coach.meeting

    paket_namen: list[str] = []
    if archiv is not None and archiv.fertig:
        import io
        import zipfile

        daten = abschluss.paket(archiv.ordner, False)
        (ziel / "paket.zip").write_bytes(daten)
        paket_namen = zipfile.ZipFile(io.BytesIO(daten)).namelist()

    nutzung = nutzung_seit(beginn)
    je_art: dict[str, dict] = defaultdict(lambda: {"anzahl": 0, "usd": 0.0, "tokens_rein": 0, "tokens_raus": 0,
                                                  "zeichen": 0, "sekunden_audio": 0.0})
    for e in nutzung:
        k = f"{e.get('art')} · {e.get('modell', e.get('anbieter', ''))}"
        d = je_art[k]
        d["anzahl"] += 1
        d["usd"] += e.get("usd") or 0.0
        for f in ("tokens_rein", "tokens_raus", "zeichen", "sekunden_audio"):
            d[f] += e.get(f) or 0
    gesamt = sum(d["usd"] for d in je_art.values())

    wechsel = [e for e in coach.protokoll if e["art"] == "wechsel"]
    lauf = {
        "stufe": EINST.stufe, "meeting_s": round(m.jetzt(), 1), "laufzeit_s": round(dauer, 1),
        "wechsel": [{"zeit": round(e["zeit"], 1), "von": e["von"] + 1, "nach": e["nach"] + 1, "durch": e.get("durch")}
                    for e in wechsel],
        "ueberblicke": ueberblicke,
        "assistent": [{"zeit": round(e["zeit"], 1), "frage": e["frage"][:80], "aktion": e.get("aktion"),
                       "sekunden": e.get("sekunden")} for e in coach.protokoll if e["art"] == "assistent"],
        "karten": [{"zeit": round(k["zeit"], 1), "art": k.get("art"), "titel": k.get("titel")} for k in coach.karten],
        "hinweise": [{"zeit": round(h.zeit, 1), "art": h.art, "text": h.text[:120]} for h in m.hinweise],
        "transkript": [{"start": round(s.start, 1), "ende": round(s.ende, 1), "sprecher": s.sprecher, "text": s.text}
                       for s in m.transkript],
        "kosten_je_art": {k: {**v, "usd": round(v["usd"], 4)} for k, v in sorted(je_art.items())},
        "kosten_usd": round(gesamt, 4),
        "kosten_je_stunde_usd": round(gesamt / (m.jetzt() / 3600), 3) if m.jetzt() > 60 else None,
        "kosten_stand": coach.kosten_stand(),
        "paket": paket_namen,
        "fehler": coach.fehler,
    }
    (ziel / "lauf.json").write_text(json.dumps(lauf, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"Stufe {EINST.stufe}: {m.jetzt():.0f} s Meeting, {dauer:.0f} s Laufzeit, {len(m.transkript)} Sätze")
    for e in lauf["wechsel"]:
        print(f"  WECHSEL {mmss(e['zeit'])} ({e['zeit']:.0f} s) Punkt {e['von']} → {e['nach']} durch {e['durch']}")
    for u in ueberblicke:
        print(f"  ÜBERBLICK v{u['version']} bei {mmss(u['zeit'])} ({u['zeit']:.0f} s)")
    for a in lauf["assistent"]:
        print(f"  NESTOR {mmss(a['zeit'])} {a['frage'][:60]!r} → {a['aktion']}")
    print("Kosten je Art:")
    for k, v in lauf["kosten_je_art"].items():
        print(f"  {k:55} {v['anzahl']:4}×  {v['usd']:.4f} $")
    print(f"  Summe {gesamt:.4f} $ · je Stunde {lauf['kosten_je_stunde_usd']} $")
    print("Paket:", ", ".join(paket_namen) or "-")
    print("Fehler:", coach.fehler)
    print("Bericht:", ziel / "lauf.json")


asyncio.run(main())
