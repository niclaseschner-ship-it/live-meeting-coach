r"""Experiment: Fortschreibung – GPT bekommt das letzte Bild als Vorlage und aktualisiert es (Stand 12:40).

    .venv\Scripts\python scripts\bild_gpt_fortschreiben.py
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bild_gpt_experiment as exp  # noqa: E402
from openai import OpenAI  # noqa: E402

FORTSCHREIBUNG = """\
Das angehängte Bild ist die visuelle Zusammenfassung dieses Meetings von vorhin. Aktualisiere es auf den neuen
Stand (Material unten): Layout, Farben, Icons und Positionen bleiben gleich, damit die Runde den Fortschritt
sieht. Ändere nur, was sich inhaltlich getan hat (Agenda-Fortschritt, neue Beschlüsse, neue offene Punkte, Stand
oben) und markiere Neues dezent mit einem kleinen Etikett „neu“. Alle Texte auf Deutsch, korrekt, kurz.
"""


def main() -> None:
    c = OpenAI()
    alt = base64.b64encode((exp.ZIEL / "A_wie_chatgpt.png").read_bytes()).decode()
    exp_text = exp.meeting_text  # Stand 10:00 – für 12:40 die Zeitgrenze anheben

    import coach.onepager as op
    from coach.pipeline import Coach
    from coach.zustand import Segment
    probe = json.loads((exp.WURZEL / "testbibliothek" / "proben" / "stadtrat" / "probe.json").read_text(encoding="utf-8"))
    bericht = json.loads((exp.WURZEL / "logs" / "bericht_stadtrat_fremd.json").read_text(encoding="utf-8"))
    co = Coach(); co._einrichten(probe["meeting"]); m = co.meeting; m.starten(virtuell=True); m.virtuelle_zeit = 760
    m.transkript = [Segment(s["sprecher"], s["text"], s["start"], s["ende"]) for s in bericht["transkript"]]
    for e in bericht["protokoll"]:
        if e.get("art") == "wechsel":
            m.punkt_wechseln(e["nach"])
    daten = op.meeting_text(m)
    del exp_text

    t0 = time.monotonic()
    r = c.responses.create(
        model="gpt-5.4",
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": FORTSCHREIBUNG + "\n\nNEUES MATERIAL (Agenda und Transkript):\n" + daten},
            {"type": "input_image", "image_url": f"data:image/png;base64,{alt}"}]}],
        tools=[{"type": "image_generation", "model": exp.BILDMODELL, "size": "1536x1024", "quality": "medium",
                "action": "edit"}],
        tool_choice={"type": "image_generation"})
    bild = next((o for o in r.output if o.type == "image_generation_call"), None)
    exp.speichern("A2_fortgeschrieben_1240", bild.result, {"sekunden": round(time.monotonic() - t0, 1), "usage": r.usage})


if __name__ == "__main__":
    main()
