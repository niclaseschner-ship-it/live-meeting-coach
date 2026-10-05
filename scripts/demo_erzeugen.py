r"""Demo-Meeting „Messeplanung 2027“ synthetisch erzeugen (frei verwendbar, keine fremde Aufnahme).

    .venv\Scripts\python scripts\demo_erzeugen.py

Schreibt demo/messeplanung.wav (24 kHz mono) und demo/messeplanung.json (Einrichtung: Agenda, Regeln, Nestor).
Drei Stimmen, ~3 Minuten, zeigt: Agenda-Wechsel auf Ansage, Abschweifung, Kraftausdruck, Beschlüsse,
Fragen an Nestor und das Live-Bild auf Zuruf. Am Anfang bleibt Stille für Nestors Begrüßung, nach jeder
Frage an Nestor Platz für seine Antwort. Kosten: ~3 min Sprachausgabe, wenige Cent.
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.config import openai_schluessel  # noqa: E402  – lädt .env bzw. den im Dashboard eingetragenen Schlüssel
from openai import OpenAI  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
ZIEL = WURZEL / "demo"
RATE = 24000
MEETING = {
    "titel": "Messeplanung 2027", "ziel": "Stand, Budget und Aufgaben für die Fachmesse im April festlegen",
    "agenda": [{"titel": "Termin und Messestand", "ziel": "Standgröße und Lage entscheiden", "minuten": 1},
               {"titel": "Budget", "ziel": "Obergrenze beschließen", "minuten": 1},
               {"titel": "Aufgaben verteilen", "ziel": "Wer macht was bis wann", "minuten": 1}],
    "regeln": [], "regel_ids": ["ausreden", "thema", "zeit", "kurz", "ton", "ergebnisse"],
    "teilnehmende": [], "assistent": True,
}
A, B, C = "onyx", "nova", "verse"  # am Stimmabgleich gewählt: deutlich verschieden voneinander
# (Startzeit in s, Stimme, Text)
DIALOG = [
    (25, A, "Danke, Nestor. Dann starten wir mit Punkt eins, Termin und Messestand. Die Messe ist vom vierzehnten bis sechzehnten April in Stuttgart."),
    (34, B, "Ich würde einen Stand mit vierzig Quadratmetern nehmen, damit wir die neue Maschine zeigen können."),
    (41, C, "Vierzig ist gut, aber dann brauchen wir einen Eckstand, sonst sieht uns da keiner."),
    (48, A, "Einverstanden. Dann halten wir fest: vierzig Quadratmeter, Eckstand. Ich buche das bis Freitag."),
    (56, C, "Übrigens, habt ihr gestern das Spiel gesehen? Der Elfmeter in der Nachspielzeit war ja unglaublich."),
    (63, B, "Ja, Wahnsinn. Aber der Schiedsrichter lag komplett daneben, das war nie ein Foul."),
    (70, C, "Und dann noch die rote Karte, das ganze Stadion hat gepfiffen."),
    (77, A, "Leute, zurück zur Messe bitte."),
    (82, A, "Nun gehen wir weiter zu Punkt zwei, Budget."),
    (87, B, "Für Stand, Aufbau und Reisen haben wir letztes Jahr zweiundzwanzigtausend Euro gebraucht."),
    (95, C, "So ein Scheiß, die Standmiete ist dieses Jahr schon wieder um zwanzig Prozent teurer geworden."),
    (103, B, "Deshalb schlage ich fünfundzwanzigtausend Euro als Obergrenze vor."),
    (109, A, "Gibt es Einwände? Gut, dann ist beschlossen: höchstens fünfundzwanzigtausend Euro."),
    (117, C, "Nestor, wo stehen wir gerade?"),
    (140, A, "Danke. Dann gehen wir weiter zu Punkt drei, Aufgaben verteilen."),
    (146, B, "Ich kümmere mich um den Standbau und hole bis Ende Oktober drei Angebote ein."),
    (153, C, "Ich übernehme die Flyer und die Einladungen an unsere Kunden."),
    (159, A, "Offen ist noch, wer die Hotels bucht. Das klären wir nächste Woche."),
    (166, B, "Nestor, zeig uns bitte die Übersicht."),
    (182, A, "Super, danke euch allen. Bis nächste Woche."),
]


def main() -> None:
    client = OpenAI(api_key=openai_schluessel())
    clips = []
    for t, stimme, text in DIALOG:
        roh = client.audio.speech.create(model="gpt-4o-mini-tts", voice=stimme, input=text, response_format="pcm",
                                         instructions="Sprich natürlich und zügig auf Deutsch, wie in einer Teambesprechung.").content
        clips.append((t, np.frombuffer(roh, dtype="<i2")))
    # Startzeit = geplante Zeit, frühestens 0,6 s nach dem Ende der vorigen Äußerung (keine Überlappung)
    plan, ende = [], 0.0
    for t, a in clips:
        start = max(t, ende + 0.6)
        plan.append((start, a))
        ende = start + len(a) / RATE
    audio = np.zeros(int((ende + 6) * RATE), dtype="<i2")
    for start, a in plan:
        i = int(start * RATE)
        audio[i:i + len(a)] = a
    ZIEL.mkdir(exist_ok=True)
    with wave.open(str(ZIEL / "messeplanung.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(audio.tobytes())
    (ZIEL / "messeplanung.json").write_text(json.dumps(MEETING, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"demo/messeplanung.wav: {len(audio) / RATE:.0f} s, {len(DIALOG)} Äußerungen")
    for (start, a), (_, _, text) in zip(plan, DIALOG):
        print(f"  {start:6.1f}–{start + len(a) / RATE:6.1f}  {text[:60]}")


if __name__ == "__main__":
    main()
