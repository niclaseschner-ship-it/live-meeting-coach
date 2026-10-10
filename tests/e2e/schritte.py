"""Schrittfunktionen der Klick-E2E (Ticket #61) – herausgehoben aus scripts/pilot_ui_abnahme.py und erweitert.

Regeln für alles hier:
- **Aktionen nur per Klick, Tippen, Tastatur, Maus** (`click`, `tap`, `fill`, `keyboard`, `mouse`). Kein
  `page.evaluate` für Aktionen, kein direkter API-Aufruf, keine Zustandsinjektion.
- `page.evaluate` nur **lesend** für Belege (Ton-Fingerabdruck, Serverzustand als Zusatzbeleg).
- Der QR-Code wird als **Bild** gelesen (Screenshot + OpenCV), nicht aus dem `<a href>` daneben.
- Sichtbarkeit, Reihenfolge und Bedienmodell kommen aus `szenarien/ui_vertrag.json`. Weicht der Code ab und steht
  die Prüfung in `bekannte_abweichungen`, wird sie als `bekannt_rot` mit Ticket gemeldet, nicht verschwiegen.

Dieselben Funktionen sollen später Stufe C (echte Anbieter, Staging) fahren; der Unterschied liegt nur im Lauf.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from playwright.async_api import Browser, Page

WURZEL = Path(__file__).resolve().parents[2]
VERTRAG = json.loads((WURZEL / "szenarien" / "ui_vertrag.json").read_text(encoding="utf-8"))
DREHBUCH = json.loads((WURZEL / "tests" / "e2e" / "drehbuch.json").read_text(encoding="utf-8"))
HANDY = {"is_mobile": True, "has_touch": True, "viewport": {"width": 390, "height": 844},
         "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/140.0.0.0 Mobile Safari/537.36")}

# Ton-Fingerabdruck: hängt einen AnalyserNode vor jedes Ziel `destination` und protokolliert alle 100 ms die
# dominante Frequenz, solange etwas klingt. Rein beobachtend – die Seite merkt davon nichts.
TON_SKRIPT = """
(() => {
  const log = []; window.__tonLog = log;
  if (!window.AudioNode || !window.AudioDestinationNode) return;
  const verbinden = AudioNode.prototype.connect;
  AudioNode.prototype.connect = function (ziel, ...rest) {
    if (ziel instanceof AudioDestinationNode && !(this instanceof AnalyserNode)) {
      const ctx = this.context;
      if (!ctx.__ohr) {
        const an = ctx.createAnalyser(); an.fftSize = 8192; an.smoothingTimeConstant = 0;
        verbinden.call(an, ctx.destination);
        ctx.__ohr = an;
        const daten = new Float32Array(an.frequencyBinCount);
        setInterval(() => {
          if (ctx.state !== "running") return;
          an.getFloatFrequencyData(daten);
          let max = -Infinity, idx = 0;
          for (let i = 4; i < daten.length; i++) if (daten[i] > max) { max = daten[i]; idx = i; }
          if (max > -60) log.push({ t: Date.now(), hz: Math.round(idx * ctx.sampleRate / an.fftSize), db: Math.round(max) });
        }, 100);
      }
      return verbinden.call(this, ctx.__ohr, ...rest);
    }
    return verbinden.call(this, ziel, ...rest);
  };
})();
"""


class Abbruch(RuntimeError):
    """Ein Schritt, ohne den der Durchlauf nicht weitergehen kann."""


# --- Bericht ----------------------------------------------------------------------------------------------------------
class Lauf:
    def __init__(self, ordner: Path, stufe: str, rauch: bool) -> None:
        self.ordner = ordner
        (ordner / "screenshots").mkdir(parents=True, exist_ok=True)
        self.stufe = stufe
        self.rauch = rauch
        self.start = time.monotonic()
        self.gestartet = datetime.now().astimezone()
        self.pruefungen: list[dict] = []
        self.screenshots: list[str] = []
        self.belege: dict = {"stufe": stufe, "rauch": rauch, "gestartet": self.gestartet.isoformat()}
        self.schritt_zeiten: list[tuple[str, float]] = []

    def _eintrag(self, name: str, status: str, detail: str = "", ticket: str = "") -> None:
        self.pruefungen.append({"name": name, "status": status, "detail": detail, "ticket": ticket,
                                "t": round(time.monotonic() - self.start, 1)})
        zeichen = {"ok": "OK  ", "fehlt": "ROT ", "bekannt_rot": "BEK ", "offen": "--  ", "ausstehend": "AUS "}[status]
        print(f"[{self.stufe}] {zeichen} {name}" + (f"  ({ticket})" if ticket else "")
              + (f" – {detail}" if detail and status != "ok" else ""), flush=True)

    def pruefen(self, name: str, ok: bool, detail: str = "", abweichung: str | None = None) -> bool:
        """abweichung: Schlüssel aus ui_vertrag.json → bekannte_abweichungen. Rot dort = bekannt_rot mit Ticket."""
        if ok:
            self._eintrag(name, "ok", detail)
        elif abweichung and abweichung in VERTRAG["bekannte_abweichungen"]:
            self._eintrag(name, "bekannt_rot", detail, VERTRAG["bekannte_abweichungen"][abweichung])
        else:
            self._eintrag(name, "fehlt", detail)
        return ok

    def offen(self, name: str, detail: str) -> None:
        self._eintrag(name, "offen", detail)

    def ausstehend(self, name: str, detail: str, ticket: str) -> None:
        self._eintrag(name, "ausstehend", detail, ticket)

    def schritt(self, name: str) -> None:
        self.schritt_zeiten.append((name, round(time.monotonic() - self.start, 1)))
        print(f"[{self.stufe}] ▸ {name}", flush=True)

    @property
    def rot(self) -> list[dict]:
        return [p for p in self.pruefungen if p["status"] == "fehlt"]

    async def bild(self, page: Page, name: str) -> None:
        datei = f"{len(self.screenshots) + 1:02d}_{name}.png"
        try:
            await page.screenshot(path=str(self.ordner / "screenshots" / datei), full_page=True)
            self.screenshots.append(datei)
        except Exception as e:  # noqa: BLE001 – ein fehlender Screenshot bricht den Lauf nicht ab
            self.belege.setdefault("screenshot_fehler", []).append(f"{name}: {type(e).__name__}")

    def schreiben(self, videos: list[str] | None = None) -> Path:
        self.belege.update(pruefungen=self.pruefungen, schritte=self.schritt_zeiten,
                           dauer_s=round(time.monotonic() - self.start, 1), videos=videos or [])
        (self.ordner / "bericht.json").write_text(json.dumps(self.belege, ensure_ascii=False, indent=2), "utf-8")
        farbe = {"ok": "#15803d", "fehlt": "#b91c1c", "bekannt_rot": "#b45309", "offen": "#64748b", "ausstehend": "#7c3aed"}
        zeilen = "".join(
            f"<tr><td style='color:{farbe[p['status']]};font-weight:600'>{p['status']}</td><td>{html.escape(p['name'])}</td>"
            f"<td>{html.escape(p['ticket'])}</td><td>{html.escape(p['detail'])}</td><td>{p['t']}</td></tr>"
            for p in self.pruefungen)
        zaehl = {s: sum(1 for p in self.pruefungen if p["status"] == s) for s in farbe}
        bilder = "".join(f"<figure><figcaption>{html.escape(n)}</figcaption><a href='screenshots/{html.escape(n)}'>"
                         f"<img loading='lazy' src='screenshots/{html.escape(n)}'></a></figure>" for n in self.screenshots)
        filme = "".join(f"<figure><figcaption>{html.escape(v)}</figcaption><video controls src='{html.escape(v)}'>"
                        "</video></figure>" for v in (videos or []))
        anbieter = html.escape(json.dumps(self.belege.get("anbieterbeweis", {}), ensure_ascii=False, indent=2))
        (self.ordner / "bericht.html").write_text(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>Klick-E2E {html.escape(self.stufe)}</title>"
            "<style>body{font:15px system-ui;margin:24px auto;max-width:1100px;padding:0 16px;color:#182033}"
            "table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #ddd;"
            "vertical-align:top}img,video{max-width:100%;border:1px solid #ddd}figure{margin:24px 0}"
            "figcaption{font-weight:600}pre{background:#f1f5f9;padding:12px;overflow:auto}</style>"
            f"<h1>Klick-E2E Stufe B · {html.escape(self.stufe)}{' · Rauch' if self.rauch else ''}</h1>"
            f"<p>{self.gestartet:%d.%m.%Y %H:%M} · Dauer {self.belege['dauer_s']} s · "
            + " · ".join(f"{k}: {v}" for k, v in zaehl.items()) + "</p>"
            "<p>ok = erfüllt · fehlt = rot · bekannt_rot = Abweichung vom Auftrag, Ticket offen · offen = in diesem "
            "Lauf nicht geprüft · ausstehend = braucht erst das genannte Ticket.</p>"
            f"<table><tr><th>Status</th><th>Prüfung</th><th>Ticket</th><th>Beleg</th><th>t [s]</th></tr>{zeilen}</table>"
            f"<h2>Anbieterbeweis</h2><pre>{anbieter}</pre><h2>Videos</h2>{filme}<h2>Screenshots</h2>{bilder}",
            encoding="utf-8")
        return self.ordner / "bericht.html"


# --- kleine Helfer ----------------------------------------------------------------------------------------------------
async def warte(page: Page, ausdruck: str, sekunden: float = 20) -> bool:
    """Lesend auf einen Zustand warten (wait_for_function liest nur)."""
    try:
        await page.wait_for_function(ausdruck, timeout=sekunden * 1000)
        return True
    except Exception:  # noqa: BLE001
        return False


async def sichtbar(page: Page, selektor: str) -> bool:
    loc = page.locator(selektor)
    try:
        return await loc.count() > 0 and await loc.first.is_visible()
    except Exception:  # noqa: BLE001
        return False


async def text(page: Page, selektor: str) -> str:
    loc = page.locator(selektor)
    return (await loc.first.inner_text()).strip() if await loc.count() else ""


async def zustand(page: Page) -> dict:
    """Serverzustand im Browser – nur als Zusatzbeleg, nie als Nachweis allein."""
    return await page.evaluate("() => typeof zustand !== 'undefined' && zustand ? zustand : null") or {}


# --- Sichtbarkeitsmatrix ---------------------------------------------------------------------------------------------
async def vertrag_pruefen(page: Page, phase: str, geraet: str, stufe: str, lauf: Lauf) -> None:
    block = VERTRAG["bereiche"].get(phase, {}).get(geraet)
    if not block:
        return
    teile = [block.get("alle", {}), block.get(stufe, {})]
    pflicht = [s for t in teile for s in t.get("pflicht", [])]
    verboten = [s for t in teile for s in t.get("verboten", [])]
    erlaubt = set(pflicht) | {s for t in teile for s in t.get("erlaubt", [])}
    seite = "abschluss" if phase == "abschluss" and geraet == "desktop" else geraet  # Handy bleibt auf handy.html
    kandidaten = VERTRAG["bereiche"]["kandidaten"].get(seite, [])
    fehlend = [s for s in pflicht if not await sichtbar(page, s)]
    zu_viel = [s for s in verboten if await sichtbar(page, s)]
    ueberzaehlig = [s for s in kandidaten if s not in erlaubt and s not in verboten and await sichtbar(page, s)]
    detail = "; ".join(x for x in (
        f"fehlt: {', '.join(fehlend)}" if fehlend else "",
        f"sichtbar, aber in dieser Phase nicht gewollt: {', '.join(zu_viel)}" if zu_viel else "",
        f"überzählig: {', '.join(ueberzaehlig)}" if ueberzaehlig else "") if x)
    lauf.pruefen(f"Sichtbarkeit {phase} · {geraet}", not (fehlend or zu_viel or ueberzaehlig),
                 detail or "Pflicht sichtbar, nichts Unerwünschtes", abweichung=f"sichtbarkeit_{phase}_{geraet}")


async def kernknoepfe_pruefen(page: Page, geraet: str, lauf: Lauf) -> None:
    sel = VERTRAG["kernknoepfe_selektor"][geraet]
    loc = page.locator(sel)
    sichtbare = []
    for i in range(await loc.count()):
        k = loc.nth(i)
        if await k.is_visible():
            sichtbare.append(((await k.get_attribute("data-knopf")) or "",
                              (await k.locator(".aktion-name").first.inner_text()).strip(), await k.bounding_box()))
    soll = [(k["knopf"], k["beschriftung"]) for k in VERTRAG["kernknoepfe"]]
    ist = [(k, b) for k, b, _ in sichtbare]
    lauf.pruefen(f"Fünf Kernknöpfe in Reihenfolge und Beschriftung ({geraet})", ist == soll,
                 f"ist={[b for _, b in ist]}")
    hoehen = [b["height"] for *_, b in sichtbare if b]
    if hoehen:
        lauf.pruefen(f"Kernknöpfe gleich hoch und kompakt ({geraet})", max(hoehen) - min(hoehen) < 2 and max(hoehen) <= 90,
                     f"Höhen {[round(h) for h in hoehen]}")
    for s in VERTRAG["nachgeordnet"][geraet]:
        loc = page.locator(s)
        if await loc.count():
            lauf.pruefen(f"Nachgeordnet unter „Weitere Aktionen“: {s.split('[')[-1].rstrip(']') if '[' in s else s}",
                         not await loc.first.is_visible(), "zugeklappt nicht sichtbar")


# --- Ablauf ----------------------------------------------------------------------------------------------------------
async def anmelden(page: Page, url: str, passwort: str, lauf: Lauf) -> None:
    lauf.schritt("Anmelden über die Worker-Anmeldeseite")
    await page.goto(url, wait_until="domcontentloaded")
    if "anmelden" in page.url and not await page.locator('input[name="passwort"]').count():
        await page.goto(url.rstrip("/") + "/anmelden?alt=1", wait_until="domcontentloaded")
    feld = page.locator('input[name="passwort"]')
    if not await feld.count():
        lauf.pruefen("Anmeldeseite des Workers erscheint", False, f"URL {page.url}")
        raise Abbruch("Keine Anmeldeseite – läuft der Worker davor?")
    await feld.fill(passwort)
    await page.get_by_role("button", name=re.compile("Anmelden", re.I)).click()
    await page.wait_for_load_state("domcontentloaded")
    ok = not await page.locator('input[name="passwort"]').count() and "falsch" not in page.url
    lauf.pruefen("Login mit Testpasswort über den Worker", ok, page.url.split("?")[0])
    if not ok:
        raise Abbruch("Testpasswort abgewiesen")


async def stufe_waehlen(page: Page, stufe: str, lauf: Lauf) -> None:
    lauf.schritt(f"Stufe {stufe} auf der Startseite wählen")
    await page.locator("#karte-basis").wait_for(state="visible", timeout=20_000)
    await vertrag_pruefen(page, "start", "desktop", stufe, lauf)
    await lauf.bild(page, "start")
    karte = page.locator(f"#karte-{stufe}")
    if await karte.is_disabled():
        lauf.pruefen(f"Startkarte {stufe} wählbar", False, "deaktiviert – Schlüssel am Server fehlt?")
        raise Abbruch("Startkarte deaktiviert")
    await karte.click()
    await page.wait_for_url("**/meeting", timeout=20_000)
    pill_ok = await warte(page, f"() => (document.getElementById('modus-pill')?.textContent || '').toLowerCase()"
                                f".includes({json.dumps(stufe)})", 20)
    lauf.pruefen("Stufe sichtbar in der Pill (Desktop)", pill_ok, await text(page, "#modus-pill"))
    await page.reload(wait_until="domcontentloaded")
    pill_ok = await warte(page, f"() => (document.getElementById('modus-pill')?.textContent || '').toLowerCase()"
                                f".includes({json.dumps(stufe)})", 20)
    lauf.pruefen("Stufe nach Reload unverändert", pill_ok, await text(page, "#modus-pill"))


async def agenda_text(page: Page, lauf: Lauf) -> None:
    lauf.schritt("Agenda per Text")
    feld = page.locator("#agenda-feld")
    await feld.wait_for(state="visible", timeout=20_000)
    await feld.fill("Wir möchten etwas besprechen.")
    await page.locator("#agenda-senden").click()
    fertig = await warte(page, "() => document.getElementById('agenda-senden')?.textContent.trim() === 'Absenden' && "
                               "!document.getElementById('agenda-antwort')?.hidden", 60)
    rueck = await text(page, "#agenda-antwort")
    lauf.pruefen("Unklare Agenda-Eingabe → sichtbare Rückfrage", fertig and rueck.startswith("Rückfrage:"), rueck[:120])
    await feld.fill(DREHBUCH["audio"]["agenda_satz"])
    await feld.press("Enter")
    soll = next(r["antwort"] for r in DREHBUCH["chat"] if r["id"] == "agenda_entwurf")
    fertig = await warte(page, f"() => document.getElementById('f-titel')?.value === {json.dumps(soll['titel'])}", 60)
    titel = await page.locator("#f-titel").input_value()
    punkte = [await page.locator('#agenda-tabelle .agenda-zeile input[placeholder="Punkt"]').nth(i).input_value()
              for i in range(await page.locator("#agenda-tabelle .agenda-zeile").count())]
    lauf.pruefen("Agenda-Entwurf per Text übernommen (Titel und Punkte aus der Antwort)",
                 fertig and punkte == [p["titel"] for p in soll["punkte"]], f"Titel={titel!r}, Punkte={punkte}")
    await lauf.bild(page, "agenda_text")


async def sprechknopf_halten(page: Page, selektor: str, sekunden: float, lauf: Lauf, name: str) -> bool:
    """Bedienmodell laut Vertrag: halten, sprechen, loslassen – mit Rückmeldung während des Haltens."""
    modell = VERTRAG["sprechknoepfe"]
    knopf = page.locator(selektor)
    await knopf.wait_for(state="visible", timeout=15_000)
    box = await knopf.bounding_box()
    if not box:
        lauf.pruefen(f"{name}: Knopf bedienbar", False, "keine Fläche")
        return False
    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    await page.mouse.down()
    rueck = await warte(page, f"() => document.querySelector({json.dumps(selektor)})?.classList.contains("
                              f"{json.dumps(modell['rueckmeldung_klasse'])})", 5)
    hinweis = ""
    for kandidat in ("#agenda-antwort", "#taste-text", "#fragen-text"):
        if await sichtbar(page, kandidat) and modell["rueckmeldung_text"] in await text(page, kandidat):
            hinweis = await text(page, kandidat)
    await asyncio.sleep(sekunden)
    await page.mouse.up()
    lauf.pruefen(f"{name}: Bedienmodell „{modell['bedienmodell']}“ mit Rückmeldung beim Halten",
                 rueck and bool(hinweis), f"Klasse {modell['rueckmeldung_klasse']}={rueck}, Text={hinweis[:60]!r}",
                 abweichung="bedienmodell_sprechknoepfe")
    # #66: loslassen → „haelt“ weg, sichtbar „verarbeitet“ oder schon Ergebnis/Fehler (nicht mehr der Haltetext)
    sel, klasse, haltetext = json.dumps(selektor), json.dumps(modell["rueckmeldung_klasse"]), json.dumps(modell["rueckmeldung_text"])
    los = await warte(page, f"""() => {{
        const k = document.querySelector({sel}); if (!k || k.classList.contains({klasse})) return false;
        if (k.classList.contains('verarbeitet')) return true;
        return ['#agenda-antwort', '#taste-text', '#fragen-text'].some((s) => {{
          const e = document.querySelector(s); return e && e.offsetParent && e.textContent.trim()
            && !e.textContent.includes({haltetext}); }});
      }}""", 5)
    lauf.pruefen(f"{name}: nach dem Loslassen sichtbare Verarbeitung oder Rückmeldung", los,
                 abweichung="bedienmodell_sprechknoepfe")
    return rueck


async def agenda_sprache(page: Page, lauf: Lauf) -> None:
    lauf.schritt("Agenda per Sprache (Agenda-Mikro wie jeden Sprechknopf bedienen)")
    vorher = await page.locator("#agenda-tabelle .agenda-zeile").count()
    await sprechknopf_halten(page, "#agenda-mikro", 7.5, lauf, "Agenda-Mikro")
    fertig = await warte(page, "() => document.getElementById('agenda-senden')?.textContent.trim() === 'Absenden' && "
                               "(document.getElementById('agenda-antwort')?.textContent || '').length > 0 && "
                               "!(document.getElementById('agenda-antwort')?.textContent || '').startsWith('Agenda wird')", 60)
    antwort = await text(page, "#agenda-antwort")
    zeilen = await page.locator("#agenda-tabelle .agenda-zeile").count()
    lauf.pruefen("Agenda per Sprache verarbeitet (Antwort sichtbar, Tabelle steht)",
                 fertig and zeilen >= 2 and not antwort.startswith(("Fehler", "Mikrofon", "Zum Diktieren", "Zu kurz")),
                 f"Antwort={antwort[:100]!r}, Zeilen {vorher}→{zeilen}")
    await lauf.bild(page, "agenda_sprache")


async def qr_lesen(page: Page, lauf: Lauf) -> str:
    """QR-Code als Bild: Element-Screenshot, weißer Rand, OpenCV-Dekoder."""
    import cv2
    import numpy as np

    lauf.schritt("QR-Code am Desktop als Bild dekodieren")
    await page.locator("#btn-handy-vorbereitung").click()
    qr = page.locator("#hf-qr svg")
    await qr.wait_for(state="visible", timeout=20_000)
    box = await qr.bounding_box()
    breite = float(await qr.get_attribute("width") or 0)
    viewbox = await qr.get_attribute("viewBox")
    lauf.pruefen("QR-Code vollständig dargestellt (skalierbar, nicht beschnitten)",
                 bool(box) and (bool(viewbox) or box["width"] >= breite - 1),
                 f"viewBox={viewbox!r}, SVG-Breite {breite:.0f}, angezeigt {box['width'] if box else 0:.0f} px")
    png = await qr.screenshot()
    (lauf.ordner / "qr.png").write_bytes(png)
    bild = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    bild = cv2.copyMakeBorder(bild, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    url, _, _ = cv2.QRCodeDetector().detectAndDecode(bild)
    if not url:
        url, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.resize(bild, None, fx=2, fy=2,
                                                                    interpolation=cv2.INTER_NEAREST))
    from urllib.parse import parse_qs, urlparse

    teile = urlparse(url) if url else None
    q = parse_qs(teile.query) if teile else {}
    lauf.belege["qr"] = {"schema": teile.scheme if teile else None, "pfad": teile.path if teile else None,
                         "parameter": sorted(q)}  # Werte nicht speichern: Kopplungsdaten
    lauf.pruefen("QR-Bild dekodiert: /handy mit Kopplungscode und Meeting", bool(url) and teile.path == "/handy"
                 and "k" in q and "meeting" in q, f"Parameter {sorted(q)}")
    if not url:
        raise Abbruch("QR-Code nicht lesbar – ohne dekodiertes Bild kein Handy-Weg")
    return url


async def handy_koppeln(handy_browser: Browser, url: str, stufe: str, lauf: Lauf, video: Path):
    lauf.schritt("Handy öffnet die dekodierte QR-Adresse (ohne Login)")
    ctx = await handy_browser.new_context(**HANDY, ignore_https_errors=True, record_video_dir=str(video),
                                          record_video_size={"width": 390, "height": 844})
    await ctx.add_init_script(TON_SKRIPT)
    handy = await ctx.new_page()
    handy.on("pageerror", lambda e: lauf.belege.setdefault("js_fehler_handy", []).append(str(e)[:200]))
    await handy.goto(url, wait_until="domcontentloaded")
    seite = await handy.content()
    lauf.pruefen("QR führt nicht zu „Kein Meeting zugeordnet“", "Kein Meeting zugeordnet" not in seite,
                 handy.url.split("?")[0])
    gekoppelt = await warte(handy, "() => !document.getElementById('app')?.hidden", 30)
    lauf.pruefen("Handy gekoppelt (App sichtbar, keine Code-Eingabe)", gekoppelt)
    if not gekoppelt:
        await lauf.bild(handy, "handy_nicht_gekoppelt")
        raise Abbruch("Handy nicht gekoppelt")
    pill = await warte(handy, f"() => (document.getElementById('modus')?.textContent || '').toLowerCase()"
                              f".includes({json.dumps(stufe)})", 15)
    lauf.pruefen("Stufe sichtbar in der Pill (Handy)", pill, await text(handy, "#modus"))
    return ctx, handy


async def start_gesperrt(page: Page, lauf: Lauf) -> None:
    gesperrt = await page.locator("#btn-start").is_disabled()
    lauf.pruefen("Kein Start ohne gekoppeltes Handy mit Mikro und Ton", gesperrt, await text(page, "#btn-start"))


async def handy_mikro(page: Page, handy: Page, lauf: Lauf) -> None:
    lauf.schritt("Am Handy „Mikrofon und Ton aktivieren“ tippen")
    await vertrag_pruefen(handy, "vorbereitung", "handy", lauf.stufe, lauf)
    await lauf.bild(handy, "handy_vorbereitung")
    await handy.locator("#btn-mikro").tap()
    t0 = time.monotonic()
    frei = await warte(page, "() => !document.getElementById('btn-start')?.disabled", 10)
    lauf.pruefen("„Meeting starten“ wird ≤ 10 s nach Mikro/Ton am Handy klickbar", frei,
                 f"{time.monotonic() - t0:.1f} s, Knopf: {await text(page, '#btn-start')!r}")
    if not frei:
        await lauf.bild(handy, "handy_mikro_fehler")
        raise Abbruch("Start bleibt gesperrt")


async def zweites_handy(handy_browser: Browser, url: str, lauf: Lauf) -> None:
    lauf.schritt("Zweites Handy mit demselben QR-Code")
    ctx = await handy_browser.new_context(**HANDY, ignore_https_errors=True)
    zweit = await ctx.new_page()
    await zweit.goto(url, wait_until="domcontentloaded")
    if await warte(zweit, "() => !document.getElementById('app')?.hidden", 15):
        mikro = zweit.locator("#btn-mikro")
        try:  # die Abweisung kann schon vor dem Tippen kommen (dann verschwindet der Knopf mitten im Tippen)
            if await mikro.is_visible():
                await mikro.tap(timeout=5000)
        except Exception:  # noqa: BLE001
            pass
    abgewiesen = await warte(zweit, "() => (document.getElementById('koppeln-falsch')?.textContent || '')"
                                    ".includes('Anderes Handy') || (document.getElementById('status')?.textContent || '')"
                                    ".includes('Anderes Handy')", 15)
    lauf.pruefen("Genau ein Handy: zweites wird sichtbar abgewiesen", abgewiesen, await text(zweit, "#status"))
    await lauf.bild(zweit, "zweites_handy")
    await ctx.close()


async def meeting_starten(page: Page, handy: Page, lauf: Lauf) -> None:
    lauf.schritt("Meeting starten (Desktop-Klick)")
    await vertrag_pruefen(page, "vorbereitung", "desktop", lauf.stufe, lauf)
    await lauf.bild(page, "vorbereitung")
    await page.locator("#btn-start").click()
    live = await warte(page, "() => !document.getElementById('live')?.hidden", 30)
    fehler = await text(page, "#start-fehler") if await sichtbar(page, "#start-fehler") else ""
    lauf.pruefen("Live-Phase nach Klick auf „Meeting starten“", live, fehler)
    if not live:
        await lauf.bild(page, "start_fehler")
        raise Abbruch("Meeting nicht gestartet")
    await asyncio.sleep(2)
    await vertrag_pruefen(page, "live", "desktop", lauf.stufe, lauf)
    await kernknoepfe_pruefen(page, "desktop", lauf)
    await warte(handy, "() => !document.getElementById('h-nestor-karte')?.hidden", 10)
    await vertrag_pruefen(handy, "live", "handy", lauf.stufe, lauf)
    await kernknoepfe_pruefen(handy, "handy", lauf)
    await lauf.bild(page, "live")
    await lauf.bild(handy, "handy_live")


async def ton_abwarten(handy: Page, lauf: Lauf, name: str, sekunden: float = 40) -> None:
    """Wartet, bis am Handy etwas klang (Begrüßung/Antwort), dann bis 2 s Ruhe – lesend über das Ton-Protokoll."""
    t0 = time.monotonic()
    gehoert = False
    while time.monotonic() - t0 < sekunden:
        log = await handy.evaluate("() => (window.__tonLog || []).length ? window.__tonLog[window.__tonLog.length-1].t : 0")
        jetzt = await handy.evaluate("() => Date.now()")
        if log:
            gehoert = True
            if jetzt - log > 2000:
                break
        await asyncio.sleep(0.5)
    lauf.belege.setdefault("ton_warten", []).append({"schritt": name, "gehoert": gehoert,
                                                    "s": round(time.monotonic() - t0, 1)})


async def kernknopf(page: Page, art: str, soll: str, lauf: Lauf, sekunden: float = 60) -> None:
    beschriftung = next(k["beschriftung"] for k in VERTRAG["kernknoepfe"] if k["knopf"] == art)
    knopf = page.locator(f'#knopf-leiste [data-knopf="{art}"]')
    frei = await warte(page, f"() => !document.querySelector('#knopf-leiste [data-knopf=\"{art}\"]')?.disabled", 60)
    if not frei:
        lauf.pruefen(f"Kernknopf {beschriftung}", False, "blieb gesperrt")
        return
    await knopf.click()
    da = await warte(page, f"() => (document.getElementById('vl-buehne')?.innerText || '').includes({json.dumps(soll)})",
                     sekunden)
    lauf.pruefen(f"Kernknopf {beschriftung}: Karte mit Sollinhalt „{soll}“", da,
                 "" if da else (await text(page, "#vl-buehne"))[:160])
    await lauf.bild(page, f"knopf_{art}")


async def transkript_pruefen(page: Page, lauf: Lauf, sekunden: float = 120) -> None:
    lauf.schritt("Sprache über das Fake-Mikro des Handys, sichtbares Transkript")
    saetze = DREHBUCH["audio"]["meeting_saetze"]
    await page.locator("#btn-transkript").click()
    letzter = json.dumps(saetze[-1][:30])
    da = await warte(page, f"() => (document.getElementById('transkript')?.innerText || '').includes({letzter})", sekunden)
    t = await text(page, "#transkript")
    fehlend = [s[:30] for s in saetze if s[:30] not in t]
    lauf.pruefen("Alle Drehbuchsätze im sichtbaren Transkript", da and not fehlend, f"fehlend: {fehlend}" if fehlend else "")
    await lauf.bild(page, "transkript")
    await page.locator("#leiste-zu").click()


async def beenden_und_abschluss(page: Page, lauf: Lauf, download: Path) -> None:
    lauf.schritt("Beenden → Abschluss")
    await page.locator("#btn-stopp").click()
    await page.wait_for_url("**/abschluss", timeout=30_000)
    await page.locator("#ab-inhalt").wait_for(state="visible", timeout=30_000)
    await asyncio.sleep(1)
    await vertrag_pruefen(page, "abschluss", "desktop", lauf.stufe, lauf)
    lagen = []
    for s in VERTRAG["abschluss_reihenfolge"]:
        loc = page.locator(s)
        if await loc.count() and await loc.first.is_visible():
            lagen.append((s, (await loc.first.bounding_box())["y"]))
    ist = [s for s, _ in sorted(lagen, key=lambda x: x[1])]
    soll = [s for s in VERTRAG["abschluss_reihenfolge"] if s in ist]
    lauf.pruefen("Abschlussreihenfolge Datenspende → Unterstützung → Protokoll → Paket", ist == soll,
                 f"ist: {' → '.join(ist)}", abweichung="abschluss_reihenfolge")
    await lauf.bild(page, "abschluss")
    paket = page.locator("#btn-paket")
    frei = await warte(page, "() => !document.getElementById('btn-paket')?.disabled", 240)
    if not frei:
        lauf.pruefen("Paket herunterladbar", False, "Knopf blieb gesperrt")
        return
    async with page.expect_download() as dl:
        await paket.click()
    datei = await dl.value
    ziel = download / "protokoll.zip"
    await datei.save_as(str(ziel))
    with zipfile.ZipFile(ziel) as z:
        namen = set(z.namelist())
        technik = json.loads(z.read("technik.json")) if "technik.json" in namen else {}
        protokoll = z.read("meeting.md").decode("utf-8", "replace") if "meeting.md" in namen else ""
        transkript = z.read("transkript.md").decode("utf-8", "replace") if "transkript.md" in namen else ""
    pflicht = {"meeting.md", "transkript.md", "agenda.md", "technik.json"}
    lauf.pruefen("ZIP enthält Pflichtdateien", pflicht <= namen, f"fehlt: {sorted(pflicht - namen)}")
    lauf.belege["technik_json_stufe"] = {k: technik.get(k) for k in ("stufe", "anbieter") if k in technik}
    lauf.pruefen("technik.json nennt die gewählte Stufe", lauf.stufe in json.dumps(technik, ensure_ascii=False).lower(),
                 json.dumps(lauf.belege["technik_json_stufe"], ensure_ascii=False))
    lauf.pruefen("Protokoll enthält Beschluss (9.000 €) und Aufgabe (Sabine, Freitag)",
                 bool(re.search(r"9\.?000", protokoll)) and "Sabine" in protokoll and "Freitag" in protokoll)
    lauf.pruefen("Transkript im ZIP enthält die Drehbuchsätze",
                 all(s[:30] in transkript for s in DREHBUCH["audio"]["meeting_saetze"]))

    lauf.schritt("Datenspende mit Feedback")
    await page.locator("#sp-einverstanden").check()
    await page.locator("#fb-text").fill("E2E-Feedback: alles klickbar.")
    frei = await warte(page, "() => !document.getElementById('btn-spende')?.disabled", 60)
    if frei:
        await page.locator("#btn-spende").click()
    gespeichert = await warte(page, "() => (document.getElementById('btn-spende')?.textContent || '').includes('gespeichert')", 60)
    lauf.pruefen("Datenspende über den Worker gespeichert", gespeichert, await text(page, "#sp-danke"))
    await lauf.bild(page, "datenspende")


async def ton_auswerten(handy: Page, stufe: str, lauf: Lauf) -> None:
    """Fingerabdruck: Premium darf am Handy nur OpenAI-Tonhöhe (440 Hz) hören, Basis nur Mistral (660 Hz)."""
    tts = DREHBUCH["tts"]
    soll, fremd = (tts["openai_hz"], tts["mistral_hz"]) if stufe == "premium" else (tts["mistral_hz"], tts["openai_hz"])
    log = await handy.evaluate("() => window.__tonLog || []")
    (lauf.ordner / "ton_handy.json").write_text(json.dumps(log), encoding="utf-8")
    nahe = lambda hz, ziel: abs(hz - ziel) <= 15  # noqa: E731
    n_soll = sum(1 for e in log if nahe(e["hz"], soll))
    n_fremd = sum(1 for e in log if nahe(e["hz"], fremd))
    lauf.belege["ton_fingerabdruck"] = {"messungen": len(log), f"{soll}Hz": n_soll, f"{fremd}Hz": n_fremd}
    lauf.pruefen(f"Handy hört die Tonhöhe der Stufe ({soll} Hz)", n_soll > 0, f"{n_soll} von {len(log)} Messungen")
    lauf.pruefen(f"Handy hört nie die fremde Tonhöhe ({fremd} Hz)", n_fremd == 0, f"{n_fremd} Messungen")


def fake_regeln(lauf: Lauf) -> list[str]:
    """Welche Drehbuch-Regeln die Fakes bisher beantwortet haben (beide Anbieter, in Reihenfolge)."""
    aus = []
    for name in ("openai", "mistral"):
        p = lauf.ordner / "fakes" / f"anfragen_{name}.jsonl"
        if p.exists():
            aus += [json.loads(z) for z in p.read_text(encoding="utf-8").splitlines()]
    return [e["regel"] for e in sorted(aus, key=lambda e: e["t"]) if e.get("regel")]


async def ansprache_pruefen(page: Page, lauf: Lauf) -> None:
    """„Nestor, …“ im Mikrofon-Ton: Premium antwortet hörbar (Realtime) mit Karte, Basis ignoriert es (Funkgerät)."""
    karte = "Sommerfest-Budget beschlossen"
    if lauf.stufe == "premium":
        da = await warte(page, f"() => (document.getElementById('vl-buehne')?.innerText || '').includes({json.dumps(karte)})", 60)
        regeln = fake_regeln(lauf)
        lauf.pruefen("Premium: Ansprache „Nestor, …“ per Sprache beantwortet (Realtime) mit Karte",
                     da and "ansprache_budget" in regeln, f"Karte={da}, Realtime-Antwort={'ansprache_budget' in regeln}")
        await lauf.bild(page, "ansprache_premium")
    else:
        await asyncio.sleep(8)  # Zeit, in der eine (falsche) Antwort käme
        regeln = fake_regeln(lauf)
        geantwortet = [r for r in regeln if r in ("assistent_antwort", "karte_budget", "karte_zur_antwort", "ansprache_budget")]
        sichtbar_ = karte in await text(page, "#vl-buehne")
        lauf.pruefen("Basis: Ansprache „Nestor, …“ ohne Sprechtaste bleibt unbeantwortet", not geantwortet and not sichtbar_,
                     f"Antwort-Regeln {geantwortet}, Karte={sichtbar_}")


async def sprechtaste_wirkung(page: Page, lauf: Lauf) -> None:
    da = await warte(page, "() => (document.getElementById('vl-buehne')?.innerText || '').includes('Antwort: Wer liefert die Fahrten')", 60)
    regeln = fake_regeln(lauf)
    lauf.pruefen("Sprechtaste wirkt: Frage transkribiert, beantwortet und als Karte sichtbar",
                 da and "assistent_antwort" in regeln, f"Karte={da}, Antwort-Regel={'assistent_antwort' in regeln}")
    await lauf.bild(page, "sprechtaste")


async def sprechtaste_handy(handy: Page, stufe: str, lauf: Lauf) -> None:
    """#66: Basis – große Sprechtaste als Hauptbedienung, gleiches Bedienmodell; Premium – nachgeordnet (Telefon)."""
    lauf.schritt("Sprechtaste am Handy je Stufe")
    knopf = next(k for k in VERTRAG["sprechknoepfe"]["knoepfe"] if k["id"] == "btn-fragen")
    soll = knopf["darstellung"][stufe]
    nachgeordnet = await handy.locator("#h-nestor-karte .zusatz-aktionen #btn-fragen").count() == 1
    if soll == "haupt":
        box = await handy.locator("#btn-fragen").bounding_box() if await sichtbar(handy, "#btn-fragen") else None
        lauf.pruefen("Basis: Sprechtaste am Handy ist große Hauptbedienung", bool(box) and not nachgeordnet
                     and box["height"] >= 48, f"sichtbar={bool(box)}, Höhe={box['height'] if box else 0:.0f}, "
                     f"nachgeordnet={nachgeordnet}")
        frei = await warte(handy, "() => !document.getElementById('btn-fragen')?.disabled", 40)
        if not frei:
            lauf.pruefen("Sprechtaste (Handy): bedienbar", False, "blieb gesperrt")
            return
        await sprechknopf_halten(handy, "#btn-fragen", 0.2, lauf, "Sprechtaste (Handy)")
    else:
        lauf.pruefen("Premium: Sprechtaste am Handy nachgeordnet unter „Weitere Aktionen“",
                     nachgeordnet and not await sichtbar(handy, "#btn-fragen"), f"nachgeordnet={nachgeordnet}")
    m = await handy.evaluate("() => { const t = document.getElementById('titel'); return t ? [t.clientWidth, "
                             "t.scrollWidth, t.clientHeight, t.scrollHeight, t.textContent] : [0, 0, 0, 0, '']; }")
    lauf.pruefen("Handy-Kopfleiste: Meeting-Titel nicht abgeschnitten",
                 m[0] >= 150 and m[1] <= m[0] + 1 and m[3] <= m[2] + 1,
                 f"{m[4]!r}: Breite {m[0]}/{m[1]} px, Höhe {m[2]}/{m[3]} px")
    await lauf.bild(handy, "handy_sprechtaste")


async def handy_abschluss(handy: Page, lauf: Lauf) -> None:
    lauf.schritt("Handy nach dem Ende (Phase Abschluss)")
    await warte(handy, "() => document.body.dataset.phase === 'abschluss'", 20)
    await vertrag_pruefen(handy, "abschluss", "handy", lauf.stufe, lauf)
    await lauf.bild(handy, "handy_abschluss")
