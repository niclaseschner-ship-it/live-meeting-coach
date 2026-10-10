"""Stufe C der Test-Pipeline (Ticket #62): dieselbe Klick-E2E wie Stufe B, aber gegen Staging mit echten Anbietern.

    Chromium Desktop ──► https://nestor-staging.<konto>.workers.dev ──► Container (Staging, max. 1) ──► OpenAI | Mistral
    Chromium Handy   ──┘   (mobile Emulation, Mikro aus tests/e2e/audio/meeting_c.wav)

Unterschiede zu B (tests/e2e/lauf.py): kein lokaler Dienst, echte Modelle → Sollfragmente statt wörtlicher Antworten,
zusätzlich Monolog-Block live, natürlicher Imperativ, Anbieterprotokoll der Hostwache (nur mit Worker-Geheimnis)
und ein Kostendeckel je Lauf (Premium 1 €, Basis 0,30 €; Entscheidung Niclas 10.10.2026). Zugangsdaten nur aus
~/.cache/lmc-e2e/staging.env (deploy/staging_einrichten.sh) – nie aus prod, nie im Bericht.

Ein grüner Lauf schreibt <Hauptrepo>/logs/pipeline/<sha>/c_<stufe>.ok – nur, wenn der Staging-Worker genau diesen
Git-Stand trägt (GET /version). Das liest das Gate in deploy/deploy.sh.

    .venv/bin/python -m tests.e2e.lauf_c --stufe beide
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WURZEL))

from tests.e2e import audio_bauen, schritte  # noqa: E402
from tests.e2e.lauf import Speicheruhr, Ziel, durchlauf, mem_available_mb  # noqa: E402

STAGING_ENV = Path(os.getenv("LMC_STAGING_ENV", str(Path.home() / ".cache" / "lmc-e2e" / "staging.env")))
DECKEL_EUR = {"premium": 1.00, "basis": 0.30}
MIN_FREI_MB = 1200  # nur zwei Chromium, kein lokaler Dienst
ANWENDUNG = "nestor-staging-nestor-staging"  # Container-Anwendung des Staging-Workers bei Cloudflare
CONTAINER_FRIST_S = 900  # Rückkehrfrist 5 min nach „Abschließen“, dann Stopp; ohne Abschließen bis sleepAfter 20 min


def staging_werte() -> dict[str, str]:
    if not STAGING_ENV.exists():
        sys.exit(f"{STAGING_ENV} fehlt – erst deploy/staging_einrichten.sh bzw. deploy/deploy.sh --staging.")
    werte = {}
    for zeile in STAGING_ENV.read_text(encoding="utf-8").splitlines():
        if "=" in zeile and not zeile.startswith("#"):
            k, v = zeile.split("=", 1)
            werte[k.strip()] = v.strip()
    return werte


def staging_sha(url: str) -> str | None:
    try:
        anfrage = urllib.request.Request(url.rstrip("/") + "/version", headers={"User-Agent": "nestor-pipeline-c/1"})
        with urllib.request.urlopen(anfrage, timeout=15) as a:  # Standard-UA „Python-urllib“ blockt Cloudflare (403)
            return json.load(a).get("git_sha")
    except Exception:  # noqa: BLE001
        return None


def container_frei_abwarten() -> None:
    """Staging hat max_instances 1: Der Container des vorigen Laufs muss gestoppt sein, sonst antwortet der Worker mit
    „Maximum number of running container instances exceeded“ (erster C-Lauf, 10.10.2026: nach „Fertig“ und 30 s
    Pause war er noch nicht frei). Fragt die Containers-API (wie deploy/rollout_warten.py instanzen) – das
    Cloudflare-Token nur im Speicher dieses Prozesses. Ohne Token: feste 3 Minuten."""
    sys.path.insert(0, str(WURZEL / "deploy"))
    import rollout_warten as rw  # noqa: PLC0415

    token = subprocess.run(["sudo", "-n", "zugang", "holen", "cloudflare-nestor"], capture_output=True,
                           text=True).stdout.strip()
    if not token:
        print("… kein Cloudflare-Token – warte pauschal 180 s auf den Staging-Container")
        time.sleep(180)
        return
    os.environ["CLOUDFLARE_API_TOKEN"] = token
    try:
        def api(pfad: str):
            anfrage = urllib.request.Request("https://api.cloudflare.com/client/v4" + pfad,
                                             headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(anfrage, timeout=30) as a:
                return json.load(a)["result"]

        konto = api("/accounts")[0]["id"]
        anwendung = next(a["id"] for a in api(f"/accounts/{konto}/containers/applications") if a.get("name") == ANWENDUNG)
        os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["NESTOR_APPLICATION_ID"] = konto, anwendung
        frist = time.monotonic() + CONTAINER_FRIST_S
        while time.monotonic() < frist:
            aktiv = rw.aktive_instanzen()
            if not aktiv:
                return
            print(f"… Staging-Container noch belegt ({len(aktiv)} aktiv) – warte")
            time.sleep(15)
        print("… Staging-Container nach Frist noch belegt – versuche es trotzdem")
    except Exception as e:  # noqa: BLE001
        print(f"… Containers-API nicht lesbar ({type(e).__name__}) – warte pauschal 180 s")
        time.sleep(180)
    finally:
        for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "NESTOR_APPLICATION_ID"):
            os.environ.pop(k, None)


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(WURZEL), *args], capture_output=True, text=True).stdout.strip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stufe", choices=("basis", "premium", "beide"), default="beide")
    p.add_argument("--ordner", help="Zielordner (Standard logs/pipeline/<zeitstempel>/c)")
    p.add_argument("--fremder-stand", action="store_true",
                   help="auch fahren, wenn Staging einen anderen Git-Stand trägt (dann keine Freigabe-Markierung)")
    args = p.parse_args()

    frei = mem_available_mb()
    if frei < MIN_FREI_MB:
        print(f"Zu wenig freier Speicher: {frei} MB verfügbar, {MIN_FREI_MB} MB nötig.\n"
              "Hebel: /nebendienste aus (Immich und Paperless pausieren) – keine Prozesse abschießen.", file=sys.stderr)
        return 2
    werte = staging_werte()
    url = werte["STAGING_URL"]
    head = git("rev-parse", "HEAD")
    sauber = not git("status", "--porcelain")
    auf_staging = staging_sha(url)
    passt = auf_staging == head and sauber
    if not passt:
        grund = (f"Staging trägt {auf_staging or 'nichts lesbares'}, HEAD ist {head}" if auf_staging != head
                 else "Arbeitsstand nicht sauber")
        if not args.fremder_stand:
            print(f"{grund}. Erst 'deploy/deploy.sh --staging' (oder --fremder-stand: fahren ohne Freigabe).",
                  file=sys.stderr)
            return 2
        print(f"Hinweis: {grund} – Lauf ohne Freigabe-Markierung.")

    haupt = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    basis = Path(args.ordner) if args.ordner else haupt / "logs" / "pipeline" / datetime.now().strftime("%Y%m%d-%H%M%S") / "c"
    audio = audio_bauen.bauen_c()
    agenda_ende = json.loads(audio["agenda"].with_suffix(".json").read_text(encoding="utf-8"))["saetze"][-1]["ende"]
    stufen = ("premium", "basis") if args.stufe == "beide" else (args.stufe,)
    ergebnisse: dict[str, schritte.Lauf] = {}
    for stufe in stufen:
        container_frei_abwarten()
        ordner = basis / stufe
        ordner.mkdir(parents=True, exist_ok=True)
        uhr = Speicheruhr()
        uhr.start()
        t0 = time.monotonic()
        ziel = Ziel(url=url, passwort=werte["STAGING_PASSWORT"], audio=audio, echt=True,
                    intern_geheimnis=werte["STAGING_WORKER_GEHEIMNIS"], deckel_eur=DECKEL_EUR[stufe],
                    agenda_halten_s=agenda_ende + 1.0)
        lauf = asyncio.run(durchlauf(ordner, stufe, False, ziel))
        lauf.belege["staging"] = {"url": url, "git_sha": auf_staging, "head": head, "freigabe": passt}
        lauf.belege["speicher"] = uhr.stopp()
        lauf.belege["wand_s"] = round(time.monotonic() - t0, 1)
        videos = sorted(str(v.relative_to(ordner)) for v in (ordner / "video").glob("*.webm"))
        lauf.schreiben(videos)
        ergebnisse[stufe] = lauf
        k = lauf.belege.get("kosten", {})
        print(f"[{stufe}] Bericht: {ordner / 'bericht.html'}  ·  {lauf.belege['wand_s']} s  ·  "
              f"Kosten {k.get('usd_dashboard', '?')} $ (≈ {k.get('eur_geschaetzt', '?')} €, Deckel {DECKEL_EUR[stufe]} €)"
              f"  ·  {len(lauf.rot)} rot")
        if passt and not lauf.rot:
            marker = haupt / "logs" / "pipeline" / head / f"c_{stufe}.ok"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(datetime.now().astimezone().isoformat(timespec="seconds") + f" {ordner}\n", encoding="utf-8")
            print(f"GATE_C_D: Freigabe Stufe C {stufe} für {head} geschrieben · {marker}")

    gesamt = basis / "bericht.html"
    gesamt.write_text("<!doctype html><meta charset=utf-8><title>Stufe C</title><h1>Stufe C (Staging, echte Anbieter)</h1>"
                      f"<p>{url} · Stand {auf_staging} · Freigabe {'ja' if passt else 'nein'}</p><ul>" + "".join(
                          f"<li><a href='{s}/bericht.html'>{s}</a>: {len(l.rot)} rot, "
                          f"{sum(1 for x in l.pruefungen if x['status'] == 'bekannt_rot')} bekannt rot, "
                          f"{l.belege.get('kosten', {}).get('usd_dashboard', '?')} $, {l.belege['wand_s']} s</li>"
                          for s, l in ergebnisse.items()) + "</ul>", encoding="utf-8")
    print(f"Gesamt: {gesamt}")
    return 1 if any(l.rot for l in ergebnisse.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
