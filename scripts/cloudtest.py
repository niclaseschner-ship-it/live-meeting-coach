r"""Cloud-Testlauf (Ticket „Cloudtest", Lastenheft: alles, bes. 2, 3, 4.2-4.6): ein echter Browser durchläuft
Nestor wie ein echter Kunde – Anmelden (falls --passwort gesetzt), Modus wählen, Agenda per Prompt einrichten,
zehn Minuten in Echtzeit zuhören (Mikrofon aus einer Datei, kein Vorspulen), im Modus Knopfdruck die Knöpfe zu
festen Zeiten drücken, Abschluss mit Paket, Feedback und Datenspende. Mitgeschnitten wird aus der Seite selbst
(sie hält ihren Zustand ohnehin über die gleiche WebSocket wie das Dashboard aktuell, siehe static/basis.js);
ein zweiter eigener /ws-Mitschnitt wäre nur eine doppelte Quelle für dieselbe Information.

    ~/.venvs/lmc/bin/python scripts/cloudtest.py --url http://127.0.0.1:8000 --modus live
    ~/.venvs/lmc/bin/python scripts/cloudtest.py --url https://nestor.example.workers.dev \
        --passwort geheim --modus knopfdruck --bericht logs/cloudtest/lauf1

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

# /tmp ist auf dem Pi eine RAM-Disk (CLAUDE.md) – Chromiums Profil- und Downloadreste gehören in die
# Arbeitskopie (gitignored), nicht dorthin. Vor dem Playwright-Import setzen, der das beim Start liest.
_TMP = WURZEL / "logs" / "cloudtest" / ".tmp"
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
    return await seite.evaluate("() => zustand")


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
    for versuch in kandidaten_feld:
        feld = versuch()
        try:
            if await feld.count() and await feld.is_visible():
                break
        except Exception:  # noqa: BLE001
            continue
    else:
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


async def startseite(seite: Page, modus: str, bericht: Bericht) -> None:
    await warten_auf(seite, "() => !!document.getElementById('karte-live')", 20.0)
    await bericht.screenshot(seite, "startseite")
    knopf = seite.locator("#karte-live" if modus == "live" else "#karte-knopfdruck")
    await knopf.click()
    await warten_auf(seite, "() => location.pathname === '/meeting'", 15.0)
    await seite.wait_for_selector("#einrichtung", state="visible", timeout=15000)


async def meeting_starten(seite: Page, agenda_text: str, bericht: Bericht) -> float:
    await einrichten(seite, agenda_text, bericht)
    await bericht.screenshot(seite, "agenda-tabelle")
    await seite.locator("#btn-start").click()
    gestartet = await warten_auf(seite, "() => !document.getElementById('live').hidden", 25.0)
    bericht.pruefen("Meeting gestartet (Mikrofon aus Datei angenommen)", "ok" if gestartet else "fehlt")
    return time.monotonic()


def ereignis_hinweisarten(ereignis: str) -> tuple[str, ...]:
    """Welche Hinweis-/Ampel-Arten ein eingebautes Ereignis im Dashboard auslösen sollte."""
    return {
        "monolog": ("monolog",), "wechsel_ansage": ("ansage",), "abschweifung": ("fokus",),
        "kraftausdruck": ("ton",), "beschluss": ("ergebnisse",), "aufgabe_ohne_zustaendig": ("ergebnisse",),
    }.get(ereignis, ())


LOKAL_OHNE_KI = {"monolog"}  # läuft auch mit LMC_OFFLINE (lokale VAD/Diarisierung, Lastenheft §3)


async def aufzeichnen(seite: Page, referenz: dict, modus: str, bericht: Bericht, meeting_start: float) -> list[dict]:
    """Zustand alle 2 s aus der Seite lesen (sie hält ihn über ihre eigene /ws aktuell) – Mitschnitt für die
    Prüfliste, Verzugsmessung je Nestor-Anweisung und für die Knöpfe im Modus Knopfdruck."""
    verlauf: list[dict] = []
    letzte_zeit = -1.0
    soll_dauer = referenz["dauer_s"] + 20
    geknopft: set[str] = set()
    naechster_screenshot = iter(sorted(SCREENSHOT_ZEITEN.items(), key=lambda kv: kv[1]))
    ss_name, ss_zeit = next(naechster_screenshot, (None, None))
    kosten_vor_erstem_knopf = None

    while time.monotonic() - meeting_start < soll_dauer + 30:
        try:
            z = await zustand(seite)
        except Exception:  # noqa: BLE001
            await asyncio.sleep(1.0)
            continue
        if not z or not z.get("hoeren"):
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

        if modus == "knopfdruck":
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

    await seite.locator("#btn-stopp").click()
    await warten_auf(seite, "() => location.pathname === '/abschluss'", 15.0)
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
            erwartet = ["protokoll.md"]
            fehlend = [n for n in erwartet if not any(n in x for x in namen)]
            bericht.pruefen("Paket-Inhalt", "ok" if not fehlend else "fehlt",
                            f"{len(namen)} Dateien: {', '.join(namen)}")
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
def pruefliste_bauen(referenz: dict, verlauf: list[dict], modus: str, bericht: Bericht) -> None:
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
    bericht.messwerte.update(modus=args.modus, gestartet=jetzt(), soll_dauer_s=referenz["dauer_s"])

    async with async_playwright() as pw:
        browser = await chromium_starten(pw, args, bericht)
        context = await browser.new_context(permissions=["microphone"])
        seite = await context.new_page()
        seite.on("pageerror", lambda e: bericht.fehler.append(f"JS-Fehler im Browser: {e}"))
        try:
            await anmelden(seite, args.url, args.passwort, bericht)
            await startseite(seite, args.modus, bericht)
            meeting_start = await meeting_starten(seite, Path(args.agenda_prompt).read_text(encoding="utf-8"),
                                                  bericht)
            verlauf = await aufzeichnen(seite, referenz, args.modus, bericht, meeting_start)
            z_letzt = verlauf[-1] if verlauf else {}
            offline = bool((z_letzt.get("schluessel") or {}).get("offline"))
            await abschluss(seite, bericht, offline)
            pruefliste_bauen(referenz, verlauf, args.modus, bericht)
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
    ap.add_argument("--modus", required=True, choices=["live", "knopfdruck"])
    ap.add_argument("--bericht", default=None)
    ap.add_argument("--referenz", default=str(CLOUDTEST / "referenz.json"))
    ap.add_argument("--audio", default=str(CLOUDTEST / "meeting.wav"))
    ap.add_argument("--agenda-prompt", default=str(CLOUDTEST / "agenda_prompt.txt"))
    ap.add_argument("--chromium", default=CHROMIUM)
    args = ap.parse_args()
    if not args.bericht:
        args.bericht = str(WURZEL / "logs" / "cloudtest" / f"{datetime.now():%Y-%m-%d_%H%M}_{args.modus}")
    asyncio.run(lauf(args))


if __name__ == "__main__":
    main()
