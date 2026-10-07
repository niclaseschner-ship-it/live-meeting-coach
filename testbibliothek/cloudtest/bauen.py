r"""Baut das Testmaterial für den Cloud-Testlauf (scripts/cloudtest.py) aus vorhandenem Material statt neu
zu erzeugen (Nachtrag des Koordinators, 07.10.2026): Grundlage ist die schon fertig vertonte Probe
„vereinsrunde" unter ~/arbeit/lmc-vertonung/vereinsrunde/ (Azure-Stimmen, eine MP3 je Äußerung, Ereignis-
Marken wie scripts/synthetisch_meeting.py sie erzeugt). Sie deckt allein schon fünf der sechs geforderten
Ereignisse ab (siehe docs/testlauf_synthetisch.md): Monolog, zwei Ansagen beim Agendawechsel, Kraftausdruck,
Abschweifung, Beschluss mit Betrag. Nur eine Aufgabe ohne Zuständige/n fehlt und wird ergänzt.

    ~/.venvs/lmc/bin/python testbibliothek/cloudtest/bauen.py

Schritt 1: Aus den 60 Äußerungen die mit Ereignis-Marke plus so viel Füllmaterial wie ins Zeitbudget passt
behalten (Rest würde die Aufnahme weit über zehn Minuten treiben – vereinsrunde allein ist 19:42 min lang).
Schritt 2: Zu einer WAV zusammensetzen, wie scripts/synthetisch_meeting.py es beim Vertonen tut (0,6 s Pause
zwischen Äußerungen, 25 s Vorlauf für Nestors Begrüßung).
Schritt 3: Einfügen, was im Material fehlt – über Teachbuddys Azure auf diesem Rechner, selbe Stimmen-Familie,
keine OpenAI-Kosten:
  - die fünf Anweisungen an Nestor aus dem Ticket (Stimme „alloy", im Material ungenutzt)
  - eine kurze Aufgabe ohne genannte Zuständigkeit (Stimme einer der fünf Personen)
Ein echter Ausschnitt mit echten (nicht synthetischen) Stimmen aus einer öffentlichen Aufnahme ist laut
Nachtrag nur „wenn er sich ohne großen Aufwand ergänzen lässt" vorgesehen; das hätte yt-dlp, einen Download
und einen manuellen Zeitfenster-Zuschnitt gebraucht – ausgelassen, siehe Bericht.

Ergebnis in testbibliothek/cloudtest/: referenz.json, agenda_prompt.txt (im Git) und meeting.wav (per
.gitignore ausgenommen).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent.parent
ZIEL = WURZEL / "testbibliothek" / "cloudtest"
QUELLE = Path.home() / "arbeit" / "lmc-vertonung" / "vereinsrunde"
sys.path.insert(0, str(WURZEL))

RATE = 24000
VORLAUF = 25.0  # Lastenheft: Begrüßung + Zeitfenster für ein "Nein"
GAP = 0.6  # Pause zwischen zwei Äußerungen, wie scripts/synthetisch_meeting.py
UNTAGGED_BUDGET = 150  # Wörter an Füllmaterial zusätzlich zu den Ereignis-Äußerungen (Zeitbudget ~10 min)
PERSON_STIMMEN = ["onyx", "nova", "echo", "shimmer", "fable"]  # wie bei der Erstvertonung von vereinsrunde
NESTOR_STIMME = "alloy"  # im Material ungenutzt, deutlich von den fünf Personen unterscheidbar

# Fünf Anweisungen an Nestor (Ticket „Cloud-Testlauf", Lastenheft 4.2/Startseite „Live"); ziel_s = Zielsekunde
# in der fertigen Aufnahme (Vorlauf schon mitgezählt), nur zur Auswahl der nächstgelegenen Sprechpause.
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
# Fehlt im Quellmaterial (vereinsrunde hat keine "aufgabe_ohne_zustaendig"): eine Aufgabe, die genannt, aber
# niemandem zugewiesen wird – thematisch passend zum Vereinsbus, Stimme von Jörg (Kassenwart, Person 1).
AUFGABE_ZIEL_S = 480
AUFGABE_TEXT = ("Und für die Probefahrt mit dem möglichen Bus müsste auch noch jemand die Zusatzversicherung "
                "klären, bevor wir losfahren.")
AUFGABE_STIMME = PERSON_STIMMEN[1]


def mp3_zu_pcm(daten: bytes) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                        "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
                       input=daten, capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype="<i2")


def azure_tts():
    """Teachbuddys Azure-Adapter, lokal (dieses Skript läuft schon auf dem Pi, kein ssh nötig)."""
    teachbuddy = Path.home() / "repos" / "teachbuddy"
    sys.path.insert(0, str(teachbuddy))
    for ziel_var, name in (("HOERSPIEL_AZURE_OPENAI_ENDPOINT", "azure-openai-endpoint"),
                           ("HOERSPIEL_AZURE_OPENAI_KEY", "azure-openai-key"),
                           ("HOERSPIEL_AZURE_OPENAI_DEPLOYMENT", "azure-openai-deployment")):
        if not os.environ.get(ziel_var):
            wert = subprocess.run(["sudo", "-n", "zugang", "holen", name], capture_output=True, text=True)
            if wert.returncode == 0:
                os.environ[ziel_var] = wert.stdout.strip()
    from podcast import vertonung

    return vertonung.aus_umgebung()


def auswahl(d: dict) -> list[int]:
    """Welche Äußerungen bleiben: alle mit Ereignis-Marke, plus so viel Füllmaterial in Originalreihenfolge,
    wie ins Wortbudget passt (immer die ganze Äußerung, nicht gekürzt)."""
    kept, fuell_woerter = [], 0
    for i, a in enumerate(d["aeusserungen"]):
        w = len(a["text"].split())
        if a.get("ereignisse"):
            kept.append(i)
        elif fuell_woerter + w <= UNTAGGED_BUDGET:
            kept.append(i)
            fuell_woerter += w
    return kept


# Im Rollenspiel heißt eine der fünf Personen (Index 4) "Nestor" (Beisitzer für Infrastruktur) und wird an
# zwei Stellen beim Namen angesprochen bzw. genannt – das würde mit dem echten Assistenten Nestor
# verwechselt werden. Nachtrag des Koordinators (07.10.2026): ihre Äußerungen ganz heraus, die zwei
# Anrede-Stellen umgeschrieben (Text ohne "Nestor", neu vertont), eine Äußerung (Abschweifung) auf eine
# andere, schon vorhandene Stimme umgehängt statt sie zu verlieren. Danach kommt "Nestor" nur noch in den
# sechs Einschüben vor (geprüft in main()).
NESTOR_PERSON_INDEX = 4
AUSGESCHLOSSEN = {41}  # Antwort der Person "Nestor" - für kein Pflicht-Ereignis gebraucht
PERSON_UMGEHAENGT = {26: 3}  # Abschweifung: Text nennt "Nestor" nicht, nur die Stimme wechselt (-> Mehmet)
TEXT_ERSETZT = {
    40: ("Wir gehen jetzt zu Agendapunkt drei, der möglichen Anschaffung eines Vereinsbusses. Wir haben noch "
        "ungefähr vier Minuten. Lasst uns zuerst einen Überblick verschaffen, was ein gebrauchter Neunsitzer "
        "kostet und mit welchen laufenden Kosten wir rechnen müssen.", ["wechsel_ansage"]),
    56: ("Wir legen uns heute auf kein Fahrzeug fest. Bis zur nächsten Sitzung stellen wir eine Übersicht mit "
        "drei gebrauchten Neunsitzern zusammen: vollständige Anschaffungsnebenkosten, geschätzte Jahreskosten, "
        "Fördermöglichkeiten, Leasingvergleich und eine Gegenüberstellung zu unseren bisherigen Miet- und "
        "Fahrtkosten. Sabine liefert dafür bis Freitag die Fahrten der Jugend aus dem letzten Jahr, Jörg die "
        "verbuchten Miet- und Erstattungskosten. Dann können wir entscheiden, ob wir einen konkreten "
        "Finanzierungsrahmen aufstellen.", ["monolog"]),
}


def nestor_pruefen(d: dict, indizes: list[int]) -> None:
    treffer = [i for i in indizes if "Nestor" in (TEXT_ERSETZT.get(i, (d["aeusserungen"][i]["text"],))[0])]
    if treffer:
        raise AssertionError(f"'Nestor' kommt noch in Äußerung(en) {treffer} vor - Material nicht sauber.")


def blocks_aus_quelle(d: dict, indizes: list[int], tts) -> list[dict]:
    indizes = [i for i in indizes if i not in AUSGESCHLOSSEN]
    nestor_pruefen(d, indizes)
    blocks = []
    for n, i in enumerate(indizes):
        a = d["aeusserungen"][i]
        person = PERSON_UMGEHAENGT.get(i, a["person"])
        if i in TEXT_ERSETZT:
            text, ereignisse = TEXT_ERSETZT[i]
            audio = mp3_zu_pcm(tts.synthese(text=text, voice=PERSON_STIMMEN[person % len(PERSON_STIMMEN)]))
        elif i in PERSON_UMGEHAENGT:
            text, ereignisse = a["text"], a.get("ereignisse", [])
            audio = mp3_zu_pcm(tts.synthese(text=text, voice=PERSON_STIMMEN[person % len(PERSON_STIMMEN)]))
        else:
            text, ereignisse = a["text"], a.get("ereignisse", [])
            audio = mp3_zu_pcm((QUELLE / "mp3" / f"{i:04d}.mp3").read_bytes())
        blocks.append({"kind": "utt", "audio": audio, "person": person, "punkt": a.get("punkt"),
                       "ereignisse": ereignisse, "text": text})
        if n < len(indizes) - 1:
            blocks.append({"kind": "gap", "audio": np.zeros(int(GAP * RATE), dtype="<i2")})
    return blocks


def zeiten(blocks: list[dict]) -> list[float]:
    """Startzeit jedes Blocks in Sekunden (Blockgrenzen = mögliche Einfügestellen)."""
    t, aus = 0.0, []
    for b in blocks:
        aus.append(t)
        t += len(b["audio"]) / RATE
    aus.append(t)
    return aus


def naechste_grenze(blocks: list[dict], ziel_s: float) -> int:
    ts = zeiten(blocks)
    return min(range(len(blocks) + 1), key=lambda i: abs(ts[i] - ziel_s))


def einfuegen(blocks: list[dict], index: int, neue: list[dict]) -> None:
    blocks[index:index] = neue


def nestor_einfuegen(blocks: list[dict], tts) -> list[dict]:
    protokoll = []
    for e in NESTOR_EINSCHUEBE:
        i = naechste_grenze(blocks, e["ziel_s"])
        start = zeiten(blocks)[i]
        frage_audio = mp3_zu_pcm(tts.synthese(text=e["text"], voice=NESTOR_STIMME))
        neue = [{"kind": "silence", "audio": np.zeros(int(0.3 * RATE), dtype="<i2")},
                {"kind": "nestor", "audio": frage_audio, "text": e["text"],
                 "recherche": e.get("recherche", False), "bild": e.get("bild", False)},
                {"kind": "silence", "audio": np.zeros(int(e["pause"] * RATE), dtype="<i2")}]
        frage_ende = start + 0.3 + len(frage_audio) / RATE
        protokoll.append({"ziel_s": e["ziel_s"], "start": round(start, 2), "ende": round(frage_ende, 2),
                          "text": e["text"], "recherche": e.get("recherche", False), "bild": e.get("bild", False),
                          "pause_s": e["pause"]})
        if "folge" in e:
            f = e["folge"]
            folge_audio = mp3_zu_pcm(tts.synthese(text=f["text"], voice=NESTOR_STIMME))
            folge_start = frage_ende + e["pause"] + 0.3
            neue += [{"kind": "silence", "audio": np.zeros(int(0.3 * RATE), dtype="<i2")},
                    {"kind": "nestor", "audio": folge_audio, "text": f["text"],
                     "recherche": False, "bild": f.get("bild", False)},
                    {"kind": "silence", "audio": np.zeros(int(f["pause"] * RATE), dtype="<i2")}]
            protokoll.append({"ziel_s": e["ziel_s"] + e["pause"], "start": round(folge_start, 2),
                              "ende": round(folge_start + len(folge_audio) / RATE, 2), "text": f["text"],
                              "recherche": False, "bild": f.get("bild", False), "pause_s": f["pause"]})
        einfuegen(blocks, i, neue)
    return protokoll


def aufgabe_einfuegen(blocks: list[dict], tts) -> dict:
    i = naechste_grenze(blocks, AUFGABE_ZIEL_S)
    start = zeiten(blocks)[i]
    audio = mp3_zu_pcm(tts.synthese(text=AUFGABE_TEXT, voice=AUFGABE_STIMME))
    neue = [{"kind": "silence", "audio": np.zeros(int(0.3 * RATE), dtype="<i2")},
            {"kind": "utt", "audio": audio, "person": 1, "punkt": 2, "ereignisse": ["aufgabe_ohne_zustaendig"],
             "text": AUFGABE_TEXT},
            {"kind": "silence", "audio": np.zeros(int(0.4 * RATE), dtype="<i2")}]
    einfuegen(blocks, i, neue)
    return {"ziel_s": AUFGABE_ZIEL_S, "start": round(start + 0.3, 2),
           "ende": round(start + 0.3 + len(audio) / RATE, 2), "text": AUFGABE_TEXT}


def referenz_bauen(blocks: list[dict]) -> list[dict]:
    ts = zeiten(blocks)
    aus = []
    for i, b in enumerate(blocks):
        if b["kind"] != "utt" or not b.get("ereignisse"):
            continue
        for e in b["ereignisse"]:
            aus.append({"ereignis": e, "zeit_s": round(ts[i], 2), "person": b["person"], "punkt": b["punkt"],
                       "text": b["text"]})
    return aus


def main() -> None:
    d = json.loads((QUELLE / "vereinsrunde.json").read_text(encoding="utf-8"))
    indizes = auswahl(d)
    woerter = sum(len(d["aeusserungen"][i]["text"].split()) for i in indizes)
    print(f"Quelle: vereinsrunde, {len(indizes)}/{len(d['aeusserungen'])} Äußerungen behalten, "
          f"{woerter} Wörter (~{woerter / 140:.1f} min).")

    tts = azure_tts()
    blocks = blocks_aus_quelle(d, indizes, tts)
    nestor_protokoll = nestor_einfuegen(blocks, tts)
    aufgabe_protokoll = aufgabe_einfuegen(blocks, tts)
    print(f"Azure (Teachbuddy, eigenes Kontingent): {tts.zeichen} Zeichen, 0 $.")

    blocks = [{"kind": "intro", "audio": np.zeros(int(VORLAUF * RATE), dtype="<i2")}] + blocks
    for p in nestor_protokoll:
        p["start"] = round(p["start"] + VORLAUF, 2)
        p["ende"] = round(p["ende"] + VORLAUF, 2)
    aufgabe_protokoll["start"] = round(aufgabe_protokoll["start"] + VORLAUF, 2)
    aufgabe_protokoll["ende"] = round(aufgabe_protokoll["ende"] + VORLAUF, 2)

    ereignisse = referenz_bauen(blocks)
    audio = np.concatenate([b["audio"] for b in blocks])
    ZIEL.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ZIEL / "meeting.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(audio.tobytes())

    referenz = {
        "quelle": "vereinsrunde (~/arbeit/lmc-vertonung), gekürzt auf Ereignis-Äußerungen + Füllmaterial",
        "titel": d["titel"], "ziel": d["ziel"], "agenda": d["agenda"], "dauer_s": round(len(audio) / RATE, 1),
        "vorlauf_s": VORLAUF, "ereignisse": ereignisse,
        "nestor": [{**p, "zeit_s": p["start"]} for p in nestor_protokoll],
        "aufgabe_ohne_zustaendig_ergaenzt": aufgabe_protokoll,
        "echte_stimmen_ausschnitt": "ausgelassen (yt-dlp/Download/Zuschnitt zu aufwändig für diesen Lauf, "
                                    "siehe Bericht) - Material ist durchgehend synthetisch (Azure).",
    }
    (ZIEL / "referenz.json").write_text(json.dumps(referenz, ensure_ascii=False, indent=1), encoding="utf-8")

    agenda_text = (
        "Betreff: Einladung Vorstandssitzung SV Eichenfeld - Donnerstag, 19 Uhr\n\n"
        "Hallo zusammen,\n\n"
        "am Donnerstag um 19 Uhr treffen wir uns zur Vorstandssitzung. Teilnehmende: "
        # Person "Nestor" kommt in der gekürzten Aufnahme nicht mehr zu Wort (s.o.) - auch nicht einladen.
        + ", ".join(p["name"] for i, p in enumerate(d["personen"]) if i != NESTOR_PERSON_INDEX) + ".\n\n"
        "Agenda:\n"
        + "\n".join(f"{i + 1}. {p['titel']} (ca. {p['minuten']} Min.) - {p['ziel']}"
                    for i, p in enumerate(d["agenda"]))
        + "\n\nBis Donnerstag!\nMartina\n"
    )
    (ZIEL / "agenda_prompt.txt").write_text(agenda_text, encoding="utf-8")

    print(f"meeting.wav: {len(audio) / RATE / 60:.2f} min, {len(ereignisse)} Ereignisse, "
          f"{len(nestor_protokoll)} Nestor-Anweisungen, Aufgabe ohne Zuständig bei {aufgabe_protokoll['start']}s.")


if __name__ == "__main__":
    main()
