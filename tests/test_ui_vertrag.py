"""UI-Vertrag statisch (Ticket #61, Stufe A): jede im Vertrag genannte ID existiert in der zugehörigen Seite.

Das Verhalten (sichtbar, Reihenfolge, Bedienmodell) prüft der Klick-Durchlauf in Stufe B (tests/e2e/). Hier nur:
Der Vertrag ist gültig und verweist auf nichts, das es nicht gibt – sonst wäre ein roter Klicktest ein Tippfehler.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
VERTRAG = json.loads((WURZEL / "szenarien" / "ui_vertrag.json").read_text(encoding="utf-8"))
STATIC = WURZEL / "static"
# IDs, die erst das Skript der Seite anlegt (agenda.js baut das Agenda-Eingabefeld zur Laufzeit)
DYNAMISCH = {"index.html": {"agenda-feld", "agenda-mikro", "agenda-senden", "agenda-antwort", "agenda-tabelle"}}


class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.klassen: set[str] = set()
        self.knoepfe: list[tuple[str, str]] = []  # (data-knopf, Klassen) in Quellreihenfolge

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        for k in (a.get("class") or "").split():
            self.klassen.add(k)
        if a.get("data-knopf"):
            self.knoepfe.append((a["data-knopf"], a.get("class") or ""))


def _seite(name: str) -> _Ids:
    p = _Ids()
    p.feed((STATIC / name).read_text(encoding="utf-8"))
    p.ids |= DYNAMISCH.get(name, set())
    if name == "index.html":  # agenda.js legt die IDs per el("…", {id: …}) an – dort nachsehen statt raten
        js = (STATIC / "agenda.js").read_text(encoding="utf-8")
        p.ids |= set(re.findall(r'\bid: "([\w-]+)"', js))
    return p


def _ids_in(selektor: str) -> list[str]:
    return re.findall(r"#([\w-]+)", selektor)


def _alle_selektoren(phase: str, geraet: str) -> list[str]:
    block = VERTRAG["bereiche"].get(phase, {}).get(geraet, {})
    sel: list[str] = []
    for teil in block.values():
        for schluessel in ("pflicht", "verboten", "erlaubt"):
            sel += teil.get(schluessel, [])
    return sel


def test_vertrag_ist_vollstaendig_aufgebaut():
    assert VERTRAG["phasen"] == ["start", "vorbereitung", "live", "abschluss"]
    assert [k["beschriftung"] for k in VERTRAG["kernknoepfe"]] == ["Stand", "Zusammenfassen", "Lücken", "Protokoll", "Überblick"]
    assert VERTRAG["abschluss_reihenfolge"] == ["#ab-datenspende", "#ab-unterstuetzung", "#ab-protokoll", "#ab-paket"]
    assert VERTRAG["sprechknoepfe"]["bedienmodell"] in ("halten", "klick")
    for phase in VERTRAG["phasen"]:
        assert phase in VERTRAG["bereiche"], phase
    for ticket in (v for k, v in VERTRAG["bekannte_abweichungen"].items() if not k.startswith("_")):
        assert re.fullmatch(r"#\d+", ticket)


def test_jede_vertrags_id_existiert_in_ihrer_seite():
    fehlend = []
    for phase, geraete in VERTRAG["seiten"].items():
        for geraet, pfad in geraete.items():
            seite = _seite(Path(pfad).name)
            for sel in _alle_selektoren(phase, geraet):
                fehlend += [f"{phase}/{geraet}: #{i} fehlt in {pfad}" for i in _ids_in(sel) if i not in seite.ids]
    kandidaten = VERTRAG["bereiche"]["kandidaten"]
    for geraet, datei in (("desktop", "index.html"), ("handy", "handy.html"), ("abschluss", "abschluss.html")):
        seite = _seite(datei)
        fehlend += [f"kandidat {geraet}: {s}" for s in kandidaten[geraet] for i in _ids_in(s) if i not in seite.ids]
    for regel in VERTRAG["regeln"]:
        for sel in [regel.get("selektor", ""), *regel.get("selektoren", {}).values()]:
            for i in _ids_in(sel):
                if not any(i in _seite(d).ids for d in ("index.html", "handy.html", "abschluss.html", "start.html")):
                    fehlend.append(f"regel {regel['id']}: #{i}")
    for k in VERTRAG["sprechknoepfe"]["knoepfe"]:
        datei = "index.html" if k["geraet"] == "desktop" else "handy.html"
        if k["id"] not in _seite(datei).ids:
            fehlend.append(f"sprechknopf {k['id']} fehlt in {datei}")
    assert not fehlend, "\n".join(fehlend)


def test_kernknoepfe_existieren_auf_beiden_geraeten():
    for datei in ("index.html", "handy.html"):
        arten = [k for k, _ in _seite(datei).knoepfe]
        for k in VERTRAG["kernknoepfe"]:
            assert k["knopf"] in arten, f"{k['knopf']} fehlt in {datei}"
