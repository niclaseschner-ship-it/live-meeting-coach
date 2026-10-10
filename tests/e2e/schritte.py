"""Schrittfunktionen der Klick-E2E (Ticket #61) – herausgehoben aus scripts/pilot_ui_abnahme.py und erweitert.

Regeln für alles hier:
- **Aktionen nur per Klick, Tippen, Tastatur, Maus** (`click`, `tap`, `fill`, `keyboard`, `mouse`). Kein
  `page.evaluate` für Aktionen, kein direkter API-Aufruf, keine Zustandsinjektion.
- `page.evaluate` nur **lesend** für Belege (Ton-Fingerabdruck, Serverzustand als Zusatzbeleg).
- Der QR-Code wird als **Bild** gelesen (Screenshot + OpenCV), nicht aus dem `<a href>` daneben.
- Sichtbarkeit, Reihenfolge und Bedienmodell kommen aus `szenarien/ui_vertrag.json`. Weicht der Code ab und steht
  die Prüfung in `bekannte_abweichungen`, wird sie als `bekannt_rot` mit Ticket gemeldet, nicht verschwiegen.

Dieselben Funktionen fahren Stufe C (Ticket #62, echte Anbieter auf Staging, tests/e2e/lauf_c.py); der Unterschied
liegt nur im Lauf: `Lauf(echt=True)` prüft gegen Sollfragmente (Regex aus drehbuch.json → audio_c.sollfragmente)
statt gegen die wörtlichen Antworten der Fakes, und es kommen Prüfungen dazu, die nur mit echten Modellen Sinn haben
(Monolog live, Imperativ, Anbieterprotokoll der Hostwache, Kostendeckel je Lauf).
"""

from __future__ import annotations

import asyncio
import contextlib
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
SOLL_C = DREHBUCH["audio_c"]["sollfragmente"]
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
    def __init__(self, ordner: Path, stufe: str, rauch: bool, echt: bool = False) -> None:
        self.ordner = ordner
        (ordner / "screenshots").mkdir(parents=True, exist_ok=True)
        self.stufe = stufe
        self.rauch = rauch
        self.echt = echt  # Stufe C: echte Modelle, Sollfragmente statt wörtlicher Fake-Antworten
        self.dialoge_annehmen = False  # Bestätigungsdialoge (confirm) sonst abbrechen – nur „Abschließen“ nimmt an
        self.t_mikro: float | None = None  # monotonic beim Tippen auf „Mikrofon und Ton“ – Start der Handy-WAV
        self.start = time.monotonic()
        self.gestartet = datetime.now().astimezone()
        self.pruefungen: list[dict] = []
        self.screenshots: list[str] = []
        self.belege: dict = {"stufe": stufe, "rauch": rauch, "echt": echt, "gestartet": self.gestartet.isoformat()}
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
        kosten = (f"<h2>Kosten (Kostenzähler der App)</h2><pre>{html.escape(json.dumps(self.belege['kosten'], ensure_ascii=False, indent=2))}</pre>"
                  if "kosten" in self.belege else "")
        (self.ordner / "bericht.html").write_text(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>Klick-E2E {'C' if self.echt else 'B'} {html.escape(self.stufe)}</title>"
            "<style>body{font:15px system-ui;margin:24px auto;max-width:1100px;padding:0 16px;color:#182033}"
            "table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #ddd;"
            "vertical-align:top}img,video{max-width:100%;border:1px solid #ddd}figure{margin:24px 0}"
            "figcaption{font-weight:600}pre{background:#f1f5f9;padding:12px;overflow:auto}</style>"
            f"<h1>Klick-E2E Stufe {'C (Staging, echte Anbieter)' if self.echt else 'B'} · {html.escape(self.stufe)}"
            f"{' · Rauch' if self.rauch else ''}</h1>"
            f"<p>{self.gestartet:%d.%m.%Y %H:%M} · Dauer {self.belege['dauer_s']} s · "
            + " · ".join(f"{k}: {v}" for k, v in zaehl.items()) + "</p>"
            "<p>ok = erfüllt · fehlt = rot · bekannt_rot = Abweichung vom Auftrag, Ticket offen · offen = in diesem "
            "Lauf nicht geprüft · ausstehend = braucht erst das genannte Ticket.</p>"
            f"<table><tr><th>Status</th><th>Prüfung</th><th>Ticket</th><th>Beleg</th><th>t [s]</th></tr>{zeilen}</table>"
            f"<h2>Anbieterbeweis</h2><pre>{anbieter}</pre>{kosten}<h2>Videos</h2>{filme}<h2>Screenshots</h2>{bilder}",
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


def passt(muster: str, text: str) -> bool:
    """Sollfragment (Regex, Groß/Klein egal) – Stufe C prüft echte Modellausgaben nicht wörtlich."""
    return bool(re.search(muster, text or "", re.IGNORECASE))


async def karten(page: Page) -> list[dict]:
    """Karten des Verlaufs aus dem Dashboard-Zustand (lesend, Zusatzbeleg zur sichtbaren Bühne)."""
    return await page.evaluate("() => (typeof zustand !== 'undefined' && zustand && zustand.karten) || []") or []


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
async def anmelden(page: Page, url: str, mail: str, pin: str, lauf: Lauf) -> None:
    """Ticket #75: kein Passwortweg mehr – Login nur noch über den Mail-PIN-Dialog, per UI-Klicks mit dem
    Testzugang (TESTZUGANG, nur Dev/Staging): Registrierungsformular ausfüllen, „Code anfordern“, PIN eintippen.
    Der Testzugang beantwortet den Code sofort mit dem festen PIN statt einer echten Mail (siehe
    cloudflare/src/pilotzugang.ts, testzugangPinPruefen) – kein Mail-Abruf nötig."""
    lauf.schritt("Anmelden über den Mail-PIN-Dialog (Testzugang)")
    await page.goto(url, wait_until="domcontentloaded")
    name_feld = page.locator('input[name="name"]')
    if not await name_feld.count():
        lauf.pruefen("Registrierungsseite des Workers erscheint", False, f"URL {page.url}")
        raise Abbruch("Keine Registrierungsseite – läuft der Worker davor?")
    await name_feld.fill("E2E Testlauf")
    await page.locator('input[name="email"]').fill(mail)
    await page.locator('textarea[name="herkunft"]').fill("Automatisierte Test-Pipeline")
    await page.locator('input[name="datenschutz"]').check()
    await page.get_by_role("button", name=re.compile("Code anfordern", re.I)).click()
    await page.wait_for_load_state("domcontentloaded")
    pin_feld = page.locator('input[name="pin"]')
    ok = await pin_feld.count() > 0
    lauf.pruefen("Registrierung führt zum PIN-Dialog", ok, page.url.split("?")[0])
    if not ok:
        raise Abbruch("Kein PIN-Feld nach der Registrierung – Testzugang falsch konfiguriert?")
    await pin_feld.fill(pin)
    await page.get_by_role("button", name=re.compile("Anmelden", re.I)).click()
    await page.wait_for_load_state("domcontentloaded")
    ok = not await page.locator('input[name="pin"]').count() and not page.url.rstrip("/").endswith("/pin")
    lauf.pruefen("Login über den Mail-PIN-Dialog mit dem Testzugang", ok, page.url.split("?")[0])
    if not ok:
        raise Abbruch("Testzugang-PIN abgewiesen")


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
    if lauf.echt:
        # Echtes Modell: die Startseite bringt schon einen Entwurf mit – „etwas besprechen“ darf eine Rückfrage oder
        # ein begründetes Beibehalten sein; rot nur bei Fehler oder Stille
        lauf.pruefen("Unklare Agenda-Eingabe → sichtbare Antwort (Rückfrage oder Begründung, kein Fehler)",
                     fertig and bool(rueck) and not rueck.startswith(("Fehler", "Agenda wird")), rueck[:120])
    else:
        lauf.pruefen("Unklare Agenda-Eingabe → sichtbare Rückfrage", fertig and rueck.startswith("Rückfrage:"), rueck[:120])
    await feld.fill(DREHBUCH["audio"]["agenda_satz"])
    await feld.press("Enter")
    if lauf.echt:
        # echtes Modell: Titel nicht vorhersagbar – Tabelle muss beide Punkte aus dem Satz tragen
        muster = json.dumps(SOLL_C["agenda_punkte"])
        fertig = await warte(page, f"""() => {{
            const punkte = [...document.querySelectorAll('#agenda-tabelle .agenda-zeile input[placeholder="Punkt"]')]
              .map((e) => e.value);
            return document.getElementById('agenda-senden')?.textContent.trim() === 'Absenden'
              && {muster}.every((m) => punkte.some((p) => new RegExp(m, 'i').test(p)));
          }}""", 90)
    else:
        soll = next(r["antwort"] for r in DREHBUCH["chat"] if r["id"] == "agenda_entwurf")
        fertig = await warte(page, f"() => document.getElementById('f-titel')?.value === {json.dumps(soll['titel'])}", 60)
    titel = await page.locator("#f-titel").input_value()
    punkte = [await page.locator('#agenda-tabelle .agenda-zeile input[placeholder="Punkt"]').nth(i).input_value()
              for i in range(await page.locator("#agenda-tabelle .agenda-zeile").count())]
    if lauf.echt:
        ok = fertig and all(any(passt(m, p) for p in punkte) for m in SOLL_C["agenda_punkte"])
    else:
        ok = fertig and punkte == [p["titel"] for p in soll["punkte"]]
    lauf.pruefen("Agenda-Entwurf per Text übernommen (Titel und Punkte aus der Antwort)", ok,
                 f"Titel={titel!r}, Punkte={punkte}")
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
    # Liegt die Knopfmitte unter einem anderen Element (am Handy die klebende Kopfleiste mit Titel/Live/Stufe – im
    # dritten und vierten C-Lauf lag die Taste genau darunter), wie ein Mensch erst scrollen (Mausrad), dann drücken.
    # Nur lesend geprüft (elementFromPoint), bedient wird mit der Maus.
    oben = f"(p) => document.elementFromPoint(p[0], p[1])?.closest({json.dumps(selektor)}) !== null"
    for _ in range(3):
        mitte = [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2]
        if await page.evaluate(oben, mitte):
            break
        hoehe = (page.viewport_size or {"height": 800})["height"]
        await page.mouse.move(mitte[0], hoehe / 2)
        await page.mouse.wheel(0, mitte[1] - hoehe / 2)
        await asyncio.sleep(0.4)
        box = await knopf.bounding_box() or box
        lauf.belege.setdefault("sprechknopf_gescrollt", []).append(name)
    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    await page.mouse.down()
    haelt = (f"() => document.querySelector({json.dumps(selektor)})?.classList.contains("
             f"{json.dumps(modell['rueckmeldung_klasse'])})")
    rueck = await warte(page, haelt, 5)
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


async def agenda_sprache(page: Page, lauf: Lauf, sekunden: float = 7.5) -> None:
    """sekunden: Haltedauer – Stufe C hält bis nach dem Satzende der Agenda-WAV (echte Transkription)."""
    lauf.schritt("Agenda per Sprache (Agenda-Mikro wie jeden Sprechknopf bedienen)")
    vorher = await page.locator("#agenda-tabelle .agenda-zeile").count()
    await sprechknopf_halten(page, "#agenda-mikro", sekunden, lauf, "Agenda-Mikro")
    fertig = await warte(page, "() => document.getElementById('agenda-senden')?.textContent.trim() === 'Absenden' && "
                               "(document.getElementById('agenda-antwort')?.textContent || '').length > 0 && "
                               "!(document.getElementById('agenda-antwort')?.textContent || '').startsWith('Agenda wird')",
                         90 if lauf.echt else 60)
    antwort = await text(page, "#agenda-antwort")
    zeilen = await page.locator("#agenda-tabelle .agenda-zeile").count()
    lauf.pruefen("Agenda per Sprache verarbeitet (Antwort sichtbar, Tabelle steht)",
                 fertig and zeilen >= 2 and not antwort.startswith(("Fehler", "Mikrofon", "Zum Diktieren", "Zu kurz")),
                 f"Antwort={antwort[:100]!r}, Zeilen {vorher}→{zeilen}")
    await lauf.bild(page, "agenda_sprache")


def qr_dekodieren(png: bytes) -> str:
    """PNG-Bytes → dekodierter QR-Inhalt; probiert Original und 2-/3-fache Skalierung, jeweils mit/ohne Otsu."""
    import cv2
    import numpy as np

    bild = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if bild is None:
        return ""
    bild = cv2.copyMakeBorder(bild, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    detektor = cv2.QRCodeDetector()
    for faktor in (None, 2, 3):
        vorbereitet = bild if faktor is None else cv2.resize(bild, None, fx=faktor, fy=faktor,
                                                             interpolation=cv2.INTER_NEAREST)
        url, _, _ = detektor.detectAndDecode(vorbereitet)
        if url:
            return url
        _, otsu = cv2.threshold(vorbereitet, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        url, _, _ = detektor.detectAndDecode(otsu)
        if url:
            return url
    return ""


async def qr_lesen(page: Page, lauf: Lauf) -> str:
    """QR-Code als Bild: Element-Screenshot(s), weißer Rand, OpenCV-Dekoder – bis zu 3 Versuche."""
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
    url = ""
    letztes_png = None
    for versuch in range(1, 4):
        png = await qr.screenshot()
        letztes_png = png
        url = qr_dekodieren(png)
        if url:
            break
        if versuch < 3:
            await asyncio.sleep(1)
    if letztes_png is not None:
        (lauf.ordner / "qr.png").write_bytes(letztes_png)
    from urllib.parse import parse_qs, urlparse

    teile = urlparse(url) if url else None
    q = parse_qs(teile.query) if teile else {}
    lauf.belege["qr"] = {"schema": teile.scheme if teile else None, "pfad": teile.path if teile else None,
                         "parameter": sorted(q), "versuche": versuch}  # Werte nicht speichern: Kopplungsdaten
    lauf.pruefen("QR-Bild dekodiert: /handy mit Kopplungscode und Meeting", bool(url) and teile.path == "/handy"
                 and "k" in q and "meeting" in q, f"Parameter {sorted(q)}, Versuche {versuch}")
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
    t0 = lauf.t_mikro = time.monotonic()  # ab hier läuft die Fake-Mikro-WAV des Handys (Stufe C: Imperativ-Takt)
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


# Stufe C: welche Kartenart ein Kernknopf erzeugt und welches Sollfragment sie tragen muss (echte Modelle)
KNOPF_KARTE = {"stand": ({"stand"}, r"Sommerfest|Budget|Vereinsbus|Punkt"),
               "zusammenfassen": ({"zusammenfassung"}, r"9[.\s]?000|neuntausend|Budget|Sabine"),
               "fehlt": ({"fehlt"}, r"\w"),
               "protokoll": ({"festgehalten", "protokoll"}, r"Sabine|9[.\s]?000|neuntausend|Budget"),
               "ueberblick": ({"ueberblick", "bild"}, r"Budget|Vereinsbus|Sommerfest|Sabine|Bild")}


async def kernknopf_echt(page: Page, art: str, lauf: Lauf, sekunden: float = 90) -> None:
    """Stufe C: nach dem Klick eine NEUE Karte der passenden Art, sichtbar auf der Bühne, mit Sollfragment."""
    beschriftung = next(k["beschriftung"] for k in VERTRAG["kernknoepfe"] if k["knopf"] == art)
    arten, muster = KNOPF_KARTE[art]
    frei = await warte(page, f"() => !document.querySelector('#knopf-leiste [data-knopf=\"{art}\"]')?.disabled", 90)
    if not frei:
        lauf.pruefen(f"Kernknopf {beschriftung}", False, "blieb gesperrt")
        return
    vorher = max((k.get("id", 0) for k in await karten(page)), default=0)
    await page.locator(f'#knopf-leiste [data-knopf="{art}"]').click()
    t0, neu = time.monotonic(), None
    while time.monotonic() - t0 < sekunden and neu is None:
        neu = next((k for k in await karten(page) if k.get("id", 0) > vorher and k.get("art") in arten), None)
        if neu is None:
            await asyncio.sleep(1)
    titel = (neu or {}).get("titel") or ""
    # Still Geliefertes (Bild, Überblick) springt nur nach vorn, wenn die vordere Karte älter als ~60 s ist – sonst
    # zeigt der Verlauf „1 neues Ergebnis – jetzt ansehen ›“ (static/verlauf.js). Beides ist sichtbar.
    klassen = json.dumps([f"vk-{a}" for a in sorted(arten)])
    sichtbar_ = bool(neu) and await warte(
        page, f"() => {klassen}.some((k) => document.querySelector('#vl-buehne article.' + k)) || "
              "(!!document.getElementById('vl-neu') && !document.getElementById('vl-neu').hidden)", 10)
    inhalt = json.dumps(neu or {}, ensure_ascii=False) + await text(page, "#vl-buehne")
    lauf.pruefen(f"Kernknopf {beschriftung}: neue Karte ({'/'.join(sorted(arten))}) sichtbar mit Sollfragment",
                 bool(neu) and sichtbar_ and passt(muster, inhalt),
                 f"nach {time.monotonic() - t0:.0f} s: {titel[:60]!r}, sichtbar={sichtbar_}" if neu
                 else f"keine neue Karte in {sekunden:.0f} s; Bühne: {(await text(page, '#vl-buehne'))[:120]!r}")
    lauf.belege.setdefault("karten_c", []).append({"knopf": art, "titel": titel[:80],
                                                   "punkte": [str(x)[:80] for x in (neu or {}).get("punkte", [])][:4]})
    await lauf.bild(page, f"knopf_{art}")


async def kernknopf(page: Page, art: str, soll: str, lauf: Lauf, sekunden: float = 60) -> None:
    if lauf.echt:
        await kernknopf_echt(page, art, lauf)
        return
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
    if lauf.echt:
        muster = SOLL_C["meeting_saetze"]
        letzter = json.dumps(muster[-1])
        da = await warte(page, f"() => new RegExp({letzter}, 'i').test(document.getElementById('transkript')?.innerText || '')",
                         sekunden + 30)
        t = await text(page, "#transkript")
        fehlend = [m for m in muster if not passt(m, t)]
        lauf.pruefen("Alle Meeting-Sätze (Sollfragmente) im sichtbaren Transkript", da and not fehlend,
                     f"fehlend: {fehlend}" if fehlend else "")
        await lauf.bild(page, "transkript")
        await page.locator("#leiste-zu").click()
        return
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
        meeting_json = json.loads(z.read("meeting.json")) if "meeting.json" in namen else {}
    pflicht = {"meeting.md", "transkript.md", "agenda.md", "technik.json"}
    lauf.pruefen("ZIP enthält Pflichtdateien", pflicht <= namen, f"fehlt: {sorted(pflicht - namen)}")
    lauf.belege["technik_json_stufe"] = {k: technik.get(k) for k in ("stufe", "anbieter") if k in technik}
    lauf.pruefen("technik.json nennt die gewählte Stufe", lauf.stufe in json.dumps(technik, ensure_ascii=False).lower(),
                 json.dumps(lauf.belege["technik_json_stufe"], ensure_ascii=False))
    if lauf.echt:
        lauf.pruefen("Protokoll enthält Beschluss (9.000 €) und Aufgabe (Sabine, Freitag)",
                     all(passt(SOLL_C[k], protokoll) for k in ("beschluss", "aufgabe", "termin")),
                     "; ".join(f"{k}={passt(SOLL_C[k], protokoll)}" for k in ("beschluss", "aufgabe", "termin")))
        fehlend = [m for m in SOLL_C["meeting_saetze"] + [SOLL_C["monolog"]] if not passt(m, transkript)]
        lauf.pruefen("Transkript im ZIP enthält die Meeting-Sätze und den Monolog (Sollfragmente)", not fehlend,
                     f"fehlend: {fehlend}" if fehlend else "")
        anbieter_soll = "OpenAI" if lauf.stufe == "premium" else "Mistral"
        domain = "openai.com" if lauf.stufe == "premium" else "mistral.ai"
        gesehen = technik.get("gesehene_ziele") or []
        fremd = [g for g in gesehen if not g.get("erlaubt") or not g.get("ziel", "").split(":")[0].endswith(domain)]
        lauf.belege["technik_json_stufe"]["gesehene_ziele"] = gesehen
        lauf.pruefen(f"technik.json: Anbieter {anbieter_soll}, Hostwache sah nur {domain}-Ziele",
                     technik.get("anbieter") == anbieter_soll and bool(gesehen) and not fremd,
                     f"anbieter={technik.get('anbieter')!r}, gesehen={[(g.get('ziel'), g.get('anzahl')) for g in gesehen]}")
        if meeting_json.get("kosten"):
            lauf.belege.setdefault("kosten", {})["zip_meeting_json"] = meeting_json["kosten"]
    else:
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
    if lauf.echt:
        # Echte Stimmen haben keine feste Tonhöhe – der Anbieterbeweis läuft in C über die Hostwache; hier nur:
        # am Handy klang überhaupt Nestors Stimme (Begrüßung, Antworten), gemessen am Ausgang des Lautsprechers.
        sekunden = len(log) / 10
        lauf.belege["ton_handy_s"] = round(sekunden, 1)
        lauf.pruefen("Handy gibt Nestors Stimme hörbar aus (Begrüßung und Antworten)", sekunden >= 5,
                     f"{sekunden:.1f} s Ton am Handy")
        return
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


async def ansprache_pruefen_echt(page: Page, handy: Page, uhr: "Ergebnisuhr", lauf: Lauf) -> None:
    """Stufe C: „Nestor, wie viel Budget …?“ – Premium antwortet hörbar am Handy (Realtime) oder als Karte mit der
    Zahl; Basis (Funkgerät) gibt keine Antwort ohne Sprechtaste."""
    t0 = time.monotonic()
    while "ansprache" not in uhr.satz_wand and time.monotonic() - t0 < 30:
        await asyncio.sleep(1)
    gesagt = uhr.satz_wand.get("ansprache")
    if lauf.stufe == "premium":
        await asyncio.sleep(25)  # Zeit für die gesprochene Antwort
        log = await handy.evaluate("() => window.__tonLog || []")
        nach = [e for e in log if gesagt and e["t"] >= gesagt * 1000 - 1000 and e["t"] <= gesagt * 1000 + 30_000]
        antwort = [k for k in await karten(page) if k.get("art") == "antwort"
                   and passt(SOLL_C["beschluss"], json.dumps(k, ensure_ascii=False))]
        lauf.pruefen("Premium: Ansprache „Nestor, …“ per Sprache beantwortet (Ton am Handy oder Karte mit 9.000)",
                     bool(gesagt) and (len(nach) >= 10 or bool(antwort)),
                     f"Satz erkannt={bool(gesagt)}, Ton danach {len(nach) / 10:.1f} s, Antwortkarten mit Zahl {len(antwort)}")
        await lauf.bild(page, "ansprache_premium")
    else:
        await asyncio.sleep(10)
        antwort = [k for k in await karten(page) if k.get("art") == "antwort"]
        lauf.pruefen("Basis: Ansprache „Nestor, …“ ohne Sprechtaste bleibt unbeantwortet", bool(gesagt) and not antwort,
                     f"Satz erkannt={bool(gesagt)}, Antwortkarten {len(antwort)}")


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


async def sprechtaste_wirkung(page: Page, lauf: Lauf, vorher: int = 0, handy: Page | None = None,
                              losgelassen_ms: float = 0) -> None:
    if lauf.echt:
        # Die Desktop-WAV beginnt bei jedem Halten von vorn („Bitte bereite eine kurze Vorstandssitzung vor.“).
        # Geprüft wird: die Frage wird beantwortet – als Karte oder hörbar am Handy (das Modell entscheidet selbst,
        # ob eine Antwort eine Karte braucht: karten.py „zeigen“). Unbeantwortet = weder noch → rot.
        t0, neu, ton_s = time.monotonic(), [], 0.0
        while time.monotonic() - t0 < 60 and not neu and ton_s < 1.0:
            neu = [k for k in await karten(page) if k.get("id", 0) > vorher and k.get("art") != "ergebnis"]
            if handy is not None:
                log = await handy.evaluate("() => window.__tonLog || []")
                ton_s = sum(1 for e in log if e["t"] > losgelassen_ms) / 10
            await asyncio.sleep(1)
        if neu or ton_s >= 1.0:  # Karte kann der Stimme nachlaufen – kurz nachsehen
            await asyncio.sleep(5)
            neu = [k for k in await karten(page) if k.get("id", 0) > vorher and k.get("art") != "ergebnis"]
        # Bedienlogik (Entscheidung Niclas 08.10.): jede Antwort zeigt eine Karte – nur Ton ist ein Produktfehler (#74)
        lauf.pruefen("Sprechtaste wirkt: Frage transkribiert, beantwortet und als Karte sichtbar",
                     bool(neu),
                     f"Karte={(neu[0].get('art'), (neu[0].get('titel') or '')[:60]) if neu else None}, "
                     f"Ton am Handy nach dem Loslassen {ton_s:.1f} s")
        await lauf.bild(page, "sprechtaste")
        return
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


async def abschliessen(page: Page, lauf: Lauf) -> None:
    """„Abschließen – 5 Minuten Rückkehrfrist“ wie ein Nutzer (Bestätigung annehmen). Erst nach der Frist meldet der
    Coach dem Worker das Meeting-Ende, und der Container wird gestoppt – Staging (max_instances 1) braucht das vor dem
    nächsten Lauf."""
    lauf.schritt("Abschließen (Rückkehrfrist startet, danach stoppt der Container)")
    lauf.dialoge_annehmen = True
    try:
        await page.locator("#btn-fertig").click()
        ok = await warte(page, "() => (document.getElementById('btn-fertig')?.textContent || '').includes('Rückkehrfrist läuft')", 20)
    finally:
        lauf.dialoge_annehmen = False
    lauf.pruefen("Abschließen startet die Rückkehrfrist", ok, await text(page, "#btn-fertig"))
    await lauf.bild(page, "abgeschlossen")


async def handy_abschluss(handy: Page, lauf: Lauf) -> None:
    lauf.schritt("Handy nach dem Ende (Phase Abschluss)")
    await warte(handy, "() => document.body.dataset.phase === 'abschluss'", 20)
    await vertrag_pruefen(handy, "abschluss", "handy", lauf.stufe, lauf)
    await lauf.bild(handy, "handy_abschluss")


# --- Ticket #72: Ergebnisse zeitnah und nie still ----------------------------------------------------------------------
class Ergebnisuhr:
    """Liest während des Meetings mit – nur lesend, alle 0,5 s: wann ein Drehbuchsatz im Zustand des Dashboards ankam
    und wann ein Text sichtbar auf der Verlaufsbühne bzw. im Band stand (Wanduhr des Testlaufs)."""

    SAETZE = ("beschließen", "Sabine liefert", "Kauf lohnt")
    VERLAUF = ("9.000", "Sabine", "Freitag", "Vereinsbus")
    BAND = ("Ergebnis-Erkennung gestört", "In Basis: Sprechtaste halten")
    # Stufe C: dieselben Schlüssel, aber als Regex (echte Transkription/Modelle schreiben nicht wörtlich gleich)
    SAETZE_C = {"beschließen": r"beschlie(ß|ss)en", "Sabine liefert": r"Sabine", "Kauf lohnt": r"Kauf|lohnt",
                "ansprache": r"wie viel Budget|wieviel Budget", "monolog": r"Tombola|Hüpfburg|Kuchenbuffet|Schulband",
                "imperativ": r"b[üu]nd"}
    VERLAUF_C = {"9.000": r"9[.\s]?000|neuntausend", "Sabine": r"Sabine", "Freitag": r"Freitag",
                 "Vereinsbus": r"Vereinsbus"}

    def __init__(self, page: Page, echt: bool = False) -> None:
        self.page = page
        self.echt = echt
        self.satz: dict[str, float] = {}
        self.satz_wand: dict[str, float] = {}  # time.time() – vergleichbar mit Date.now() der Seiten (Ton-Protokoll)
        self.verlauf: dict[str, float] = {}
        self.band: dict[str, float] = {}
        self.band_texte: list[str] = []
        self.artefakte: list[str] = []
        self.taste_hinweise = 0
        self.monolog: list[tuple[float, int, str]] = []  # (monotonic, Sekunden laut Anzeige, Farbe) – nur Änderungen
        self.karten: list[dict] = []
        self.punkte: list[str] = []  # Titel des jeweils aktuellen Agendapunkts („Jetzt“), in Reihenfolge
        self._task: asyncio.Task | None = None

    def starten(self) -> None:
        self._task = asyncio.ensure_future(self._lauf())

    def stoppen(self) -> None:
        if self._task:
            self._task.cancel()

    async def _lauf(self) -> None:
        while True:
            try:
                d = await self.page.evaluate("""() => {
                  const z = (typeof zustand !== 'undefined' && zustand) || {};
                  const band = document.getElementById('band');
                  const kurz = [...document.querySelectorAll('#regel-ampeln .ampel')]
                    .find((a) => /kurz/i.test(a.querySelector('strong')?.textContent || ''));
                  return { buehne: document.getElementById('vl-buehne')?.innerText || '',
                    band: band && !band.hidden ? band.innerText : '',
                    segmente: (z.segmente || []).map((s) => s.text),
                    artefakte: ((z.artefakte || {}).liste || []).map((a) => a.was),
                    taste: (z.hinweise || []).filter((h) => h.art === 'taste').length,
                    kurz: kurz ? { detail: kurz.querySelector('.detail')?.textContent || '',
                                   farbe: ['rot', 'gelb', 'gruen', 'grau'].find((f) => kurz.classList.contains(f)) || '',
                                   sichtbar: !!kurz.offsetParent } : null,
                    karten: (z.karten || []).map((k) => ({ id: k.id, art: k.art, titel: k.titel || '' })),
                    punkt: document.getElementById('punkt-titel')?.textContent || '' };
                }""")
            except Exception:  # noqa: BLE001 – Seite lädt gerade neu
                await asyncio.sleep(0.5)
                continue
            jetzt, wand = time.monotonic(), time.time()
            if self.echt:
                for k, m in self.SAETZE_C.items():
                    if any(passt(m, s) for s in d["segmente"]) and k not in self.satz:
                        self.satz[k], self.satz_wand[k] = jetzt, wand
                for k, m in self.VERLAUF_C.items():
                    if passt(m, d["buehne"]):
                        self.verlauf.setdefault(k, jetzt)
            else:
                for k in self.SAETZE:
                    if any(k in s for s in d["segmente"]):
                        self.satz.setdefault(k, jetzt)
                for k in self.VERLAUF:
                    if k in d["buehne"]:
                        self.verlauf.setdefault(k, jetzt)
            for k in self.BAND:
                if k in d["band"]:
                    self.band.setdefault(k, jetzt)
            if d["band"] and d["band"] not in self.band_texte:
                self.band_texte.append(d["band"][:160])
            if d["kurz"]:
                treffer = re.search(r"(\d+):(\d\d) am Stück", d["kurz"]["detail"])
                sek = int(treffer[1]) * 60 + int(treffer[2]) if treffer else 0
                if not self.monolog or self.monolog[-1][1:] != (sek, d["kurz"]["farbe"]):
                    self.monolog.append((jetzt, sek, d["kurz"]["farbe"]))
            if d.get("punkt") and d["punkt"] not in self.punkte:
                self.punkte.append(d["punkt"])
            for k in d["karten"]:
                if all(k["id"] != x["id"] for x in self.karten):
                    self.karten.append({**k, "t": jetzt})
            self.artefakte, self.taste_hinweise = d["artefakte"], max(self.taste_hinweise, d["taste"])
            await asyncio.sleep(0.5)

    def abstand(self, satz: str, *sichtbar: str) -> float | None:
        if satz not in self.satz or any(k not in self.verlauf for k in sichtbar):
            return None
        return max(self.verlauf[k] for k in sichtbar) - self.satz[satz]


async def ergebnisse_zeitnah_pruefen(page: Page, uhr: Ergebnisuhr, lauf: Lauf) -> None:
    """Ticket #72: Entscheidung und Aufgabe mit Termin stehen ≤ 60 s nach dem Satz als Karte im Verlauf (Schnell-
    Erkennung); der simulierte HTTP-500 der Artefakt-Erkennung steht sichtbar im Band, der nächste Takt holt das
    Ergebnis doch; Basis erklärt das Funkgerät einmal im Band."""
    lauf.schritt("Ergebnisse zeitnah, Anbieterfehler sichtbar (#72)")
    t0 = time.monotonic()
    grenze = 60 if lauf.echt else 90  # C: der Imperativ (Basis: Sprechtaste im WAV-Takt) darf nicht verpasst werden
    while time.monotonic() - t0 < grenze and not (
            uhr.abstand("beschließen", "9.000") is not None and uhr.abstand("Sabine liefert", "Sabine", "Freitag") is not None
            and any("Vereinsbus" in a for a in uhr.artefakte)):
        await asyncio.sleep(1)
    for name, satz, sichtbar in (("Entscheidung (9.000 €)", "beschließen", ("9.000",)),
                                 ("Aufgabe mit Termin (Sabine, Freitag)", "Sabine liefert", ("Sabine", "Freitag"))):
        d = uhr.abstand(satz, *sichtbar)
        lauf.pruefen(f"{name} erscheint ≤ 60 s nach dem Satz als Karte im Verlauf", d is not None and d <= 60,
                     f"{d:.1f} s nach dem Satz" if d is not None else
                     f"Satz gesehen={satz in uhr.satz}, sichtbar={[k for k in sichtbar if k in uhr.verlauf]}")
    if lauf.echt:
        # Kein simulierter Fehler in C – stattdessen: der offene Punkt Vereinsbus wird erkannt, und jeder echte
        # Anbieterfehler, der im Band stand, wird als Beleg mitgeschrieben (nicht verschwiegen)
        gestoert = [t for t in uhr.band_texte if "gestört" in t or "Fehler" in t]
        lauf.belege["band_fehler"] = gestoert
        lauf.pruefen("Keine Anbieterstörung im Band (echte KI-Aufrufe liefen durch)", not gestoert, "; ".join(gestoert)[:200])
        if lauf.stufe == "basis":
            lauf.pruefen("Basis: beim ignorierten „Nestor, …“ einmal „In Basis: Sprechtaste halten“ im Band",
                         "In Basis: Sprechtaste halten" in uhr.band and uhr.taste_hinweise >= 1,
                         f"Band={'In Basis: Sprechtaste halten' in uhr.band}, Hinweise={uhr.taste_hinweise}")
        await lauf.bild(page, "ergebnisse_zeitnah")
        return
    regeln = fake_regeln(lauf)
    simuliert = "schnell_vereinsbus_fehler" in regeln
    lauf.pruefen("Simulierter Anbieterfehler (HTTP 500) bei der Artefakt-Erkennung sichtbar im Band",
                 simuliert and "Ergebnis-Erkennung gestört" in uhr.band,
                 f"Fake-500={simuliert}, Band={'Ergebnis-Erkennung gestört' in uhr.band}"
                 + (f", {uhr.band['Ergebnis-Erkennung gestört'] - uhr.satz['Kauf lohnt']:.1f} s nach dem Satz"
                    if "Ergebnis-Erkennung gestört" in uhr.band and "Kauf lohnt" in uhr.satz else ""))
    lauf.pruefen("Nach dem Fehler wiederholt der nächste Takt – das Ergebnis kommt doch",
                 any("Vereinsbus" in a for a in uhr.artefakte) and "schnell_vereinsbus" in regeln,
                 f"Artefakte: {uhr.artefakte}")
    if lauf.stufe == "basis":
        lauf.pruefen("Basis: beim ignorierten „Nestor, …“ einmal „In Basis: Sprechtaste halten“ im Band",
                     "In Basis: Sprechtaste halten" in uhr.band and uhr.taste_hinweise == 1,
                     f"Band={'In Basis: Sprechtaste halten' in uhr.band}, Hinweise={uhr.taste_hinweise}")
    await lauf.bild(page, "ergebnisse_zeitnah")


# --- Ticket #62: nur Stufe C (echte Anbieter auf Staging) --------------------------------------------------------------
def handy_wav_lage(name: str = "meeting_c") -> list[dict]:
    return json.loads((WURZEL / "tests" / "e2e" / "audio" / f"{name}.json").read_text(encoding="utf-8"))["saetze"]


async def monolog_und_imperativ(page: Page, handy: Page, uhr: Ergebnisuhr, lauf: Lauf, schwelle: float = 60) -> None:
    """#57/#67 auf echter Strecke: ein Block einer Stimme ≥ 90 s mit Pausen < 2 s → die Monologanzeige („Sich kurz
    fassen“, mm:ss am Stück) wächst live und erreicht die Schwelle; danach „Nestor, bündel mir mal die Ergebnisse.“
    → Zusammenfassen. Premium hört den Namen; Basis (Funkgerät) braucht die Sprechtaste – das Handy hält sie im Takt
    der WAV genau über dem Imperativ (Startzeit der WAV = Tippen auf „Mikrofon und Ton“)."""
    lauf.schritt("Monolog-Block live und natürlicher Imperativ „bündle mir mal die Ergebnisse“")
    lage = handy_wav_lage()
    imp = next(x for x in lage if x["art"] == "imperativ")
    mono = [x for x in lage if x["art"] == "monolog"]
    lauf.belege["monolog_block_s"] = round(mono[-1]["ende"] - mono[0]["start"], 1)
    t_mikro = lauf.t_mikro or time.monotonic()
    if lauf.stufe == "basis":
        bis = t_mikro + imp["start"] - 0.6
        if time.monotonic() > bis:
            lauf.pruefen("Basis: Sprechtaste rechtzeitig vor dem Imperativ gehalten", False,
                         f"{time.monotonic() - bis:.1f} s zu spät – Ablauf davor dauerte zu lange")
        else:
            await asyncio.sleep(bis - time.monotonic())
            frei = await warte(handy, "() => !document.getElementById('btn-fragen')?.disabled", 2)
            await handy.locator("#btn-fragen").scroll_into_view_if_needed()
            lauf.belege["imperativ_taste_vorher"] = await handy.evaluate(
                "() => { const k = document.getElementById('btn-fragen'); return k ? { disabled: k.disabled, "
                "klassen: k.className, nestor: document.getElementById('nestor-zustand')?.textContent || '' } : null; }")
            await sprechknopf_halten(handy, "#btn-fragen", imp["ende"] - imp["start"] + 1.0, lauf,
                                     "Sprechtaste (Handy) über dem Imperativ")
            if not frei:
                lauf.belege["imperativ_taste_war_gesperrt"] = True
    else:
        rest = t_mikro + imp["ende"] - time.monotonic()
        if rest > 0:
            await asyncio.sleep(rest)
    t0 = time.monotonic()
    karte = None
    while time.monotonic() - t0 < 60 and karte is None:
        # die Karte, die nach Beginn des Imperativs entstand – der Schritt selbst kann später beginnen (vierter
        # C-Lauf: Karte 4 s nach dem Satz, Schritt erst Minuten danach → per ID-Vergleich übersehen)
        karte = next((k for k in uhr.karten if k["t"] >= t_mikro + imp["start"] and k["art"] == "zusammenfassung"), None)
        await asyncio.sleep(1)
    ab_imperativ = (karte["t"] - (t_mikro + imp["ende"])) if karte else None
    lauf.pruefen("Imperativ „bündle mir mal die Ergebnisse“ löst Zusammenfassen aus (Karte im Verlauf)", bool(karte),
                 f"Karte {karte['titel']!r} {ab_imperativ:.0f} s nach Satzende" if karte
                 else f"keine Zusammenfassungs-Karte binnen 60 s; Imperativ im Transkript={'imperativ' in uhr.satz}")
    await lauf.bild(page, "imperativ")

    # Monologanzeige: Werte während des Blocks (Lage relativ zur WAV) – wächst sie live, erreicht sie die Schwelle?
    von, bis_ = t_mikro + mono[0]["start"], t_mikro + mono[-1]["ende"] + 8
    block = [(t - t_mikro, sek, farbe) for t, sek, farbe in uhr.monolog if von <= t <= bis_]
    werte = [sek for _, sek, _ in block]
    steigend = sum(1 for a, b in zip(werte, werte[1:]) if b > a)
    lauf.belege["monolog_anzeige"] = [(round(t, 1), sek, farbe) for t, sek, farbe in block][:200]
    lauf.pruefen("Monologanzeige wächst live während des Blocks (≥ 10 steigende Schritte)", steigend >= 10,
                 f"{steigend} Schritte, Werte {werte[:3]}…{werte[-3:]}")
    hoch = max(werte, default=0)
    farbe_erreicht = any(f in ("gelb", "rot") for _, sek, f in block if sek >= schwelle)
    lauf.pruefen(f"Monologanzeige erreicht die Schwelle ({schwelle:.0f} s) und färbt sich",
                 hoch >= schwelle and farbe_erreicht, f"höchstens {hoch} s, Farbe ab Schwelle={farbe_erreicht}")


async def ergebnisse_ende_pruefen(uhr: Ergebnisuhr, lauf: Lauf) -> None:
    """Stufe C, vor dem Beenden: der offene Prüfauftrag Vereinsbus ist erkannt (bei echten Modellen oft erst mit der
    gebündelten Auswertung, nicht in den ersten 60 s) und die Themenzuordnung ist plausibel: Sommerfest-Budget wurde
    aktueller Punkt oder Nestor hat den Wechsel dorthin angeboten (#72)."""
    lauf.pruefen("Offener Punkt/Prüfauftrag Vereinsbus (Kauf lohnt?) als Ergebnis erkannt",
                 any(passt(SOLL_C["offen"], a or "") for a in uhr.artefakte), f"Artefakte: {uhr.artefakte}",
                 abweichung=f"c_offener_punkt_{lauf.stufe}")
    angeboten = [t for t in uhr.band_texte if passt("Sommerfest", t)]
    lauf.belege["themen"] = {"punkte": uhr.punkte, "band": angeboten[:3]}
    lauf.pruefen("Themenzuordnung plausibel: Sommerfest-Budget aktuell oder als nächster Punkt angeboten",
                 any(passt("Sommerfest", p) for p in uhr.punkte) or bool(angeboten),
                 f"aktuelle Punkte {uhr.punkte}, Angebote {angeboten[:2]}")


async def anbieterprotokoll_pruefen(page: Page, url: str, geheimnis: str, lauf: Lauf) -> None:
    """Anbieterbeweis ohne Fakes: die Hostwache im Staging-Container nennt, welche Ziele sie gesehen hat. Lesend, mit
    den Cookies des Desktops (führt in denselben Container) und dem Worker-Geheimnis in X-Nestor-Intern."""
    lauf.schritt("Anbieterprotokoll der Hostwache lesen (vor dem Beenden – danach stoppt der Container)")
    antwort = await page.context.request.get(url.rstrip("/") + "/api/intern/anbieter-protokoll",
                                             headers={"X-Nestor-Intern": geheimnis})
    daten = await antwort.json() if antwort.ok else {}
    domain = "openai.com" if lauf.stufe == "premium" else "mistral.ai"
    gesehen = daten.get("gesehen") or []
    fremd = [g for g in gesehen if not g.get("erlaubt") or not g.get("ziel", "").split(":")[0].endswith(domain)]
    lauf.belege["anbieterbeweis"] = {"http": antwort.status, **daten}
    lauf.pruefen(f"Hostwache (Staging): nur {domain}-Ziele kontaktiert, keine Abweisung",
                 antwort.ok and daten.get("stufe") == lauf.stufe and bool(gesehen) and not fremd,
                 f"HTTP {antwort.status}, stufe={daten.get('stufe')!r}, "
                 f"gesehen={[(g.get('ziel'), g.get('anzahl'), g.get('erlaubt')) for g in gesehen]}")


class Kostenwache:
    """Deckel je Lauf (Entscheidung Niclas 10.10.2026): alle 5 s den Kostenstand des Dashboards lesen (lesend, wie
    die Anzeige „… $“ ihn zeigt). Über dem Deckel: Lauf über die Oberfläche beenden („Beenden“-Klick) und als
    „Deckel gerissen“ markieren. Der Kostenzähler rechnet in Dollar; verglichen wird vorsichtig Dollar gegen den
    Euro-Deckel (1 $ < 1 €, der Lauf endet also eher zu früh als zu spät)."""

    EUR_JE_USD = 0.86  # nur für die Anzeige im Bericht

    def __init__(self, page: Page, deckel_eur: float, lauf: Lauf) -> None:
        self.page, self.deckel, self.lauf = page, deckel_eur, lauf
        self.usd = 0.0
        self.gerissen = False

    async def lesen(self) -> float:
        try:
            k = await self.page.evaluate("() => (typeof zustand !== 'undefined' && zustand && zustand.kosten) || null")
        except Exception:  # noqa: BLE001 – Seite lädt neu oder ist schon auf /abschluss
            k = None
        if k:
            self.usd = max(self.usd, float(k.get("meeting") or 0), float(k.get("heute") or 0))
        return self.usd

    async def wachen(self) -> None:
        while True:
            if await self.lesen() >= self.deckel:
                self.gerissen = True
                return
            await asyncio.sleep(5)

    def beleg(self) -> dict:
        return {"usd_dashboard": round(self.usd, 4), "eur_geschaetzt": round(self.usd * self.EUR_JE_USD, 4),
                "deckel_eur": self.deckel, "gerissen": self.gerissen}


async def mit_kostendeckel(ablauf, wache: Kostenwache, lauf: Lauf) -> None:
    """Führt den Ablauf aus, solange die Kostenwache nicht anschlägt; schlägt sie an, wird der Ablauf abgebrochen und
    das Meeting über die Oberfläche beendet."""
    arbeit = asyncio.ensure_future(ablauf)
    waechter = asyncio.ensure_future(wache.wachen())
    fertig, _ = await asyncio.wait({arbeit, waechter}, return_when=asyncio.FIRST_COMPLETED)
    if waechter in fertig and not arbeit.done():
        arbeit.cancel()
        with contextlib.suppress(BaseException):
            await arbeit
        try:
            if await sichtbar(wache.page, "#btn-stopp"):
                await wache.page.locator("#btn-stopp").click()
        except Exception:  # noqa: BLE001
            pass
        lauf.pruefen(f"Kostendeckel je Lauf ({wache.deckel:.2f} €) eingehalten", False,
                     f"Deckel gerissen bei {wache.usd:.2f} $ – Meeting über „Beenden“ abgebrochen")
        raise Abbruch("Deckel gerissen")
    waechter.cancel()
    await wache.lesen()
    arbeit.result()
