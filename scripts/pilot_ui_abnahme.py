"""Wiederholbare UI-Klickabnahme für den Pilot (Ticket #56).

Alle fachlichen Aktionen laufen über die sichtbare Browseroberfläche: Login,
Stufenkarte, Agenda-Absenden, QR-Einstieg am anonymen Handy, Mikrofonfreigabe,
Meetingstart und Paketdownload. Das Mikrofonsignal ist synthetisch aus den
vorhandenen Testaufnahmen zusammengesetzt. KI-Aussagen werden nur als bestanden
gewertet, wenn ein echter Online-Lauf den Text im Transkript, in einer Ergebnis-
Karte und im heruntergeladenen Protokoll belegt.

Beispiel:
  LMC_TEST_PASSWORT=... .venv/bin/python scripts/pilot_ui_abnahme.py \
      --url https://pilot.example --stufe premium --bericht logs/pilot-ui

Das Passwort wird ausschließlich aus der mit --passwort-env benannten
Umgebungsvariable gelesen und nie in den Bericht geschrieben.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import time
import traceback
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import numpy as np
from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parent.parent
CLOUDTEST = ROOT / "testbibliothek" / "cloudtest"
CHROMIUM = "/usr/bin/chromium"
RATE = 24_000

# Sämtliche UI-Stellen stehen hier, damit Anpassungen an der Oberfläche gezielt
# und zentral nachgeführt werden können.
UI = {
    "password": 'input[name="passwort"]',
    "basis_card": "#karte-basis",
    "premium_card": "#karte-premium",
    "stage": "#modus-pill",
    "agenda_root": "#einrichtung",
    "agenda_textarea": "#agenda-feld",
    "agenda_send": "#agenda-senden",
    "agenda_rows": "#agenda-tabelle .agenda-zeile",
    "handy_setup": "#btn-handy-vorbereitung",
    "qr_link": "#hf-text a[href]",
    "phone_app": "#app",
    "phone_mic": "#btn-mikro",
    "meeting_start": "#btn-start",
    "meeting_stop": "#btn-stopp",
    "transcript_toggle": "#btn-transkript",
    "transcript_close": "#leiste-zu",
    "transcript": "#transkript",
    "result_cards": "#vl-buehne",
    "package": "#btn-paket",
    "completion": "#ab-inhalt",
}

SCENARIO = (
    "Bitte bereite eine kurze Vorstandssitzung vor. Ein Agendapunkt heißt "
    "Sommerfest-Budget, ein zweiter Vereinsbus-Prüfauftrag."
)
SOLLFRAGMENTE = {
    "Budgetobergrenze": re.compile(r"(?:9\s*[.]?\s*000|neun\s*tausend)", re.I),
    "Zuschussobergrenze": re.compile(r"(?:3\s*[.]?\s*500|drei\s*tausend\s*f[uü]nfhundert)", re.I),
    "Verantwortliche": re.compile(r"Sabine", re.I),
    "Termin": re.compile(r"Freitag", re.I),
}
SOLLFRAGMENTE_OHNE_TERMIN = {k: v for k, v in SOLLFRAGMENTE.items() if k != "Termin"}
_URL_RE = re.compile(r"(?i)\b(?:https?|wss?)://[^\s<>\"']+")


def termin_enthalten(text: str, laufbeginn: date | datetime | str) -> bool:
    """Freitag oder ein explizites ISO-Freitagsdatum von Laufstart bis +7 Tage."""
    if SOLLFRAGMENTE["Termin"].search(text):
        return True
    return any(re.search(rf"(?<!\d){tag}(?!\d)", text)
               for tag in iso_freitagsfenster(laufbeginn))


def iso_freitagsfenster(laufbeginn: date | datetime | str) -> list[str]:
    if isinstance(laufbeginn, str):
        laufbeginn = datetime.fromisoformat(laufbeginn).date()
    elif isinstance(laufbeginn, datetime):
        laufbeginn = laufbeginn.date()
    freitage = []
    for offset in range(8):
        tag = laufbeginn + timedelta(days=offset)
        if tag.weekday() == 4:
            freitage.append(tag.isoformat())
    return freitage


def ui_semantik_enthalten(text: str, laufbeginn: date | datetime | str) -> bool:
    return (all(pattern.search(text) for pattern in SOLLFRAGMENTE_OHNE_TERMIN.values())
            and termin_enthalten(text, laufbeginn))


def sichere_details(text: str) -> str:
    """Entfernt Query/Fragment aus URLs in Fehlerdetails und Stacktraces."""
    def ersetzen(match: re.Match) -> str:
        url = match.group(0)
        suffix = ""
        while url and url[-1] in ".,;:)]}":
            suffix = url[-1] + suffix
            url = url[:-1]
        return protokoll_url(url) + suffix
    return _URL_RE.sub(ersetzen, text)


def kompaktmaterial() -> tuple[np.ndarray, dict]:
    """Schneidet nur Beschluss und Verantwortungs-/Terminvergabe aus dem Test-WAV."""
    import wave

    ref = json.loads((CLOUDTEST / "referenz.json").read_text(encoding="utf-8"))
    wav_path = CLOUDTEST / "meeting.wav"
    with wave.open(str(wav_path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("meeting.wav muss 24-kHz-Mono-PCM16 sein")
        raw = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")

    # Grenzen stammen aus dem bekannten Testmaterial; die erste Spanne enthält
    # den Budgetbeschluss, die zweite den Auftrag mit Sabine/Jörg und Freitag.
    clips = ((420.24, 456.16), (518.81, 547.94))
    chunks = [raw[int(a * RATE):int(b * RATE)] for a, b in clips]
    if any(not len(chunk) for chunk in chunks):
        raise ValueError("Beschluss-/Aufgabenausschnitt fehlt im Test-WAV")
    pause = np.zeros(int(0.8 * RATE), dtype="<i2")
    pcm = np.concatenate((chunks[0], pause, chunks[1])).astype("<i2", copy=False)
    ref_short = {
        "dauer_s": len(pcm) / RATE,
        "ereignisse": [
            {"ereignis": "beschluss", "zeit_s": 0.0,
             "text": "Sommerfest: maximal 9.000 Euro Ausgaben und maximal 3.500 Euro Zuschuss."},
            {"ereignis": "aufgabe", "zeit_s": len(chunks[0]) / RATE + 0.8,
             "text": "Sabine liefert bis Freitag die Fahrten der Jugend des letzten Jahres."},
        ],
        "nestor": [], "grenzfaelle": [],
    }
    # Referenz-JSON wird nur zum Ermitteln der dokumentierten Testausschnitte gelesen.
    del ref
    return pcm, ref_short


class Lauf:
    def __init__(self, ordner: Path, stufe: str) -> None:
        self.ordner = ordner
        self.ordner.mkdir(parents=True, exist_ok=True)
        (ordner / "screenshots").mkdir(exist_ok=True)
        self.stufe = stufe
        self.start = time.monotonic()
        self.started_at = datetime.now().astimezone()
        self.screenshots: list[str] = []
        self.pruefungen: list[dict] = []
        self.fehler: list[str] = []
        self.belege: dict = {"laufart": "echte UI-Klickabnahme", "gestartet": self.started_at.isoformat(),
                             "stufe": stufe,
                             "offline_semantisch_bestanden": False}

    def pruefen(self, name: str, ok: bool, detail: str = "") -> None:
        try:
            print(f"[{self.stufe}] {'OK' if ok else 'FEHLT'}: {name}", flush=True)
        except BrokenPipeError:
            pass  # Ein Chat-/Terminalwechsel darf die Browserabnahme nicht abbrechen.
        self.pruefungen.append({"name": name, "status": "ok" if ok else "fehlt", "detail": detail})
        if not ok:
            self.fehler.append(name + (": " + detail if detail else ""))

    def ueberspringen(self, name: str, detail: str) -> None:
        self.pruefungen.append({"name": name, "status": "offline", "detail": detail})

    async def screenshot(self, page: Page, name: str) -> None:
        datei = f"{name}.png"
        await page.screenshot(path=str(self.ordner / "screenshots" / datei), full_page=True)
        if datei not in self.screenshots:
            self.screenshots.append(datei)

    def schreiben(self) -> None:
        self.belege["pruefungen"] = self.pruefungen
        self.belege["fehler"] = self.fehler
        self.belege["dauer_s"] = round(time.monotonic() - self.start, 1)
        self.belege["durchlaufklasse"] = "online" if self.belege.get("ki_online") else "offline_oder_nicht_belegt"
        self.belege["ki_semantik"] = ("bestanden" if self.belege.get("semantik_bestanden") else
                                      "fehlgeschlagen" if self.belege.get("ki_online") else "nicht_belegt")
        (self.ordner / "bericht.json").write_text(
            json.dumps(self.belege, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = "".join(
            f"<tr><td>{html.escape(p['status'])}</td><td>{html.escape(p['name'])}</td>"
            f"<td>{html.escape(p['detail'])}</td></tr>" for p in self.pruefungen)
        bilder = "".join(f'<figure><figcaption>{html.escape(Path(name).stem)}</figcaption>'
                         f'<a href="screenshots/{html.escape(name)}">'
                         f'<img loading="lazy" src="screenshots/{html.escape(name)}"></a></figure>'
                         for name in self.screenshots)
        (self.ordner / "bericht.html").write_text(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>UI-Abnahme</title>"
            "<style>body{font:16px system-ui;margin:24px auto;max-width:1100px;padding:16px;color:#182033}"
            "table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #ddd}"
            "img{max-width:100%;border:1px solid #ddd}figure{margin:30px 0}figcaption{font-weight:700}</style>"
            f"<h1>UI-Klickabnahme · {html.escape(self.stufe)}</h1><p>KI-Semantik: {html.escape(self.belege['ki_semantik'])}.</p>"
            "<p>KI-Semantik wird nur im Online-Lauf gewertet. Offline-Läufe sind "
            "separat gekennzeichnet und können semantisch nicht bestehen.</p>"
            f"<table><thead><tr><th>Status</th><th>Prüfung</th><th>Beleg</th></tr></thead><tbody>{rows}</tbody></table>{bilder}",
            encoding="utf-8")


async def warte(page: Page, predicate: str, timeout: float = 20) -> bool:
    try:
        await page.wait_for_function(predicate, timeout=timeout * 1000)
        return True
    except Exception:
        return False


def protokoll_url(url: str) -> str:
    """Query und Fragment verbergen, weil QR-Links Kopplungsdaten enthalten."""
    p = urlparse(url)
    host = p.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = f":{p.port}" if p.port else ""
    except ValueError:
        port = ""
    return urlunparse((p.scheme, host + port, p.path, "", "", ""))


async def zustand(page: Page) -> dict:
    # Ausschließlich lesender Browserzustand als Prüfbeleg.
    return await page.evaluate("() => typeof zustand !== 'undefined' ? zustand : null") or {}


async def anmelden(page: Page, url: str, passwort: str, lauf: Lauf) -> None:
    await page.goto(url, wait_until="domcontentloaded")
    if "anmelden" in page.url and not await page.locator(UI["password"]).count():
        await page.goto(url.rstrip("/") + "/anmelden?alt=1", wait_until="domcontentloaded")
    feld = page.locator(UI["password"])
    if await feld.count():
        if not passwort:
            raise RuntimeError("Loginformular sichtbar, aber Passwort-Umgebungsvariable leer")
        await feld.fill(passwort)
        await page.get_by_role("button", name=re.compile("Anmelden", re.I)).click()
        await page.wait_for_load_state("domcontentloaded")
        if await page.locator(UI["password"]).count() or "falsch" in page.url:
            raise RuntimeError("Testpasswort wurde abgewiesen")
        lauf.pruefen("Testpasswort-Login über UI", True)
    else:
        lauf.pruefen("Login nicht erforderlich", True, "Startseite wurde ohne Loginformular angezeigt")


async def stufe_waehlen(page: Page, stufe: str, lauf: Lauf) -> None:
    sel = UI["basis_card"] if stufe == "basis" else UI["premium_card"]
    karte = page.locator(sel)
    if await karte.is_disabled():
        raise RuntimeError(f"Startkarte {stufe} ist deaktiviert; Server meldet fehlende Stufenkonfiguration")
    await karte.click()
    await page.wait_for_url("**/meeting", timeout=20_000)
    if not await warte(page, "() => typeof zustand !== 'undefined' && !!zustand?.stufe"):
        raise RuntimeError("WebSocket-Zustand mit gewählter Stufe kam nach der Navigation nicht an")
    z = await zustand(page)
    stage = await page.locator(UI["stage"]).inner_text()
    ok = z.get("stufe") == stufe and stufe in stage.lower()
    lauf.pruefen("Stufe nach Startkarten-Klick im Dashboard", ok, f"state={z.get('stufe')!r}, pill={stage!r}")
    await page.reload(wait_until="domcontentloaded")
    if not await warte(page, "() => typeof zustand !== 'undefined' && !!zustand"):
        raise RuntimeError("Dashboardzustand nach Reload nicht eingetroffen")
    z = await zustand(page)
    stage = await page.locator(UI["stage"]).inner_text()
    lauf.pruefen("Stufe im Dashboard nach Reload", z.get("stufe") == stufe and stufe in stage.lower(),
                 f"state={z.get('stufe')!r}, pill={stage!r}")


async def agenda_absenden(page: Page, lauf: Lauf) -> None:
    await page.locator(UI["agenda_root"]).wait_for(state="visible", timeout=20_000)
    field = page.locator(UI["agenda_textarea"]).first
    await field.wait_for(state="visible", timeout=10_000)
    if await field.is_disabled():
        state = await zustand(page)
        offline = bool(state.get("schluessel", {}).get("offline") or not state.get("schluessel_vorhanden"))
        if not offline:
            raise RuntimeError("Agenda-Prompt im UI deaktiviert, obwohl der Zustand nicht offline ist")
        lauf.ueberspringen("Agenda-Text per KI absenden", "Offline-Testserver hat keinen Agenda-Schlüssel")
        # Lokaler Offline-Klicklauf: Agenda ausschließlich über sichtbare Eingaben
        # aufbauen. Dieser Weg ist weder Prompt- noch KI-Semantiknachweis.
        rows = page.locator(UI["agenda_rows"])
        for titel in ("Sommerfest-Budget", "Vereinsbus-Prüfauftrag"):
            if await rows.count() <= 0:
                await page.locator("#agenda-tabelle .agenda-plus").click()
            elif await rows.count() < (2 if titel.startswith("Vereinsbus") else 1):
                await page.locator("#agenda-tabelle .agenda-plus").click()
            row = rows.nth(0 if titel.startswith("Sommerfest") else 1)
            await row.locator('input[placeholder="Punkt"]').fill(titel)
        await page.locator("#f-titel").fill("Lokaler Offline-UI-Test")
        count = await rows.count()
        lauf.pruefen("Offline-Agenda per sichtbaren Tabellenfeldern", count >= 2,
                     f"{count} sichtbare Agenda-Zeilen (ohne KI-Semantik)")
        ergebnisse = page.locator('#einrichtung input[type="checkbox"][value="ergebnisse"]')
        if await ergebnisse.count() and not await ergebnisse.is_checked():
            await ergebnisse.check(force=True)
        lauf.ueberspringen("Regel Ergebnisse festhalten im Offline-Test", "Keine Auswertung ohne KI")
        return
    async def agenda_werte() -> tuple[str, list[str]]:
        title = await page.locator("#f-titel").input_value()
        punkt_locator = page.locator('#agenda-tabelle .agenda-zeile input[placeholder="Punkt"]')
        points = [await punkt_locator.nth(i).input_value() for i in range(await punkt_locator.count())]
        return title, points

    vorher = await agenda_werte()
    await field.fill("Wir möchten etwas besprechen.")
    await page.locator(UI["agenda_send"]).click()
    rueckfrage_da = await warte(page,
        "() => document.getElementById('agenda-senden')?.textContent.trim() === 'Absenden' && "
        "!document.getElementById('agenda-antwort')?.hidden", timeout=120)
    rueckfrage = (await page.locator("#agenda-antwort").inner_text()).strip()
    unveraendert = (await agenda_werte()) == vorher
    lauf.pruefen("Allgemeine Agenda-Eingabe stellt sichtbare Rückfrage ohne Agendaänderung",
                 rueckfrage_da and rueckfrage.startswith("Rückfrage:") and unveraendert,
                 f"Antwort={rueckfrage[:180]!r}, Agenda unverändert={unveraendert}")
    if not rueckfrage_da or not rueckfrage.startswith("Rückfrage:") or not unveraendert:
        raise RuntimeError("Allgemeine Agenda-Eingabe ergab keine unverändernde sichtbare Rückfrage")

    await field.fill(SCENARIO)
    await page.locator(UI["agenda_send"]).click()
    done = await warte(page,
        "() => document.getElementById('agenda-senden')?.textContent.trim() === 'Absenden' && "
        "!document.getElementById('agenda-antwort')?.hidden", timeout=120)
    count = await page.locator(UI["agenda_rows"]).count()
    titel = await page.locator("#f-titel").input_value()
    lauf.pruefen("Agenda per sichtbarem Absenden-Klick übernommen", done and count >= 2,
                 f"Antwort sichtbar={done}, Zeilen={count}, Titel={titel!r}")
    if not done or count < 2:
        raise RuntimeError("Agenda-Antwort fehlt oder enthält weniger als zwei sichtbare Zeilen")
    ergebnisse = page.locator('#einrichtung input[type="checkbox"][value="ergebnisse"]')
    if await ergebnisse.count() and not await ergebnisse.is_checked():
        await ergebnisse.check(force=True)
    lauf.pruefen("Regel Ergebnisse festhalten über UI aktiviert",
                 await ergebnisse.count() > 0 and await ergebnisse.is_checked())


def stimmen_mithoeren(page: Page, letzte_stimme: dict) -> None:
    def websocket_verfolgen(ws) -> None:
        def empfangen(frame) -> None:
            try:
                nachricht = json.loads(frame)
            except (TypeError, ValueError):
                return
            if isinstance(nachricht, dict) and nachricht.get("typ") == "stimme":
                letzte_stimme["zeit"] = time.monotonic()
        ws.on("framereceived", empfangen)
    page.on("websocket", websocket_verfolgen)


async def handystart(page: Page, browser, stufe: str, lauf: Lauf, letzte_stimme: dict):
    await page.locator(UI["handy_setup"]).click()
    link = page.locator(UI["qr_link"])
    await page.wait_for_function("() => document.getElementById('hf-code')?.textContent.trim() !== '–'",
                                 timeout=15_000)
    qr_url = await link.get_attribute("href") if await link.count() else None
    local_qr_fallback = False
    if not qr_url:
        base = urlparse(page.url)
        if base.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError("QR-Link hat keine auslesbare Adresse")
        code = await page.locator("#hf-code").inner_text()
        code = code.replace("-", "").strip()
        if len(code) < 8:
            raise RuntimeError("Lokaler QR-Link fehlt und der sichtbare Kopplungscode ist ungültig")
        # Chromium akzeptiert Secure-Cookies auf localhost, nicht zuverlässig
        # auf einer nackten IPv4-Adresse. Der sichtbare Code bleibt derselbe.
        local_host = "localhost" if base.hostname in ("localhost", "127.0.0.1") else base.netloc
        qr_url = f"{base.scheme}://{local_host}:{base.port}/handy?k={code}"
        local_qr_fallback = True
    parsed = urlparse(qr_url)
    lauf.pruefen("QR-Adresse aus sichtbarem DOM gelesen", parsed.path == "/handy" and bool(parsed.query),
                 f"{parsed.scheme}://<lokaler-host>{parsed.path}"
                 + (" (lokaler Test: sichtbaren Code an lokale URL angehängt)" if local_qr_fallback else
                    " (Query-Werte aus Sicherheitsgründen nicht gespeichert)"))

    origin = f"{parsed.scheme}://{parsed.netloc}"
    phone_context = await browser.new_context(
        is_mobile=True, has_touch=True, viewport={"width": 390, "height": 844})
    await phone_context.grant_permissions(["microphone"], origin=origin)
    # Im Browser wird nur die Testregie als Aufnahmequelle verwendet. Die Seite
    # selbst fordert das Mikrofon erst nach dem echten Tippen auf btn-mikro an.
    import cloudtest_takt as takt
    await phone_context.add_init_script(takt.INIT_SCRIPT)
    phone = await phone_context.new_page()
    stimmen_mithoeren(phone, letzte_stimme)
    phone.on("pageerror", lambda e: lauf.fehler.append(f"Handy-JS: {e}"))
    await phone.goto(qr_url, wait_until="domcontentloaded")
    if not await warte(phone, "() => !document.getElementById('app')?.hidden", timeout=30):
        raise RuntimeError("Anonymer Handy-Kontext wurde über QR nicht gekoppelt")
    pz = await zustand(phone)
    pstage = pz.get("stufe")
    lauf.pruefen("Anonymer Handy-Kontext sieht gewählte Stufe", pstage == stufe, f"state={pstage!r}")
    await phone.reload(wait_until="domcontentloaded")
    if not await warte(phone, "() => !document.getElementById('app')?.hidden", timeout=20):
        raise RuntimeError("Handy-Kontext nach Reload nicht gekoppelt")
    pz = await zustand(phone)
    lauf.pruefen("Stufe im Handy nach Reload", pz.get("stufe") == stufe, f"state={pz.get('stufe')!r}")
    await phone.locator(UI["phone_mic"]).click()
    ready = await warte(page,
        "() => typeof zustand !== 'undefined' && zustand.handys > 0 && "
        "zustand.mikro?.quelle === 'handy' && zustand.lautsprecher === 'handy'", timeout=30)
    pz = await zustand(phone)
    lauf.pruefen("Mikrofon am Handy per btn-mikro aktiviert", ready,
                 f"handys={pz.get('handys')}, quelle={pz.get('mikro', {}).get('quelle')}, "
                 f"lautsprecher={pz.get('lautsprecher')}")
    if not ready:
        diagnostic = await phone.evaluate("() => ({secure: isSecureContext, media: !!navigator.mediaDevices, "
            "status: document.getElementById('status')?.textContent, "
            "kopplung: document.getElementById('koppeln-falsch')?.textContent, "
            "mikrotext: document.getElementById('mikro-text')?.textContent, "
            "mikroLaeuft: typeof mikro !== 'undefined' ? mikro.laeuft() : null})")
        lauf.belege["phone_mic_diagnose"] = diagnostic
        await lauf.screenshot(phone, "handy_fehler")
        raise RuntimeError("Handy-Mikrofon wurde serverseitig nicht als aktive Quelle gesehen")
    second_context = await browser.new_context(is_mobile=True, has_touch=True,
                                               viewport={"width": 390, "height": 844})
    second_phone = await second_context.new_page()
    await second_phone.goto(qr_url, wait_until="domcontentloaded")
    rejected = await warte(second_phone,
        "() => !document.getElementById('koppeln-falsch')?.hidden && "
        "document.getElementById('koppeln-falsch')?.textContent.includes('Anderes Handy verbunden')", timeout=15)
    # Das Interface unterscheidet den 4409-Fehler im Status-Text und im Hilfetext;
    # die Verbindung kann auch noch vor dem Rendering der Fehlermeldung schließen.
    if not rejected:
        rejected = await warte(second_phone,
            "() => document.getElementById('status')?.textContent.includes('Anderes Handy verbunden')", timeout=5)
    lauf.pruefen("Zweites anonymes Handy wird im UI abgewiesen", rejected)
    await second_context.close()
    return phone_context, phone


async def meeting_starten(page: Page, stufe: str, lauf: Lauf) -> None:
    button = page.locator(UI["meeting_start"])
    await button.wait_for(state="visible", timeout=15_000)
    await page.wait_for_function("() => !document.getElementById('btn-start')?.disabled", timeout=30_000)
    await button.click()
    if not await warte(page, "() => !!zustand?.hoeren", timeout=30):
        raise RuntimeError("Desktop-Meetingstart per btn-start wurde nicht bestätigt")
    live = not await page.locator("#live").is_hidden()
    prep_hidden = await page.locator(UI["agenda_root"]).is_hidden()
    lauf.pruefen("Vorbereitungs-/Live-Phase nach btn-start", live and prep_hidden,
                 f"live sichtbar={live}, Vorbereitung verborgen={prep_hidden}")
    state = await zustand(page)
    lauf.belege["ki_online"] = bool(state.get("schluessel_vorhanden") and not state.get("schluessel", {}).get("offline"))
    ids = state.get("regel_ids") or []
    lauf.pruefen("Ergebnisregel sitzt im aktiven Meetingzustand", "ergebnisse" in ids,
                 f"regel_ids={ids!r}")
    buttons = page.locator("#knopf-leiste .knopf-art:visible")
    count = await buttons.count()
    lauf.pruefen("Genau fünf kompakte Kernaktionen sichtbar", count == 5, f"sichtbar={count}")
    boxes = [await buttons.nth(i).bounding_box() for i in range(count)]
    heights = [b["height"] for b in boxes if b]
    lauf.pruefen("Kernknöpfe gleich hoch und kompakt", len(heights) == 5 and max(heights) - min(heights) < 2 and max(heights) <= 90,
                 f"Höhen: {[round(h, 1) for h in heights]}")
    await lauf.screenshot(page, "dashboard_live")


async def space_taste_pruefen(page: Page, stufe: str, lauf: Lauf) -> None:
    if stufe != "basis":
        return
    taste = page.locator("#btn-taste")
    if await taste.is_visible():
        await taste.focus()
        await page.keyboard.down("Space")
        try:
            gehalten = await warte(page, "() => document.getElementById('btn-taste')?.classList.contains('haelt')",
                                   timeout=3)
            await asyncio.sleep(0.2)
        finally:
            await page.keyboard.up("Space")
        lauf.pruefen("Leertaste löst bei fokussierter Sprechtaste Halten aus", gehalten)
    else:
        lauf.ueberspringen("Leertaste auf Sprechtaste", "Basis-Sprechtaste ist in diesem Offline-Zustand verborgen")


async def begruessung_abwarten(page: Page, letzte_stimme: dict, lauf: Lauf) -> None:
    """Wartet wie cloudtest_takt.Regie auf die abgeschlossene Begrüßung.

    Empfangene stimme-Pakete werden nur als Zeitmarker erfasst. Der Browserzustand
    bleibt lesend; die Aufnahme startet erst nach ruhigem, stabilem Zustand.
    """
    import cloudtest_takt as takt

    start = time.monotonic()
    stabil_seit = None
    deadline = start + takt.BEGRUESSUNG_LIMIT_S
    while time.monotonic() < deadline:
        state = await page.evaluate("""() => ({
          zustand: (typeof zustand !== 'undefined' && zustand)
            ? (zustand.assistent?.zustand ?? null) : null,
          rest: (typeof stimme !== 'undefined' && stimme.ctx)
            ? Math.max(0, stimme.naechste - stimme.ctx.currentTime) : 0,
          hoeren: (typeof zustand !== 'undefined' && zustand) ? !!zustand.hoeren : false
        })""")
        now = time.monotonic()
        last = letzte_stimme.get("zeit")
        voice_quiet = last is not None and now - last >= takt.FERTIG_RUHE_S
        state_finished = state.get("zustand") in takt.NESTOR_FERTIG
        quiet = voice_quiet and float(state.get("rest") or 0) <= 0.05
        done = state_finished and quiet
        stabil_seit = stabil_seit if done and stabil_seit is not None else now if done else None
        if stabil_seit is not None and now - stabil_seit >= takt.STABIL_S:
            lauf.pruefen("Begrüßung vor synthetischer Aufnahme abgeschlossen",
                         True, f"Assistent={state.get('zustand')}, Tonruhe≥{takt.FERTIG_RUHE_S}s, stabil≥{takt.STABIL_S}s")
            return
        await asyncio.sleep(takt.TAKT_S)
    raise TimeoutError(
        f"Begrüßung nicht innerhalb {takt.BEGRUESSUNG_LIMIT_S:.0f}s beendet "
        f"(Assistent={state.get('zustand')!r}, Tonpaket empfangen={letzte_stimme.get('zeit') is not None})"
    )


async def audio_abspielen(page: Page, phone: Page, lauf: Lauf, letzte_stimme: dict) -> None:
    import base64

    # Nur das gekoppelte Handy empfängt und spielt die Stimme tatsächlich ab.
    await begruessung_abwarten(phone, letzte_stimme, lauf)
    # PTT-Keycheck erst nach Begrüßung; selbst kurze Test-Aktivität darf deren
    # tatsächliche Sprachaufnahme weder triggern noch überlappen.
    await space_taste_pruefen(page, lauf.stufe, lauf)
    pcm, _referenz = kompaktmaterial()
    encoded = base64.b64encode(pcm.tobytes()).decode("ascii")
    await phone.evaluate("b => window.__testMikro.laden(91, b)", encoded)
    await phone.evaluate("() => window.__testMikro.starten(91)")
    lauf.belege["testaudio_s"] = round(len(pcm) / RATE, 1)
    # Nur warten bis der synthetische WAV-Ausschnitt durch den echten Handy-WS
    # und die serverseitige Audioverarbeitung gelaufen ist.
    await phone.wait_for_function("() => !window.__testMikro.stand().laeuft", timeout=120_000)
    deadline = time.monotonic() + 120
    last_signature = None
    stable_since = None
    transcript_ready = False
    transcript = ""
    while time.monotonic() < deadline:
        segments = await page.evaluate("""() => ((typeof zustand !== 'undefined' && zustand?.segmente) || []).map(s => ({
          start: s.start, sprecher: s.sprecher, text: s.text || ''
        }))""")
        transcript = " ".join(s["text"] for s in segments)
        has_all = all(pattern.search(transcript) for pattern in SOLLFRAGMENTE.values())
        signature = json.dumps(segments, ensure_ascii=False, sort_keys=True)
        now = time.monotonic()
        if has_all and signature == last_signature:
            stable_since = stable_since if stable_since is not None else now
            if now - stable_since >= 2.0:
                transcript_ready = True
                break
        else:
            stable_since = None
        last_signature = signature
        await asyncio.sleep(0.25)
    await page.locator(UI["transcript_toggle"]).click()
    await warte(page, "() => document.getElementById('transkript')?.innerText.length > 0", timeout=30)
    transcript = await page.locator(UI["transcript"]).inner_text()
    lauf.belege["transkript_text"] = transcript
    await lauf.screenshot(page, "transkript")
    fehlend = [label for label, pattern in SOLLFRAGMENTE.items() if not pattern.search(transcript)]
    text_ok = not fehlend and transcript_ready
    lauf.pruefen("Beschluss und Aufgabe im sichtbaren UI-Transkript", text_ok,
                 "Alle vier Aussagen nach 2s stabiler ASR-Ruhe gefunden" if text_ok else
                 (("ASR-Zustand nach 120s nicht vollständig/stabil" if not transcript_ready else
                   "Fehlt: " + ", ".join(fehlend))))
    # Die Karte entsteht durch eine echte Bedienaktion. Laufende Artefaktkarten
    # aus dem Hintergrund zählen nicht als Ergebnis der expliziten Abnahme.
    z_vorher = await zustand(page)
    karten_vorher = {k.get("id") for k in z_vorher.get("karten", [])}
    zusammenfassen = page.locator('#knopf-leiste [data-knopf="zusammenfassen"]')
    await zusammenfassen.wait_for(state="visible", timeout=20_000)
    if await zusammenfassen.is_disabled():
        raise RuntimeError("UI-Knopf ‚Ergebnisse bündeln‘ ist deaktiviert")
    await zusammenfassen.click()
    karte_da = await warte(page,
        "() => (zustand?.karten || []).some(k => !" + json.dumps(list(karten_vorher)) +
        ".includes(k.id) && k.art === 'zusammenfassung')", timeout=120)
    lauf.pruefen("Neue Ergebnis-Karte nach UI-Klick auf Ergebnisse bündeln", karte_da)
    if not karte_da:
        raise RuntimeError("Der UI-Klick erzeugte keine neue Zusammenfassungs-Karte")
    termin_js = "|".join(["Freitag", *iso_freitagsfenster(lauf.started_at)])
    await warte(page,
        "() => { const t = document.getElementById('vl-buehne')?.innerText || ''; "
        "return /(?:9\\s*[.]?\\s*000|neun\\s*tausend)/i.test(t) && "
        "/(?:3\\s*[.]?\\s*500|drei\\s*tausend\\s*f[uü]nfhundert)/i.test(t) && "
        "/Sabine/i.test(t) && new RegExp(" + json.dumps(termin_js) + ", 'i').test(t); }", timeout=30)
    cards = await page.locator(UI["result_cards"]).inner_text()
    lauf.belege["ergebnis_karten_text"] = cards
    card_ok = ui_semantik_enthalten(cards, lauf.started_at)
    lauf.pruefen("Beschluss und Aufgabe in sichtbarer Ergebnis-Karte", card_ok,
                 "Aussagen inkl. Freitag/ISO-Freitag im 7-Tage-Fenster gefunden" if card_ok else
                 "Karteninhalt enthält nicht alle Sollfragmente oder nennt einen Termin außerhalb des 7-Tage-Fensters")
    finaler_stand = await zustand(page)
    lauf.belege["ki_zustand"] = {
        "stufe": finaler_stand.get("stufe"),
        "schluessel_vorhanden": finaler_stand.get("schluessel_vorhanden"),
        "offline": finaler_stand.get("schluessel", {}).get("offline"),
    }
    lauf.belege["ki_online"] = bool(finaler_stand.get("schluessel_vorhanden") and
                                     not finaler_stand.get("schluessel", {}).get("offline"))
    lauf.belege["semantik_bestanden"] = bool(text_ok and card_ok and lauf.belege["ki_online"])


async def abschluss_und_paket(page: Page, lauf: Lauf) -> None:
    panel_zu = await transkriptpanel_schliessen(page)
    lauf.pruefen("Transkriptpanel per sichtbarem Schließenknopf vor Meetingende geschlossen", panel_zu)
    if not panel_zu:
        raise RuntimeError("Transkriptpanel ließ sich vor dem Beenden nicht über den UI-Knopf schließen")
    await page.locator(UI["meeting_stop"]).click()
    if not await warte(page, "() => location.pathname.includes('abschluss') || "
                            "!document.getElementById('ab-inhalt')?.hidden", timeout=30):
        raise RuntimeError("Abschlussseite nach UI-Klick auf Beenden fehlt")
    await page.locator(UI["completion"]).wait_for(state="visible", timeout=30_000)
    online = bool(lauf.belege.get("ki_online"))
    await page.locator(UI["package"]).wait_for(state="visible", timeout=30_000)
    await page.locator(UI["package"]).wait_for(state="attached")
    if not await warte(page, "() => !document.getElementById('btn-paket')?.disabled", timeout=240):
        lauf.pruefen("Paketdownload über UI verfügbar", False, "Button blieb deaktiviert")
        return
    async with page.expect_download() as dl:
        await page.locator(UI["package"]).click()
    download = await dl.value
    path = lauf.ordner / "protokoll.zip"
    await download.save_as(str(path))
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        required = {"meeting.md", "meeting.html", "meeting-mit-regelanalyse.html",
                    "transkript.md", "agenda.md", "hinweise.md", "technik.json"}
        missing = sorted(required - set(names))
        protocol_name = next((n for n in ("protokoll.md", "meeting.md") if n in names), None)
        protocol = archive.read(protocol_name).decode("utf-8", errors="replace") if protocol_name else ""
        transcript_zip = (archive.read("transkript.md").decode("utf-8", errors="replace")
                          if "transkript.md" in names else "")
    lauf.belege["paket_dateien"] = names
    online_semantik = bool(online and protocol_name and not missing)
    protocol_text_ok = ui_semantik_enthalten(protocol, lauf.started_at)
    transcript_zip_ok = all(pattern.search(transcript_zip) for pattern in SOLLFRAGMENTE.values())
    prot_ok = online_semantik and protocol_text_ok and transcript_zip_ok
    lauf.pruefen("UI-ZIP enthält Pflichtdateien und Beschluss/Aufgabe in Protokoll und Transkript",
                 prot_ok,
                 "Semantische Prüfung nur online" if online_semantik else
                 ("Pflichtdateien fehlen: " + ", ".join(missing) if missing else
                  "Offline/Modell nicht bestätigt; ZIP-Inhalt ist kein KI-Semantiknachweis"))
    lauf.belege["protokoll_semantik"] = {
        "inhalt_vorhanden": protocol_text_ok,
        "terminfenster_start": lauf.started_at.date().isoformat(),
        "zulaessige_iso_freitage": iso_freitagsfenster(lauf.started_at),
        "transkript_enthaelt_freitag": transcript_zip_ok,
    }
    # Ein Offline-Lauf darf lokale UI-Prüfungen bestehen, aber nie als semantischer Erfolg gelten.
    lauf.belege["offline_semantisch_bestanden"] = False
    lauf.belege["semantik_bestanden"] = bool(lauf.belege.get("semantik_bestanden") and prot_ok and online_semantik)
    await lauf.screenshot(page, "abschluss")


async def transkriptpanel_schliessen(page: Page) -> bool:
    panel = page.locator("#leiste")
    if not await panel.count() or not await panel.is_visible():
        return True
    close_button = page.locator(UI["transcript_close"])
    if not await close_button.is_visible():
        return False
    await close_button.click()
    return await warte(page, "() => document.getElementById('leiste')?.hidden === true", timeout=5)


async def run(args) -> Lauf:
    passwort = os.environ.get(args.passwort_env)
    local = urlparse(args.url).hostname in ("localhost", "127.0.0.1", "::1")
    if not passwort and not local:
        raise SystemExit(f"Umgebungsvariable {args.passwort_env!r} ist leer oder nicht gesetzt")
    report = Lauf(Path(args.bericht), args.stufe)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=args.chromium, headless=True,
                                           args=["--no-sandbox", "--use-fake-ui-for-media-stream"])
        context = await browser.new_context(permissions=["microphone"])
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import cloudtest_takt as takt
        await context.add_init_script(takt.INIT_SCRIPT)
        page = await context.new_page()
        async def dialog_beantworten(dialog):
            if dialog.type == "alert":
                report.fehler.append(sichere_details(f"Browser-Fehlermeldung: {dialog.message}"))
                await dialog.dismiss()
            else:
                await dialog.accept()  # ausschließlich eigene synthetische Testrunde
        page.on("dialog", dialog_beantworten)
        letzte_stimme = {"zeit": None}
        stimmen_mithoeren(page, letzte_stimme)
        page.on("pageerror", lambda e: report.fehler.append(sichere_details(f"Browser-JS: {e}")))
        page.on("requestfailed", lambda r: report.fehler.append(
            sichere_details(f"Netzwerk: {r.method} {r.url} ({r.failure})")))
        phone_context = None
        try:
            await anmelden(page, args.url, passwort, report)
            await stufe_waehlen(page, args.stufe, report)
            await agenda_absenden(page, report)
            phone_context, phone = await handystart(page, browser, args.stufe, report, letzte_stimme)
            await meeting_starten(page, args.stufe, report)
            report.pruefen("Tatsächlicher Desktop-Klick auf btn-start", True)
            if args.bis_start:
                await space_taste_pruefen(page, args.stufe, report)
                report.ueberspringen("Live-ASR, Ergebniskarte und Paket-Semantik",
                                     "Lokaler Offline-UI-Lauf endet nach dem Meetingstart")
            else:
                await audio_abspielen(page, phone, report, letzte_stimme)
                await abschluss_und_paket(page, report)
        except Exception as exc:
            report.belege["ausnahme_traceback"] = sichere_details(traceback.format_exc())
            report.fehler.append(sichere_details(f"Lauf abgebrochen: {type(exc).__name__}: {exc}"))
            try:
                await report.screenshot(page, "fehler")
            except Exception:
                pass
        finally:
            # Eigene synthetische Testrunden über die UI beenden, auch bei fehlgeschlagener Abnahme.
            try:
                if not await transkriptpanel_schliessen(page):
                    raise RuntimeError("Transkriptpanel ließ sich nicht über den sichtbaren Schließenknopf schließen")
                stop = page.locator(UI["meeting_stop"])
                if await stop.count() and await stop.is_visible():
                    await stop.click()
                    await page.wait_for_url("**/abschluss", timeout=30_000)
                fertig = page.locator("#btn-fertig")
                if await fertig.count() and await fertig.is_visible():
                    await page.wait_for_function("() => !document.getElementById('btn-fertig')?.disabled", timeout=120_000)
                    await fertig.click()
                    await page.wait_for_function("() => document.getElementById('btn-fertig')?.disabled", timeout=15_000)
                    report.belege["test_cleanup"] = "Eigene Testrunde über UI abgeschlossen; automatische 5-Minuten-Rückkehrfrist"
            except Exception as exc:
                report.belege["cleanup_traceback"] = sichere_details(traceback.format_exc())
                report.fehler.append(sichere_details(f"UI-Testabschluss fehlgeschlagen: {type(exc).__name__}: {exc}"))
            if phone_context:
                await phone_context.close()
            await context.close()
            await browser.close()
    report.schreiben()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Pilot-Basis-URL")
    parser.add_argument("--stufe", choices=("basis", "premium"), required=True)
    parser.add_argument("--bericht", required=True, help="Zielordner für JSON/HTML, Screenshots und UI-ZIP")
    parser.add_argument("--passwort-env", default="LMC_TEST_PASSWORT",
                        help="Name der Umgebungsvariable mit dem Testpasswort (Standard: LMC_TEST_PASSWORT)")
    parser.add_argument("--chromium", default=CHROMIUM)
    parser.add_argument("--bis-start", action="store_true",
                        help="lokaler Offline-UI-Lauf: nach sichtbarem Meetingstart beenden, keine Semantik werten")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(f"Bericht: {Path(args.bericht).resolve() / 'bericht.html'}")
    if result.fehler:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
