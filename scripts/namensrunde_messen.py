r"""Namensrunde messen (Ticket #27): vier verschiedene Stimmen stellen sich reihum vor, danach redet jede.

In den Demos wurde nur eine von mehreren Personen mit Namen erkannt. Dieses Skript baut eine Probe mit vier Azure-
Stimmen (onyx, nova, echo, shimmer – dieselben wie im Cloudtest-Material, 0 $ über Teachbuddys Kontingent), spielt
sie durch den echten Hörstrom (Pausenerkennung, Stimm-Fingerabdruck CAM++, Sprecherzuordnung – wie live) und
ordnet die Namen zu. Der Text kommt aus dem Drehbuch statt aus dem Live-Text (kostet nichts, und es geht hier
um die Sprecherzuordnung, nicht um die Texterkennung).

Gemessen: Wie viele der vier Namen landen bei der richtigen Stimme (Mehrheit der späteren Redebeiträge jeder Person
trägt ihren Namen) und wie viele bei einer falschen. Zwei Verfahren:
    vorher   der Name gilt für den Sprecher, dem die Vorstellung in diesem Moment zugeordnet ist (bis Ticket #27)
    nachher  der Name wird mit dem Fingerabdruck der Vorstellung gemerkt und still der passenden Stimme zugeordnet

    ~/.venvs/lmc/bin/python scripts/namensrunde_messen.py [--neu] [--runden 3]

`--neu` vertont die Probe neu; `--runden` mischt die Reihenfolge der Stimmen für mehrere Durchgänge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import wave
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL / "testbibliothek" / "cloudtest"))
ORDNER = WURZEL / "testbibliothek" / "namensrunde"
RATE = 24000
LUECKE = 0.9

PERSONEN = [
    {"name": "Anna", "stimme": "nova", "vorstellung": "Hallo, ich bin Anna.",
     "beitraege": ["Ich habe mir die Zahlen vom letzten Quartal angeschaut, der Umsatz liegt etwas unter Plan.",
                   "Aus meiner Sicht sollten wir die Kampagne im Frühjahr deutlich früher starten."]},
    {"name": "David", "stimme": "onyx", "vorstellung": "Ich heiße David.",
     "beitraege": ["Beim Lager haben wir das Problem, dass die Lieferungen ständig zu spät kommen.",
                   "Ich kann bis Freitag eine Liste mit den drei wichtigsten Lieferanten machen."]},
    {"name": "Lea", "stimme": "shimmer", "vorstellung": "Lea hier, ich mache das Marketing.",
     "beitraege": ["Für die Messe brauchen wir noch Flyer, und die Druckerei braucht drei Wochen Vorlauf.",
                   "Wenn wir das Budget nicht erhöhen, wird der Stand dieses Jahr eher klein ausfallen."]},
    {"name": "Tarek", "stimme": "echo", "vorstellung": "Mein Name ist Tarek.",
     "beitraege": ["Die Technik für den Stand ist gebucht, nur der Strom ist noch nicht bestätigt.",
                   "Ich würde vorschlagen, dass wir nächste Woche noch einmal kurz telefonieren."]},
]


def vertonen(neu: bool) -> dict[str, np.ndarray]:
    """Je Satz ein PCM-Stück (24 kHz), zwischengespeichert in testbibliothek/namensrunde/ (nicht im Git)."""
    ORDNER.mkdir(parents=True, exist_ok=True)
    tts = None
    aus = {}
    for p in PERSONEN:
        for i, text in enumerate([p["vorstellung"], *p["beitraege"]]):
            datei = ORDNER / f"{p['name'].lower()}_{i}.pcm"
            if datei.exists() and not neu:
                aus[(p["name"], i)] = np.frombuffer(datei.read_bytes(), dtype="<i2")
                continue
            if tts is None:
                from bauen_grenzfaelle import azure_tts
                tts = azure_tts()
            from bauen_grenzfaelle import mp3_zu_pcm
            pcm = mp3_zu_pcm(tts.synthese(text=text, voice=p["stimme"]))
            datei.write_bytes(pcm.astype("<i2").tobytes())
            aus[(p["name"], i)] = pcm
    if tts is not None:
        print(f"Azure (Teachbuddy, eigenes Kontingent): {tts.zeichen} Zeichen, 0 $.")
    return aus


def drehbuch(reihenfolge: list[dict], stuecke) -> tuple[np.ndarray, list[dict]]:
    """Vorstellungsrunde reihum, danach zwei Runden Redebeiträge. [{name, text, start, ende, vorstellung}]"""
    teile, zeilen, t = [np.zeros(int(1.0 * RATE), dtype="<i2")], [], 1.0
    folge = [(p, 0) for p in reihenfolge] + [(p, 1) for p in reihenfolge] + [(p, 2) for p in reversed(reihenfolge)]
    for p, i in folge:
        pcm = stuecke[(p["name"], i)]
        zeilen.append({"name": p["name"], "text": [p["vorstellung"], *p["beitraege"]][i], "start": round(t, 3),
                       "ende": round(t + len(pcm) / RATE, 3), "vorstellung": i == 0})
        teile += [pcm, np.zeros(int(LUECKE * RATE), dtype="<i2")]
        t += len(pcm) / RATE + LUECKE
    return np.concatenate(teile), zeilen


def alt_name_lernen(coach):
    """Das Verfahren bis Ticket #27 (coach/pipeline.py, name_lernen): der Name gilt für den Sprecher des Satzes."""
    from coach.assistent import name_aus
    from coach.hoeren import UNSICHER

    def lernen(sprecher, text, start=0.0, ende=0.0):
        if not sprecher.startswith("Person ") or sprecher == UNSICHER or sprecher in coach.namen:
            return
        name = name_aus(text, coach.meeting.teilnehmende)
        if not name or name in coach.namen.values():
            return
        coach._name_setzen(sprecher, name)
    return lernen


async def durchgang(pcm: np.ndarray, zeilen: list[dict], verfahren: str) -> dict:
    import coach.hoeren as hoeren
    from coach.pipeline import Coach

    class Drehbuchtext:
        """Statt des Live-Texts: der Satz aus dem Drehbuch, dessen Ende am nächsten liegt."""
        def __init__(self, teiltext, satz, prompt, stichwoerter):
            self.satz, self.gesendete_sekunden, self.fehler = satz, 0.0, None

        async def verbinden(self):
            pass

        async def audio(self, pcm24k):
            pass

        async def commit(self, meta):
            z = min(zeilen, key=lambda x: abs(x["ende"] - meta["ende"]))
            await self.satz(meta, z["text"] if abs(z["ende"] - meta["ende"]) < 1.5 else "")

        async def schliessen(self):
            pass

    hoeren.LiveText = Drehbuchtext
    c = Coach()
    c._einrichten({"titel": "Namensrunde", "agenda": [], "regel_ids": []})
    c._client = object()  # nur „vorhanden“ – es geht kein Aufruf hinaus (keine Agenda, Nestor aus)
    c.assistent.aktiv = False
    c.simulation_laeuft = True
    if verfahren == "vorher":
        c.name_lernen = alt_name_lernen(c)
        c._namen_zuordnen = lambda: None
    await c.hoeren_starten()
    c.assistent.vorstellung_bis = max(z["ende"] for z in zeilen if z["vorstellung"]) + 45
    for i in range(0, len(pcm), 2400):
        await c.hoeren_zufuehren(pcm[i:i + 2400].tobytes())
        if i % (RATE * 2) == 0:
            c.takt()
            await asyncio.sleep(0)
    for _ in range(3):  # Analyse-Rückstand abarbeiten, dann wie im Takt zuordnen
        await asyncio.sleep(0.3)
        c.takt()
    await c.hoeren_beenden()
    c._namen_zuordnen() if verfahren == "nachher" else None
    # Bewertung: Wer trägt die späteren Beiträge jeder Person?
    ergebnis = {}
    for p in {z["name"] for z in zeilen}:
        labels = []
        for z in zeilen:
            if z["name"] != p or z["vorstellung"]:
                continue
            treffer = [s.sprecher for s in c.meeting.transkript if abs(s.start - z["start"]) < 1.5]
            labels += treffer[:1]
        ergebnis[p] = max(set(labels), key=labels.count) if labels else None
    richtig = sum(1 for p, l in ergebnis.items() if l == p)
    falsch = sum(1 for p, l in ergebnis.items() if l in ergebnis and l != p)
    vorstellungen = {z["name"]: next((s.sprecher for s in c.meeting.transkript if abs(s.start - z["start"]) < 1.5), None)
                     for z in zeilen if z["vorstellung"]}
    return {"verfahren": verfahren, "richtig": richtig, "falsch": falsch, "zuordnung": ergebnis,
            "namen": dict(c.namen), "personen": len(c.hoerstrom.stimmen.register.summen) if c.hoerstrom else None,
            "vorstellung_als": vorstellungen}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--neu", action="store_true")
    ap.add_argument("--runden", type=int, default=3)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    stuecke = vertonen(args.neu)
    zufall = random.Random(27)
    summen = {"vorher": [0, 0], "nachher": [0, 0]}
    for runde in range(args.runden):
        reihenfolge = list(PERSONEN)
        if runde:
            zufall.shuffle(reihenfolge)
        pcm, zeilen = drehbuch(reihenfolge, stuecke)
        with wave.open(str(ORDNER / f"namensrunde_{runde + 1}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())
        (ORDNER / f"namensrunde_{runde + 1}.json").write_text(json.dumps(zeilen, ensure_ascii=False, indent=1))
        print(f"Runde {runde + 1}: Reihenfolge {', '.join(p['name'] for p in reihenfolge)} ({len(pcm) / RATE:.0f} s)")
        for verfahren in ("vorher", "nachher"):
            e = await durchgang(pcm, zeilen, verfahren)
            summen[verfahren][0] += e["richtig"]
            summen[verfahren][1] += e["falsch"]
            print(f"  {verfahren:8} {e['richtig']}/4 richtig, {e['falsch']} falsch · Vorstellung erkannt als "
                  f"{e['vorstellung_als']} · Namen {e['namen']} · Stimmen im Register {e['personen']}")
    n = 4 * args.runden
    for verfahren, (richtig, falsch) in summen.items():
        print(f"Gesamt {verfahren}: {richtig}/{n} Namen richtig, {falsch} falsch")


if __name__ == "__main__":
    asyncio.run(main())
