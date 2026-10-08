r"""Bewertung eines Cloud-Testlaufs nach der Qualitätsrubrik (docs/qualitaet.md, Ticket #11): rechnet die
messbaren Kennzahlen aus dem Bericht/Mitschnitt eines scripts/cloudtest.py-Laufs und lässt die Urteilskriterien
(1–5, mit Begründung) von einem Sprachmodell mit Bild-Eingabe bewerten – über Codex auf dem Pi
(`codex exec -i <Screenshot> …`, geprüft: funktioniert, 0 $ über das ChatGPT-Abo). Ohne Codex (z. B. nicht
angemeldet) stehen die Urteile als „übersprungen“ im Bericht, die Kennzahlen und Screenshots bleiben – dann
entscheidet der Koordinator von Auge.

    ~/.venvs/lmc/bin/python scripts/cloudtest_bewerten.py logs/cloudtest/2026-10-08_0306_premium

Liest <lauf>/bericht.json (von cloudtest.py geschrieben – Prüfliste mit Status/Begründung je Punkt, das ist
schon die eine Quelle für Treffer/Fehlauslöser/Verzug, hier nicht zweimal berechnen) und <lauf>/ws.jsonl
(für die Ruhe-Kennzahl: wie viele Hinweise insgesamt, nicht nur die zu einem erwarteten Ereignis passenden).
Schreibt <lauf>/bewertung.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

VERZUG_RE = re.compile(r"Verzug ([+-]?\d+(?:\.\d+)?)s")
# Bis zu so viele Screenshots gehen an Codex (Laufzeit/Umfang begrenzen) – immer Start, Abschluss und sonst
# gleichmäßig verteilt, damit "Verständlichkeit auf einen Blick" den ganzen Lauf abdeckt, nicht nur den Anfang.
MAX_BILDER = 8


def bericht_laden(ordner: Path) -> dict:
    return json.loads((ordner / "bericht.json").read_text(encoding="utf-8"))


def ws_zeilen(ordner: Path) -> list[dict]:
    datei = ordner / "ws.jsonl"
    if not datei.exists():
        return []
    aus = []
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        if zeile.strip():
            aus.append(json.loads(zeile))
    return aus


def kennzahlen_bauen(bericht: dict, ws: list[dict]) -> dict:
    """Treffer/Fehlauslöser/Verzug kommen aus bericht["pruefliste"] (dort schon von cloudtest.py anhand des
    vollständigen WS-Mitschnitts entschieden) – hier nur noch gezählt und nach Rubrik (qualitaet.md) sortiert,
    nicht neu bewertet. Nur die Ruhe-Kennzahl (Hinweise insgesamt) braucht den rohen Mitschnitt."""
    pl = bericht["pruefliste"]
    ok = [p for p in pl if p["status"] == "ok"]
    fehlt = [p for p in pl if p["status"] == "fehlt"]
    # Fehlauslöser: Grenzfälle, die NICHT reagieren sollten, aber reagiert haben ("erwartet: kein_..." + fehlt)
    fehlausloeser = [p for p in fehlt if "erwartet: kein" in p["detail"] or "erwartet: keine_antwort" in p["detail"]]
    verpasst = [p for p in fehlt if p not in fehlausloeser]
    # "Antwortzeit" meint Nestors Reaktion auf eine Anweisung/einen Grenzfall, nicht den Verzug einer
    # Ereignis-Erkennung (z. B. Monolog) - sonst mischen sich zwei verschiedene Dinge in einer Kennzahl.
    antwort_pruefpunkte = [p for p in pl if p["name"].startswith(("Nestor-Anweisung", "Grenzfall"))]
    verzuege = [float(m.group(1)) for p in antwort_pruefpunkte for m in [VERZUG_RE.search(p["detail"])] if m]

    hinweise_gesamt = 0
    gesehen = set()
    for z in ws:
        d = z.get("daten", {})
        if z.get("richtung") != "empfangen" or not isinstance(d, dict) or "hinweise" not in d:
            continue
        for h in d.get("hinweise") or []:
            hid = h.get("id")
            if hid is None or hid not in gesehen:
                if hid is not None:
                    gesehen.add(hid)
                hinweise_gesamt += 1
    dauer_min = bericht["messwerte"].get("meeting_s", 0) / 60 or 1

    return {
        "treffer": len(ok), "verpasst": len(verpasst), "fehlausloeser": len(fehlausloeser),
        "beobachtet": len([p for p in pl if p["status"] == "beobachtet"]),
        "uebersprungen_offline": len([p for p in pl if p["status"] == "offline"]),
        "antwortzeit_median_s": sorted(verzuege)[len(verzuege) // 2] if verzuege else None,
        "antwortzeit_max_s": max(verzuege) if verzuege else None,
        "hinweise_gesamt": hinweise_gesamt, "hinweise_je_10min": round(hinweise_gesamt / dauer_min * 10, 1),
        "kosten_usd": bericht["messwerte"].get("kosten_usd", 0.0),
        "kosten_je_stunde_usd": round(bericht["messwerte"].get("kosten_usd", 0.0) / dauer_min * 60, 3) if dauer_min else 0,
        "ablage_wartezeit_s": bericht["messwerte"].get("ablage_wartezeit_s"),
        "kaltstart_s": bericht["messwerte"].get("kaltstart_s"),
    }


def schlimmste_stellen(bericht: dict, n: int = 5) -> list[dict]:
    """Die n Prüfpunkte mit Status "fehlt" - einfachste ehrliche Näherung an "schlimmste Stellen": alles
    andere wäre eine zweite, unbelegte Gewichtung obendrauf. Screenshot: der zeitlich nächste, falls aus dem
    Namen (dashboard_M_SS) eine Zeit hervorgeht."""
    fehlt = [p for p in bericht["pruefliste"] if p["status"] == "fehlt"]
    aus = []
    for p in fehlt[:n]:
        zeit_m = re.search(r"bei (\d+)s", p["name"] + " " + p["detail"])
        screenshot = naechster_screenshot(bericht, int(zeit_m.group(1))) if zeit_m else None
        aus.append({"name": p["name"], "detail": p["detail"], "screenshot": screenshot,
                   "zeit_s": int(zeit_m.group(1)) if zeit_m else None})
    return aus


def naechster_screenshot(bericht: dict, zeit_s: int) -> str | None:
    kandidaten = [s for s in bericht["screenshots"] if s.startswith("dashboard_")]
    if not kandidaten:
        return None
    def zu_sekunden(name: str) -> int:
        ziffern = name.removeprefix("dashboard_")
        m = re.match(r"(\d+)(\d{2})$", ziffern)  # z. B. "530" -> 5 min 30 s
        return int(m.group(1)) * 60 + int(m.group(2)) if m else 0
    return min(kandidaten, key=lambda s: abs(zu_sekunden(s) - zeit_s))


def bilder_auswaehlen(ordner: Path, bericht: dict) -> list[Path]:
    alle = [s for s in bericht["screenshots"] if (ordner / "screenshots" / f"{s}.png").exists()]
    ohne_dashboard = [s for s in alle if not s.startswith("dashboard_")]  # startseite, agenda-tabelle, abschluss
    dashboard = [s for s in alle if s.startswith("dashboard_")]
    if len(dashboard) > MAX_BILDER - len(ohne_dashboard):
        schritt = len(dashboard) / (MAX_BILDER - len(ohne_dashboard))
        dashboard = [dashboard[int(i * schritt)] for i in range(MAX_BILDER - len(ohne_dashboard))]
    namen = ohne_dashboard + dashboard
    return [ordner / "screenshots" / f"{n}.png" for n in namen]


RUBRIK = (WURZEL / "docs" / "qualitaet.md").read_text(encoding="utf-8")
URTEIL_AUFTRAG = """\
Du bewertest einen automatisierten Testlauf des Meeting-Assistenten "Nestor" nach der folgenden Rubrik \
(docs/qualitaet.md):

{rubrik}

Hier die gerechneten Kennzahlen dieses Laufs:
{kennzahlen}

Die angehängten Bilder sind Dashboard-Screenshots aus dem Lauf, in zeitlicher Reihenfolge (erstes = Startseite \
bzw. früh im Meeting, letztes = Abschlussseite bzw. spät im Meeting).

Vergib je Kriterium eine Note 1-5 (1 = nicht brauchbar, 5 = wie ein aufmerksamer menschlicher Protokollant) \
mit einer kurzen Begründung (höchstens 2 Sätze, konkret auf das Gesehene bezogen, nicht nur auf die Kennzahlen). \
Antworte NUR mit JSON, genau dieser Form:
{{"antwortguete": {{"note": 1-5, "begruendung": "..."}},
 "verstaendlichkeit": {{"note": 1-5, "begruendung": "..."}},
 "live_bild_ueberblick": {{"note": 1-5, "begruendung": "..."}},
 "abschluss": {{"note": 1-5, "begruendung": "..."}},
 "gesamteindruck": {{"note": 1-5, "begruendung": "drei Sätze: würdest du das deinem Team empfehlen?"}}}}
Wenn ein Kriterium aus den Bildern/Kennzahlen nicht beurteilbar ist (z. B. kein Live-Bild im Material), \
"note": null und das in der Begründung sagen - nicht raten.
"""


async def urteile_holen(kennzahlen: dict, bilder: list[Path]) -> dict | None:
    if not bilder:
        return None
    prompt = URTEIL_AUFTRAG.format(rubrik=RUBRIK, kennzahlen=json.dumps(kennzahlen, ensure_ascii=False, indent=1))
    try:
        # coach/ki_abo.codex() kennt kein Bild-Argument (coach/ ist für dieses Ticket tabu) - deshalb hier der
        # rohe codex-exec-Aufruf mit -i <Bild> …, geprüft dass das funktioniert (siehe Ticket-Bericht).
        text = await _codex_mit_bildern(prompt, bilder)
    except Exception as e:  # noqa: BLE001
        print(f"Codex-Urteil nicht möglich ({type(e).__name__}): {e}")
        return None
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0)) if m else None


async def _codex_mit_bildern(prompt: str, bilder: list[Path]) -> str:
    """Direkter codex-exec-Aufruf mit -i <Bild> … - Fallback, falls coach/ki_abo.codex() kein Bild-Argument
    unterstützt (coach/ ist für dieses Ticket tabu, also hier nachgebaut statt dort erweitert)."""
    import os

    befehl = os.environ.get("LMC_CODEX_BEFEHL", "codex").split() + [
        "exec", "-c", "model_reasoning_effort=low", "--skip-git-repo-check", "--sandbox", "read-only",
        "--ephemeral"]
    for b in bilder:
        befehl += ["-i", str(b)]
    befehl.append("-")
    p = await asyncio.create_subprocess_exec(*befehl, stdin=asyncio.subprocess.PIPE,
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    raus, _ = await asyncio.wait_for(p.communicate(prompt.encode("utf-8")), 300)
    if p.returncode != 0:
        raise RuntimeError(f"codex exec beendet mit {p.returncode}")
    text = raus.decode("utf-8", "replace").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return m.group(1) if m else text


NOTEN_NAMEN = {"antwortguete": "Antwortgüte", "verstaendlichkeit": "Verständlichkeit auf einen Blick",
              "live_bild_ueberblick": "Live-Bild/Überblick", "abschluss": "Abschluss",
              "gesamteindruck": "Gesamteindruck"}


def _s(wert) -> str:
    return "–" if wert is None else f"{wert} s"


def bewertung_schreiben(ordner: Path, bericht: dict, kennzahlen: dict, urteile: dict | None,
                        schlimmste: list[dict]) -> None:
    z = [f"# Bewertung – {bericht['messwerte'].get('modus', '?')}", "",
        f"Lauf: `{ordner}` · Gestartet {bericht['messwerte'].get('gestartet', '?')} · "
        f"Dauer {bericht['messwerte'].get('meeting_s', '?')} s", "",
        "## Messbare Kennzahlen", "",
        "| Kennzahl | Wert |", "|---|---|",
        f"| Treffer | {kennzahlen['treffer']} |",
        f"| Verpasst | {kennzahlen['verpasst']} |",
        f"| Fehlauslöser | {kennzahlen['fehlausloeser']} |",
        f"| Dokumentiert (kein klares Richtig/Falsch) | {kennzahlen['beobachtet']} |",
        f"| Übersprungen (offline) | {kennzahlen['uebersprungen_offline']} |",
        f"| Antwortzeit, Median | {_s(kennzahlen['antwortzeit_median_s'])} |",
        f"| Antwortzeit, am längsten | {_s(kennzahlen['antwortzeit_max_s'])} |",
        f"| Hinweise insgesamt / je 10 min | {kennzahlen['hinweise_gesamt']} / {kennzahlen['hinweise_je_10min']} |",
        f"| Kosten gesamt / je Stunde | {kennzahlen['kosten_usd']:.4f} $ / {kennzahlen['kosten_je_stunde_usd']:.3f} $ |",
        f"| Kaltstart Startseite | {_s(kennzahlen['kaltstart_s'])} |",
        f"| Wartezeit bis Abschlusspaket fertig | {_s(kennzahlen['ablage_wartezeit_s'])} |",
        "", "## Urteile (1–5)", ""]
    if urteile is None:
        z += ["Übersprungen – kein Codex-Urteil möglich (siehe Protokoll). Screenshots liegen unter "
             f"`{ordner / 'screenshots'}`, Entscheidung beim Koordinator.", ""]
    else:
        z += ["| Kriterium | Note | Begründung |", "|---|---|---|"]
        for schluessel, name in NOTEN_NAMEN.items():
            u = urteile.get(schluessel) or {}
            z.append(f"| {name} | {u.get('note', '–')} | {u.get('begruendung', '')} |")
        z.append("")
    z += ["## Die schlimmsten Stellen", ""]
    if not schlimmste:
        z += ["Keine ❌-Prüfpunkte in diesem Lauf.", ""]
    for s in schlimmste:
        bild = f" ([{s['screenshot']}](screenshots/{s['screenshot']}.png))" if s["screenshot"] else ""
        # Zeit steht meist schon im Namen ("… bei 25s") - nicht doppelt anhängen.
        zeit_teil = f" (bei {s['zeit_s']}s)" if s["zeit_s"] and "bei" not in s["name"] else ""
        z.append(f"- **{s['name']}**{zeit_teil}{bild}: {s['detail']}")
    (ordner / "bewertung.md").write_text("\n".join(z), encoding="utf-8")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lauf", help="Berichtordner eines scripts/cloudtest.py-Laufs (enthält bericht.json)")
    ap.add_argument("--ohne-urteil", action="store_true", help="Codex-Urteile überspringen (nur Kennzahlen)")
    args = ap.parse_args()
    ordner = Path(args.lauf)

    bericht = bericht_laden(ordner)
    ws = ws_zeilen(ordner)
    if not ws:
        print(f"Hinweis: keine ws.jsonl in {ordner} – Ruhe-Kennzahl (Hinweise) bleibt 0 (älterer Lauf vor #11?).")
    kennzahlen = kennzahlen_bauen(bericht, ws)
    schlimmste = schlimmste_stellen(bericht)
    bilder = bilder_auswaehlen(ordner, bericht)
    print(f"Kennzahlen: {json.dumps(kennzahlen, ensure_ascii=False)}")
    print(f"{len(bilder)} Screenshots für das Urteil ausgewählt: {[b.name for b in bilder]}")

    urteile = None if args.ohne_urteil else await urteile_holen(kennzahlen, bilder)
    bewertung_schreiben(ordner, bericht, kennzahlen, urteile, schlimmste)
    print(f"Bewertung: {ordner / 'bewertung.md'}")


if __name__ == "__main__":
    asyncio.run(main())
