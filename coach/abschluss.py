"""Abschlussseite: eigenes Paket, Unterstützung und Datenspende (Lastenheft 2 Schritt 5, 4.4–4.6).

Liest ausschließlich aus dem fertig geschriebenen `bericht.json` eines Meeting-Ordners (coach/archiv.py) –
so bleibt diese Datei unabhängig davon, ob das Meeting noch läuft oder der Coach längst zurückgesetzt ist.
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import datetime
from pathlib import Path

from .config import EINST

# Stufe, Bedeutung, Faktor auf die API-Kosten (Lastenheft 4.5)
STUFEN = (
    ("deckung", "Kosten sicher gedeckt", 2),
    ("fair", "plus Anteil an Entwicklung und Betrieb", 4),
    ("foerderer", "ermöglicht neue Funktionen", 8),
)


def stufen(kosten_usd: float) -> list[dict]:
    """Drei Unterstützungsvorschläge in Euro: aufgerundet, mindestens 2 €, streng steigend."""
    eur = max(kosten_usd, 0.0) * EINST.eur_je_usd
    ergebnis: list[dict] = []
    letzter = 0
    for id_, bedeutung, faktor in STUFEN:
        betrag = max(2, math.ceil(eur * faktor), letzter + 1)
        ergebnis.append({"id": id_, "bedeutung": bedeutung, "betrag": betrag})
        letzter = betrag
    return ergebnis


def _mmss(sekunden: float) -> str:
    s = max(0, round(sekunden))
    return f"{s // 60:02d}:{s % 60:02d}"


def _transkript_md(eintraege: list[dict]) -> str:
    zeilen = [f"**[{_mmss(e['start'])}] {e['sprecher']}:** {e['text']}" for e in eintraege]
    return "# Transkript\n\n" + ("\n\n".join(zeilen) if zeilen else "_Kein Transkript._") + "\n"


def _agenda_md(punkte: list[dict]) -> str:
    zeilen = [f"- **{p['titel']}** – {p['minuten']:.0f} min geplant, {p['genutzt'] / 60:.0f} min genutzt"
              for p in punkte]
    return "# Agenda\n\n" + ("\n".join(zeilen) if zeilen else "_Keine Agenda._") + "\n"


def _hinweise_md(hinweise: list[dict]) -> str:
    zeilen = [f"- [{_mmss(h['zeit'])}] {h['text']}" for h in hinweise]
    return "# Hinweise\n\n" + ("\n".join(zeilen) if zeilen else "_Keine Hinweise._") + "\n"


def _bericht(ordner: Path) -> dict:
    return json.loads((ordner / "bericht.json").read_text(encoding="utf-8"))


def paket(ordner: Path, mit_aufnahme: bool) -> bytes:
    """ZIP für die Runde: Protokoll, Abschlussbild bzw. Überblick, Transkript, Agenda, Hinweise, meeting.json und
    tasks.json (Ticket #26) – ohne debug/ und bericht.json."""
    ordner = Path(ordner)
    bericht = _bericht(ordner)
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
        protokoll = ordner / "protokoll.md"
        if protokoll.exists():
            z.write(protokoll, "protokoll.md")
        # Abschlussbild (Premium) bzw. Überblick als Text (Basis: steht an der Stelle des Bilds, Lastenheft 4.7)
        for bild in ("zusammenfassung.png", "zusammenfassung.svg", "ueberblick.md", "meeting.json", "tasks.json"):
            if (ordner / bild).exists():
                z.write(ordner / bild, bild)
        z.writestr("transkript.md", _transkript_md(bericht.get("transkript", [])))
        z.writestr("agenda.md", _agenda_md(bericht.get("agenda", [])))
        z.writestr("hinweise.md", _hinweise_md(bericht.get("hinweise", [])))
        if mit_aufnahme and (ordner / "aufnahme.wav").exists():
            z.write(ordner / "aufnahme.wav", "aufnahme.wav")
    return puffer.getvalue()


def spenden_dateien(ordner: Path, feedback: str, mit_aufnahme: bool) -> dict[str, bytes]:
    """Dateien für eine Datenspende: Transkript, Hinweise, Agenda, Dynamik, Feedback – optional die Aufnahme."""
    ordner = Path(ordner)
    bericht = _bericht(ordner)
    dateien = {
        "transkript.md": _transkript_md(bericht.get("transkript", [])).encode("utf-8"),
        "hinweise.md": _hinweise_md(bericht.get("hinweise", [])).encode("utf-8"),
        "agenda.md": _agenda_md(bericht.get("agenda", [])).encode("utf-8"),
        "dynamik.json": json.dumps(bericht.get("dynamik", {}), ensure_ascii=False, indent=1).encode("utf-8"),
        "feedback.txt": (feedback or "").encode("utf-8"),
    }
    if mit_aufnahme and (ordner / "aufnahme.wav").exists():
        dateien["aufnahme.wav"] = (ordner / "aufnahme.wav").read_bytes()
    return dateien


class Ablage:
    """Schnittstelle für Spenden-Ablagen – schmal gehalten, eine R2-Umsetzung kommt in einem anderen Ticket."""

    def ablegen(self, name: str, dateien: dict[str, bytes]) -> None:
        raise NotImplementedError


class OrdnerAblage(Ablage):
    """Lokaler Ordner `spenden/<datum>_<kurz-id>/` (Pfad aus LMC_SPENDEN)."""

    def __init__(self, wurzel: Path | str | None = None) -> None:
        self.wurzel = Path(wurzel) if wurzel is not None else Path(EINST.spenden)

    def ablegen(self, name: str, dateien: dict[str, bytes]) -> None:
        ordner = self.wurzel / f"{datetime.now():%Y-%m-%d}_{name}"
        ordner.mkdir(parents=True, exist_ok=True)
        for dateiname, inhalt in dateien.items():
            (ordner / dateiname).write_bytes(inhalt)
