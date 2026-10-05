"""Live-Bild über OpenAI (Standard): GPT-5.4 liest Agenda und Transkript und ruft den Bildgenerator selbst auf –
so wie ChatGPT es macht. Ab dem zweiten Bild bekommt es das letzte Bild als Vorlage und schreibt es fort.

Experiment 05.10.2026 (scripts/bild_gpt_experiment.py, Stadtrat 10:00 und 12:40): saubereres Layout als unsere
SVGs (keine Pfeile im Text), korrektes Deutsch; Fortschreibung behält Layout, Icons und Positionen und markiert
Neues mit „neu“. ~55 s und ~7–8 Cent je Bild (Qualität medium, 1536×1024).
"""

from __future__ import annotations

import base64
import time

from .config import EINST
from .onepager import meeting_text
from .zustand import Meeting

AUFTRAG = """\
Erstelle eine visuelle Zusammenfassung dieses Meetings als One-Pager-Infografik im Querformat (16:9) –
so, dass die Runde auf dem Beamer auf einen Blick sieht: Wo stehen wir, was ist entschieden, was ist offen,
wie hängen die Themen zusammen. Kein Fließtext-Protokoll.

Gestaltung: moderne, ruhige Business-Infografik, heller Hintergrund, klare Raster und Karten, schlichte
Linien-Icons, sparsame Farben mit Bedeutung (Grün = entschieden, Bernstein = offen, Blau = aktuell,
Grau = außerhalb der Agenda). Oben Titel und eine Kernaussage, darunter die Agenda als Fortschrittsleiste,
in der Mitte die Themen mit kurzen Kernaussagen, Beschlüsse mit Ergebnis gut sichtbar. Abschweifungen ohne
Bezug zur Agenda als eigener, grau abgesetzter Bereich „außerhalb der Agenda“.
Alle Texte auf Deutsch, korrekt geschrieben, kurz (Stichworte), gut lesbar. Pfeile und Linien dürfen keinen
Text überdecken. Nur Inhalte aus dem Material unten, nichts erfinden. Personen nicht namentlich bewerten;
Sprecher heißen im Material „Person N“ und erscheinen nicht im Bild.
"""

FORTSCHREIBUNG = """\
Das angehängte Bild ist die visuelle Zusammenfassung dieses Meetings von vorhin. Aktualisiere es auf den neuen
Stand (Material unten): Layout, Farben, Icons und Positionen bleiben gleich, damit die Runde den Fortschritt
sieht. Ändere nur, was sich inhaltlich getan hat (Agenda-Fortschritt, neue Beschlüsse, neue offene Punkte,
Stand oben), entferne alte „neu“-Etiketten und markiere Neues dezent mit einem kleinen Etikett „neu“.
"""

FOKUS = """\
FOKUS DIESES BILDES (auf Wunsch der Runde): {fokus}
Zeige nur, was zu diesem Fokus gehört, dafür ausführlicher. Titel oben mit dem Fokus als Untertitel.
"""


async def erzeugen(client, meeting: Meeting, vorher: dict | None = None, fokus: str | None = None) -> dict:
    """Liefert {png, analyse (Bildauftrag als Text, für Nestor), messung}."""
    t0 = time.monotonic()
    text = AUFTRAG
    if fokus:
        text += "\n" + FOKUS.format(fokus=fokus)
    inhalt = [{"type": "input_text", "text": text + "\n\nMATERIAL (Agenda und Transkript):\n" + meeting_text(meeting)}]
    werkzeug = {"type": "image_generation", "model": EINST.bild_modell, "size": "1536x1024",
                "quality": EINST.bild_qualitaet}
    if vorher and vorher.get("png") and not fokus:
        inhalt[0]["text"] = FORTSCHREIBUNG + "\n" + inhalt[0]["text"]
        inhalt.append({"type": "input_image",
                       "image_url": "data:image/png;base64," + base64.b64encode(vorher["png"]).decode()})
        werkzeug["action"] = "edit"
    antwort = await client.responses.create(
        model=EINST.bild_text_modell, input=[{"role": "user", "content": inhalt}],
        tools=[werkzeug], tool_choice={"type": "image_generation"})
    bild = next((o for o in antwort.output if getattr(o, "type", "") == "image_generation_call"), None)
    if bild is None or not bild.result:
        raise RuntimeError("Kein Bild erhalten")
    nutzung = getattr(antwort, "usage", None)
    return {"png": base64.b64decode(bild.result),
            "analyse": getattr(bild, "revised_prompt", None) or "",
            "messung": [{"modell": f"{EINST.bild_text_modell}+{EINST.bild_modell}",
                         "sekunden": round(time.monotonic() - t0, 1),
                         "tokens_rein": getattr(nutzung, "input_tokens", None),
                         "tokens_raus": getattr(nutzung, "output_tokens", None),
                         "fortschreibung": bool(vorher and vorher.get("png") and not fokus)}]}
