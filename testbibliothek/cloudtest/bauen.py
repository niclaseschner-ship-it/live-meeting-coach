r"""Baut das Testmaterial für den Cloud-Testlauf (scripts/cloudtest.py): ein ~10-minütiges synthetisches
Teammeeting mit eingebauten Ereignissen, einem echten Schnitzel aus der Demo und fünf Anweisungen an Nestor.

    ~/.venvs/lmc/bin/python testbibliothek/cloudtest/bauen.py

Schritt 1: Drehbuch über das ChatGPT-Abo (Codex, keine API-Kosten) – wie scripts/synthetisch_meeting.py, aber mit
fest vorgegebener Drei-Punkte-Agenda, damit sich die Ereignisse gezielt platzieren lassen.
Schritt 2: Vertonung je Äußerung über Teachbuddys Azure auf diesem Rechner (podcast.vertonung, keine OpenAI-
Kosten) – direkt aufgerufen statt über ssh, weil dieses Skript schon auf dem Pi läuft.
Schritt 3: Einfügen eines echten Schnitzels aus demo/messeplanung.wav und der fünf Nestor-Anweisungen
(gpt-4o-mini-tts, ein paar Cent) – jeweils an der Äußerungsgrenze, die ihrer Zielzeit am nächsten liegt.
Ergebnis in testbibliothek/cloudtest/: drehbuch.json, referenz.json, agenda_prompt.txt (im Git) und
meeting.wav (per .gitignore ausgenommen).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent.parent
ZIEL = WURZEL / "testbibliothek" / "cloudtest"
sys.path.insert(0, str(WURZEL))
from coach.config import openai_schluessel  # noqa: E402
from coach.ki_abo import codex  # noqa: E402

RATE = 24000
VORLAUF = 25.0  # Lastenheft: Begrüßung + Zeitfenster für ein "Nein"
GAP = 0.6  # Pause zwischen zwei Äußerungen, wie scripts/synthetisch_meeting.py
AZURE_STIMMEN = ["onyx", "nova", "echo", "shimmer"]  # vier Personen, Azure-Bereitstellung
NESTOR_STIMMEN = ["verse", "coral"]  # deutlich anders als die Azure-Stimmen der Runde

THEMA = "Planung des Messestands für die Hannover Messe 2027"
AGENDA = [
    {"titel": "Planungsstand und nächste Schritte", "ziel": "Überblick, was schon steht"},
    {"titel": "Budget und Standgestaltung", "ziel": "Obergrenze und Standgröße beschließen"},
    {"titel": "Aufgabenverteilung", "ziel": "Wer macht was bis wann"},
]
PERSONEN = ["Mara", "Jonas", "Elif", "Timo"]

AUFTRAG = f"""\
Schreibe das Drehbuch einer realistischen deutschen Teambesprechung: {THEMA}
Vier Personen: {", ".join(PERSONEN)}. Rund 7 Minuten gesprochener Text (rund 980 Wörter), natürliche
gesprochene Sprache mit Füllwörtern, Rückfragen und halben Sätzen – kein Theaterdialog. Keine Unterbrechungen
(jede Person redet aus).
Genau drei Agendapunkte in dieser Reihenfolge, jeweils ausführlich besprochen:
1. {AGENDA[0]["titel"]} – {AGENDA[0]["ziel"]}
2. {AGENDA[1]["titel"]} – {AGENDA[1]["ziel"]}
3. {AGENDA[2]["titel"]} – {AGENDA[2]["ziel"]}
Baue diese Ereignisse ein und markiere jede betroffene Äußerung (Feld "ereignisse"):
- gleich am Anfang (erste oder zweite Äußerung) ein Monolog einer Person über mehr als 70 Sekunden
  gesprochener Zeit zum aktuellen Planungsstand: monolog
- beim Wechsel zu Punkt 2 eine ausdrückliche Ansage, z. B. "Wir kommen zu Punkt zwei": wechsel_ansage
- mitten in Punkt 2 eine Abschweifung von rund 40 Sekunden über Fußball (Wochenendspiel, Tabelle o. Ä.),
  darin ein deutscher Kraftausdruck: abschweifung, kraftausdruck
- gegen Ende von Punkt 2 ein klarer Beschluss mit einem konkreten Euro-Betrag für den Stand: beschluss
- beim Wechsel zu Punkt 3 eine Ansage, z. B. "Dann zu Punkt drei, der Aufgabenverteilung": wechsel_ansage
- gegen Ende eine Aufgabe, die klar benannt, aber niemandem ausdrücklich zugewiesen wird: aufgabe_ohne_zustaendig
Keine Fragen an einen Assistenten, keine Marke "nestor_frage" – die kommen in einem späteren Schritt dazu.
Antworte nur mit JSON:
{{"titel": "...", "ziel": "...",
  "agenda": [{{"titel": "...", "ziel": "...", "minuten": 2}}],
  "personen": [{{"name": "Vorname", "rolle": "..."}}],
  "aeusserungen": [{{"person": 0, "text": "...", "punkt": 0, "ereignisse": ["monolog"]}}]}}
"punkt" ist der Agendapunkt (ab 0), zu dem die Äußerung inhaltlich gehört; bei der Fußball-Abschweifung -1.
"""

# Fünf Anweisungen an Nestor (Lastenheft 4.2/Startseite „Live“); Zielzeit = Sekunde in der fertigen Aufnahme.
NESTOR_EINSCHUEBE = [
    {"ziel_s": 150, "text": "Nestor, wo stehen wir gerade?", "pause": 22.0},
    {"ziel_s": 300, "text": "Nestor, gib uns einen kurzen Überblick, was ein Messestand auf einer Fachmesse "
                             "in Deutschland typischerweise kostet.", "pause": 35.0, "recherche": True,
     "folge": {"text": "Ja, mach uns dazu eine Folie.", "pause": 10.0, "bild": True}},
    {"ziel_s": 360, "text": "Nestor, wie ist der aktuelle Stand bei der Förderung von Messeauftritten für "
                             "kleine Unternehmen?", "pause": 35.0, "recherche": True},
    {"ziel_s": 420, "text": "Nestor, fass bitte kurz zusammen, was wir zu Punkt zwei besprochen haben.",
     "pause": 22.0},
    {"ziel_s": 540, "text": "Nestor, mach uns die visuelle Übersicht.", "pause": 10.0, "bild": True},
]
SCHNITZEL_ZIEL_S = 220  # irgendwo in Punkt 2 (Budget), zwischen Abschweifung (~3:40) und Beschluss
SCHNITZEL_DAUER = 20.0
SCHNITZEL_QUELLE_START = 80.0  # Sekunde in demo/messeplanung.wav


def mp3_zu_pcm(daten: bytes) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                        "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
                       input=daten, capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype="<i2")


ZIEL_WOERTER = 950  # ~6,8 min Sprechzeit; mit Vorlauf, Schnitzel und Nestor-Pausen zusammen ~10 min


async def drehbuch(neu: bool = False) -> dict:
    datei = ZIEL / "drehbuch.json"
    if datei.exists() and not neu:
        d = json.loads(datei.read_text(encoding="utf-8"))
        vorher = len(d["aeusserungen"])
        kuerzen(d)
        if len(d["aeusserungen"]) != vorher:
            datei.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        woerter = sum(len(a["text"].split()) for a in d["aeusserungen"])
        print(f"Drehbuch: vorhanden ({datei}), auf {woerter} Wörter gekürzt (--neu zum Neuerzeugen).")
        return d
    text = await codex(AUFTRAG, frist=600)
    d = json.loads(text)
    kuerzen(d)
    ZIEL.mkdir(parents=True, exist_ok=True)
    datei.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    woerter = sum(len(a["text"].split()) for a in d["aeusserungen"])
    print(f"Drehbuch: {len(d['aeusserungen'])} Äußerungen, {woerter} Wörter (~{woerter / 140:.1f} min), "
          f"Ereignisse: {sorted({e for a in d['aeusserungen'] for e in a.get('ereignisse', [])})}")
    return d


def kuerzen(d: dict) -> None:
    """Zielmenge Wörter: die längsten Äußerungen ohne Ereignis-Marke zuerst entfernen (Codex liefert oft
    mehr als die erbetenen ~7 Minuten)."""
    aeusserungen = d["aeusserungen"]
    woerter = lambda a: len(a["text"].split())  # noqa: E731
    gesamt = sum(woerter(a) for a in aeusserungen)
    ohne_marke = sorted((a for a in aeusserungen if not a.get("ereignisse")), key=woerter, reverse=True)
    for a in ohne_marke:
        if gesamt <= ZIEL_WOERTER:
            break
        aeusserungen.remove(a)
        gesamt -= woerter(a)


def azure_vertonen(d: dict) -> list[dict]:
    """Je Äußerung eine Azure-TTS-Datei (Teachbuddy, lokal auf dem Pi) – Blöcke mit Audio und Metadaten."""
    import os

    teachbuddy = Path.home() / "repos" / "teachbuddy"
    sys.path.insert(0, str(teachbuddy))
    # Zugangsdaten holen wie bin-zugang.sh, aber im selben Prozess (kein eigenes Shell-Sourcing nötig)
    for ziel_var, name in (("HOERSPIEL_AZURE_OPENAI_ENDPOINT", "azure-openai-endpoint"),
                           ("HOERSPIEL_AZURE_OPENAI_KEY", "azure-openai-key"),
                           ("HOERSPIEL_AZURE_OPENAI_DEPLOYMENT", "azure-openai-deployment")):
        if not os.environ.get(ziel_var):
            wert = subprocess.run(["sudo", "-n", "zugang", "holen", name], capture_output=True, text=True)
            if wert.returncode == 0:
                os.environ[ziel_var] = wert.stdout.strip()
    from podcast import vertonung

    tts = vertonung.aus_umgebung()
    blocks = []
    for i, a in enumerate(d["aeusserungen"]):
        mp3 = tts.synthese(text=a["text"], voice=AZURE_STIMMEN[a["person"] % len(AZURE_STIMMEN)])
        pcm = mp3_zu_pcm(mp3)
        blocks.append({"kind": "utt", "audio": pcm, "person": a["person"], "punkt": a.get("punkt"),
                       "ereignisse": a.get("ereignisse", []), "text": a["text"]})
        if i < len(d["aeusserungen"]) - 1:
            blocks.append({"kind": "gap", "audio": np.zeros(int(GAP * RATE), dtype="<i2")})
    print(f"Vertonung (Azure, Teachbuddy): {tts.zeichen} Zeichen, 0 $ (eigenes Kontingent).")
    return blocks


def openai_tts(client, text: str, voice: str) -> np.ndarray:
    roh = client.audio.speech.create(model="gpt-4o-mini-tts", voice=voice, input=text, response_format="pcm",
                                     instructions="Sprich natürlich auf Deutsch, wie jemand in einer Sitzung.").content
    return np.frombuffer(roh, dtype="<i2")


def zeiten(blocks: list[dict]) -> list[float]:
    """Startzeit jedes Blocks in Sekunden (Blockgrenzen = mögliche Einfügestellen)."""
    t, aus = 0.0, []
    for b in blocks:
        aus.append(t)
        t += len(b["audio"]) / RATE
    aus.append(t)  # Ende der Aufnahme als letzte Grenze
    return aus


def naechste_grenze(blocks: list[dict], ziel_s: float, nur_punkt: int | None = None) -> int:
    """Blockindex, dessen Grenze (davor) der Zielzeit am nächsten liegt – optional nur innerhalb eines
    Agendapunkts (Grenze muss zwischen zwei Äußerungen desselben Punkts liegen, nicht mittenrein in eine)."""
    ts = zeiten(blocks)
    kandidaten = range(len(blocks) + 1)
    if nur_punkt is not None:
        kandidaten = [i for i in kandidaten
                     if (i == 0 or blocks[i - 1].get("punkt") in (nur_punkt, None))
                     and (i == len(blocks) or blocks[i].get("punkt") in (nur_punkt, None))]
    return min(kandidaten, key=lambda i: abs(ts[i] - ziel_s))


def einfuegen(blocks: list[dict], index: int, neue: list[dict]) -> None:
    blocks[index:index] = neue


def nestor_einfuegen(blocks: list[dict], client) -> list[dict]:
    """Die fünf Anweisungen chronologisch einfügen; jede verschiebt die Zeiten der folgenden Blöcke."""
    protokoll = []
    for n, e in enumerate(NESTOR_EINSCHUEBE):
        stimme = NESTOR_STIMMEN[n % len(NESTOR_STIMMEN)]
        i = naechste_grenze(blocks, e["ziel_s"])
        start = zeiten(blocks)[i]
        frage_audio = openai_tts(client, e["text"], stimme)
        neue = [{"kind": "silence", "audio": np.zeros(int(0.3 * RATE), dtype="<i2")},
                {"kind": "nestor", "audio": frage_audio, "art": "frage", "text": e["text"],
                 "recherche": e.get("recherche", False), "bild": e.get("bild", False)},
                {"kind": "silence", "audio": np.zeros(int(e["pause"] * RATE), dtype="<i2")}]
        frage_ende = start + 0.3 + len(frage_audio) / RATE
        protokoll.append({"ziel_s": e["ziel_s"], "start": round(start, 2), "ende": round(frage_ende, 2),
                          "text": e["text"], "recherche": e.get("recherche", False), "bild": e.get("bild", False),
                          "pause_s": e["pause"]})
        if "folge" in e:
            f = e["folge"]
            folge_audio = openai_tts(client, f["text"], stimme)
            folge_start = frage_ende + e["pause"] + 0.3
            neue += [{"kind": "silence", "audio": np.zeros(int(0.3 * RATE), dtype="<i2")},
                    {"kind": "nestor", "audio": folge_audio, "art": "frage", "text": f["text"],
                     "recherche": False, "bild": f.get("bild", False)},
                    {"kind": "silence", "audio": np.zeros(int(f["pause"] * RATE), dtype="<i2")}]
            protokoll.append({"ziel_s": e["ziel_s"] + e["pause"], "start": round(folge_start, 2),
                              "ende": round(folge_start + len(folge_audio) / RATE, 2), "text": f["text"],
                              "recherche": False, "bild": f.get("bild", False), "pause_s": f["pause"]})
        einfuegen(blocks, i, neue)
    return protokoll


def schnitzel_einfuegen(blocks: list[dict]) -> dict:
    with wave.open(str(WURZEL / "demo" / "messeplanung.wav")) as w:
        roh = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    von, bis = int(SCHNITZEL_QUELLE_START * RATE), int((SCHNITZEL_QUELLE_START + SCHNITZEL_DAUER) * RATE)
    schnitt = roh[von:bis]
    i = naechste_grenze(blocks, SCHNITZEL_ZIEL_S, nur_punkt=1)
    start = zeiten(blocks)[i]
    neue = [{"kind": "silence", "audio": np.zeros(int(0.3 * RATE), dtype="<i2")},
            {"kind": "schnitzel", "audio": schnitt},
            {"kind": "silence", "audio": np.zeros(int(0.3 * RATE), dtype="<i2")}]
    einfuegen(blocks, i, neue)
    return {"start": round(start + 0.3, 2), "ende": round(start + 0.3 + SCHNITZEL_DAUER, 2),
           "quelle": "demo/messeplanung.wav", "quelle_von_s": SCHNITZEL_QUELLE_START}


def referenz_bauen(blocks: list[dict]) -> list[dict]:
    """Ereignisse aus den Äußerungs-Blöcken (monolog, wechsel_ansage, abschweifung, kraftausdruck, beschluss,
    aufgabe_ohne_zustaendig) mit ihrer tatsächlichen Zeit in der fertigen Aufnahme."""
    ts = zeiten(blocks)
    aus = []
    for i, b in enumerate(blocks):
        if b["kind"] != "utt" or not b.get("ereignisse"):
            continue
        for e in b["ereignisse"]:
            aus.append({"ereignis": e, "zeit_s": round(ts[i], 2), "person": b["person"], "punkt": b["punkt"],
                       "text": b["text"]})
    return aus


async def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--neu", action="store_true", help="Drehbuch neu über Codex erzeugen statt das vorhandene zu nutzen")
    args = ap.parse_args()
    d = await drehbuch(neu=args.neu)
    blocks = azure_vertonen(d)
    from openai import OpenAI

    client = OpenAI(api_key=openai_schluessel())
    nestor_protokoll = nestor_einfuegen(blocks, client)
    schnitzel_protokoll = schnitzel_einfuegen(blocks)
    blocks = [{"kind": "intro", "audio": np.zeros(int(VORLAUF * RATE), dtype="<i2")}] + blocks

    ereignisse = referenz_bauen(blocks)
    audio = np.concatenate([b["audio"] for b in blocks])
    with wave.open(str(ZIEL / "meeting.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(audio.tobytes())

    # nestor_einfuegen/schnitzel_einfuegen haben vor dem Voranstellen des Vorlaufs gemessen - hier nachtragen.
    for p in nestor_protokoll:
        p["start"] = round(p["start"] + VORLAUF, 2)
        p["ende"] = round(p["ende"] + VORLAUF, 2)
    schnitzel_protokoll["start"] = round(schnitzel_protokoll["start"] + VORLAUF, 2)
    schnitzel_protokoll["ende"] = round(schnitzel_protokoll["ende"] + VORLAUF, 2)

    referenz = {
        "titel": d["titel"], "ziel": d["ziel"], "agenda": AGENDA, "dauer_s": round(len(audio) / RATE, 1),
        "vorlauf_s": VORLAUF, "ereignisse": ereignisse,
        "nestor": [{**p, "zeit_s": p["start"]} for p in nestor_protokoll],
        "schnitzel": schnitzel_protokoll,
    }
    (ZIEL / "referenz.json").write_text(json.dumps(referenz, ensure_ascii=False, indent=1), encoding="utf-8")

    agenda_text = (f"{d['titel']}. {d['ziel']}. Drei Punkte, zusammen etwa 45 Minuten: "
                   f"1. {AGENDA[0]['titel']} ({AGENDA[0]['ziel']}), "
                   f"2. {AGENDA[1]['titel']} ({AGENDA[1]['ziel']}), "
                   f"3. {AGENDA[2]['titel']} ({AGENDA[2]['ziel']}).")
    (ZIEL / "agenda_prompt.txt").write_text(agenda_text, encoding="utf-8")

    tts_sekunden = sum(len(b["audio"]) / RATE for b in blocks if b["kind"] == "nestor")
    kosten = round(tts_sekunden / 60 * 0.015, 4)
    print(f"meeting.wav: {len(audio) / RATE / 60:.2f} min, {len(ereignisse)} Ereignisse, "
          f"{len(nestor_protokoll)} Nestor-Anweisungen, Schnitzel bei {schnitzel_protokoll['start']}s.")
    print(f"OpenAI-Kosten (Nestor-Stimme, gpt-4o-mini-tts, {tts_sekunden:.1f}s Sprache): {kosten:.4f} $")


if __name__ == "__main__":
    asyncio.run(main())
