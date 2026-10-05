r"""Synthetische Meetings mit eingebauten Ereignissen – Referenz exakt bekannt, nur für die Logik.

    .venv\Scripts\python scripts\synthetisch_meeting.py drehbuch teamweekly "Team-Weekly einer Agentur …"
    .venv\Scripts\python scripts\synthetisch_meeting.py vertonen teamweekly [--azure]

Schritt 1 (drehbuch) schreibt Codex über das ChatGPT-Abo (keine API-Kosten): Agenda, Personen und Äußerungen,
jede mit Ereignis-Marken (wechsel_ansage, wechsel_still, monolog, unterbrechung, abschweifung, kraftausdruck,
angriff, beschluss, aufgabe_ohne_zustaendig, nestor_frage). Ergebnis: testbibliothek/synthetisch/<name>.json.
Schritt 2 (vertonen) macht daraus eine WAV mit je einer Stimme pro Person (gpt-4o-mini-tts, ~0,015 $ je Minute
Sprache) und schreibt die Referenz mit Zeitpunkten dazu. Synthetische Stimmen verwirren die Sprechertrennung
(Demo 05.10.) – für Akustik und Sprecher taugt das nicht, für Agenda, Regeln-Logik, Ergebnisse und Nestor schon.
"""

from __future__ import annotations

import asyncio
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.config import openai_schluessel  # noqa: E402
from coach.ki_abo import codex  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
ZIEL = WURZEL / "testbibliothek" / "synthetisch"
RATE = 24000
# am Stimmabgleich (CAM++) gewählt: möglichst unähnlich zueinander
STIMMEN = ["onyx", "nova", "verse", "ballad", "sage"]

AUFTRAG = """\
Schreibe das Drehbuch einer realistischen deutschen Besprechung: {thema}
Dauer etwa {minuten} Minuten gesprochener Text (rund {woerter} Wörter), {personen} Personen, natürliche
gesprochene Sprache mit Füllwörtern, Rückfragen und halben Sätzen – kein Theaterdialog.
Baue diese Ereignisse ein und markiere jede betroffene Äußerung: {ereignisse}.
Antworte nur mit JSON:
{{"titel": "...", "ziel": "...",
  "agenda": [{{"titel": "...", "ziel": "...", "minuten": 5}}],
  "personen": [{{"name": "Vorname", "rolle": "..."}}],
  "aeusserungen": [{{"person": 0, "text": "...", "punkt": 0, "ereignisse": ["monolog"]}}]}}
"punkt" ist der Agendapunkt (ab 0), zu dem die Äußerung inhaltlich gehört; bei einer Abschweifung -1.
Ereignis-Marken: wechsel_ansage, wechsel_still, monolog, unterbrechung (die Äußerung fällt der vorigen ins Wort),
abschweifung, kraftausdruck, angriff, beschluss, aufgabe_ohne_zustaendig, nestor_frage (beginnt mit „Nestor,“).
"""

STANDARD_EREIGNISSE = ("ein Agenda-Wechsel mit ausdrücklicher Ansage, einer ohne Ansage, ein Monolog von über 90 "
                       "Sekunden, zwei Unterbrechungen, eine Abschweifung, ein Beschluss, eine Aufgabe ohne "
                       "Zuständigen, zwei Fragen an den Moderationsassistenten Nestor")


async def drehbuch(name: str, thema: str, minuten: int = 15, personen: int = 4,
                   ereignisse: str = STANDARD_EREIGNISSE) -> None:
    text = await codex(AUFTRAG.format(thema=thema, minuten=minuten, woerter=minuten * 140, personen=personen,
                                      ereignisse=ereignisse), frist=600)
    d = json.loads(text)
    ZIEL.mkdir(parents=True, exist_ok=True)
    (ZIEL / f"{name}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    woerter = sum(len(a["text"].split()) for a in d["aeusserungen"])
    print(f"{name}: {len(d['aeusserungen'])} Äußerungen, {woerter} Wörter (~{woerter / 140:.0f} min), "
          f"Ereignisse: {sorted({e for a in d['aeusserungen'] for e in a.get('ereignisse', [])})}")


def mp3_zu_pcm(daten: bytes) -> np.ndarray:
    import io

    import av

    c = av.open(io.BytesIO(daten))
    rs = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    teile = [f.to_ndarray().reshape(-1) for fr in c.decode(c.streams.audio[0]) for f in rs.resample(fr)]
    c.close()
    return np.concatenate(teile).astype("<i2")


def azure_clips(name: str, d: dict) -> list[np.ndarray]:
    """Über Teachbuddys Azure-Vertonung auf dem Pi (freies Kontingent); Zugangsdaten bleiben dort."""
    import subprocess
    import tempfile

    fern = f"~/arbeit/lmc-vertonung/{name}"
    subprocess.run(["ssh", "-o", "BatchMode=yes", "pi", f"mkdir -p {fern}"], check=True)
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(ZIEL / f"{name}.json"),
                    str(WURZEL / "scripts" / "pi_vertonen.py"), f"pi:{fern}/"], check=True)
    subprocess.run(["ssh", "-o", "BatchMode=yes", "pi",
                    f"cd ~/repos/teachbuddy && source bin-zugang.sh >/dev/null 2>&1 && TEACHBUDDY_SPRECHTEMPO=1.0 "
                    f".venv/bin/python {fern}/pi_vertonen.py {fern}/{name}.json {fern}/mp3"], check=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["scp", "-q", "-r", "-o", "BatchMode=yes", f"pi:{fern}/mp3", tmp], check=True)
        return [mp3_zu_pcm((Path(tmp) / "mp3" / f"{i:04d}.mp3").read_bytes()) for i in range(len(d["aeusserungen"]))]


def openai_clips(d: dict) -> list[np.ndarray]:
    from openai import OpenAI

    client = OpenAI(api_key=openai_schluessel())
    return [np.frombuffer(client.audio.speech.create(
        model="gpt-4o-mini-tts", voice=STIMMEN[a["person"] % len(STIMMEN)], input=a["text"], response_format="pcm",
        instructions="Sprich natürlich auf Deutsch, wie in einer Besprechung.").content, dtype="<i2")
        for a in d["aeusserungen"]]


def vertonen(name: str, azure: bool = False) -> None:
    d = json.loads((ZIEL / f"{name}.json").read_text(encoding="utf-8"))
    clips = azure_clips(name, d) if azure else openai_clips(d)
    teile, referenz, t = [np.zeros(int(20 * RATE), dtype="<i2")], [], 20.0  # 20 s für Nestors Begrüßung
    for a, x in zip(d["aeusserungen"], clips):
        unterbricht = "unterbrechung" in a.get("ereignisse", [])
        luecke = 0.0 if unterbricht else 0.6
        if unterbricht and len(teile) > 1:  # in die letzten 0,8 s der vorigen Äußerung hineinsprechen
            vorher = teile.pop()
            n = min(len(vorher), int(0.8 * RATE))
            mix = vorher[-n:].astype(np.int32) + x[:n].astype(np.int32)
            teile += [vorher[:-n], np.clip(mix, -32768, 32767).astype("<i2"), x[n:]]
            t -= n / RATE
        else:
            teile += [np.zeros(int(luecke * RATE), dtype="<i2"), x]
            t += luecke
        referenz.append({"von": round(t, 2), "bis": round(t + len(x) / RATE, 2), "person": a["person"],
                         "punkt": a.get("punkt"), "ereignisse": a.get("ereignisse", []), "text": a["text"]})
        t += len(x) / RATE
        if "nestor_frage" in a.get("ereignisse", []):
            teile.append(np.zeros(int(22 * RATE), dtype="<i2"))  # Platz für Nestors Antwort
            t += 22
    audio = np.concatenate(teile)
    with wave.open(str(ZIEL / f"{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(audio.tobytes())
    meeting = {"titel": d["titel"], "ziel": d["ziel"], "agenda": d["agenda"], "regeln": [],
               "regel_ids": ["ausreden", "thema", "zeit", "kurz", "ton", "ergebnisse"], "teilnehmende": [],
               "assistent": True}
    (ZIEL / f"{name}.json.meeting").write_text(json.dumps(meeting, ensure_ascii=False, indent=1), encoding="utf-8")
    (ZIEL / f"{name}.referenz.json").write_text(json.dumps(referenz, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}.wav: {len(audio) / RATE / 60:.1f} min")


if __name__ == "__main__":
    if sys.argv[1] == "drehbuch":
        # drehbuch <name> <thema> [ereignisse] [minuten] [personen]
        ereignisse = sys.argv[4] if len(sys.argv) > 4 else STANDARD_EREIGNISSE
        asyncio.run(drehbuch(sys.argv[2], sys.argv[3], int(sys.argv[5]) if len(sys.argv) > 5 else 15,
                             int(sys.argv[6]) if len(sys.argv) > 6 else 4, ereignisse))
    elif sys.argv[1] == "vertonen":
        vertonen(sys.argv[2], azure="--azure" in sys.argv)
