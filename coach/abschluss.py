"""Abschlussseite: eigenes Paket, Unterstützung und Datenspende (Lastenheft 2 Schritt 5, 4.4–4.6).

Liest ausschließlich aus dem fertig geschriebenen `bericht.json` eines Meeting-Ordners (coach/archiv.py) –
so bleibt diese Datei unabhängig davon, ob das Meeting noch läuft oder der Coach längst zurückgesetzt ist.
"""

from __future__ import annotations

import html
import io
import json
import math
import shutil
import time
import zipfile
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SpendeDatei:
    """Eine Datei der Spende/des Feedbacks, in Upload-Reihenfolge: Texte zuerst, die – optionale, große –
    Aufnahme zuletzt, damit bei einem Abbruch wenigstens die Texte ankommen. `inhalt` für kleine, im Speicher
    gehaltene Texte; `pfad` für Dateien, die von der Platte gestreamt werden, ohne sie ganz in den Speicher zu
    lesen."""

    name: str
    inhalt: bytes | None = None
    pfad: Path | None = None

    def groesse(self) -> int:
        return len(self.inhalt) if self.inhalt is not None else self.pfad.stat().st_size  # type: ignore[union-attr]


@dataclass(frozen=True)
class SpendeTeilergebnis:
    """Ergebnis einer einzelnen hochgeladenen Datei – ohne ihren Inhalt, nur was die Telegram-Meldung braucht."""

    datei: str
    bytes: int
    ok: bool


@dataclass(frozen=True)
class SpendeErgebnis:
    """Rückmeldung einer Ablage: einzelne Dateien können fehlschlagen (typischerweise die große, optionale
    Aufnahme), ohne dass die ganze Spende als gescheitert gilt – `vollstaendig` ist nur wahr, wenn jede Datei
    ok war."""

    teile: list[SpendeTeilergebnis]
    dauer_sekunden: float

    @property
    def vollstaendig(self) -> bool:
        return bool(self.teile) and all(t.ok for t in self.teile)


def spenden_dateien(ordner: Path, feedback: str, mit_aufnahme: bool) -> list[SpendeDatei]:
    """Dateien für eine Datenspende, in Upload-Reihenfolge: Transkript, Hinweise, Agenda, Dynamik, Feedback,
    Technik – optional zuletzt die Aufnahme. Eine künftige weitere Textdatei reiht sich hier einfach vor der
    Aufnahme ein."""
    ordner = Path(ordner)
    bericht = _bericht(ordner)
    dateien = [
        SpendeDatei("transkript.md", inhalt=_transkript_md(bericht.get("transkript", [])).encode("utf-8")),
        SpendeDatei("hinweise.md", inhalt=_hinweise_md(bericht.get("hinweise", [])).encode("utf-8")),
        SpendeDatei("agenda.md", inhalt=_agenda_md(bericht.get("agenda", [])).encode("utf-8")),
        SpendeDatei("dynamik.json", inhalt=json.dumps(bericht.get("dynamik", {}), ensure_ascii=False, indent=1).encode("utf-8")),
        SpendeDatei("feedback.txt", inhalt=(feedback or "").encode("utf-8")),
        SpendeDatei("technik.json", inhalt=json.dumps(bericht.get("technik", {}), ensure_ascii=False, indent=2).encode("utf-8")),
    ]
    if mit_aufnahme and (ordner / "aufnahme.wav").exists():
        dateien.append(SpendeDatei("aufnahme.wav", pfad=ordner / "aufnahme.wav"))
    return dateien


class Ablage:
    """Schnittstelle für Spenden-Ablagen – schmal gehalten, eine R2-Umsetzung in coach/ablage_r2.py."""

    def ablegen(self, name: str, dateien: list[SpendeDatei]) -> SpendeErgebnis:
        raise NotImplementedError


class OrdnerAblage(Ablage):
    """Lokaler Ordner `spenden/<datum>_<kurz-id>/` (Pfad aus LMC_SPENDEN)."""

    def __init__(self, wurzel: Path | str | None = None) -> None:
        self.wurzel = Path(wurzel) if wurzel is not None else Path(EINST.spenden)

    def ablegen(self, name: str, dateien: list[SpendeDatei]) -> SpendeErgebnis:
        start = time.monotonic()
        ordner = self.wurzel / f"{datetime.now():%Y-%m-%d}_{name}"
        ordner.mkdir(parents=True, exist_ok=True)
        teile: list[SpendeTeilergebnis] = []
        for datei in dateien:
            ziel = ordner / datei.name
            if datei.inhalt is not None:
                ziel.write_bytes(datei.inhalt)
            else:
                shutil.copyfile(datei.pfad, ziel)  # type: ignore[arg-type]
            teile.append(SpendeTeilergebnis(datei.name, datei.groesse(), True))
        return SpendeErgebnis(teile, time.monotonic() - start)
