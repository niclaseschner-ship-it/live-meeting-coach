r"""Cloud-Testlauf (Ticket „Cloudtest", Lastenheft: alles, bes. 2, 3, 4.2-4.6): ein echter Browser durchläuft
Nestor wie ein echter Kunde – Anmelden (falls --passwort gesetzt), Stufe wählen (Ticket #13: Basis/Premium
statt der früheren Modi live/Knopfdruck), Agenda per Prompt einrichten, zehn Minuten in Echtzeit zuhören
(Mikrofon aus einer Datei, kein Vorspulen), mit --nur-knopfdruck (nur in Basis) die Knöpfe zu festen Zeiten
drücken, Abschluss mit Paket, Feedback und Datenspende. Mitgeschnitten wird aus der Seite selbst (sie hält
ihren Zustand ohnehin über die gleiche WebSocket wie das Dashboard aktuell, siehe static/basis.js); ein
zweiter eigener /ws-Mitschnitt wäre nur eine doppelte Quelle für dieselbe Information.

    ~/.venvs/lmc/bin/python scripts/cloudtest.py --url http://127.0.0.1:8000 --stufe premium
    ~/.venvs/lmc/bin/python scripts/cloudtest.py --url http://127.0.0.1:8000 --stufe basis
    ~/.venvs/lmc/bin/python scripts/cloudtest.py --url https://nestor.example.workers.dev \
        --passwort geheim --stufe basis --nur-knopfdruck --bericht logs/cloudtest/lauf1

Playwright mit dem System-Chromium (kein `playwright install`): --use-fake-ui-for-media-stream und
--use-file-for-fake-audio-capture=<meeting.wav> lassen Chromium die Aufnahme wie ein echtes Mikrofon in
Echtzeit liefern. Testmaterial und Referenz: testbibliothek/cloudtest/ (siehe dort bauen.py und README in
docs/cloudtest.md). Ohne OpenAI-Schlüssel bzw. mit LMC_OFFLINE=1 am Server werden alle KI-Prüfpunkte als
„übersprungen (offline)" statt als Fehler geführt – lokale Signale (Zeit, Monolog, Redeanteile, Überlappung)
laufen auch offline und werden echt geprüft.

Robuste Oberflächen-Stellen: der Einrichten-Bereich (Agenda per Prompt) kann sich ändern (paralleles Ticket
#10); seine Selektoren sind hier an einer Stelle gebündelt (siehe `agenda_eingabe_finden`), alles andere
(Start/Stopp, Knopfleiste, Abschluss) nutzt stabile IDs aus static/index.html bzw. static/abschluss.html.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
CLOUDTEST = WURZEL / "testbibliothek" / "cloudtest"
CHROMIUM = "/usr/bin/chromium"

# /tmp ist auf dem Pi eine RAM-Disk (CLAUDE.md) – Chromiums Profilreste sollen trotzdem nicht dorthin.
# Aber NICHT unter die Arbeitskopie (WURZEL liegt hier in einem Worktree unter .claude/worktrees/<id>/ –
# das macht den Pfad so lang, dass Chromiums eigener Singleton-Socket im Profilordner den Unix-Socket-
# Limit von 108 Byte reißt und beim Start sofort mit SIGTRAP abbricht, egal wie viel Speicher frei ist;
# erst durch gezieltes Nachstellen gefunden, siehe Bericht). Stattdessen ein kurzer, fester Pfad im
# Home-Verzeichnis, außerhalb jedes Worktrees. Vor dem Playwright-Import setzen, der das beim Start liest.
_TMP = Path.home() / ".cache" / "lmc-cloudtest-tmp"
_TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMPDIR"] = str(_TMP)

from playwright.async_api import Page, async_playwright  # noqa: E402

# Meetingzeit (zustand.zeit, Sekunden seit Start), zu der jeweils etwas passieren soll.
SCREENSHOT_ZEITEN = {"2:45": 165, "5:30": 330, "9:30": 570}
KNOPF_ZEITEN = {"stand": 180, "regeln": 360, "verwerfen_5": 510, "protokoll": 570}


def jetzt() -> str:
    return datetime.now().strftime("%H:%M:%S")


class Bericht:
    """Sammelt alles für bericht.md/bericht.json, chronologisch und mit Klartext-Begründung je Eintrag."""

    def __init__(self, ordner: Path) -> None:
        self.ordner = ordner
        self.ordner.mkdir(parents=True, exist_ok=True)
        (self.ordner / "screenshots").mkdir(exist_ok=True)
        self.log: list[str] = []
        self.pruefliste: list[dict] = []
        self.messwerte: dict = {}
        self.fehler: list[str] = []
        self.screenshots: list[str] = []

    def notieren(self, text: str) -> None:
        zeile = f"[{jetzt()}] {text}"
        self.log.append(zeile)
        print(zeile)

    def pruefen(self, name: str, status: str, detail: str = "") -> None:
        """status: 'ok' | 'fehlt' | 'offline' (KI-Prüfpunkt im Testlauf ohne Schlüssel übersprungen)."""
        self.pruefliste.append({"name": name, "status": status, "detail": detail})
        zeichen = {"ok": "✅", "fehlt": "❌", "offline": "⏭️"}[status]
        self.notieren(f"{zeichen} {name}{' – ' + detail if detail else ''}")

    async def screenshot(self, seite: Page, name: str) -> None:
        pfad = self.ordner / "screenshots" / f"{name}.png"
        await seite.screenshot(path=str(pfad))
        self.screenshots.append(name)
        self.notieren(f"Screenshot: {name}")

    def schreiben(self) -> None:
        (self.ordner / "bericht.json").write_text(json.dumps({
            "messwerte": self.messwerte, "pruefliste": self.pruefliste, "fehler": self.fehler,
            "screenshots": self.screenshots,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        ok = sum(1 for p in self.pruefliste if p["status"] == "ok")
        fehlt = sum(1 for p in self.pruefliste if p["status"] == "fehlt")
        offline = sum(1 for p in self.pruefliste if p["status"] == "offline")
        zeilen = [
            f"# Cloud-Testlauf – {self.messwerte.get('modus', '?')}", "",
            f"Gestartet {self.messwerte.get('gestartet', '?')}, Dauer {self.messwerte.get('meeting_s', '?')} s "
            f"(Soll ~{self.messwerte.get('soll_dauer_s', '?')} s). "
            f"Kaltstart Startseite: {self.messwerte.get('kaltstart_s', '?')} s.",
            "", f"**Prüfliste:** {ok} ✅ · {fehlt} ❌ · {offline} ⏭️ übersprungen (offline)", "",
            "| Prüfpunkt | Status | Detail |", "|---|---|---|",
        ]
        zeichen = {"ok": "✅", "fehlt": "❌", "offline": "⏭️"}
        for p in self.pruefliste:
            zeilen.append(f"| {p['name']} | {zeichen[p['status']]} | {p['detail']} |")
        zeilen += ["", "## Kosten", "",
                  f"- Gesamt (zustand.kosten.meeting): {self.messwerte.get('kosten_usd', 0):.4f} $", "",
                  "## Screenshots", ""]
        zeilen += [f"- [{s}](screenshots/{s}.png)" for s in self.screenshots]
        if self.fehler:
            zeilen += ["", "## Aufgefallene Fehler (nicht behoben, nur notiert)", ""]
            zeilen += [f"- {f}" for f in self.fehler]
        zeilen += ["", "## Protokoll", ""] + [f"- {z}" for z in self.log]
        (self.ordner / "bericht.md").write_text("\n".join(zeilen), encoding="utf-8")


async def zustand(seite: Page) -> dict:
    return await seite.evaluate("() => zustand") or {}  # null, bis die WebSocket den ersten Stand geliefert hat


async def warten_auf(seite: Page, ausdruck: str, timeout_s: float = 20.0, takt: float = 0.3) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        try:
            if await seite.evaluate(ausdruck):
                return True
        except Exception:  # noqa: BLE001 – Seite navigiert gerade, kurz weiterprobieren
            pass
        await asyncio.sleep(takt)
    return False


class SchrittFehler(RuntimeError):
    """Ein Ablaufschritt ist nicht wie erwartet eingetreten – mit Screenshot und Begründung abgebrochen,
    statt blind weiterzumachen (z. B. auf einen inzwischen verdeckten/versteckten Knopf zu klicken)."""


async def schritt_oder_abbrechen(seite: Page, bericht: "Bericht", name: str, ausdruck: str,
                                 timeout_s: float = 20.0) -> None:
    """Wartet auf `ausdruck`; bei Erfolg ein ✅-Prüfpunkt, sonst Screenshot + ❌ + Abbruch (SchrittFehler) –
    kein Folgeschritt (z. B. ein Klick auf einen inzwischen unsichtbaren Knopf) läuft dann noch blind los."""
    if await warten_auf(seite, ausdruck, timeout_s):
        bericht.pruefen(name, "ok")
        return
    await bericht.screenshot(seite, f"fehler_{name}".replace(" ", "_"))
    z = None
    try:
        z = await zustand(seite)
    except Exception:  # noqa: BLE001
        pass
    detail = f"zustand.fehler={z.get('fehler')!r}, hoeren={z.get('hoeren')}" if z else "Zustand nicht lesbar"
    bericht.pruefen(name, "fehlt", detail)
    raise SchrittFehler(f"{name}: {detail}")


# ---------- Robuste Stelle: Einrichten-Bereich (Agenda per Prompt), paralleles Ticket #10 kann die DOM ändern ----
async def agenda_eingabe_finden(seite: Page):
    """Liefert (eingabefeld, senden_knopf) für die Agenda per Prompt – mehrere Strategien, die erste, die ein
    sichtbares Element liefert, gewinnt. Wenn alles fehlschlägt: None, None (Aufrufer fällt auf die
    Vorgabetabelle zurück und vermerkt es im Bericht statt das Skript abbrechen zu lassen)."""
    kandidaten_feld = [
        lambda: seite.locator("#einrichtung textarea").first,
        lambda: seite.get_by_placeholder(re.compile("sprechen|einfügen|Agenda", re.I)).first,
        lambda: seite.locator("#einrichtung").get_by_role("textbox").first,
    ]
    # Die Seite füllt den Einrichten-Bereich erst über ihre eigene Start-IIFE (agendaInit(), Regeln,
    # Szenarien …), das kann nach dem Laden noch ein paar hundert ms dauern - mehrfach probieren statt
    # einmalig, sonst ein falsches "nicht gefunden" durch reine Zeitlupe.
    t0 = time.monotonic()
    feld = None
    while time.monotonic() - t0 < 8.0:
        for versuch in kandidaten_feld:
            kandidat = versuch()
            try:
                if await kandidat.count() and await kandidat.is_visible():
                    feld = kandidat
                    break
            except Exception:  # noqa: BLE001
                continue
        if feld is not None:
            break
        await asyncio.sleep(0.3)
    if feld is None:
        return None, None
    kandidaten_knopf = [
        lambda: seite.locator("#einrichtung").get_by_role("button", name=re.compile("Absenden|Senden", re.I)).first,
        lambda: seite.locator("#agenda-senden"),
    ]
    for versuch in kandidaten_knopf:
        knopf = versuch()
        try:
            if await knopf.count():
                return feld, knopf
        except Exception:  # noqa: BLE001
            continue
    return feld, None


async def einrichten(seite: Page, agenda_text: str, bericht: Bericht) -> None:
    # In der Cloud kommt der erste Stand über die WebSocket spürbar später als lokal – erst darauf warten
    if not await warten_auf(seite, "() => !!zustand", timeout_s=60.0):
        bericht.pruefen("Erster Stand vom Server", "fehlt", "nach 60 s kein Zustand über die WebSocket")
    feld, knopf = await agenda_eingabe_finden(seite)
    if feld is None:
        bericht.pruefen("Agenda-Eingabefeld gefunden", "fehlt",
                        "keine der bekannten Stellen im Einrichten-Bereich getroffen (Oberfläche geändert?)")
        return
    deaktiviert = await feld.is_disabled()
    if deaktiviert:
        bericht.pruefen("Agenda per Prompt", "offline",
                        "Eingabefeld deaktiviert (kein Schlüssel/LMC_OFFLINE) – Tabelle bleibt bei Vorgabe")
        return
    if knopf is None:
        bericht.pruefen("Agenda-Senden-Knopf gefunden", "fehlt", "Eingabefeld da, Knopf nicht gefunden")
        return
    vor = await zustand(seite)
    await feld.fill(agenda_text)
    await knopf.click()
    bekommen = await warten_auf(seite, "() => !!(zustand && zustand.titel && zustand.agenda && "
                                       "zustand.agenda.length > 0)", timeout_s=30.0)
    nach = await zustand(seite)
    if bekommen and nach.get("titel") and nach.get("agenda"):
        titel, n_punkte = nach.get("titel"), len(nach.get("agenda", []))
        bericht.pruefen("Agenda aus Einladungsmail übernommen (Titel/Ziel/Agenda gefüllt)", "ok",
                        f"Titel „{titel}“, {n_punkte} Punkte")
    else:
        bericht.pruefen("Agenda aus Einladungsmail übernommen", "fehlt",
                        f"vorher leer={not vor.get('agenda')}, nachher titel={nach.get('titel')!r}")


# ---------- Ablauf ----------
async def anmelden(seite: Page, url: str, passwort: str, bericht: Bericht) -> None:
    t0 = time.monotonic()
    await seite.goto(url)
    if "anmelden" in seite.url or await seite.locator('input[name="passwort"]').count():
        await seite.locator('input[name="passwort"]').fill(passwort)
        await seite.get_by_role("button", name=re.compile("Anmelden", re.I)).click()
        await seite.wait_for_load_state("domcontentloaded")
        if "falsch" in seite.url or await seite.locator('input[name="passwort"]').count():
            bericht.pruefen("Anmeldung", "fehlt", "Passwort nicht akzeptiert")
            raise SystemExit(1)
        bericht.pruefen("Anmeldung", "ok")
    bericht.messwerte["kaltstart_s"] = round(time.monotonic() - t0, 1)


async def startseite(seite: Page, stufe: str, nur_knopfdruck: bool, bericht: Bericht) -> None:
    await schritt_oder_abbrechen(seite, bericht, "Startseite geladen",
                                 "() => !!document.getElementById('karte-basis')", 20.0)
    if nur_knopfdruck:
        await seite.locator("#nur-knopfdruck").check()
    await bericht.screenshot(seite, "startseite")
    knopf = seite.locator("#karte-basis" if stufe == "basis" else "#karte-premium")
    if await knopf.is_disabled():
        # Ticket #13: ohne Schlüssel (Mistral für Basis, OpenAI für Premium) ist die Karte deaktiviert -
        # unabhängig von LMC_OFFLINE (coach/api_start.py prüft nur, ob ein Schlüssel-String vorhanden ist).
        # Für den offline-Probelauf braucht es einen Platzhalter-Schlüssel in der Umgebung/.env; ein echter
        # KI-Aufruf bleibt trotzdem aus, weil coach/pipeline.py ki_verfuegbar() zuerst LMC_OFFLINE prüft.
        await bericht.screenshot(seite, "fehler_stufe_deaktiviert")
        bericht.pruefen(f"Stufe {stufe} wählbar", "fehlt",
                        "Karte deaktiviert – kein Schlüssel (OPENAI_API_KEY/MISTRAL_API_KEY) in der Umgebung")
        raise SchrittFehler(f"Stufe {stufe} ist auf diesem Server nicht eingerichtet (kein Schlüssel)")
    await knopf.click()
    await schritt_oder_abbrechen(seite, bericht, "Weiter zu /meeting", "() => location.pathname === '/meeting'", 15.0)
    await seite.wait_for_selector("#einrichtung", state="visible", timeout=15000)


async def meeting_starten(seite: Page, agenda_text: str, bericht: Bericht) -> float:
    await einrichten(seite, agenda_text, bericht)
    await bericht.screenshot(seite, "agenda-tabelle")
    await seite.locator("#btn-start").click()
    # Hart abbrechen statt blind weiterzumachen: ohne laufendes Meeting wäre jeder folgende Schritt
    # (Knöpfe, Mitschnitt, "Beenden"-Klick) ohnehin sinnlos und würde nur auf unsichtbare Elemente warten.
    await schritt_oder_abbrechen(seite, bericht, "Meeting gestartet (Mikrofon aus Datei angenommen)",
                                 "() => !document.getElementById('live').hidden", 25.0)
    return time.monotonic()


def ereignis_hinweisarten(ereignis: str) -> tuple[str, ...]:
    """Welche Hinweis-/Ampel-Arten ein eingebautes Ereignis im Dashboard auslösen sollte."""
    return {
        "monolog": ("monolog",), "wechsel_ansage": ("ansage",), "abschweifung": ("fokus",),
        "kraftausdruck": ("ton",), "beschluss": ("ergebnisse",), "aufgabe_ohne_zustaendig": ("ergebnisse",),
    }.get(ereignis, ())


LOKAL_OHNE_KI = {"monolog"}  # läuft auch mit LMC_OFFLINE (lokale VAD/Diarisierung, Lastenheft §3)


async def aufzeichnen(seite: Page, referenz: dict, nur_knopfdruck: bool, bericht: Bericht,
                      meeting_start: float) -> list[dict]:
    """Zustand alle 2 s aus der Seite lesen (sie hält ihn über ihre eigene /ws aktuell) – Mitschnitt für die
    Prüfliste, Verzugsmessung je Nestor-Anweisung und für die Knöpfe mit --nur-knopfdruck."""
    verlauf: list[dict] = []
    letzte_zeit = -1.0
    soll_dauer = referenz["dauer_s"] + 20
    geknopft: set[str] = set()
    naechster_screenshot = iter(sorted(SCREENSHOT_ZEITEN.items(), key=lambda kv: kv[1]))
    ss_name, ss_zeit = next(naechster_screenshot, (None, None))
    kosten_vor_erstem_knopf = None
    vorzeitig_beendet = False  # hoeren wurde false, bevor wir absichtlich "Beenden" gedrückt haben

    while time.monotonic() - meeting_start < soll_dauer + 30:
        try:
            z = await zustand(seite)
        except Exception:  # noqa: BLE001
            await asyncio.sleep(1.0)
            continue
        if not z or not z.get("hoeren"):
            vorzeitig_beendet = True
            break
        t = z.get("zeit", 0.0)
        if t < letzte_zeit - 2.0:
            bericht.notieren(f"Meetingzeit sprang von {letzte_zeit:.0f}s auf {t:.0f}s zurück – "
                             "Mikrofon-Datei ist wohl in Schleife gelaufen, beende den Lauf jetzt.")
            break
        letzte_zeit = t
        verlauf.append(z)

        if ss_zeit is not None and t >= ss_zeit:
            await bericht.screenshot(seite, f"dashboard_{ss_name.replace(':', '')}")
            ss_name, ss_zeit = next(naechster_screenshot, (None, None))

        if nur_knopfdruck:
            offline = bool((z.get("schluessel") or {}).get("offline"))
            if "stand" not in geknopft and t >= KNOPF_ZEITEN["stand"]:
                geknopft.add("stand")
                kosten_vor_erstem_knopf = z.get("kosten", {}).get("meeting", 0.0)
                await knopf_druecken(seite, "stand", offline, bericht)
            if "regeln" not in geknopft and t >= KNOPF_ZEITEN["regeln"]:
                geknopft.add("regeln")
                await knopf_druecken(seite, "regeln", offline, bericht)
            if "verwerfen_5" not in geknopft and t >= KNOPF_ZEITEN["verwerfen_5"]:
                geknopft.add("verwerfen_5")
                await verwerfen_5(seite, bericht)
            if "protokoll" not in geknopft and t >= KNOPF_ZEITEN["protokoll"]:
                geknopft.add("protokoll")
                await knopf_druecken(seite, "protokoll", offline, bericht)
            if kosten_vor_erstem_knopf is not None:
                bericht.messwerte.setdefault("kein_ki_vor_erstem_knopf", kosten_vor_erstem_knopf == 0.0)

        if t >= soll_dauer:
            break
        await asyncio.sleep(2.0)

    if vorzeitig_beendet:
        # Das Mikro/Meeting ist von selbst aus "hoeren" - "Beenden" ist dann versteckt (app.js: btn-stopp.hidden
        # = !z.hoeren) und ein Klick würde nur 30 s lang auf ein unsichtbares Element warten. Stattdessen den
        # letzten bekannten Stand und, falls vorhanden, zustand.fehler klar vermerken und zur Abschlussseite
        # nur gehen, wenn der Server selbst schon dort gelandet ist (z. B. ein serverseitiges Beenden).
        letzter = verlauf[-1] if verlauf else {}
        bericht.notieren(f"Hörstrom endete vorzeitig bei {letzter.get('zeit', '?')}s "
                         f"(Soll ~{soll_dauer:.0f}s) – zustand.fehler={letzter.get('fehler')!r}.")
        bericht.pruefen("Meeting lief bis zum Ende durch (nicht vorzeitig beendet)", "fehlt",
                        f"hoeren wurde false bei {letzter.get('zeit', '?')}s statt bei ~{soll_dauer:.0f}s")
        if await seite.evaluate("() => location.pathname") != "/abschluss":
            raise SchrittFehler("Meeting endete vorzeitig, ohne auf der Abschlussseite zu landen")
        return verlauf

    await seite.locator("#btn-stopp").click()
    await schritt_oder_abbrechen(seite, bericht, "Zur Abschlussseite gewechselt",
                                 "() => location.pathname === '/abschluss'", 15.0)
    return verlauf


async def knopf_druecken(seite: Page, art: str, offline: bool, bericht: Bericht) -> None:
    t0 = time.monotonic()
    await seite.locator(f'.knopf-art[data-knopf="{art}"]').click()
    fertig = await warten_auf(seite, f"() => !(zustand.knopf && zustand.knopf.laeuft === '{art}')", 60.0)
    dauer = round(time.monotonic() - t0, 1)
    z = await zustand(seite)
    fehler = (z.get("knopf") or {}).get("fehler")
    titel = f"Knopf „{art}“"
    if offline:
        bericht.pruefen(f"{titel} (offline)", "offline",
                        f"{dauer} s, Fehlermeldung: {fehler or '(keine)'}" if fehler else f"{dauer} s")
    elif fehler:
        bericht.pruefen(titel, "fehlt", f"{dauer} s, Fehler: {fehler}")
    else:
        bericht.pruefen(titel, "ok" if fertig else "fehlt", f"{dauer} s")


async def verwerfen_5(seite: Page, bericht: Bericht) -> None:
    vor = await zustand(seite)
    vorher_segmente = len(vor.get("segmente", []))
    await seite.locator("#knopf-verwerfen-5").click()
    await asyncio.sleep(1.5)
    nach = await zustand(seite)
    bericht.pruefen("Letzte 5 Minuten verwerfen", "ok",
                    f"Segmente vorher {vorher_segmente}, nachher {len(nach.get('segmente', []))}")


# ---------- Abschluss ----------
async def abschluss(seite: Page, bericht: Bericht, offline: bool) -> None:
    da = await warten_auf(seite, "() => !document.getElementById('ab-inhalt').hidden", 40.0)
    if not da:
        bericht.pruefen("Abschlussseite geladen", "fehlt")
        return
    await bericht.screenshot(seite, "abschluss")

    fertig = await warten_auf(seite, "() => !document.getElementById('btn-paket').disabled", 30.0)
    if not fertig:
        bericht.pruefen("Paket herunterladen", "fehlt", "Ablage wurde nicht fertig")
    else:
        async with seite.expect_download() as dl_info:
            await seite.locator("#btn-paket").click()
        download = await dl_info.value
        # In die Arbeitskopie statt /tmp (RAM-Disk) speichern, nur zur Prüfung des Inhalts
        pfad = bericht.ordner / "paket.zip"
        await download.save_as(str(pfad))
        try:
            with zipfile.ZipFile(pfad) as z:
                namen = z.namelist()
            # protokoll.md kommt nur, wenn es eine echte Ergebnisprüfung gab (Regel 10, braucht KI,
            # coach/abschluss.py: paket() nimmt die Datei nur mit, wenn sie existiert) - mit LMC_OFFLINE
            # also erwartbar nicht dabei. Sonst (transkript.md, agenda.md, hinweise.md) immer Pflicht.
            erwartet = ["transkript.md", "agenda.md", "hinweise.md"] + ([] if offline else ["protokoll.md"])
            fehlend = [n for n in erwartet if not any(n in x for x in namen)]
            bericht.pruefen("Paket-Inhalt", "ok" if not fehlend else "fehlt",
                            f"{len(namen)} Dateien: {', '.join(namen)}" + (f" (fehlt: {fehlend})" if fehlend else ""))
        except Exception as e:  # noqa: BLE001
            bericht.pruefen("Paket-Inhalt", "fehlt", f"ZIP nicht lesbar: {e}")

    await seite.locator("#fb-text").fill("Cloud-Testlauf (automatisiert) – nur zur Prüfung des Ablaufs.")
    await seite.locator("#btn-feedback").click()
    ok = await warten_auf(seite, "() => !document.getElementById('fb-danke').hidden", 10.0)
    bericht.pruefen("Feedback senden", "ok" if ok else "fehlt")

    await seite.locator("#sp-einverstanden").check()
    if not await seite.locator("#btn-spende").is_disabled():
        await seite.locator("#btn-spende").click()
        ok = await warten_auf(seite, "() => !document.getElementById('sp-danke').hidden", 15.0)
        bericht.pruefen("Datenspende mit Häkchen senden", "ok" if ok else "fehlt")
    else:
        bericht.pruefen("Datenspende mit Häkchen senden", "fehlt", "Knopf blieb deaktiviert (Ablage nicht fertig?)")


# ---------- Prüfliste gegen referenz.json ----------
def pruefliste_bauen(referenz: dict, verlauf: list[dict], bericht: Bericht) -> None:
    offline_lauf = bool(verlauf) and bool((verlauf[-1].get("schluessel") or {}).get("offline"))

    for e in referenz["ereignisse"]:
        name = f"Ereignis „{e['ereignis']}“ bei {e['zeit_s']:.0f}s"
        if e["ereignis"] not in LOKAL_OHNE_KI and offline_lauf:
            bericht.pruefen(name, "offline", "braucht Text-/Themen-KI, mit LMC_OFFLINE nicht verfügbar")
            continue
        arten = ereignis_hinweisarten(e["ereignis"])
        treffer = [h for z in verlauf for h in z.get("hinweise", [])
                  if h.get("art") in arten and abs(h.get("zeit", 1e9) - e["zeit_s"]) < 90]
        if treffer:
            verzug = min(h["zeit"] for h in treffer) - e["zeit_s"]
            bericht.pruefen(name, "ok", f"Verzug {verzug:+.0f}s")
        else:
            bericht.pruefen(name, "fehlt", "kein passender Hinweis im Mitschnitt")

    for n in referenz["nestor"]:
        kurz = n["text"][:40] + "…" if len(n["text"]) > 40 else n["text"]
        name = f"Nestor-Anweisung „{kurz}“"
        if offline_lauf:
            bericht.pruefen(name, "offline", "ohne Schlüssel keine Antwort möglich")
            continue
        karten = [k for z in verlauf for k in z.get("karten", []) if k.get("zeit", 0) >= n["start"] - 5]
        if karten:
            bericht.pruefen(name, "ok", f"Antwort nach {karten[0]['zeit'] - n['start']:.1f}s")
        else:
            bericht.pruefen(name, "fehlt", "keine Karte danach gesehen")

    fehler_eintraege = [f for z in verlauf for f in ([z["fehler"]] if z.get("fehler") else [])]
    bericht.pruefen("Keine Einträge in fehler", "ok" if not fehler_eintraege else "fehlt",
                    "; ".join(sorted(set(fehler_eintraege))[:3]))

    if verlauf:
        bericht.messwerte["kosten_usd"] = verlauf[-1].get("kosten", {}).get("meeting", 0.0)
        bericht.messwerte["meeting_s"] = round(verlauf[-1].get("zeit", 0.0), 1)


async def chromium_starten(pw, args: argparse.Namespace, bericht: Bericht, versuche: int = 5):
    """Start mit Wiederholung: der Pi hat wenig freien Speicher (andere Dienste, mehrere parallele
    Sitzungen) und Chromiums Start schlägt unter Druck gelegentlich mit SIGTRAP fehl (PartitionAlloc bricht
    hart ab, statt zu warten) – schon beobachtet, kein Einzelfall. Ein neuer Versuch nach kurzer Pause
    reicht meist, weil der Speicherdruck schwankt; schlägt es mehrfach fehl, ist das ein echter Befund."""
    sparsam = ["--disable-gpu", "--disable-software-rasterizer", "--renderer-process-limit=1",
              "--js-flags=--max-old-space-size=256"]
    fehler = None
    for versuch in range(1, versuche + 1):
        try:
            return await pw.chromium.launch(
                executable_path=args.chromium, headless=True,
                args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                     f"--use-file-for-fake-audio-capture={args.audio}",
                     "--autoplay-policy=no-user-gesture-required", *sparsam])
        except Exception as e:  # noqa: BLE001
            fehler = e
            bericht.notieren(f"Chromium-Start Versuch {versuch}/{versuche} fehlgeschlagen ({type(e).__name__}) "
                             "– vermutlich Speicherdruck auf dem Pi, neuer Versuch in 5 s.")
            await asyncio.sleep(5.0)
    bericht.fehler.append(f"Chromium startete nach {versuche} Versuchen nicht (Speicherdruck auf dem Pi): {fehler}")
    raise RuntimeError(f"Chromium startete nach {versuche} Versuchen nicht: {fehler}")


# ---------- main ----------
async def lauf(args: argparse.Namespace) -> Bericht:
    referenz = json.loads(Path(args.referenz).read_text(encoding="utf-8"))
    bericht = Bericht(Path(args.bericht))
    stufe_text = f"{args.stufe}" + (" · nur auf Knopfdruck" if args.nur_knopfdruck else "")
    bericht.messwerte.update(modus=stufe_text, gestartet=jetzt(), soll_dauer_s=referenz["dauer_s"])

    async with async_playwright() as pw:
        browser = await chromium_starten(pw, args, bericht)
        context = await browser.new_context(permissions=["microphone"])
        seite = await context.new_page()
        # JS-Fehler, Konsole und native Dialoge (alert/confirm) mitschneiden: ein unbeantworteter Dialog
        # würde die Seite sonst stillschweigend blockieren und jeden folgenden Klick "einfrieren" lassen.
        seite.on("pageerror", lambda e: bericht.fehler.append(f"JS-Fehler im Browser: {e}"))
        seite.on("console", lambda m: bericht.fehler.append(f"Konsole ({m.type}): {m.text}")
                 if m.type == "error" else None)
        seite.on("dialog", lambda d: (bericht.notieren(f"Dialog automatisch bestätigt: {d.message}"),
                                      asyncio.ensure_future(d.accept())))
        verlauf: list[dict] = []
        try:
            await anmelden(seite, args.url, args.passwort, bericht)
            await startseite(seite, args.stufe, args.nur_knopfdruck, bericht)
            meeting_start = await meeting_starten(seite, Path(args.agenda_prompt).read_text(encoding="utf-8"),
                                                  bericht)
            verlauf = await aufzeichnen(seite, referenz, args.nur_knopfdruck, bericht, meeting_start)
            z_letzt = verlauf[-1] if verlauf else {}
            offline = bool((z_letzt.get("schluessel") or {}).get("offline"))
            await abschluss(seite, bericht, offline)
            pruefliste_bauen(referenz, verlauf, bericht)
        except SchrittFehler as e:
            bericht.fehler.append(f"Lauf abgebrochen: {e}")
            bericht.notieren(f"Abgebrochen: {e}")
            if verlauf:  # trotz Abbruch die bis dahin gesammelten Prüfpunkte gegen die Referenz auswerten
                pruefliste_bauen(referenz, verlauf, bericht)
        finally:
            await context.close()
            await browser.close()
    bericht.schreiben()
    bericht.notieren(f"Bericht: {bericht.ordner / 'bericht.md'}")
    return bericht


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--passwort", default=None)
    ap.add_argument("--stufe", required=True, choices=["basis", "premium"], help="Ticket #13: Nestor Basis/Premium")
    ap.add_argument("--nur-knopfdruck", action="store_true",
                    help="nur zusammen mit --stufe basis: der frühere Modus „Auf Knopfdruck“")
    ap.add_argument("--bericht", default=None)
    ap.add_argument("--referenz", default=str(CLOUDTEST / "referenz.json"))
    ap.add_argument("--audio", default=str(CLOUDTEST / "meeting.wav"))
    ap.add_argument("--agenda-prompt", default=str(CLOUDTEST / "agenda_prompt.txt"))
    ap.add_argument("--chromium", default=CHROMIUM)
    args = ap.parse_args()
    if args.nur_knopfdruck and args.stufe != "basis":
        ap.error("--nur-knopfdruck gibt es nur mit --stufe basis (Ticket #13).")
    if not args.bericht:
        name = f"{args.stufe}-knopfdruck" if args.nur_knopfdruck else args.stufe
        args.bericht = str(WURZEL / "logs" / "cloudtest" / f"{datetime.now():%Y-%m-%d_%H%M}_{name}")
    asyncio.run(lauf(args))


if __name__ == "__main__":
    main()
