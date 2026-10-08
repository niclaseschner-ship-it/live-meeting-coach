r"""Meeting-Artefakte (Ticket #26) auf echtem Material: Erkennung, Nachfrage beim Punktwechsel, Fünf-Minuten-
Zusammenfassung und das Schließen einer Lücke per Stimme – mit echten Modellaufrufen, ohne Sprachausgabe.

    OPENAI_API_KEY=… LMC_STIMME_AUS=1 ~/.venvs/lmc/bin/python scripts/bench_artefakte.py incident premium
    MISTRAL_API_KEY=… LMC_STIMME_AUS=1 ~/.venvs/lmc/bin/python scripts/bench_artefakte.py verein basis

Material: `transkript.md` aus einem Paket der Cloudläufe (Live-Transkript, wie es Nestor wirklich sah) –
`incident`: Incident-Review aus logs/cloudtest/cloud_premium_grenz2/paket.zip, `verein`: Vereinsrunde
(testbibliothek/cloudtest/referenz.json) aus logs/cloudtest/cloud_basis_1/paket.zip. Pfad zur entpackten Datei mit
--transkript, sonst wird das Paket unter logs/cloudtest/ (auch des Haupt-Checkouts) gesucht.

Ablauf wie live: Sätze in Sprechreihenfolge, ein Erkennungslauf je Minute Sprache, Punktwechsel an den Zeiten der
Ansagen (mit Regel 10 → Nachfrage), Fünf-Minuten-Frage mit Ja, am Ende der letzte Lauf. Ausgabe: Artefakte mit
Lücken, Nachfragen, Zusammenfassung, Tokens und Kosten je Stufe und hochgerechnet je Stunde Sprache.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import kosten  # noqa: E402
from coach import pipeline as P  # noqa: E402
from coach.zustand import Segment  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
MATERIAL = {
    "incident": {"paket": "cloud_premium_grenz2", "referenz": "referenz_grenzfaelle.json",
                 "wechsel": {"02:46": 1, "08:24": 2, "10:18": 3},
                 "antwort": ("Sofie übernimmt die Statusseite bis Freitag.", "Jonas")},
    "verein": {"paket": "cloud_basis_1", "referenz": "referenz.json",
               "wechsel": {"02:49": 1, "08:05": 2},
               "antwort": ("Das macht Jörg, bis zur nächsten Sitzung.", "Person 1")},
}
ZEILE = re.compile(r"^\*\*\[(\d+):(\d\d)\] ([^:*]+):\*\* (.*)$")


def transkript_lesen(text: str) -> list[Segment]:
    saetze = []
    for z in text.splitlines():
        m = ZEILE.match(z.strip())
        if m:
            start = int(m[1]) * 60 + int(m[2])
            saetze.append(Segment(m[3].strip(), m[4].strip(), float(start), 0.0))
    for a, b in zip(saetze, saetze[1:] + [None]):  # Ende ≈ Beginn des nächsten Satzes, höchstens 15 Wörter/5 s
        a.ende = min(b.start if b else a.start + 5, a.start + max(1.5, len(a.text.split()) / 2.5))
        a.ende = max(a.ende, a.start + 0.5)
    return saetze


def paket_finden(name: str) -> str:
    for basis in (WURZEL, WURZEL.parents[2] if len(WURZEL.parents) > 2 else WURZEL):
        p = basis / "logs" / "cloudtest" / name / "paket.zip"
        if p.exists():
            return zipfile.ZipFile(io.BytesIO(p.read_bytes())).read("transkript.md").decode("utf-8")
    raise SystemExit(f"Paket {name} nicht gefunden – --transkript angeben")


async def lauf(material: str, stufe: str, transkript: str | None, antwort: bool) -> dict:
    cfg = MATERIAL[material]
    text = Path(transkript).read_text(encoding="utf-8") if transkript else paket_finden(cfg["paket"])
    saetze = transkript_lesen(text)
    ref = json.loads((WURZEL / "testbibliothek" / "cloudtest" / cfg["referenz"]).read_text(encoding="utf-8"))
    nutzung: list[dict] = []
    P.nutzung_loggen = lambda e: nutzung.append(e)  # nichts ins Protokoll, nur mitzählen

    c = P.Coach()
    c.stufe_setzen(stufe)
    c._einrichten({"titel": ref["titel"], "ziel": ref["ziel"], "agenda": ref["agenda"],
                   "regel_ids": ["zeit", "ergebnisse"], "assistent": False})
    m, art = c.meeting, c.artefakte
    m.starten(virtuell=True)
    wechsel = {int(k[:2]) * 60 + int(k[3:]): p for k, p in cfg["wechsel"].items()}
    ende = art.geplantes_ende()
    fuenf_bei = max(ende - 300, ende / 2) if ende else None
    aus: dict = {"material": material, "stufe": stufe, "modell": P.EINST.analyse_modell, "nachfragen": [],
                 "zusammenfassung": None}
    for s in saetze:
        for t in sorted(wechsel):
            if t <= s.start:
                ziel = wechsel.pop(t)
                m.virtuelle_zeit = float(t)
                alt = m.aktiver_punkt
                m.punkt_wechseln(ziel)
                gefragt = await art.punkt_abgeschlossen(alt)
                if gefragt:
                    aus["nachfragen"].append({"zeit": t, "punkt": alt + 1, "text": art.rueckfrage.text})
                    art.rueckfrage = None
        if fuenf_bei is not None and s.start >= fuenf_bei and aus["zusammenfassung"] is None:
            m.virtuelle_zeit = s.start
            await art.erkennen()
            aus["zusammenfassung"] = {"zeit": s.start, "text": art.zusammenfassung()[0]}
        m.virtuelle_zeit = s.ende
        m.transkript.append(s)
        neu = sum(x.dauer for x in art._neue_saetze())
        from coach.artefakte import MIN_SPRACHE, SPAETESTENS_SEKUNDEN, SPRACHE_SEKUNDEN

        if neu >= SPRACHE_SEKUNDEN[stufe] or (neu >= MIN_SPRACHE and m.jetzt() - art.letzter_lauf >= SPAETESTENS_SEKUNDEN):
            await art.erkennen()
    await art.erkennen()
    aus["artefakte"] = [a.bild() for a in art.liste]
    if antwort:
        satz, wer = cfg["antwort"]
        luecken = art.luecken_liste(3)
        from coach.artefakte import Rueckfrage, frage_zu

        art.rueckfrage = Rueckfrage("nachfrage", " ".join(frage_zu(a) for a in luecken), [a.id for a in luecken],
                                    m.jetzt(), m.jetzt() + 30)
        vorher = {a.id: a.bild() for a in luecken}
        ok = await art.antwort_deuten(satz, wer)
        aus["antwort"] = {"gefragt": art.rueckfrage.text if art.rueckfrage else None, "satz": satz, "erkannt": ok,
                          "danach": [a.bild() for a in art.liste if a.id in vorher or a.herkunft == "stimme"],
                          "vorher": list(vorher.values())}
    aufrufe = [e for e in nutzung if e.get("art") == "artefakte"]
    usd = sum(kosten.dollar(e) for e in aufrufe)
    sprache = sum(s.dauer for s in saetze)
    aus["kosten"] = {"aufrufe": len(aufrufe), "tokens_rein": sum(e.get("tokens_rein") or 0 for e in aufrufe),
                     "tokens_raus": sum(e.get("tokens_raus") or 0 for e in aufrufe), "usd": round(usd, 5),
                     "meeting_minuten": round(saetze[-1].ende / 60, 1), "sprache_minuten": round(sprache / 60, 1),
                     "usd_je_stunde_meeting": round(usd / (saetze[-1].ende / 3600), 3)}
    return aus


def zeigen(aus: dict) -> None:
    print(f"\n=== {aus['material']} · {aus['stufe']} · {aus['modell']}")
    for a in aus["artefakte"]:
        luecke = f"  FEHLT: {', '.join(a['luecken'])}" if a["luecken"] else ""
        print(f"[{a['zeit_text']}] P{(a['punkt'] or 0) + 1 if a['punkt'] is not None else '-'} {a['typ_name']:<13} "
              f"{a['was']} | wer={a['wer']} | bis={a['bis']}"
              + (f" | status={a['status']}" if a["typ"] == "entscheidung" else "")
              + (f" | reaktion={a['reaktion']} hoch={a['hoch']}" if a["typ"] == "risiko" else "")
              + f" | k={a['konfidenz']:.2f}{luecke}")
    for n in aus["nachfragen"]:
        print(f"\nNachfrage nach Punkt {n['punkt']} ({n['zeit']} s): {n['text']}")
    if aus["zusammenfassung"]:
        print(f"\nFünf-Minuten-Zusammenfassung ({aus['zusammenfassung']['zeit']:.0f} s): {aus['zusammenfassung']['text']}")
    if aus.get("antwort"):
        a = aus["antwort"]
        print(f"\nAntwort „{a['satz']}“ auf: {a['gefragt']} → erkannt={a['erkannt']}")
        for x in a["danach"]:
            print(f"   {x['id']}. {x['was']} | wer={x['wer']} | bis={x['bis']} | Lücken={x['luecken']}")
    print(f"\nKosten: {json.dumps(aus['kosten'], ensure_ascii=False)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("material", choices=sorted(MATERIAL))
    ap.add_argument("stufe", choices=("premium", "basis"))
    ap.add_argument("--transkript")
    ap.add_argument("--modell", help="anderes Analysemodell (z. B. mistral-small-latest)")
    ap.add_argument("--ohne-antwort", action="store_true")
    ap.add_argument("--json", help="Ergebnis zusätzlich als JSON ablegen")
    arg = ap.parse_args()
    if arg.modell:
        from coach.config import EINST, stufe_setzen

        stufe_setzen(arg.stufe)
        object.__setattr__(EINST, "analyse_modell", arg.modell)
        P.Coach.stufe_setzen = lambda self, stufe, nur_knopfdruck=False: self.client_neu()
    ergebnis = asyncio.run(lauf(arg.material, arg.stufe, arg.transkript, not arg.ohne_antwort))
    zeigen(ergebnis)
    if arg.json:
        Path(arg.json).write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
