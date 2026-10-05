r"""Experiment: Live-Bild über OpenAI-Bildgenerierung statt SVG von Claude.

    .venv\Scripts\python scripts\bild_gpt_experiment.py

Varianten auf dem Stadtrat-Transkript (Stand 10:00), Ausgabe in logs/onepager/gpt/:
  A  wie ChatGPT: GPT-5.4 bekommt Transkript + Auftrag und ruft das Werkzeug image_generation selbst auf
  B  unsere Strukturanalyse (logs/onepager/messung/final_10min/analyse.md) direkt an das Bildmodell, medium
  C  wie B, Qualität high
Gemessen: Dauer und Token-Nutzung (für die Kosten).
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import coach.config  # noqa: E402,F401  – lädt .env
from openai import OpenAI  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
ZIEL = WURZEL / "logs" / "onepager" / "gpt"
BILDMODELL = sys.argv[1] if len(sys.argv) > 1 else "gpt-image-2"

AUFTRAG = """\
Erstelle eine visuelle Zusammenfassung dieses Meetings als One-Pager-Infografik im Querformat (16:9) –
so, dass die Runde auf dem Beamer auf einen Blick sieht: Wo stehen wir, was ist entschieden, was ist offen,
wie hängen die Themen zusammen. Kein Fließtext-Protokoll.

Gestaltung: moderne, ruhige Business-Infografik, heller Hintergrund, klare Raster und Karten, schlichte
Linien-Icons, sparsame Farben mit Bedeutung (Grün = entschieden, Bernstein = offen, Blau = aktuell,
Grau = außerhalb der Agenda). Oben Titel und eine Kernaussage, darunter die Agenda als Fortschrittsleiste,
in der Mitte die Themen mit kurzen Kernaussagen, Beschlüsse mit Ergebnis gut sichtbar.
Alle Texte auf Deutsch, korrekt geschrieben, kurz (Stichworte), gut lesbar. Pfeile und Linien dürfen keinen
Text überdecken. Nur Inhalte aus dem Material unten, nichts erfinden. Personen nicht namentlich bewerten.
"""


def meeting_text() -> str:
    from coach.onepager import meeting_text as mt
    from coach.pipeline import Coach
    from coach.zustand import Segment

    probe = json.loads((WURZEL / "testbibliothek" / "proben" / "stadtrat" / "probe.json").read_text(encoding="utf-8"))
    bericht = json.loads((WURZEL / "logs" / "bericht_stadtrat_fremd.json").read_text(encoding="utf-8"))
    c = Coach()
    c._einrichten(probe["meeting"])
    m = c.meeting
    m.starten(virtuell=True)
    m.virtuelle_zeit = 600
    m.transkript = [Segment(s["sprecher"], s["text"], s["start"], s["ende"]) for s in bericht["transkript"] if s["start"] < 600]
    for e in bericht["protokoll"]:
        if e.get("art") == "wechsel" and e["zeit"] <= 600:
            m.punkt_wechseln(e["nach"])
    return mt(m)


def speichern(name: str, b64: str, messung: dict) -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    (ZIEL / f"{name}.png").write_bytes(base64.b64decode(b64))
    (ZIEL / f"{name}.json").write_text(json.dumps(messung, indent=1, default=str), encoding="utf-8")
    print(name, json.dumps(messung, default=str)[:400], flush=True)


def main() -> None:
    c = OpenAI()
    daten = meeting_text()
    analyse = (WURZEL / "logs" / "onepager" / "messung" / "final_10min" / "analyse.md").read_text(encoding="utf-8")

    # A: wie ChatGPT – Sprachmodell liest das Material und ruft den Bildgenerator selbst auf
    t0 = time.monotonic()
    r = c.responses.create(model="gpt-5.4", input=AUFTRAG + "\n\nMATERIAL (Agenda und Transkript):\n" + daten,
                           tools=[{"type": "image_generation", "model": BILDMODELL, "size": "1536x1024",
                                   "quality": "medium"}],
                           tool_choice={"type": "image_generation"})
    bild = next((o for o in r.output if o.type == "image_generation_call"), None)
    if bild is not None and bild.result:
        speichern("A_wie_chatgpt", bild.result, {"sekunden": round(time.monotonic() - t0, 1), "usage": r.usage,
                                                 "bildauftrag": getattr(bild, "revised_prompt", None)})
    else:
        print("A: kein Bild", r.output)

    # B/C: unsere Strukturanalyse direkt an das Bildmodell
    for name, qualitaet in (("B_analyse_medium", "medium"), ("C_analyse_high", "high")):
        t0 = time.monotonic()
        r = c.images.generate(model=BILDMODELL, prompt=AUFTRAG + "\n\nSTRUKTURANALYSE:\n" + analyse,
                              size="1536x1024", quality=qualitaet)
        speichern(name, r.data[0].b64_json, {"sekunden": round(time.monotonic() - t0, 1), "usage": r.usage})


if __name__ == "__main__":
    main()
