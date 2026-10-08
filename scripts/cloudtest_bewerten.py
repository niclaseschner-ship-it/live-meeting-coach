r"""Bewertung eines Cloud-Testlaufs nach der Qualitätsrubrik (docs/qualitaet.md, Ticket #11): rechnet die
messbaren Kennzahlen aus dem Mitschnitt eines scripts/cloudtest.py-Laufs und lässt die Urteilskriterien
(1–5, mit Begründung) von einem Sprachmodell mit Bild-Eingabe bewerten – über Codex auf dem Pi
(`codex exec -i <Screenshot> …`, geprüft: funktioniert, 0 $ über das ChatGPT-Abo). Ohne Codex (z. B. nicht
angemeldet) stehen die Urteile als „übersprungen“ im Bericht, die Kennzahlen und Screenshots bleiben – dann
entscheidet der Koordinator von Auge.

    ~/.venvs/lmc/bin/python scripts/cloudtest_bewerten.py logs/cloudtest/2026-10-08_0306_premium

Liest, wenn vorhanden, <lauf>/ws.jsonl + die referenz.json aus bericht.json["messwerte"]["referenz_datei"] und
berechnet die Prüfliste DAMIT NEU (scripts/cloudtest.py: pruefpunkte_berechnen) statt die in bericht.json
gespeicherten Urteile zu übernehmen - die können von einer älteren Skriptversion stammen, insbesondere ohne
die Versatz-Korrektur (Nachtrag nach dem ersten echten Cloud-Lauf: Referenzzeiten und Meetinguhr liefen dort
~6-15 s auseinander, wachsend über den Lauf - Chromium spielt die Mikrofon-Datei nicht exakt ab "Meeting
starten"). Nur wenn `ws.jsonl` oder die referenz.json fehlen (ältere Läufe), fällt es auf die gespeicherte
Prüfliste zurück - dann ohne Versatz-Korrektur, mit Hinweis im Protokoll.
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
import cloudtest as ct  # noqa: E402 - selbe Auswertungslogik wie der Live-Lauf, hier nicht verdoppeln

VERZUG_RE = re.compile(r"Verzug ([+-]?\d+(?:\.\d+)?)s")
# Bis zu so viele Screenshots gehen an Codex (Laufzeit/Umfang begrenzen) – immer Start, Abschluss und sonst
# gleichmäßig verteilt, damit "Verständlichkeit auf einen Blick" den ganzen Lauf abdeckt, nicht nur den Anfang.
MAX_BILDER = 8


def bericht_laden(ordner: Path) -> dict:
    return json.loads((ordner / "bericht.json").read_text(encoding="utf-8"))


def ws_frames_laden(ordner: Path) -> list[dict]:
    datei = ordner / "ws.jsonl"
    if not datei.exists():
        return []
    aus = []
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        if zeile.strip():
            aus.append(json.loads(zeile))
    return aus


def nur_knopfdruck_aus_bericht(bericht: dict) -> bool:
    """Ticket #17 Punkt 7: neuere Berichte tragen das Feld direkt (scripts/cloudtest.py pruefliste_bauen());
    ältere (vor dieser Änderung) nur über den Text in messwerte.modus ("… · nur auf Knopfdruck")."""
    wert = bericht["messwerte"].get("nur_knopfdruck")
    if wert is not None:
        return bool(wert)
    return "knopfdruck" in bericht["messwerte"].get("modus", "").lower()


def pruefliste_neu_berechnen(bericht: dict, frames: list[dict]) -> tuple[list[dict], float | None] | None:
    """Frisch aus dem WS-Mitschnitt + referenz.json (mit Versatz-Korrektur). None, wenn das nicht geht
    (keine ws.jsonl oder referenz_datei unbekannt/fehlt) - dann übernimmt main() die gespeicherte Prüfliste."""
    referenz = ct.referenz_laden(bericht["messwerte"])
    if not frames or referenz is None:
        return None
    zustaende = ct.zustaende_aus_frames(frames)
    if not zustaende:
        return None
    hinweise = ct._hinweise_dedup(zustaende)
    karten = ct._karten_dedup(zustaende)
    stimme = ct.nachrichten_aus_frames(frames, "stimme")
    offline_lauf = bool((zustaende[-1].get("schluessel") or {}).get("offline"))
    plan, _ = ct.meeting_plan(bericht["messwerte"], zustaende)  # #25: Referenz auf die Meetinguhr mit Pausen
    return ct.pruefpunkte_berechnen(referenz, zustaende, hinweise, karten, stimme, offline_lauf,
                                    nur_knopfdruck_aus_bericht(bericht), plan,
                                    **ct.ungefragt_eingaben(bericht["messwerte"], frames, zustaende))


def kennzahlen_bauen(bericht: dict, frames: list[dict], pruefliste: list[dict], versatz: float | None) -> dict:
    """Treffer/Fehlauslöser/Verzug aus der (ggf. frisch mit Versatz-Korrektur berechneten) Prüfliste - hier
    nur noch gezählt und nach Rubrik (qualitaet.md) sortiert, nicht neu bewertet."""
    ok = [p for p in pruefliste if p["status"] == "ok"]
    fehlt = [p for p in pruefliste if p["status"] == "fehlt"]
    # Fehlauslöser: Grenzfälle, die NICHT reagieren sollten, aber reagiert haben ("erwartet: kein_..." + fehlt), und
    # seit #28 jede Nestor-Äußerung ohne Auslöser laut Referenz und Bedienplan („Fehlauslöser bei …s“)
    fehlausloeser = [p for p in fehlt if p["name"].startswith("Fehlauslöser") or "erwartet: kein" in p["detail"]
                     or "erwartet: keine_antwort" in p["detail"]]
    verpasst = [p for p in fehlt if p not in fehlausloeser]
    # "Antwortzeit" meint Nestors Reaktion auf eine Anweisung/einen Grenzfall, nicht den Verzug einer
    # Ereignis-Erkennung (z. B. Monolog) - sonst mischen sich zwei verschiedene Dinge in einer Kennzahl.
    antwort_pruefpunkte = [p for p in pruefliste if p["name"].startswith(("Nestor-Anweisung", "Grenzfall"))]
    verzuege = [float(m.group(1)) for p in antwort_pruefpunkte for m in [VERZUG_RE.search(p["detail"])] if m]

    zustaende = ct.zustaende_aus_frames(frames) if frames else []
    hinweise_gesamt = len(ct._hinweise_dedup(zustaende)) if zustaende else 0
    dauer_min = bericht["messwerte"].get("meeting_s", 0) / 60 or 1
    referenz = ct.referenz_laden(bericht["messwerte"])
    spannweite = None
    if zustaende and referenz is not None:
        plan, _ = ct.meeting_plan(bericht["messwerte"], zustaende)
        if plan:
            referenz = ct.takt.referenz_auf_meetinguhr(referenz, plan)
        spannweite = ct.versatz_spannweite(referenz, ct._segmente_dedup(zustaende))

    kosten = max(bericht["messwerte"].get("kosten_usd", 0.0), ct.meeting_kosten(zustaende))
    anschluss = ct.anschluss_kennzahlen(ct.referenz_laden(bericht["messwerte"]), pruefliste)
    return {**anschluss,
        "treffer": len(ok), "verpasst": len(verpasst), "fehlausloeser": len(fehlausloeser),
        "beobachtet": len([p for p in pruefliste if p["status"] == "beobachtet"]),
        "uebersprungen_offline": len([p for p in pruefliste if p["status"] == "offline"]),
        "antwortzeit_median_s": sorted(verzuege)[len(verzuege) // 2] if verzuege else None,
        "antwortzeit_max_s": max(verzuege) if verzuege else None,
        "hinweise_gesamt": hinweise_gesamt, "hinweise_je_10min": round(hinweise_gesamt / dauer_min * 10, 1),
        "kosten_usd": kosten,
        "kosten_je_stunde_usd": round(kosten / dauer_min * 60, 3) if dauer_min else 0,
        "ablage_wartezeit_s": bericht["messwerte"].get("ablage_wartezeit_s"),
        "kaltstart_s": bericht["messwerte"].get("kaltstart_s"),
        "versatz_s": round(versatz, 1) if versatz is not None else None,
        "versatz_anfang_s": spannweite[0] if spannweite else None,
        "versatz_ende_s": spannweite[1] if spannweite else None,
    }


def schlimmste_stellen(pruefliste: list[dict], bericht: dict, n: int = 6) -> list[dict]:
    """Die n Prüfpunkte mit Status "fehlt" - einfachste ehrliche Näherung an "schlimmste Stellen": alles
    andere wäre eine zweite, unbelegte Gewichtung obendrauf. Screenshot: der zeitlich nächste, falls aus dem
    Namen (dashboard_M_SS) eine Zeit hervorgeht."""
    fehlt = [p for p in pruefliste if p["status"] == "fehlt"]
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
    return "–" if wert is None else f"{round(wert, 1)} s"


def takt_zeilen(tk: dict) -> list[str]:
    """Kennzahlen-Zeilen zum abwechselnden Reden (#25) und aus #21 Punkt 5 – leer bei einem Lauf am Stück."""
    if not tk:
        return []
    ungestoert = tk.get("begruessung_ungestoert")
    return [
        f"| Begrüßung ungestört / gesprochen | {'ja' if ungestoert else ('nein' if ungestoert is False else '–')}"
        f" / {_s(tk.get('begruessung_s'))} |",
        f"| Bestätigung sichtbar (Median / längste) | {_s(tk.get('bestaetigung_sichtbar_median_s'))} / "
        f"{_s(tk.get('bestaetigung_sichtbar_max_s'))} |",
        f"| Erster Ton nach Frage-Ende (Median / längste) | {_s(tk.get('erster_ton_median_s'))} / "
        f"{_s(tk.get('erster_ton_max_s'))} |",
        f"| Warten bis Zeitlimit | {tk.get('zeitlimits', 0)} |",
        f"| Ton ohne Text / Text ohne Ton | {tk.get('ton_ohne_text', '–')} / {tk.get('text_ohne_ton', '–')} "
        f"(von {tk.get('ton_bloecke', '–')} Ton-Blöcken, {tk.get('antworten_text', '–')} Antworttexten) |",
        f"| Tonspur-Abweichung, größte | {_s(tk.get('tonspur_abweichung_max_s'))} |",
    ]


def bewertung_schreiben(ordner: Path, bericht: dict, kennzahlen: dict, urteile: dict | None,
                        schlimmste: list[dict], takt_punkte: list[dict] | None = None,
                        takt_kennzahlen: dict | None = None) -> None:
    z = [f"# Bewertung – {bericht['messwerte'].get('modus', '?')}", "",
        f"Lauf: `{ordner}` · Gestartet {bericht['messwerte'].get('gestartet', '?')} · "
        f"Dauer {bericht['messwerte'].get('meeting_s', '?')} s", "",
        "## Messbare Kennzahlen", "",
        "| Kennzahl | Wert |", "|---|---|",
        f"| Treffer | {kennzahlen['treffer']} |",
        f"| Verpasst | {kennzahlen['verpasst']} |",
        f"| Fehlauslöser | {kennzahlen['fehlausloeser']} |",
        f"| davon ungefragte Antworten (ohne Auslöser laut Referenz und Bedienplan) | "
        f"{kennzahlen.get('ungefragte_antworten', '–')} |",
        f"| Verpasste Anschlussfragen (Rückfrage ohne Namen) | {kennzahlen.get('verpasste_anschlussfragen', '–')} von "
        f"{kennzahlen.get('anschlussfragen', '–')} |",
        f"| Dokumentiert (kein klares Richtig/Falsch) | {kennzahlen['beobachtet']} |",
        f"| Übersprungen (offline) | {kennzahlen['uebersprungen_offline']} |",
        f"| Antwortzeit, Median | {_s(kennzahlen['antwortzeit_median_s'])} |",
        f"| Antwortzeit, am längsten | {_s(kennzahlen['antwortzeit_max_s'])} |",
        f"| Hinweise insgesamt / je 10 min | {kennzahlen['hinweise_gesamt']} / {kennzahlen['hinweise_je_10min']} |",
        f"| Kosten gesamt / je Stunde | {kennzahlen['kosten_usd']:.4f} $ / {kennzahlen['kosten_je_stunde_usd']:.3f} $ |",
        f"| Kaltstart Startseite | {_s(kennzahlen['kaltstart_s'])} |",
        f"| Wartezeit bis Abschlusspaket fertig | {_s(kennzahlen['ablage_wartezeit_s'])} |",
        f"| Versatz Referenzzeit↔Meetinguhr | {_s(kennzahlen['versatz_s'])} "
        f"(Anfang {_s(kennzahlen['versatz_anfang_s'])} → Ende {_s(kennzahlen['versatz_ende_s'])}) |",
        *takt_zeilen(takt_kennzahlen or {}),
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
    if takt_punkte:
        zeichen = {"ok": "✅", "fehlt": "❌", "beobachtet": "📝", "offline": "⏭️"}
        z += ["", "## Abwechselnd reden (#25)", "", "| Prüfpunkt | Status | Detail |", "|---|---|---|"]
        z += [f"| {p['name'].removeprefix('Takt: ')} | {zeichen[p['status']]} | {p['detail']} |" for p in takt_punkte]
    bedienung = (takt_kennzahlen or {}).get("bedienung") or []
    if bedienung:  # Ticket #27: jeder Druck des Tests mit Nestors Reaktion – wie bei den Zurufen
        z += ["", "## Bedienung", "", "| Zeit | Knopf | Satz | Reaktion von Nestor |", "|---|---|---|---|"]
        for b in bedienung:
            zeit = ct.mmss(b["zeit"]) if b.get("zeit") is not None else f"Lauf {b['t']:.0f}s"
            name = b["name"] + (f" ({b['dauer_s']:.1f} s)" if b.get("dauer_s") else "")
            satz = f"„{b['satz']}“" if b.get("satz") else "–"
            z.append(f"| {zeit} | {name} | {satz} | {ct.takt.bedienung_text(b)} |")
    (ordner / "bewertung.md").write_text("\n".join(z), encoding="utf-8")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lauf", help="Berichtordner eines scripts/cloudtest.py-Laufs (enthält bericht.json)")
    ap.add_argument("--ohne-urteil", action="store_true", help="Codex-Urteile überspringen (nur Kennzahlen)")
    args = ap.parse_args()
    ordner = Path(args.lauf)

    bericht = bericht_laden(ordner)
    frames = ws_frames_laden(ordner)
    if not frames:
        print(f"Hinweis: keine ws.jsonl in {ordner} – Ruhe-Kennzahl (Hinweise) bleibt 0, keine Versatz-Korrektur "
             "möglich (älterer Lauf vor #11?). Fällt auf die im Bericht gespeicherte Prüfliste zurück.")

    neu = pruefliste_neu_berechnen(bericht, frames)
    if neu is not None:
        pruefliste, versatz = neu
        print(f"Prüfliste neu berechnet (Versatz-Korrektur: "
             f"{'nicht schätzbar' if versatz is None else f'{versatz:+.1f}s'}).")
    else:
        pruefliste, versatz = bericht["pruefliste"], bericht["messwerte"].get("versatz_s")
        print("Prüfliste aus bericht.json übernommen (keine Neuberechnung möglich) - ohne Versatz-Korrektur, "
             "falls das ein älterer Lauf ist.")

    kennzahlen = kennzahlen_bauen(bericht, frames, pruefliste, versatz)
    takt_punkte, takt_kennzahlen = ct.takt_auswerten(bericht["messwerte"], frames)
    # Treffer/Verpasst bleiben die Referenz-Prüfliste (vergleichbar mit älteren Läufen); ❌ aus dem Takt
    # gehören trotzdem zu den schlimmsten Stellen.
    schlimmste = schlimmste_stellen(pruefliste + [p for p in takt_punkte if p["status"] == "fehlt"], bericht)
    if takt_kennzahlen:
        print(f"Takt: {json.dumps({k: v for k, v in takt_kennzahlen.items() if k != 'bedienung'}, ensure_ascii=False)}")
    bilder = bilder_auswaehlen(ordner, bericht)
    print(f"Kennzahlen: {json.dumps(kennzahlen, ensure_ascii=False)}")
    print(f"{len(bilder)} Screenshots für das Urteil ausgewählt: {[b.name for b in bilder]}")

    urteile = None if args.ohne_urteil else await urteile_holen(kennzahlen, bilder)
    bewertung_schreiben(ordner, bericht, kennzahlen, urteile, schlimmste, takt_punkte, takt_kennzahlen)
    print(f"Bewertung: {ordner / 'bewertung.md'}")

    # Ticket #19: HTML-Testbericht (Audio+Zeitstrahl+Screenshots) ist seitdem Standard für jeden Lauf - hier am
    # Ende statt doppelt von Hand aufgerufen. Lazy-Import (erst hier, nicht oben), weil cloudtest_bericht.py
    # umgekehrt diese Datei importiert (nur_knopfdruck_aus_bericht()) - ein Import an dieser Stelle vermeidet
    # jede Unklarheit über die Reihenfolge beim zirkulären Import.
    import cloudtest_bericht
    try:
        html_pfad = cloudtest_bericht.erzeugen(ordner)
        print(f"Bericht: {html_pfad} ({html_pfad.stat().st_size / 1_000_000:.1f} MB)")
    except Exception as e:  # noqa: BLE001 - ffmpeg/Audio kann je nach Lauf fehlen; Kennzahlen/Urteil bleiben gültig
        print(f"HTML-Bericht nicht erzeugt ({type(e).__name__}: {e}) - bewertung.md/bericht.md stehen trotzdem.")


if __name__ == "__main__":
    asyncio.run(main())
