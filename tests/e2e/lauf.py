"""Stufe B der Test-Pipeline (Ticket #61): lokale Klick-E2E gegen Fake-Anbieter, 0 €.

Aufbau je Stufe (seriell; alle Dienste werden je Stufe frisch gestartet – auch gegen globalen Zustand im Coach):

    Chromium Desktop ──► wrangler dev (Worker, https://localhost:18787) ──► uvicorn tests.e2e.coach_app (127.0.0.1:18000)
    Chromium Handy   ──┘      LOKAL_COACH_URL statt Container                 ├─► Fake-OpenAI  127.0.0.11:18011
      (mobile Emulation, Mikro aus meeting_e2e.wav)                           └─► Fake-Mistral 127.0.0.12:18012

Alles landet unter logs/pipeline/<ts>/b/<stufe>/ (Screenshots, Videos, bericht.html, Fake-Protokolle, Dienst-Logs),
Browserprofile und Temporäres unter ~/.cache/lmc-e2e – nie in /tmp (RAM-Disk auf dem Pi).

    .venv/bin/python -m tests.e2e.lauf --stufe basis --rauch
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WURZEL))

from tests.e2e import audio_bauen, schritte  # noqa: E402
from tests.e2e.fake_anbieter import umgebung as fake_umgebung  # noqa: E402

CACHE = Path.home() / ".cache" / "lmc-e2e"
COACH_PORT, WORKER_PORT = 18000, 18787
WORKER_URL = f"https://localhost:{WORKER_PORT}"
CHROMIUM = os.getenv("LMC_E2E_CHROMIUM", "/usr/bin/chromium")
# workerd im installierten wrangler 4.86 kennt Kompatibilitätsdaten bis 2026-05-03; das Projekt verlangt 2026-10-07.
# Nur für den lokalen Lauf heruntergesetzt – die Worker-Logik nutzt nichts, was danach kam.
KOMPAT_DATUM = os.getenv("LMC_E2E_KOMPAT_DATUM", "2026-05-03")
MIN_FREI_MB = 2048


# --- Speicher ---------------------------------------------------------------------------------------------------------
def mem_available_mb() -> int:
    for zeile in Path("/proc/meminfo").read_text().splitlines():
        if zeile.startswith("MemAvailable:"):
            return int(zeile.split()[1]) // 1024
    return 0


class Speicheruhr(threading.Thread):
    """Misst während des Laufs den kleinsten freien Speicher – daraus die RAM-Spitze des Laufs."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.start_mb = mem_available_mb()
        self.min_mb = self.start_mb
        self._stopp = threading.Event()

    def run(self) -> None:
        while not self._stopp.wait(1.0):
            self.min_mb = min(self.min_mb, mem_available_mb())

    def stopp(self) -> dict:
        self._stopp.set()
        return {"frei_start_mb": self.start_mb, "frei_min_mb": self.min_mb, "spitze_mb": self.start_mb - self.min_mb}


# --- Dienste ---------------------------------------------------------------------------------------------------------
class Dienste:
    def __init__(self, ordner: Path, stufe: str) -> None:
        self.ordner = ordner
        self.stufe = stufe
        self.prozesse: list[tuple[str, subprocess.Popen]] = []
        self.geheimnis = secrets.token_hex(16)
        self.passwort = secrets.token_urlsafe(12)
        self.tmp = CACHE / "tmp"
        self.tmp.mkdir(parents=True, exist_ok=True)

    def _starten(self, name: str, befehl: list[str], env: dict, cwd: Path = WURZEL) -> None:
        log = (self.ordner / "dienste").joinpath(f"{name}.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen(befehl, cwd=cwd, env=env, stdout=log.open("w"), stderr=subprocess.STDOUT,
                             start_new_session=True)
        self.prozesse.append((name, p))

    def _basis_env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LMC_", "OPENAI_", "MISTRAL_"))}
        env.update(TMPDIR=str(self.tmp), PYTHONUNBUFFERED="1")
        return env

    def fakes(self) -> None:
        self._starten("fakes", [sys.executable, "-m", "tests.e2e.fake_anbieter", "--log", str(self.ordner / "fakes")],
                      self._basis_env())

    def coach(self) -> None:
        env = self._basis_env()
        lauf = self.ordner
        env.update(fake_umgebung())
        env.update({
            "LMC_BETRIEB": "cloud", "LMC_WORKER_GEHEIMNIS": self.geheimnis, "LMC_WORKER_URL": WORKER_URL,
            "OPENAI_API_KEY": "sk-e2e-fake-" + "0" * 24, "LMC_MISTRAL_SCHLUESSEL": "e2e-fake-mistral",
            "LMC_SCHLUESSEL_DATEI": str(lauf / "coach" / "kein_schluessel"),
            "LMC_KOPPLUNG_DATEI": str(lauf / "coach" / "kopplung"),
            "LMC_ARCHIV": str(lauf / "coach" / "meetings"), "LMC_SPENDEN": str(lauf / "coach" / "spenden"),
            "LMC_FLOSKEL_ORDNER": str(lauf / "coach" / "floskeln"), "LMC_AUFNAHME": "0",
            "LMC_E2E_NETZLOG": str(lauf / "netzwaechter.jsonl"), "LMC_E2E_LAUFORDNER": str(lauf),
            "LMC_PORT": str(COACH_PORT), "LMC_PAYPAL_ME": "e2e-test",  # macht „Unterstützung“ sichtbar (Reihenfolge)
        })
        self._starten("coach", [sys.executable, "-m", "uvicorn", "tests.e2e.coach_app:app", "--host", "127.0.0.1",
                                "--port", str(COACH_PORT), "--ws", "websockets", "--log-level", "warning"], env)

    def worker(self) -> None:
        env = self._basis_env()
        kunden = json.dumps({"e2e": {"hash": hashlib.sha256(self.passwort.encode()).hexdigest(), "max_meetings": 5}})
        befehl = ["npx", "wrangler", "dev", "--enable-containers=false", "--compatibility-date", KOMPAT_DATUM,
                  "--local-protocol", "https", "--ip", "127.0.0.1", "--port", str(WORKER_PORT),
                  "--persist-to", str(self.ordner / "wrangler-state"), "--show-interactive-dev-session=false",
                  "--var", f"LOKAL_COACH_URL:http://127.0.0.1:{COACH_PORT}", "--var", f"WORKER_GEHEIMNIS:{self.geheimnis}",
                  "--var", f"COOKIE_GEHEIMNIS:{secrets.token_hex(16)}", "--var", f"KUNDEN:{kunden}",
                  "--var", f"WORKER_URL:{WORKER_URL}", "--var", "AUTO_FREIGABE:0"]
        env["WRANGLER_SEND_METRICS"] = "false"
        self._starten("worker", befehl, env, cwd=WURZEL / "cloudflare")

    def warten(self, url: str, sekunden: float, name: str) -> None:
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        frist = time.monotonic() + sekunden
        while time.monotonic() < frist:
            for n, p in self.prozesse:
                if p.poll() is not None:
                    raise RuntimeError(f"Dienst {n} beendet (Code {p.returncode}) – siehe dienste/{n}.log")
            try:
                urllib.request.urlopen(url, timeout=2, context=ctx)
                return
            except urllib.error.HTTPError:
                return  # antwortet – Status egal
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        raise RuntimeError(f"{name} nicht erreichbar nach {sekunden:.0f} s ({url})")

    def rss_mb(self) -> int:
        """Summe RSS aller Prozesse unserer Sitzungen (Dienste) in MB."""
        gesamt = 0
        for _, p in self.prozesse:
            try:
                aus = subprocess.run(["ps", "-o", "rss=", "-g", str(os.getpgid(p.pid))], capture_output=True, text=True)
                gesamt += sum(int(x) for x in aus.stdout.split())
            except (ProcessLookupError, ValueError):
                pass
        return gesamt // 1024

    def stoppen(self) -> None:
        for _, p in reversed(self.prozesse):
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        for _, p in self.prozesse:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass


# --- Anbieterbeweis -----------------------------------------------------------------------------------------------
def anbieterbeweis(ordner: Path, stufe: str, lauf: schritte.Lauf) -> None:
    def lesen(name: str) -> list[dict]:
        p = ordner / "fakes" / f"anfragen_{name}.jsonl"
        return [json.loads(z) for z in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    oa, mi = lesen("openai"), lesen("mistral")
    eigen, fremd = (oa, mi) if stufe == "premium" else (mi, oa)
    fremd_name = "Mistral" if stufe == "premium" else "OpenAI"
    netz = ordner / "netzwaechter.jsonl"
    netz_versuche = [json.loads(z) for z in netz.read_text().splitlines()] if netz.exists() else []
    unbekannt = [e for e in oa + mi if e.get("fehler") == "unbekannter_prompt"]
    arten = sorted({e.get("pfad", "") + (f" ({e['ws_art']})" if e.get("ws_art") else "") for e in eigen
                    if e.get("art") in ("http", "ws")})
    lauf.belege["anbieterbeweis"] = {
        "openai_anfragen": len(oa), "mistral_anfragen": len(mi), "eigene_endpunkte": arten,
        "regeln": sorted({e["regel"] for e in eigen if e.get("regel")}),
        "netzwaechter_verweigert": netz_versuche[:10], "unbekannte_prompts": unbekannt[:5],
        "umlenkung": json.loads((ordner / "umlenkung.json").read_text()) if (ordner / "umlenkung.json").exists() else {},
    }
    lauf.pruefen(f"Anbieterbeweis: {fremd_name}-Protokoll leer", not fremd, f"{len(fremd)} Anfragen")
    lauf.pruefen("Anbieterbeweis: Anfragen beim Anbieter der Stufe", bool(eigen), f"{len(eigen)} Anfragen, {arten}")
    lauf.pruefen("Kein Verbindungsversuch außerhalb von Loopback (Netzwächter)", not netz_versuche,
                 "; ".join(f"{v['host']} {v.get('aufrufer')}" for v in netz_versuche[:3]))
    lauf.pruefen("Keine unbekannten Prompts (Drehbuch passt zum Code)", not unbekannt,
                 "; ".join(e.get("prompt_anfang", "")[:80] for e in unbekannt[:3]))
    live_ws = any(e.get("ws_art") == "live_text" for e in eigen)
    lauf.pruefen("Live-Text-WebSocket beim Anbieter der Stufe geöffnet", live_ws)
    weg = lauf.belege["anbieterbeweis"]["umlenkung"].get("weg")
    if weg == "testnaht_bis_60":
        lauf.ausstehend("Realtime-WS über LMC_*_WS_URL aus coach/anbieter.py",
                        "heute per Testnaht in tests/e2e/coach_app.py umgelenkt", "#60")


# --- Durchlauf ----------------------------------------------------------------------------------------------------
async def durchlauf(ordner: Path, stufe: str, rauch: bool, dienste: Dienste) -> schritte.Lauf:
    from playwright.async_api import async_playwright

    lauf = schritte.Lauf(ordner, stufe, rauch)
    audio = audio_bauen.bauen()
    lauf.belege["audio"] = {k: str(v.relative_to(WURZEL)) for k, v in audio.items()}
    video = ordner / "video"
    gemeinsam = ["--no-sandbox", "--disable-gpu", "--renderer-process-limit=2", "--ignore-certificate-errors",
                 "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 "--autoplay-policy=no-user-gesture-required", "--disable-dev-shm-usage"]
    handy = handy_ctx = desk_ctx = None
    async with async_playwright() as pw:
        desktop_browser = await pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=gemeinsam + [
            f"--use-file-for-fake-audio-capture={audio['agenda']}"])
        handy_browser = await pw.chromium.launch(executable_path=CHROMIUM, headless=True, args=gemeinsam + [
            f"--use-file-for-fake-audio-capture={audio['meeting']}"])
        desk_ctx = await desktop_browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True,
                                                     accept_downloads=True, record_video_dir=str(video),
                                                     record_video_size={"width": 640, "height": 400})
        seite = await desk_ctx.new_page()
        seite.on("pageerror", lambda e: lauf.belege.setdefault("js_fehler_desktop", []).append(str(e)[:200]))
        seite.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
        try:
            await schritte.anmelden(seite, WORKER_URL, dienste.passwort, lauf)
            await schritte.stufe_waehlen(seite, stufe, lauf)
            await schritte.agenda_text(seite, lauf)
            await schritte.agenda_sprache(seite, lauf)
            await schritte.start_gesperrt(seite, lauf)
            url = await schritte.qr_lesen(seite, lauf)
            handy_ctx, handy = await schritte.handy_koppeln(handy_browser, url, stufe, lauf, video)
            await schritte.handy_mikro(seite, handy, lauf)
            await schritte.zweites_handy(handy_browser, url, lauf)
            await schritte.meeting_starten(seite, handy, lauf)
            await schritte.ton_abwarten(handy, lauf, "Begrüßung", 45)
            if rauch:
                await schritte.kernknopf(seite, "stand", "Stand Sommerfest-Budget", lauf)
                lauf.offen("Transkript, übrige Kernknöpfe, Sprechtaste, Abschluss, ZIP, Datenspende",
                           "Rauchmodus endet nach Meetingstart und einem Kernknopf")
            else:
                await schritte.transkript_pruefen(seite, lauf)
                for art, soll in (("stand", "Stand Sommerfest-Budget"), ("zusammenfassen", "9.000"),
                                  ("fehlt", "fehlt"), ("protokoll", "Festgehalten"), ("ueberblick", "Budget beschlossen, Vereinsbus")):
                    await schritte.kernknopf(seite, art, soll, lauf)
                    await schritte.ton_abwarten(handy, lauf, art, 20)
                if stufe == "basis":
                    await schritte.sprechknopf_halten(seite, "#btn-taste", 2.5, lauf, "Sprechtaste (Basis)")
                    await schritte.ton_abwarten(handy, lauf, "Sprechtaste", 30)
                else:
                    lauf.offen("Ansprache „Nestor, …“ per Sprache (Premium)", "Satz fehlt noch im Drehbuch-Audio")
                await schritte.beenden_und_abschluss(seite, lauf, ordner)
        except schritte.Abbruch as e:
            lauf.belege["abbruch"] = str(e)
            await lauf.bild(seite, "abbruch")
        except Exception as e:  # noqa: BLE001
            import traceback

            lauf.belege["ausnahme"] = traceback.format_exc()[-2000:]
            lauf.pruefen("Durchlauf ohne Ausnahme", False, f"{type(e).__name__}: {str(e)[:200]}")
            await lauf.bild(seite, "ausnahme")
        finally:
            if handy is not None:
                await schritte.ton_auswerten(handy, stufe, lauf)
            lauf.belege["rss_dienste_mb"] = dienste.rss_mb()
            for ctx in (handy_ctx, desk_ctx):
                if ctx is not None:
                    await ctx.close()
            await handy_browser.close()
            await desktop_browser.close()
    return lauf


def stufe_fahren(basis: Path, stufe: str, rauch: bool) -> schritte.Lauf:
    ordner = basis / stufe
    ordner.mkdir(parents=True, exist_ok=True)
    dienste = Dienste(ordner, stufe)
    uhr = Speicheruhr()
    uhr.start()
    t0 = time.monotonic()
    try:
        dienste.fakes()
        dienste.coach()
        dienste.worker()
        dienste.warten("http://127.0.0.11:18011/bereit", 30, "Fake-OpenAI")  # 404, nicht protokolliert
        dienste.warten(f"http://127.0.0.1:{COACH_PORT}/api/start", 90, "Coach")
        dienste.warten(f"{WORKER_URL}/anmelden", 120, "Worker (wrangler dev)")
        lauf = asyncio.run(durchlauf(ordner, stufe, rauch, dienste))
    finally:
        dienste.stoppen()
    anbieterbeweis(ordner, stufe, lauf)
    lauf.belege["speicher"] = uhr.stopp()
    lauf.belege["wand_s"] = round(time.monotonic() - t0, 1)
    videos = sorted(str(p.relative_to(ordner)) for p in (ordner / "video").glob("*.webm"))
    lauf.schreiben(videos)
    shutil.rmtree(ordner / "wrangler-state", ignore_errors=True)
    return lauf


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stufe", choices=("basis", "premium", "beide"), default="beide")
    p.add_argument("--rauch", action="store_true", help="nur bis Meetingstart und einen Kernknopf (~2 min je Stufe)")
    p.add_argument("--ordner", help="Zielordner (Standard logs/pipeline/<zeitstempel>/b)")
    args = p.parse_args()
    frei = mem_available_mb()
    if frei < MIN_FREI_MB:
        print(f"Zu wenig freier Speicher: {frei} MB verfügbar, {MIN_FREI_MB} MB nötig.\n"
              "Hebel: /nebendienste aus (Immich und Paperless pausieren) – keine Prozesse abschießen.", file=sys.stderr)
        return 2
    basis = Path(args.ordner) if args.ordner else WURZEL / "logs" / "pipeline" / datetime.now().strftime("%Y%m%d-%H%M%S") / "b"
    stufen = ("basis", "premium") if args.stufe == "beide" else (args.stufe,)
    ergebnisse = {}
    for stufe in stufen:
        lauf = stufe_fahren(basis, stufe, args.rauch)
        ergebnisse[stufe] = lauf
        print(f"[{stufe}] Bericht: {lauf.ordner / 'bericht.html'}  ·  {lauf.belege['wand_s']} s  ·  "
              f"RAM-Spitze {lauf.belege['speicher']['spitze_mb']} MB (Dienste {lauf.belege['rss_dienste_mb']} MB RSS)")
    gesamt = basis / "bericht.html"
    gesamt.write_text("<!doctype html><meta charset=utf-8><title>Stufe B</title><h1>Stufe B</h1><ul>" + "".join(
        f"<li><a href='{s}/bericht.html'>{s}</a>: {len(l.rot)} rot, "
        f"{sum(1 for x in l.pruefungen if x['status'] == 'bekannt_rot')} bekannt rot, "
        f"{l.belege['wand_s']} s</li>" for s, l in ergebnisse.items()) + "</ul>", encoding="utf-8")
    print(f"Gesamt: {gesamt}")
    return 1 if any(l.rot for l in ergebnisse.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
