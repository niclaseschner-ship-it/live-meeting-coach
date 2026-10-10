"""Meeting als Text für die Live-Bild- und Überblick-Aufträge (coach/bild_gpt.py, coach/ueberblick.py).

Der frühere Zeichenweg über das Claude-Abo (`claude -p`, SVG) ist mit Ticket #60 entfernt: Premium zeichnet das
Live-Bild ausschließlich mit OpenAI, Basis schreibt den Überblick als Text mit Mistral.
"""

from __future__ import annotations

from .analyse import mmss
from .zustand import Meeting

MAX_TRANSKRIPT_ZEICHEN = 30000


def meeting_text(meeting: Meeting) -> str:
    zeilen = [f"Titel: {meeting.titel or '-'}", f"Ziel: {meeting.ziel or '-'}",
              f"Laufzeit bisher: {mmss(meeting.jetzt())} Minuten", "", "Agenda:"]
    for i, p in enumerate(meeting.agenda, start=1):
        zeilen.append(f"{i}. {p.titel}" + (f" – {p.ziel}" if p.ziel else "")
                      + f" [{meeting.status(i - 1)}]")
    transkript = "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in meeting.transkript if s.text)
    zeilen += ["", "Transkript:", transkript[-MAX_TRANSKRIPT_ZEICHEN:]]
    return "\n".join(zeilen)
