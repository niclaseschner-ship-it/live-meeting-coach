r"""AMI-Meeting-Korpus als Proben aufbereiten (CC BY 4.0, groups.inf.ed.ac.uk/ami).

    .venv\Scripts\python scripts\ami_laden.py ES2002a ES2002b ES2002c ES2002d

Erwartet in testbibliothek/ami/ die Raumaufnahme <m>.Array1-01.wav (16 kHz, ein Kanal des Tischmikrofon-Arrays –
entspricht unserem Laptop auf dem Tisch) und die Annotationen (ami_public_manual_1.6.2.zip, entpackt nach anno/).
Schreibt testbibliothek/audio/ami_<m>.wav (24 kHz) und .json (Einrichtung, Sprache Englisch) sowie
testbibliothek/proben/ami_<m>/probe.json mit Referenz:
- sprecher: wer wann spricht (Abschnitte je Person A–D) – für Sprechertrennung, Überlappung, Unterbrechung
- themen: Themenabschnitte mit Startzeit – für Agenda-Wechsel
- beschluesse: die Beschlüsse aus der Zusammenfassung – für Regel 10 und Nestors Antworten
Die AMI-Sitzungen sind gespielte Designbesprechungen (vier Personen entwerfen eine Fernbedienung), auf Englisch.
Abspielen mit LMC_SPRACHE=en.
"""

from __future__ import annotations

import json
import re
import sys
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent
AMI = WURZEL / "testbibliothek" / "ami"
ANNO = AMI / "anno"
NITE = "{http://nite.sourceforge.net/}"
SITZUNG = {"a": "Kick-off", "b": "Funktionaler Entwurf", "c": "Konzeptioneller Entwurf", "d": "Detailentwurf"}


def woerter(m: str) -> dict[str, float]:
    zeiten = {}
    for f in ANNO.glob(f"words/{m}.*.words.xml"):
        for w in ET.parse(f).getroot():
            if w.get("starttime"):
                zeiten[w.get(f"{NITE}id")] = float(w.get("starttime"))
    return zeiten


def themenamen() -> dict[str, str]:
    namen = {}
    for t in ET.parse(ANNO / "ontologies" / "default-topics.xml").getroot().iter("topicname"):
        namen[t.get(f"{NITE}id")] = t.get("name")
    return namen


def themen(m: str, zeiten: dict, namen: dict) -> list[dict]:
    aus = []
    for t in ET.parse(ANNO / "topics" / f"{m}.topic.xml").getroot().iter("topic"):
        start = None
        for k in t.findall(f"{NITE}child"):
            for wid in re.findall(r"id\(([^)]+)\)", k.get("href", ""))[:1]:
                if wid in zeiten and (start is None or zeiten[wid] < start):
                    start = zeiten[wid]
        zeiger = t.find(f"{NITE}pointer")
        typ = re.search(r"id\(([^)]+)\)", zeiger.get("href")).group(1) if zeiger is not None else ""
        if start is not None:
            aus.append({"start": round(start, 2), "thema": t.get("other_description") or namen.get(typ, typ), "typ": typ})
    return sorted(aus, key=lambda x: x["start"])


def sprecher(m: str) -> list[dict]:
    aus = []
    for f in sorted(ANNO.glob(f"segments/{m}.*.segments.xml")):
        person = f.name.split(".")[1]
        for s in ET.parse(f).getroot():
            aus.append({"von": float(s.get("transcriber_start")), "bis": float(s.get("transcriber_end")), "person": person})
    return sorted(aus, key=lambda x: x["von"])


def beschluesse(m: str) -> list[str]:
    f = ANNO / "abstractive" / f"{m}.abssumm.xml"
    if not f.exists():
        return []
    d = ET.parse(f).getroot().find("decisions")
    return [s.text.strip() for s in d.iter("sentence")] if d is not None else []


def auf_24k(m: str) -> float:
    with wave.open(str(AMI / f"{m}.Array1-01.wav")) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
        rate = w.getframerate()
    ziel = np.arange(0, len(a) - 1, rate / 24000)
    b = np.interp(ziel, np.arange(len(a)), a)
    b *= min(4.0, 0.25 * 32767 / max(1.0, np.percentile(np.abs(b), 99.5)))  # Raummikrofon ist leise
    with wave.open(str(WURZEL / "testbibliothek" / "audio" / f"ami_{m}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(np.clip(b, -32768, 32767).astype("<i2").tobytes())
    return len(b) / 24000


def main() -> None:
    namen = themenamen()
    for m in sys.argv[1:]:
        dauer = auf_24k(m)
        th = themen(m, woerter(m), namen)
        # Agenda wie in einer echten Besprechung: die inhaltlichen Themen in Reihenfolge, ohne Organisatorisches
        inhaltlich = [t for t in th if not t["typ"].startswith("top.1")]
        agenda, gesehen = [], set()
        for t in inhaltlich:
            if t["thema"] not in gesehen:
                gesehen.add(t["thema"])
                agenda.append({"titel": t["thema"], "ziel": "", "minuten": 5})
        meeting = {"titel": f"Fernbedienung entwerfen – {SITZUNG[m[-1]]} (AMI {m}, englisch)",
                   "ziel": "Eine neue Fernbedienung entwerfen (Designteam mit vier Rollen)",
                   "agenda": agenda[:8], "regeln": [], "regel_ids": ["ausreden", "thema", "zeit", "kurz", "ton", "ergebnisse"],
                   "teilnehmende": [], "assistent": True}
        probe = {"name": f"ami_{m}", "titel": f"AMI {m}: {SITZUNG[m[-1]]}",
                 "quelle": {"korpus": "AMI Meeting Corpus", "lizenz": "CC BY 4.0", "datei": f"{m}.Array1-01.wav"},
                 "setting": "Besprechungsraum, vier Personen, Tischmikrofon-Array (Kanal 1), gespieltes Designprojekt, englisch",
                 "meeting": meeting,
                 "referenz": {"themen": th, "sprecher": sprecher(m), "beschluesse": beschluesse(m)},
                 "eignung": ["sprecher", "ueberlappung", "unterbrechung", "agenda", "ergebnisse"]}
        (WURZEL / "testbibliothek" / "audio" / f"ami_{m}.json").write_text(json.dumps(meeting, ensure_ascii=False, indent=1), encoding="utf-8")
        d = WURZEL / "testbibliothek" / "proben" / f"ami_{m}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "probe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"ami_{m}: {dauer / 60:.1f} min, {len(th)} Themenabschnitte, {len(agenda)} Agendapunkte, "
              f"{len(probe['referenz']['sprecher'])} Sprecherabschnitte, {len(probe['referenz']['beschluesse'])} Beschlüsse")


if __name__ == "__main__":
    main()
