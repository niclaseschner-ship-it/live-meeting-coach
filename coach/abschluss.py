"""Abschlussseite: eigenes Paket, Unterstützung und Datenspende (Lastenheft 2 Schritt 5, 4.4–4.6).

Liest ausschließlich aus dem fertig geschriebenen `bericht.json` eines Meeting-Ordners (coach/archiv.py) –
so bleibt diese Datei unabhängig davon, ob das Meeting noch läuft oder der Coach längst zurückgesetzt ist.
"""

from __future__ import annotations

import html
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


def meeting_daten(ordner: Path) -> dict:
    """Korrigier- und kopierbare Standardgliederung aus Ticket #22."""
    pfad = Path(ordner) / "meeting.json"
    return json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else {
        "kopf": {"titel": _bericht(Path(ordner)).get("titel", "Meeting")}, "entscheidungen": [], "aufgaben": [],
        "offene_punkte": [], "risiken": [], "parkplatz": [], "agenda": [], "luecken": 0,
    }


def meeting_markdown(d: dict, regelanalyse: dict | None = None) -> str:
    k = d.get("kopf", {})
    out = [f"# {k.get('titel') or 'Meeting'}", "", f"**Datum:** {k.get('datum') or '–'}  ",
           f"**Dauer:** {_mmss(k.get('dauer_sekunden') or 0)}", ""]
    def liste(titel: str, key: str, felder: tuple[str, ...]) -> None:
        out.extend([f"## {titel}", ""])
        werte = d.get(key) or []
        if not werte:
            out.extend(["_Keine._", ""])
            return
        for x in werte:
            teile = [str(x.get(f) or "⚠ fehlt") for f in felder]
            out.append("- " + " · ".join(teile))
        out.append("")
    liste("Entscheidungen", "entscheidungen", ("was", "status", "wer"))
    liste("Aufgaben", "aufgaben", ("was", "wer", "bis"))
    liste("Offene Punkte", "offene_punkte", ("was", "wer", "bis"))
    liste("Risiken", "risiken", ("was", "wer", "reaktion"))
    liste("Parkplatz", "parkplatz", ("was",))
    out.extend(["## Agenda", ""])
    agenda = d.get("agenda") or []
    if not agenda:
        out.append("_Keine._")
    for p in agenda:
        out.append(f"- {p.get('nr') or '–'}. {p.get('titel') or '⚠ fehlt'} – "
                   f"{p.get('soll_minuten') or 0} min geplant, {p.get('ist_minuten') or 0} min genutzt")
    if regelanalyse:
        out.extend(["", "## Regelanalyse", "", "### Redeanteile", ""])
        out.extend(f"- {n}: {s:.0f} s" for n, s in (regelanalyse.get("redeanteile") or {}).items())
        out.extend(["", "### Hinweise", ""])
        out.extend(f"- [{_mmss(h.get('zeit', 0))}] {h.get('text', '')}" for h in regelanalyse.get("hinweise") or [])
    return "\n".join(out).strip() + "\n"


def meeting_html(d: dict, regelanalyse: dict | None = None) -> str:
    """Eigenständiges, druckbares HTML; Word/Outlook übernehmen Tabellen und Überschriften beim Kopieren."""
    md = meeting_markdown(d, regelanalyse)
    # Bewusst kleiner eigener Renderer für die von uns erzeugte, geschlossene Markdown-Struktur.
    teile = []
    in_liste = False
    for zeile in md.splitlines():
        if zeile.startswith("- "):
            if not in_liste:
                teile.append("<ul>")
                in_liste = True
            teile.append(f"<li>{html.escape(zeile[2:])}</li>")
            continue
        if in_liste:
            teile.append("</ul>")
            in_liste = False
        if zeile.startswith("# "): teile.append(f"<h1>{html.escape(zeile[2:])}</h1>")
        elif zeile.startswith("## "): teile.append(f"<h2>{html.escape(zeile[3:])}</h2>")
        elif zeile.startswith("### "): teile.append(f"<h3>{html.escape(zeile[4:])}</h3>")
        elif zeile:
            teile.append(f"<p>{html.escape(zeile).replace('**', '')}</p>")
    if in_liste:
        teile.append("</ul>")
    return "<!doctype html><html lang='de'><meta charset='utf-8'><title>Nestor Meeting</title><style>body{font:11pt Arial;max-width:850px;margin:35px auto;color:#172033}h1,h2{color:#312e81}li{margin:.35em 0}@media print{body{margin:0}}</style><body>" + "".join(teile) + "</body></html>"


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
        meeting = meeting_daten(ordner)
        analyse = {"redeanteile": bericht.get("redeanteile", {}), "hinweise": bericht.get("hinweise", [])}
        z.writestr("meeting.md", meeting_markdown(meeting))
        z.writestr("meeting.html", meeting_html(meeting))
        z.writestr("meeting-mit-regelanalyse.html", meeting_html(meeting, analyse))
        # Abschlussbild (Premium) bzw. Überblick als Text (Basis: steht an der Stelle des Bilds, Lastenheft 4.7)
        for bild in ("zusammenfassung.png", "zusammenfassung.svg", "ueberblick.md", "meeting.json", "tasks.json"):
            if (ordner / bild).exists():
                z.write(ordner / bild, bild)
        z.writestr("transkript.md", _transkript_md(bericht.get("transkript", [])))
        z.writestr("agenda.md", _agenda_md(bericht.get("agenda", [])))
        z.writestr("hinweise.md", _hinweise_md(bericht.get("hinweise", [])))
        z.writestr("technik.json", json.dumps(bericht.get("technik", {}), ensure_ascii=False, indent=2))
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
        "technik.json": json.dumps(bericht.get("technik", {}), ensure_ascii=False, indent=2).encode("utf-8"),
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
