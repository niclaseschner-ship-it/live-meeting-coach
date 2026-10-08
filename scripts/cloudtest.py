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

Zwei Testmaterialien unter testbibliothek/cloudtest/ (--referenz/--audio/--agenda-prompt wählen):
  referenz.json / meeting.wav / agenda_prompt.txt                        (#9, Vereinsrunde)
  referenz_grenzfaelle.json / meeting_grenzfaelle.wav / agenda_prompt_grenzfaelle.txt  (#11, Incident-Review
      mit zwölf Grenzfällen der Ansprache – siehe docs/qualitaet.md)

Playwright mit dem System-Chromium (kein `playwright install`). Seit Ticket #25 reden die Teilnehmenden
abwechselnd mit Nestor: ein Init-Script ersetzt getUserMedia durch eine steuerbare WebAudio-Quelle, der Test
spielt das Material abschnittsweise und wartet dazwischen, bis Nestor fertig ist (scripts/cloudtest_takt.py).
Mit --am-stueck der alte Modus: --use-file-for-fake-audio-capture=<meeting.wav> lässt Chromium die Datei am
Stück wie ein echtes Mikrofon in Echtzeit liefern (Lasttests). Testmaterial und Referenz: testbibliothek/cloudtest/ (siehe dort bauen.py und README in
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

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cloudtest_takt as takt  # noqa: E402 – abwechselnd reden (#25)

# Meetingzeit (zustand.zeit, Sekunden seit Start), zu der jeweils etwas passieren soll.
SCREENSHOT_TAKT = 30.0  # Sekunden (Ticket #11: "alle 30 s plus an jedem Ereignis")
KNOPF_ZEITEN = {"stand": 180, "regeln": 360, "verwerfen_5": 510, "protokoll": 570}


def screenshot_ziele(referenz: dict) -> list[float]:
    """Alle 30 s plus an jedem Ereignis/jeder Nestor-Anweisung/jedem Grenzfall aus referenz.json – sortiert
    und ohne Dopplungen (ein fester Takt allein hätte kurze Ereignisse zwischen zwei Aufnahmen verpasst)."""
    takt = [round(t, 1) for t in range(0, int(referenz["dauer_s"]) + 30, int(SCREENSHOT_TAKT))]
    ereignisse = [e["zeit_s"] for e in referenz.get("ereignisse", [])]
    nestor = [n["start"] for n in referenz.get("nestor", [])]
    grenzfaelle = [g["start"] for g in referenz.get("grenzfaelle", [])]
    return sorted(set(takt) | set(ereignisse) | set(nestor) | set(grenzfaelle))


def jetzt() -> str:
    return datetime.now().strftime("%H:%M:%S")


def mmss(sekunden: float) -> str:
    s = max(0, int(sekunden))
    return f"{s // 60}:{s % 60:02d}"


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

    STATUS_ZEICHEN = {"ok": "✅", "fehlt": "❌", "offline": "⏭️", "beobachtet": "📝"}

    def pruefen(self, name: str, status: str, detail: str = "") -> None:
        """status: 'ok' | 'fehlt' | 'offline' (KI-Prüfpunkt ohne Schlüssel übersprungen) | 'beobachtet'
        (kein klares Richtig/Falsch möglich, z. B. Grenzfälle mit Ticket-Vorgabe "Ergebnis dokumentieren" –
        wird im Bericht festgehalten, ohne es als ✅/❌ zu werten)."""
        self.pruefliste.append({"name": name, "status": status, "detail": detail})
        self.notieren(f"{self.STATUS_ZEICHEN[status]} {name}{' – ' + detail if detail else ''}")

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
        beobachtet = sum(1 for p in self.pruefliste if p["status"] == "beobachtet")
        versatz = self.messwerte.get("versatz_s")
        versatz_zeile = (f"Versatz Referenzzeit↔Meetinguhr: {versatz:+.1f}s" if versatz is not None
                        else "Versatz Referenzzeit↔Meetinguhr: nicht schätzbar")
        if self.messwerte.get("versatz_anfang_s") is not None:
            versatz_zeile += (f" (wächst von {self.messwerte['versatz_anfang_s']:+.1f}s am Anfang auf "
                              f"{self.messwerte['versatz_ende_s']:+.1f}s am Ende)")
        zeilen = [
            f"# Cloud-Testlauf – {self.messwerte.get('modus', '?')}", "",
            f"Gestartet {self.messwerte.get('gestartet', '?')}, Dauer {self.messwerte.get('meeting_s', '?')} s "
            f"(Soll ~{self.messwerte.get('soll_dauer_s', '?')} s). "
            f"Kaltstart Startseite: {self.messwerte.get('kaltstart_s', '?')} s. {versatz_zeile}.",
            "", f"**Prüfliste:** {ok} ✅ · {fehlt} ❌ · {offline} ⏭️ übersprungen (offline) · "
                f"{beobachtet} 📝 dokumentiert (kein klares Richtig/Falsch)", "",
            "| Prüfpunkt | Status | Detail |", "|---|---|---|",
        ]
        for p in self.pruefliste:
            zeilen.append(f"| {p['name']} | {self.STATUS_ZEICHEN[p['status']]} | {p['detail']} |")
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
    # null, bis die WebSocket den ersten Stand geliefert hat; auf der Startseite gibt es `zustand` gar nicht
    return await seite.evaluate("() => (typeof zustand !== 'undefined' ? zustand : null)") or {}


# ---------- Reine Funktionen auf einer Liste von ws.jsonl-Zeilen ({"t","richtung","daten"}) ----------
# Getrennt von WsSpur, damit scripts/cloudtest_bewerten.py dieselbe Auswertung auf einer bereits gespeicherten
# ws.jsonl fahren kann (z. B. mit einer korrigierten Versatz-Schätzung), ohne einen Live-Lauf zu brauchen.
def zustaende_aus_frames(frames: list[dict]) -> list[dict]:
    """Volle Zustands-Broadcasts (nicht die schmalen Typen pegel/knopf/stimme/stimme_stopp), in der
    empfangenen Reihenfolge, mit dem Mitschnitt-Zeitstempel ("_t") ergänzt."""
    aus = []
    for f in frames:
        d = f["daten"]
        if f["richtung"] != "empfangen" or not isinstance(d, dict) or "typ" in d or "zeit" not in d:
            continue
        aus.append({**d, "_t": f["t"]})
    return aus


def nachrichten_aus_frames(frames: list[dict], typ: str) -> list[dict]:
    aus = []
    for f in frames:
        d = f["daten"]
        if f["richtung"] == "empfangen" and isinstance(d, dict) and d.get("typ") == typ:
            aus.append({**d, "_t": f["t"]})
    return aus


class WsSpur:
    """Mitschnitt aller Nachrichten auf der Zustands-WebSocket (/ws, nicht /ws/audio – das ist nur Mikrofon-
    Binärdaten), mit Zeit relativ zum Laufstart – Ticket #11 Punkt 4 (Traces). Einzige verlässliche Quelle für
    die Auswertung (pruefliste_bauen): das 2-s-Polling von aufzeichnen() sieht nur Momentaufnahmen und verpasst
    kurzlebige Hinweise/Kartenwechsel zwischen zwei Abfragen."""

    def __init__(self, ordner: Path, start: float) -> None:
        self.start = start
        self.frames: list[dict] = []
        self.datei = (ordner / "ws.jsonl").open("w", encoding="utf-8")
        # Für das Abwarten (scripts/cloudtest_takt.py, #25): wann zuletzt Ton kam, wie oft gestoppt wurde
        self.letzte_stimme_t: float | None = None
        self.stopp_zahl = 0
        self._stimme_bytes: list[tuple[float, int]] = []

    def anhaengen(self, seite: Page) -> None:
        seite.on("websocket", self._bei_websocket)

    def _bei_websocket(self, ws) -> None:
        if not ws.url.rstrip("/").endswith("/ws"):  # nicht /ws/audio (Mikrofon, binär, irrelevant fürs Protokoll)
            return
        ws.on("framereceived", lambda d: self._rahmen("empfangen", d))
        ws.on("framesent", lambda d: self._rahmen("gesendet", d))

    def _rahmen(self, richtung: str, daten) -> None:
        if isinstance(daten, (bytes, bytearray)):
            return  # kommt auf /ws nicht vor, nur zur Sicherheit
        try:
            geparst = json.loads(daten)
        except (ValueError, TypeError):
            geparst = daten
        eintrag = {"t": round(time.monotonic() - self.start, 3), "richtung": richtung, "daten": geparst}
        self.frames.append(eintrag)
        if richtung == "empfangen" and isinstance(geparst, dict):
            if geparst.get("typ") == "stimme":
                self.letzte_stimme_t = eintrag["t"]
                self._stimme_bytes.append((eintrag["t"], len(geparst.get("pcm") or "") * 3 // 4))
            elif geparst.get("typ") == "stimme_stopp":
                self.stopp_zahl += 1
        self.datei.write(json.dumps(eintrag, ensure_ascii=False) + "\n")

    def schliessen(self) -> None:
        self.datei.close()

    # ---- Abgeleitete Sichten für die Auswertung ----
    def zustaende(self) -> list[dict]:
        return zustaende_aus_frames(self.frames)

    def nachrichten(self, typ: str) -> list[dict]:
        return nachrichten_aus_frames(self.frames, typ)

    def stimme_dauer_seit(self, t: float) -> float:
        """Sekunden Nestor-Ton, die seit Laufzeit t ankamen (24 kHz, 16 bit)."""
        return sum(n for tt, n in self._stimme_bytes if tt >= t) / 2 / 24000

    def nestor_wav_schreiben(self, ziel: Path) -> float:
        """Nestors gesprochene Antworten aus den "stimme"-Nachrichten (Base64-PCM, 24 kHz mono, wie
        static/basis.js sie abspielt) zu einer WAV zusammensetzen, mit Stille für die Lücken dazwischen –
        zum Nachhören, ob die Stimme passt. Liefert die Gesamtdauer in Sekunden (0, wenn nichts da war)."""
        return nestor_wav_aus_frames(self.frames, ziel)


STIMME_RATE = 24000


stimme_platzieren = takt.stimme_platzieren  # Ticket #25: dort, weil auch die Takt-Prüfungen sie brauchen


def nestor_wav_aus_frames(frames: list[dict], ziel: Path) -> float:
    import base64
    import wave

    import numpy as np

    platz = [p for p in stimme_platzieren(frames) if p["dauer"] > 0]
    if not platz:
        return 0.0
    audio = np.zeros(int((platz[-1]["pos"] + platz[-1]["dauer"]) * STIMME_RATE) + 1, dtype="<i2")
    for p in platz:
        pcm = np.frombuffer(base64.b64decode(p["pcm"]), dtype="<i2")[:int(round(p["dauer"] * STIMME_RATE))]
        a = int(round(p["pos"] * STIMME_RATE))
        n = max(0, min(len(pcm), len(audio) - a))
        audio[a:a + n] = pcm[:n]
    with wave.open(str(ziel), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(STIMME_RATE); w.writeframes(audio.tobytes())
    return len(audio) / STIMME_RATE


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


# Ticket #17 Punkt 7 / #19: ohne diese beiden angewählten Regeln kann die Prüfliste Kraftausdruck/Beschluss
# gar nicht erkennen (coach/regeln.py STANDARD enthält beide nicht) - der Lauf testet sie aber (referenz_
# grenzfaelle.json: "kraftausdruck", "beschluss", "aufgabe_ohne_zustaendig"). Checkbox-Wert = Regel-ID
# (static/app.js regelKachel(): value: r.id), unabhängig davon, in welcher Gruppe (verlässlich/Beta) sie steht.
REGELN_PFLICHT = ("ton", "ergebnisse")


async def regeln_anwaehlen(seite: Page, bericht: Bericht) -> None:
    """Respektvoller Ton + Ergebnisse festhalten anwählen, falls noch nicht Standard (coach/regeln.py:
    STANDARD = ["ausreden", "thema", "zeit", "kurz"] - beide fehlen dort)."""
    fehlend = []
    for regel_id in REGELN_PFLICHT:
        kasten = seite.locator(f'#einrichtung input[type="checkbox"][value="{regel_id}"]')
        # Die Regel-Kacheln füllt app.js erst, nachdem /api/regeln geantwortet hat (regelwahl()) - kurz
        # mehrfach probieren statt einmalig, sonst ein falsches "nicht gefunden" durch reine Zeitlupe
        # (dasselbe Muster wie agenda_eingabe_finden()).
        if not await warten_auf(seite, f'() => document.querySelector(\'#einrichtung input[value="{regel_id}"]\') '
                                       '!== null', timeout_s=8.0):
            fehlend.append(f"{regel_id} (Kästchen nicht gefunden)")
            continue
        try:
            if await kasten.is_checked():
                continue
            if await kasten.is_disabled():
                fehlend.append(f"{regel_id} (deaktiviert – noch nicht umgesetzt?)")
                continue
            await kasten.check(force=True)  # Kachel-Label liegt über dem Kästchen (b0e158f)
        except Exception as e:  # noqa: BLE001
            fehlend.append(f"{regel_id} ({type(e).__name__}: {e})")
    if fehlend:
        bericht.pruefen("Regeln „Respektvoller Ton“ + „Ergebnisse festhalten“ angewählt", "fehlt",
                        f"nicht gesetzt: {', '.join(fehlend)}")
    else:
        bericht.pruefen("Regeln „Respektvoller Ton“ + „Ergebnisse festhalten“ angewählt", "ok")


async def einrichten(seite: Page, agenda_text: str, bericht: Bericht) -> None:
    # In der Cloud kommt der erste Stand über die WebSocket spürbar später als lokal – erst darauf warten
    if not await warten_auf(seite, "() => !!zustand", timeout_s=60.0):
        bericht.pruefen("Erster Stand vom Server", "fehlt", "nach 60 s kein Zustand über die WebSocket")
    await regeln_anwaehlen(seite, bericht)
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
    # Titel/Ziel/Agenda landen erst mit dem Klick auf "Meeting starten" (/api/einrichten) im Server-Zustand -
    # die Antwort auf die Agenda per Prompt füllt nur die Formularfelder. Also dort lesen, nicht zustand.*
    # (Nachtrag des Koordinators nach dem ersten Cloud-Lauf: zustand.titel blieb '', obwohl die Tabelle
    # sichtbar gefüllt war).
    vor_zeilen = await seite.locator("#agenda-tabelle .agenda-zeile").count()
    vor_titel = await seite.locator("#f-titel").input_value()
    await feld.fill(agenda_text)
    t0 = time.monotonic()
    await knopf.click()
    # Warten, bis Nestor geantwortet hat (Knopf wieder „Absenden“, Antwortzeile sichtbar) – sonst startet der Test
    # das Meeting mit der Vorgabe-Agenda (Cloud-Lauf 08.10., 05:06: Titel blieb „Testmeeting“)
    bekommen = await warten_auf(
        seite, "() => document.getElementById('agenda-senden').textContent.trim() !== '…' && "
              "!document.getElementById('agenda-antwort').hidden", timeout_s=120.0)
    bericht.messwerte["agenda_prompt_sekunden"] = round(time.monotonic() - t0, 1)
    if (await seite.locator("#f-titel").input_value()) == vor_titel:
        bericht.fehler.append(f"Agenda per Prompt: Titel unverändert „{vor_titel}“")
    titel = await seite.locator("#f-titel").input_value()
    ziel = await seite.locator("#f-ziel").input_value()
    n_punkte = await seite.locator("#agenda-tabelle .agenda-zeile").count()
    if bekommen and titel and n_punkte > 0:
        bericht.pruefen("Agenda aus Einladungsmail übernommen (Titel/Ziel/Agenda gefüllt)", "ok",
                        f"Titel „{titel}“, Ziel „{ziel}“, {n_punkte} Punkte")
    else:
        bericht.pruefen("Agenda aus Einladungsmail übernommen", "fehlt",
                        f"vorher {vor_zeilen} Zeilen, nachher Titel={titel!r}, {n_punkte} Zeilen")


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
    await schritt_oder_abbrechen(seite, bericht, "Meeting gestartet (Mikrofon angenommen)",
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
                      meeting_start: float, regie: "takt.Regie | None" = None) -> list[dict]:
    """Zustand alle 2 s aus der Seite lesen (sie hält ihn über ihre eigene /ws aktuell) – Mitschnitt für die
    Prüfliste, Verzugsmessung je Nestor-Anweisung und für die Knöpfe mit --nur-knopfdruck.

    Mit `regie` (abwechselnd reden, #25) ist die Länge offen: Schluss 20 s nach dem letzten Abschnitt; die
    Screenshot-Ziele für Ereignisse/Grenzfälle kommen von der Regie, sobald sie den Abschnitt abspielt."""
    verlauf: list[dict] = []
    letzte_zeit = -1.0
    soll_dauer = referenz["dauer_s"] + 20
    schutz = soll_dauer + 30
    geknopft: set[str] = set()
    if regie is None:
        ziele = screenshot_ziele(referenz)
    else:
        # grob: Pausen (Begrüßung, je Antwort bis 60 s) verlängern das Meeting; nur ein Notausgang
        schutz = referenz["dauer_s"] + takt.BEGRUESSUNG_LIMIT_S + 75 * len(regie.abschnitte) + 60
        ziele = [float(t) for t in range(0, int(schutz), int(SCREENSHOT_TAKT))]
        lauf_zu_meeting = regie.lauf_start - meeting_start  # Laufachse → (grob) Meetinguhr
    regie_genommen: set[float] = set()
    regie_ende: float | None = None
    naechster_screenshot = iter(ziele)
    ss_zeit = next(naechster_screenshot, None)
    kosten_vor_erstem_knopf = None
    vorzeitig_beendet = False  # hoeren wurde false, bevor wir absichtlich "Beenden" gedrückt haben

    async def screenshot_bei(zeit: float) -> None:
        name = f"dashboard_{mmss(zeit).replace(':', '')}"
        if name not in bericht.screenshots:
            await bericht.screenshot(seite, name)

    while time.monotonic() - meeting_start < schutz:
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

        while ss_zeit is not None and t >= ss_zeit:
            await screenshot_bei(ss_zeit)
            ss_zeit = next(naechster_screenshot, None)
        if regie is not None:
            jetzt_lauf = time.monotonic() - regie.lauf_start
            for ziel in list(regie.screenshot_ziele):
                if ziel <= jetzt_lauf and ziel not in regie_genommen:
                    regie_genommen.add(ziel)
                    await screenshot_bei(ziel + lauf_zu_meeting)

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

        if regie is None and t >= soll_dauer:
            break
        if regie is not None and regie.fertig:
            regie_ende = t if regie_ende is None else regie_ende
            if t >= regie_ende + 20:
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


_MEETING_COOKIE = "nestor_meeting"  # coach/api_abschluss.py – fällt mit "Fertig" weg (nur Cloud, --passwort)


async def fertig_und_neues_meeting(seite: Page, url: str, cloud: bool, bericht: Bericht) -> None:
    """Ticket #17 Punkt 7 / #19: „Fertig“ drücken und prüfen, dass ein neuer Aufruf ein neues Meeting bekommt,
    statt das gerade beendete (fortgeschriebenes Protokoll, altes Thema) wiederzuverwenden. Kein neuer
    Meeting-Lauf dafür nötig: `coach/api_abschluss.py` setzt bei "Fertig" zurück auf ein leeres Meeting
    (`coach.einrichten({})`) und löscht in der Cloud das Meeting-Cookie - beides lässt sich ohne zehn weitere
    Minuten Mikrofon-Mitschnitt prüfen, indem man die Seite einfach neu lädt."""
    await seite.locator("#btn-fertig").click()
    zurueck = await warten_auf(seite, "() => location.pathname === '/'", 15.0)
    if not zurueck:
        bericht.pruefen("„Fertig“ führt zurück zur Startseite", "fehlt",
                        f"Pfad blieb {await seite.evaluate('() => location.pathname')}")
        return
    bericht.pruefen("„Fertig“ führt zurück zur Startseite", "ok")

    if cloud:
        cookies = await seite.context.cookies()
        noch_da = any(c["name"] == _MEETING_COOKIE for c in cookies)
        bericht.pruefen("Meeting-Cookie nach „Fertig“ entfernt (Cloud)", "fehlt" if noch_da else "ok",
                        f"Cookie „{_MEETING_COOKIE}“ " + ("noch gesetzt" if noch_da else "weg"))

    # "Ein neuer Aufruf bekommt ein neues Meeting": erneut auf die Seite gehen (kein Meeting starten, keine
    # KI-Kosten) und prüfen, dass der Server-Zustand leer ist statt das gerade beendete Meeting zu zeigen.
    # Die Startseite (/) kennt keinen Meeting-Zustand – der neue Aufruf ist das Dashboard (/meeting), wie nach
    # der Stufenwahl (static/start.js). Früher endete der Lauf hier mit „zustand is not defined“.
    await seite.goto(url.rstrip("/") + "/meeting")
    frisch = await warten_auf(
        seite, "() => typeof zustand !== 'undefined' && !!zustand && !zustand.titel && !(zustand.agenda && zustand.agenda.length) && !zustand.hoeren",
        20.0)
    if frisch:
        bericht.pruefen("Neuer Aufruf bekommt ein neues (leeres) Meeting", "ok")
    else:
        z = await zustand(seite)
        bericht.pruefen("Neuer Aufruf bekommt ein neues (leeres) Meeting", "fehlt",
                        f"Pfad {await seite.evaluate('() => location.pathname')}, zustand.titel={z.get('titel')!r}, "
                        f"hoeren={z.get('hoeren')}, Agendapunkte={len(z.get('agenda') or [])}")


# ---------- Abschluss ----------
async def abschluss(seite: Page, bericht: Bericht, offline: bool, url: str, cloud: bool) -> None:
    da = await warten_auf(seite, "() => !document.getElementById('ab-inhalt').hidden", 40.0)
    if not da:
        bericht.pruefen("Abschlussseite geladen", "fehlt")
        return
    await bericht.screenshot(seite, "abschluss")

    # Das Abschlussbild braucht 1-2 min (gemessen im ersten Cloud-Lauf) - bis zu 4 min warten und die
    # tatsächliche Wartezeit selbst als Messwert festhalten (das ist ein Nutzer-Erlebnis-Wert, Ticket #11).
    t0 = time.monotonic()
    fertig = await warten_auf(seite, "() => !document.getElementById('btn-paket').disabled", 240.0)
    bericht.messwerte["ablage_wartezeit_s"] = round(time.monotonic() - t0, 1)
    if not fertig:
        await bericht.screenshot(seite, "fehler_ablage_nicht_fertig")
        bericht.pruefen("Paket herunterladen", "fehlt",
                        f"Ablage nach {bericht.messwerte['ablage_wartezeit_s']:.0f}s immer noch nicht fertig")
    else:
        bericht.notieren(f"Ablage fertig nach {bericht.messwerte['ablage_wartezeit_s']:.0f}s.")
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

    # Feedback läuft seit #18 über den schwebenden Knopf (static/feedback.js), auf jeder Seite gleich;
    # #fb-text auf der Abschlussseite ist nur noch die Anmerkung zur Datenspende.
    await seite.locator("#fb-text").fill("Cloud-Testlauf (automatisiert) – nur zur Prüfung des Ablaufs.")
    try:
        await seite.locator("#fb-schwebend").click()
        await seite.locator("#fb-nachricht").fill("Cloud-Testlauf (automatisiert) – nur zur Prüfung des Ablaufs.")
        await seite.locator("#fb-senden").click()
        ok = await warten_auf(seite, "() => !document.getElementById('fb-dank').hidden", 20.0)
        detail = ""
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {e}"[:300]
    if ok:
        bericht.pruefen("Feedback senden", "ok")
    else:
        await bericht.screenshot(seite, "fehler_feedback")
        bericht.pruefen("Feedback senden", "fehlt", detail)
    await seite.keyboard.press("Escape")

    await seite.locator("#sp-einverstanden").check()
    if not await seite.locator("#btn-spende").is_disabled():
        await seite.locator("#btn-spende").click()
        ok = await warten_auf(seite, "() => !document.getElementById('sp-danke').hidden", 15.0)
        bericht.pruefen("Datenspende mit Häkchen senden", "ok" if ok else "fehlt")
    else:
        bericht.pruefen("Datenspende mit Häkchen senden", "fehlt", "Knopf blieb deaktiviert (Ablage nicht fertig?)")

    await fertig_und_neues_meeting(seite, url, cloud, bericht)


# ---------- Auswertungshelfer auf dem WS-Mitschnitt (ws.jsonl) – die einzige verlässliche Quelle ----------
def _hinweise_dedup(zustaende: list[dict]) -> list[dict]:
    gesehen, aus = set(), []
    for z in zustaende:
        for h in z.get("hinweise") or []:
            hid = h.get("id")
            if hid is not None and hid in gesehen:
                continue
            if hid is not None:
                gesehen.add(hid)
            aus.append(h)
    return aus


def _karten_dedup(zustaende: list[dict]) -> list[dict]:
    gesehen, aus = set(), []
    for z in zustaende:
        for k in z.get("karten") or []:
            kid = k.get("id")
            if kid is not None and kid in gesehen:
                continue
            if kid is not None:
                gesehen.add(kid)
            aus.append(k)
    return aus


def _aktiver_punkt_wechsel(zustaende: list[dict]) -> list[tuple[float, int, int]]:
    """(meeting_zeit, alter Punkt, neuer Punkt) bei jeder Änderung von aktiver_punkt."""
    aus, letzter = [], None
    for z in zustaende:
        ap = z.get("aktiver_punkt")
        if letzter is not None and ap is not None and ap != letzter:
            aus.append((z.get("zeit", 0.0), letzter, ap))
        letzter = ap if ap is not None else letzter
    return aus


def _naechstes_fenster(zeit_s: float, verzug_max: float = 90.0):
    return lambda t: 0 <= t - zeit_s <= verzug_max or abs(t - zeit_s) < 5  # etwas Vorlauf erlaubt (Messungenauigkeit)


# ---------- Versatz Referenzzeit <-> Meetinguhr (Nachtrag nach dem ersten echten Cloud-Lauf, #11) ----------
# Chromium spielt die Fake-Mikrofon-Datei nicht exakt ab "Meeting starten" (zeit=0), sondern schon vorher -
# ein eingebautes Ereignis bei Referenzzeit X taucht im Mitschnitt systematisch erst bei X + Versatz auf
# (gemessen im ersten Cloud-Lauf: ~5,7 s). Ohne Korrektur wirkt jede Antwort zu spät oder ganz verpasst.
def _segmente_dedup(zustaende: list[dict]) -> list[dict]:
    """Jede Zustandsmeldung trägt die komplette, wachsende Segmentliste - dieselben Segmente stecken in
    hunderten Momentaufnahmen. Für den Textabgleich reicht die Menge der unterschiedlichen (start, text)."""
    gesehen, aus = set(), []
    for z in zustaende:
        for s in z.get("segmente") or []:
            schluessel = (s.get("start"), s.get("text"))
            if schluessel not in gesehen:
                gesehen.add(schluessel)
                aus.append(s)
    return aus


def segment_match(segmente: list[dict], text: str, schwelle: float = 0.55) -> dict | None:
    """Bestpassendes transkribiertes Segment zu `text` (Ähnlichkeitsquote, keine reine Teilstring-Suche -
    die matcht sonst jeden kurzen Segment-Schnipsel wie "Nestor," fälschlich gegen jeden längeren Zielsatz,
    der mit dem Namen beginnt - genau das lieferte beim ersten Versuch mit echten Cloud-Daten groben
    Unsinn). `segmente` ist die bereits entdoppelte Liste (siehe _segmente_dedup), sonst viel zu langsam auf
    einem langen Mitschnitt. None, wenn nichts über der Schwelle liegt."""
    import difflib

    ziel = " ".join(text.lower().split())
    if not ziel:
        return None
    bestes, beste_quote = None, 0.0
    for s in segmente:
        kandidat = " ".join((s.get("text") or "").lower().split())
        if not kandidat:
            continue
        quote = difflib.SequenceMatcher(None, ziel, kandidat).ratio()
        if quote > beste_quote:
            beste_quote, bestes = quote, s
    return bestes if beste_quote >= schwelle else None


def versatz_schaetzen(referenz: dict, segmente: list[dict]) -> float | None:
    """Median aus (beobachtete Segment-Startzeit - Referenzzeit) über alle Grenzfall-/Nestor-Texte, die sich
    im Mitschnitt wiederfinden lassen. `segmente` bereits entdoppelt (_segmente_dedup). None, wenn nichts
    passt (z. B. Offline-Lauf ohne Transkript)."""
    kandidaten: list[tuple[str, float]] = []
    for g in referenz.get("grenzfaelle", []):
        for teil in g.get("teile", []):
            kandidaten.append((teil["text"], teil["start"]))
    for n in referenz.get("nestor", []):
        kandidaten.append((n["text"], n["start"]))
    diffs = []
    for text, referenz_zeit in kandidaten:
        seg = segment_match(segmente, text)
        if seg is not None and seg.get("start") is not None:
            diffs.append(seg["start"] - referenz_zeit)
    if not diffs:
        return None
    diffs.sort()
    return diffs[len(diffs) // 2]


def referenz_verschieben(referenz: dict, versatz: float) -> dict:
    """Kopie von referenz.json mit allen Zeitstempeln um `versatz` verschoben, damit ereignis_pruefen/
    nestor_reaktion unverändert gegen die Meetinguhr vergleichen können."""
    if not versatz:
        return referenz
    r = json.loads(json.dumps(referenz))  # einfache tiefe Kopie
    for e in r.get("ereignisse", []):
        e["zeit_s"] += versatz
    for n in r.get("nestor", []):
        n["start"] += versatz
        n["ende"] += versatz
    for g in r.get("grenzfaelle", []):
        g["start"] += versatz
        g["ende"] += versatz
        for t in g.get("teile", []):
            t["start"] += versatz
            t["ende"] += versatz
    return r


def antwortfenster_start(segmente: list[dict], text: str, versatz_zeit: float) -> float:
    """Ende des Segments mit der Frage (Meetinguhr) ist der genauere Startpunkt fürs Antwortfenster als die
    versatzkorrigierte Referenzzeit (Nachtrag des Koordinators, Punkt 3) - Segment-Abgleich bevorzugt, sonst
    die Korrektur über den geschätzten/gemessenen Versatz. `segmente` bereits entdoppelt (_segmente_dedup)."""
    seg = segment_match(segmente, text)
    return seg["ende"] if seg and seg.get("ende") is not None else versatz_zeit


def versatz_spannweite(referenz: dict, segmente: list[dict]) -> tuple[float, float] | None:
    """Versatz am Anfang und am Ende des Mitschnitts statt nur im Median (Punkt 4): wächst er über den Lauf,
    deutet das auf einen Verarbeitungsrückstand im Container hin, nicht nur auf einen festen Startversatz.
    Robuster als ein Vergleich über Wanduhr-Zeitstempel (die hängen zusätzlich am Zeitpunkt, den Chromium
    wirklich als "Meeting starten" zählt - unsicher, siehe seite_bis_meeting_start_s) - hier zählt nur, wann
    ein bekannter Text tatsächlich im Transkript auftaucht."""
    kandidaten: list[tuple[float, float]] = []  # (referenz_zeit, diff), nach referenz_zeit sortiert
    for g in referenz.get("grenzfaelle", []):
        for teil in g.get("teile", []):
            kandidaten.append((teil["start"], teil["text"]))
    for n in referenz.get("nestor", []):
        kandidaten.append((n["start"], n["text"]))
    kandidaten.sort()
    diffs = []
    for referenz_zeit, text in kandidaten:
        seg = segment_match(segmente, text)
        if seg is not None and seg.get("start") is not None:
            diffs.append(seg["start"] - referenz_zeit)
    if len(diffs) < 2:
        return None
    return round(diffs[0], 1), round(diffs[-1], 1)


def ereignis_pruefen(ereignis: dict, zustaende: list[dict], hinweise: list[dict]) -> tuple[bool, str]:
    """(erkannt?, Begründung) für ein eingebautes Ereignis aus referenz.json – je Typ das passende Signal
    (Nachtrag des Koordinators nach dem ersten Cloud-Lauf): Agendawechsel = aktiver_punkt ändert sich,
    Fokus/Ton/Ergebnisse = die jeweilige Hinweisart, Beschluss zusätzlich über das Ergebnis am Agendapunkt."""
    art, ziel = ereignis["ereignis"], ereignis["zeit_s"]
    if art == "wechsel_ansage":
        treffer = [w for w in _aktiver_punkt_wechsel(zustaende) if _naechstes_fenster(ziel)(w[0])]
        if treffer:
            return True, f"aktiver_punkt {treffer[0][1]}→{treffer[0][2]} bei {treffer[0][0]:.0f}s (Verzug {treffer[0][0] - ziel:+.0f}s)"
    arten = ereignis_hinweisarten(art)
    treffer_h = [h for h in hinweise if h.get("art") in arten and _naechstes_fenster(ziel)(h.get("zeit", -1e9))]
    if treffer_h:
        n = min(treffer_h, key=lambda h: abs(h["zeit"] - ziel))
        return True, (f"Hinweis „{n.get('art')}“ bei {n['zeit']:.0f}s (Verzug {n['zeit'] - ziel:+.0f}s): "
                      f"{n.get('text', '')[:60]}")
    if art in ("beschluss", "aufgabe_ohne_zustaendig"):
        for z in zustaende:
            if z.get("zeit", 0) < ziel - 5:
                continue
            for p in z.get("agenda") or []:
                e = (p.get("ergebnis") or {}).get("ergebnis")
                if e:
                    return True, f"Ergebnis im Agendapunkt „{p.get('titel', '?')}“ bei {z['zeit']:.0f}s: {e[:60]}"
            break
    return False, "kein passendes Signal (aktiver_punkt/Hinweis/Ergebnis) im Mitschnitt"


def nestor_reaktion(start: float, ende_fenster: float, zustaende: list[dict], hinweise: list[dict],
                    karten: list[dict], stimme_frames: list[dict], bild: bool) -> tuple[bool, str]:
    """Für eine Nestor-Anweisung/einen Grenzfall: erste Reaktion im Fenster [start, ende_fenster] – erster Ton
    (stimme-Nachricht), neue Karte, oder (bei "bild") eine neue Live-Bild-Version. "Erster Ton" nutzt die
    Mitschnitt-Zeit der stimme-Nachricht (keine eigene "zeit" im Protokoll) über den WS-Offset."""
    kandidaten = []
    erste_karte = next((k for k in karten if start - 2 <= k.get("zeit", -1e9) <= ende_fenster), None)
    if erste_karte:
        kandidaten.append((erste_karte["zeit"],
                          f"Karte „{erste_karte.get('titel', '')[:40]}“ bei {erste_karte['zeit']:.1f}s"))
    if bild:
        versionen = [(z.get("zeit", 0), z.get("onepager_version")) for z in zustaende
                    if start - 2 <= z.get("zeit", -1e9) <= ende_fenster and z.get("onepager_version")]
        if versionen:
            kandidaten.append((versionen[0][0], f"neues Live-Bild (Version {versionen[0][1]}) bei {versionen[0][0]:.1f}s"))
    if stimme_frames:
        # stimme-Nachrichten tragen keine Meeting-Zeit; grob über die nächstgelegene Zustandsmeldung zuordnen.
        for s in stimme_frames:
            z_nah = min(zustaende, key=lambda z: abs(z["_t"] - s["_t"]), default=None)
            if z_nah and start - 2 <= z_nah.get("zeit", -1e9) <= ende_fenster:
                kandidaten.append((z_nah["zeit"], f"erster Ton (stimme-Nachricht) um {z_nah['zeit']:.1f}s"))
                break
    if not kandidaten:
        return False, "keine Karte, kein Live-Bild, kein Ton im Erwartungsfenster"
    zeit, begruendung = min(kandidaten, key=lambda k: k[0])
    return True, f"{begruendung} (Verzug {zeit - start:+.1f}s)"


# ---------- Prüfliste gegen referenz.json – reine Berechnung, kein Bericht/keine Seite nötig ----------
# So verwendet scripts/cloudtest_bewerten.py beim nachträglichen Auswerten (z. B. mit korrigiertem Versatz)
# exakt dieselbe Logik wie der Live-Lauf hier, statt sie zu verdoppeln.
def pruefpunkte_berechnen(referenz_roh: dict, zustaende: list[dict], hinweise: list[dict], karten: list[dict],
                          stimme_frames: list[dict], offline_lauf: bool,
                          nur_knopfdruck: bool = False,
                          plan: list[dict] | None = None) -> tuple[list[dict], float | None]:
    """`nur_knopfdruck` (Ticket #17 Punkt 7): in diesem Modus reagiert Nestor grundsätzlich nicht auf
    spontane Ansprache (kein KI-Aufruf ohne Knopf, siehe scripts/cloudtest.py aufzeichnen()/kein_ki_vor_
    erstem_knopf) - ein "fehlt" bei einer Nestor-Anweisung/einem Grenzfall, der eine Antwort erwartet, wäre
    also kein echter Mangel, sondern eine Eigenschaft des Modus. Solche Punkte werden "beobachtet" (📝)
    statt "fehlt"/"ok" gewertet; Grenzfälle, die ausdrücklich KEINE Reaktion erwarten ("keine_antwort",
    "kein_fehlausloeser", "kein_abbruch"), bleiben normal geprüft - da stimmt die Erwartung auch hier.

    `plan` (Ticket #25, abwechselnd reden): der auf die Meetinguhr gebrachte Zeitplan der Abschnitte
    (meeting_plan()). Dann werden die Referenzzeiten erst damit umgerechnet – Pausen verschieben alles danach –
    und der Segment-Abgleich schätzt nur noch den kleinen Restversatz (Verarbeitung bis zum Transkript)."""
    segmente = _segmente_dedup(zustaende)  # einmal statt bei jedem Textabgleich neu (sonst zu langsam)
    if plan:
        referenz_roh = takt.referenz_auf_meetinguhr(referenz_roh, plan)
    versatz = versatz_schaetzen(referenz_roh, segmente)
    referenz = referenz_verschieben(referenz_roh, versatz or 0.0)
    aus: list[dict] = []

    def pruefen(name: str, status: str, detail: str = "") -> None:
        aus.append({"name": name, "status": status, "detail": detail})

    for e in referenz.get("ereignisse", []):
        name = f"Ereignis „{e['ereignis']}“ bei {e['zeit_s']:.0f}s"
        if e["ereignis"] not in LOKAL_OHNE_KI and offline_lauf:
            pruefen(name, "offline", "braucht Text-/Themen-KI, mit LMC_OFFLINE nicht verfügbar")
            continue
        erkannt, begruendung = ereignis_pruefen(e, zustaende, hinweise)
        pruefen(name, "ok" if erkannt else "fehlt", begruendung)

    # #9-Schema (Nestor-Anweisungen) - weiter unterstützt, falls referenz.json das alte Format hat.
    for n in referenz.get("nestor", []):
        kurz = n["text"][:40] + "…" if len(n["text"]) > 40 else n["text"]
        name = f"Nestor-Anweisung „{kurz}“"
        if nur_knopfdruck:
            pruefen(name, "beobachtet", "nur auf Knopfdruck: spontane Ansprache nicht vorgesehen (#17 Punkt 7)")
            continue
        if offline_lauf:
            pruefen(name, "offline", "ohne Schlüssel keine Antwort möglich")
            continue
        fenster_start = antwortfenster_start(segmente, n["text"], n["start"])
        fenster_ende = fenster_start + max(n.get("pause_s", 30) * 1.5, 30)
        bild = "bild" in (n.get("art") or "") or "übersicht" in n["text"].lower() or "visuelle" in n["text"].lower()
        erkannt, begruendung = nestor_reaktion(fenster_start, fenster_ende, zustaende, hinweise, karten,
                                               stimme_frames, bild)
        pruefen(name, "ok" if erkannt else "fehlt", begruendung)

    # #11-Schema (Grenzfälle der Ansprache) - je nach erwartetem Verhalten unterschiedlich gewertet.
    grenzfaelle = referenz.get("grenzfaelle", [])
    for i, g in enumerate(grenzfaelle):
        name = f"Grenzfall {g['id']}"
        erwartet = g["erwartet"]
        if offline_lauf:
            pruefen(name, "offline", f"erwartet: {erwartet} – ohne Schlüssel nicht prüfbar")
            continue
        # "Ansprache nicht vorgesehen" gilt nur für Fälle, die überhaupt eine Reaktion erwarten (inkl.
        # Agendawechsel per Ansage) - "keine_antwort"/"kein_fehlausloeser"/"kein_abbruch" bleiben unten
        # normal geprüft, weil "keine Reaktion" im Modus "nur auf Knopfdruck" ohnehin zutrifft.
        if nur_knopfdruck and erwartet not in ("keine_antwort", "kein_fehlausloeser", "kein_abbruch"):
            pruefen(name, "beobachtet",
                    f"erwartet: {erwartet} – nur auf Knopfdruck: spontane Ansprache nicht vorgesehen (#17 Punkt 7)")
            continue
        fenster_start = antwortfenster_start(segmente, g["teile"][-1]["text"], g["ende"])
        fenster_ende = (grenzfaelle[i + 1]["start"] if i + 1 < len(grenzfaelle) else g["ende"] + 60)
        bild = erwartet in ("folie",) or "bild" in erwartet or "übersicht" in g["teile"][0]["text"].lower()
        reagiert, begruendung = nestor_reaktion(fenster_start, fenster_ende, zustaende, hinweise, karten,
                                                stimme_frames, bild)
        if erwartet in ("antwort", "ja_dann_antwort", "antwort_mit_quellen", "nachfrage_oder_bild_mit_fokus", "folie"):
            pruefen(name, "ok" if reagiert else "fehlt", f"erwartet: {erwartet} – {begruendung}")
        elif erwartet in ("keine_antwort", "kein_fehlausloeser", "kein_abbruch"):
            # "kein_abbruch" (Fall 10) prüft zusätzlich, dass hoeren danach nicht abbrach
            zustand_danach = next((z for z in zustaende if z.get("zeit", -1) >= g["ende"]), None)
            abgebrochen = erwartet == "kein_abbruch" and zustand_danach is not None and not zustand_danach.get("hoeren")
            if reagiert or abgebrochen:
                grund = begruendung if reagiert else "hoeren wurde false (Meeting/Mikro gestoppt)"
                pruefen(name, "fehlt", f"erwartet: {erwartet}, aber reagiert – {grund}")
            else:
                pruefen(name, "ok", f"erwartet: {erwartet} – keine Reaktion ausgelöst, wie vorgesehen")
        elif erwartet == "agendawechsel":
            treffer = [w for w in _aktiver_punkt_wechsel(zustaende) if g["ende"] - 2 <= w[0] <= fenster_ende]
            pruefen(name, "ok" if treffer else "fehlt",
                   f"erwartet: Agendawechsel – {'aktiver_punkt ' + str(treffer[0][1]) + '→' + str(treffer[0][2]) if treffer else 'kein Wechsel gesehen'}")
        else:
            # "antwort_erwuenscht_dokumentieren" (Nuschelvarianten) und "nestor_verstummt" (Hineinreden,
            # ohne echte Nestor-Stimme im Offline-Material nicht sauber nachstellbar): nur dokumentieren.
            pruefen(name, "beobachtet", f"erwartet: {erwartet} – {begruendung}")

    fehler_eintraege = sorted({h.get("text", "") for h in hinweise if h.get("art") == "ton"} |
                              {z["fehler"] for z in zustaende if z.get("fehler")})
    pruefen("Keine Einträge in fehler", "ok" if not any(z.get("fehler") for z in zustaende) else "fehlt",
           "; ".join(list(fehler_eintraege)[:3]))
    return aus, versatz


def meeting_plan(messwerte: dict, zustaende: list[dict]) -> tuple[list[dict] | None, float | None]:
    """(Zeitplan auf der Meetinguhr, Versatz Meetinguhr − Laufachse) für einen Lauf mit abwechselndem Reden
    (#25); (None, None) für einen Lauf am Stück oder ältere Berichte."""
    zeitplan = (messwerte.get("takt") or {}).get("zeitplan")
    if not zeitplan:
        return None, None
    versatz = takt.uhr_versatz(zustaende)
    if versatz is None:
        return None, None
    return takt.zeitplan_auf_meetinguhr(zeitplan, versatz), versatz


def takt_auswerten(messwerte: dict, frames: list[dict]) -> tuple[list[dict], dict]:
    """Prüfpunkte/Kennzahlen zum abwechselnden Reden und aus #21 Punkt 5 (cloudtest_takt.takt_pruefpunkte)
    aus Bericht + Mitschnitt – von Live-Lauf, Bewertung und HTML-Bericht gleich genutzt."""
    t = messwerte.get("takt")
    if not t:
        return [], {}
    zustaende = zustaende_aus_frames(frames)
    _, versatz = meeting_plan(messwerte, zustaende)
    offline = bool(zustaende) and bool((zustaende[-1].get("schluessel") or {}).get("offline"))
    return takt.takt_pruefpunkte(t, zustaende, stimme_platzieren(frames), nachrichten_aus_frames(frames, "stimme"),
                                 versatz, offline)


def pruefliste_bauen(referenz_roh: dict, verlauf: list[dict], spur: "WsSpur", bericht: Bericht,
                     nur_knopfdruck: bool = False) -> None:
    """Live-Lauf: berechnet (pruefpunkte_berechnen) und schreibt jeden Punkt in den Bericht."""
    offline_lauf = bool(verlauf) and bool((verlauf[-1].get("schluessel") or {}).get("offline"))
    zustaende = spur.zustaende()
    hinweise = _hinweise_dedup(zustaende)
    karten = _karten_dedup(zustaende)
    stimme_frames = spur.nachrichten("stimme")
    bericht.messwerte["ws_zustandsmeldungen"] = len(zustaende)
    bericht.messwerte["nur_knopfdruck"] = nur_knopfdruck  # Ticket #17 Punkt 7 - für cloudtest_bewerten.py

    plan, uhr = meeting_plan(bericht.messwerte, zustaende)
    if plan:
        bericht.messwerte["uhr_versatz_s"] = round(uhr, 3)
        bericht.notieren(f"Takt: {len(plan)} Abschnitte, Meetinguhr − Laufachse {uhr:+.2f}s; Referenz endet auf "
                         f"der Meetinguhr bei {takt.referenz_auf_meetinguhr(referenz_roh, plan)['dauer_s']:.0f}s")
    pruefpunkte, versatz = pruefpunkte_berechnen(referenz_roh, zustaende, hinweise, karten, stimme_frames,
                                                 offline_lauf, nur_knopfdruck, plan)
    bericht.messwerte["versatz_s"] = round(versatz, 1) if versatz is not None else None
    bezeichnung = "Restversatz nach Zeitplan" if plan else "Versatz Referenzzeit↔Meetinguhr"
    bericht.notieren(f"{bezeichnung}: {versatz:+.1f}s (aus Segment-Abgleich)" if versatz is not None
                     else f"{bezeichnung}: nicht schätzbar (kein passendes Segment im Mitschnitt)")
    referenz_abgleich = takt.referenz_auf_meetinguhr(referenz_roh, plan) if plan else referenz_roh
    spannweite = versatz_spannweite(referenz_abgleich, _segmente_dedup(zustaende))
    bericht.messwerte["versatz_anfang_s"], bericht.messwerte["versatz_ende_s"] = spannweite or (None, None)
    if spannweite:
        bericht.notieren(f"Versatz wächst über den Lauf: {spannweite[0]:+.1f}s am Anfang → {spannweite[1]:+.1f}s "
                         "am Ende (Hinweis auf Verarbeitungsrückstand im Container, falls deutlich größer)")
    for p in pruefpunkte:
        bericht.pruefen(p["name"], p["status"], p["detail"])
    takt_punkte, takt_kennzahlen = takt_auswerten(bericht.messwerte, spur.frames)
    for p in takt_punkte:
        bericht.pruefen(p["name"], p["status"], p["detail"])
    if takt_kennzahlen:
        bericht.messwerte["takt_kennzahlen"] = takt_kennzahlen

    if zustaende:
        bericht.messwerte["kosten_usd"] = zustaende[-1].get("kosten", {}).get("meeting", 0.0)
        bericht.messwerte["meeting_s"] = round(zustaende[-1].get("zeit", 0.0), 1)
    elif verlauf:
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
            # Am Stück: Chromium spielt die Datei selbst als Mikrofon. Sonst ersetzt cloudtest_takt.INIT_SCRIPT
            # getUserMedia durch eine steuerbare WebAudio-Quelle (#25) - die Datei-Flags entfallen dann.
            mikro = [f"--use-file-for-fake-audio-capture={args.audio}"] if args.am_stueck else []
            return await pw.chromium.launch(
                executable_path=args.chromium, headless=True,
                args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", *mikro,
                     "--autoplay-policy=no-user-gesture-required", *sparsam])
        except Exception as e:  # noqa: BLE001
            fehler = e
            bericht.notieren(f"Chromium-Start Versuch {versuch}/{versuche} fehlgeschlagen ({type(e).__name__}) "
                             "– vermutlich Speicherdruck auf dem Pi, neuer Versuch in 5 s.")
            await asyncio.sleep(5.0)
    bericht.fehler.append(f"Chromium startete nach {versuche} Versuchen nicht (Speicherdruck auf dem Pi): {fehler}")
    raise RuntimeError(f"Chromium startete nach {versuche} Versuchen nicht: {fehler}")


async def abwechselnd_aufzeichnen(seite: Page, spur: WsSpur, pcm, referenz: dict, args: argparse.Namespace,
                                  bericht: Bericht, lauf_start: float, meeting_start: float) -> list[dict]:
    """Ticket #25: Meeting-Audio abschnittsweise über das steuerbare Mikrofon, Nestor abwarten (Regie), daneben
    wie immer der Zustandsmitschnitt mit Screenshots (aufzeichnen)."""
    # Die Seite holt das Mikrofon erst nach /api/start (static/app.js) - kurz darauf warten
    await warten_auf(seite, "() => window.__testMikro && window.__testMikro.stroeme > 0", 15.0)
    stand = await seite.evaluate("() => window.__testMikro ? window.__testMikro.stand() : null")
    if stand and stand.get("stroeme"):
        bericht.pruefen("Steuerbares Mikrofon von der Seite übernommen", "ok", f"{stand['stroeme']} Strom/Ströme")
    else:
        bericht.pruefen("Steuerbares Mikrofon von der Seite übernommen", "fehlt",
                        "getUserMedia der Seite lief nicht über das Init-Script")
    # Mit „nur auf Knopfdruck“ antwortet Nestor nie spontan - dann nur am Anfang kurz auf eine Begrüßung warten
    abschnitte = takt.abschnitte_bauen(referenz, pcm, args.bis, ohne_warten=args.nur_knopfdruck)
    bericht.notieren(f"Takt: {len(abschnitte)} Abschnitte, gewartet wird nach "
                     f"{', '.join(a['warten']['id'] for a in abschnitte if a.get('warten')) or '—'}")
    regie = takt.Regie(seite, spur, pcm, abschnitte, lauf_start, bericht.notieren, referenz)
    aufgabe = asyncio.ensure_future(regie.lauf())
    try:
        return await aufzeichnen(seite, referenz, args.nur_knopfdruck, bericht, meeting_start, regie)
    finally:
        if not aufgabe.done():
            aufgabe.cancel()
        (erg,) = await asyncio.gather(aufgabe, return_exceptions=True)
        if isinstance(erg, Exception):
            bericht.fehler.append(f"Regie (abwechselnd reden) abgebrochen: {type(erg).__name__}: {erg}")
        bericht.messwerte["takt"] = regie.ergebnis()


# ---------- main ----------
def referenz_laden(messwerte: dict) -> dict | None:
    """Die Referenz eines Laufs (für cloudtest_bewerten.py/cloudtest_bericht.py), mit --bis gekürzt wie im Lauf."""
    pfad = messwerte.get("referenz_datei")
    if not pfad or not Path(pfad).exists():
        return None
    referenz = json.loads(Path(pfad).read_text(encoding="utf-8"))
    return takt.referenz_kuerzen(referenz, messwerte.get("bis_s"))


async def lauf(args: argparse.Namespace) -> Bericht:
    referenz = json.loads(Path(args.referenz).read_text(encoding="utf-8"))
    pcm = None
    if not args.am_stueck:
        pcm = takt.wav_laden(Path(args.audio))
        problem = takt.material_pruefen(referenz, pcm)
        if problem:
            raise SystemExit(f"Testmaterial passt nicht: {problem}")
    referenz = takt.referenz_kuerzen(referenz, args.bis)
    bericht = Bericht(Path(args.bericht))
    stufe_text = (f"{args.stufe}" + (" · nur auf Knopfdruck" if args.nur_knopfdruck else "")
                  + (" · am Stück" if args.am_stueck else " · abwechselnd"))
    bericht.messwerte.update(modus=stufe_text, gestartet=jetzt(), soll_dauer_s=referenz["dauer_s"],
                             referenz_datei=str(Path(args.referenz).resolve()),  # für cloudtest_bewerten.py
                             am_stueck=args.am_stueck, bis_s=args.bis)

    lauf_start = time.monotonic()
    async with async_playwright() as pw:
        browser = await chromium_starten(pw, args, bericht)
        context = await browser.new_context(permissions=["microphone"])
        if not args.am_stueck:
            await context.add_init_script(takt.INIT_SCRIPT)  # steuerbares Mikrofon (#25)
        seite = await context.new_page()
        # JS-Fehler, Konsole, native Dialoge (alert/confirm) und alle WebSocket-Nachrichten mitschneiden –
        # ein unbeantworteter Dialog würde die Seite sonst stillschweigend blockieren und jeden folgenden
        # Klick "einfrieren" lassen; der WS-Mitschnitt (ws.jsonl, Ticket #11) ist die einzige verlässliche
        # Grundlage für die Prüfliste (2-s-Polling verpasst kurzlebige Hinweise/Kartenwechsel).
        seite.on("pageerror", lambda e: bericht.fehler.append(f"JS-Fehler im Browser: {e}"))
        seite.on("console", lambda m: bericht.fehler.append(f"Konsole ({m.type}): {m.text}")
                 if m.type == "error" else None)
        seite.on("requestfailed", lambda r: bericht.fehler.append(
            f"Netzanfrage fehlgeschlagen: {r.method} {r.url} ({r.failure or '?'})"))
        seite.on("dialog", lambda d: (bericht.notieren(f"Dialog automatisch bestätigt: {d.message}"),
                                      asyncio.ensure_future(d.accept())))
        spur = WsSpur(bericht.ordner, lauf_start)
        spur.anhaengen(seite)
        verlauf: list[dict] = []
        meeting_start = lauf_start  # Platzhalter, falls der Lauf schon vor meeting_starten() abbricht
        try:
            await anmelden(seite, args.url, args.passwort, bericht)
            await startseite(seite, args.stufe, args.nur_knopfdruck, bericht)
            meeting_start = await meeting_starten(seite, Path(args.agenda_prompt).read_text(encoding="utf-8"),
                                                  bericht)
            # Rohdaten für die Versatz-Schätzung (Nachtrag nach dem ersten echten Cloud-Lauf: die
            # Referenzzeiten aus dem Drehbuch und die Meetinguhr liefen dort ~6 s auseinander, weil Chromium
            # die Mikrofon-Datei schon vor "Meeting starten" zu spielen beginnt). Direkt gemessen reicht
            # nicht als Korrektur (siehe pruefliste_bauen) - nur zur Einordnung mit abgelegt.
            bericht.messwerte["seite_bis_meeting_start_s"] = round(meeting_start - lauf_start, 1)
            if args.am_stueck:
                verlauf = await aufzeichnen(seite, referenz, args.nur_knopfdruck, bericht, meeting_start)
            else:
                verlauf = await abwechselnd_aufzeichnen(seite, spur, pcm, referenz, args, bericht, lauf_start,
                                                         meeting_start)
            z_letzt = verlauf[-1] if verlauf else {}
            offline = bool((z_letzt.get("schluessel") or {}).get("offline"))
            await abschluss(seite, bericht, offline, args.url, bool(args.passwort))
            pruefliste_bauen(referenz, verlauf, spur, bericht, args.nur_knopfdruck)
        except Exception as e:  # noqa: BLE001 – auch unerwartete Fehler: Bericht trotzdem schreiben
            if not isinstance(e, SchrittFehler):
                e = f"{type(e).__name__}: {str(e)[:300]}"
            bericht.fehler.append(f"Lauf abgebrochen: {e}")
            bericht.notieren(f"Abgebrochen: {e}")
            if verlauf:  # trotz Abbruch die bis dahin gesammelten Prüfpunkte gegen die Referenz auswerten
                pruefliste_bauen(referenz, verlauf, spur, bericht, args.nur_knopfdruck)
        finally:
            dauer_stimme = spur.nestor_wav_schreiben(bericht.ordner / "nestor_stimme.wav")
            if dauer_stimme:
                bericht.notieren(f"nestor_stimme.wav: {dauer_stimme:.1f}s gesprochene Antworten mitgeschnitten.")
            spur.schliessen()
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
    ap.add_argument("--am-stueck", action="store_true",
                    help="alter Modus (Lasttests): Audio am Stück als Fake-Mikrofon, ohne auf Nestor zu warten")
    ap.add_argument("--bis", type=float, default=None,
                    help="nur die ersten SEKUNDEN des Materials (Quellzeit) – kurze Probeläufe, nicht mit --am-stueck")
    args = ap.parse_args()
    if args.bis and args.am_stueck:
        ap.error("--bis gibt es nur im abwechselnden Modus (ohne --am-stueck).")
    if args.nur_knopfdruck and args.stufe != "basis":
        ap.error("--nur-knopfdruck gibt es nur mit --stufe basis (Ticket #13).")
    if not args.bericht:
        name = f"{args.stufe}-knopfdruck" if args.nur_knopfdruck else args.stufe
        args.bericht = str(WURZEL / "logs" / "cloudtest" / f"{datetime.now():%Y-%m-%d_%H%M}_{name}")
    asyncio.run(lauf(args))


if __name__ == "__main__":
    main()
