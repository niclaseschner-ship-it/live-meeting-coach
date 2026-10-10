#!/usr/bin/env python3
"""Deploy-Helfer (Ticket #65): Cloudflare-Containers-API – laufende Instanzen prüfen, auf einen Rollout warten.

Ersetzt die hart kodierten `/tmp/nestor_rollout.py` und `/tmp/nestor_ui56_rollout.py` (RAM-Disk, Konto- und
Anwendungs-ID im Quelltext). Beide IDs kommen jetzt ausschließlich aus der Umgebung – nie als Literal hier im
Repo. `deploy/deploy.sh` setzt sie vor dem Aufruf (aus Env-Überschreibung oder aus `wrangler`-Befehlen
ermittelt, siehe dortige Kommentare).

Nötige Umgebung:
  CLOUDFLARE_API_TOKEN     – Secret `cloudflare-nestor` (nur per Env, nie als Argument/Datei)
  CLOUDFLARE_ACCOUNT_ID    – Cloudflare-Konto-ID
  NESTOR_APPLICATION_ID    – ID der Container-Anwendung "nestor-nestor"

Aufrufe:
  rollout_warten.py konto
      Druckt die Konto-ID aus `GET /accounts` (braucht nur das Token). Rückfall für Konto-Tokens, mit denen
      `wrangler whoami` an `/memberships` scheitert (Ticket #62); rc=1, wenn nicht genau ein Konto sichtbar ist.

  rollout_warten.py instanzen
      Druckt jede nicht-inaktive Instanz; rc=1 wenn mindestens eine läuft, sonst 0. Fürs Deploy-Gate
      ("Abbruch bei laufenden Container-Instanzen außer --erzwingen").

  rollout_warten.py neuester-tag
      Druckt das Bild-Tag des jüngsten Rollout-Eintrags (`/rollouts`, newest-first – wie schon im
      Vorgängerskript `/tmp/nestor_rollout.py` angenommen). deploy.sh ruft das direkt nach `wrangler deploy`
      auf, statt den Tag von Hand aus der Konsolenausgabe abzulesen.

  rollout_warten.py warten --tag <bildtag> [--frist 600]
      Wartet, bis ein Rollout für ein Image, dessen Name mit `:<bildtag>` endet, auf `completed` steht UND die
      Anwendung selbst dieses Image trägt. rc=1 bei `failed` oder Zeitüberschreitung.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _umgebung(name: str) -> str:
    wert = os.environ.get(name)
    if not wert:
        sys.exit(f"{name} fehlt in der Umgebung (siehe Kopfkommentar dieser Datei).")
    return wert


def _basis_url() -> str:
    konto = _umgebung("CLOUDFLARE_ACCOUNT_ID")
    anwendung = _umgebung("NESTOR_APPLICATION_ID")
    return f"https://api.cloudflare.com/client/v4/accounts/{konto}/containers/applications/{anwendung}"


def _get(pfad: str) -> dict:
    token = _umgebung("CLOUDFLARE_API_TOKEN")
    anfrage = urllib.request.Request(_basis_url() + pfad, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(anfrage, timeout=30) as antwort:
            return json.load(antwort)["result"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Cloudflare-API {pfad}: HTTP {e.code} – {e.read().decode(errors='replace')[:300]}")


def aktive_instanzen() -> list[dict]:
    daten = _get("/instances")
    return [i for i in daten.get("instances", []) if i.get("status", {}).get("state") != "inactive"]


def cmd_konto(_args: argparse.Namespace) -> int:
    token = _umgebung("CLOUDFLARE_API_TOKEN")
    anfrage = urllib.request.Request("https://api.cloudflare.com/client/v4/accounts",
                                     headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(anfrage, timeout=30) as antwort:
            konten = json.load(antwort).get("result") or []
    except urllib.error.HTTPError as e:
        sys.exit(f"Cloudflare-API /accounts: HTTP {e.code}")
    if len(konten) != 1:
        sys.exit(f"Erwartet genau ein Konto, sichtbar: {len(konten)} – CLOUDFLARE_ACCOUNT_ID von Hand setzen.")
    print(konten[0]["id"])
    return 0


def cmd_instanzen(_args: argparse.Namespace) -> int:
    aktive = aktive_instanzen()
    for i in aktive:
        print(f"aktiv: {i.get('id', '?')} {i.get('status')} {i.get('image')}")
    if not aktive:
        print("keine aktiven Instanzen")
    return 1 if aktive else 0


def cmd_neuester_tag(_args: argparse.Namespace) -> int:
    rollouts = _get("/rollouts?limit=1")
    if not rollouts:
        sys.exit("Kein Rollout gefunden.")
    bild = rollouts[0].get("target_configuration", {}).get("image", "")
    tag = bild.rsplit(":", 1)[-1] if ":" in bild else ""
    if not tag:
        sys.exit(f"Konnte kein Bild-Tag aus {bild!r} lesen.")
    print(tag)
    return 0


def cmd_warten(args: argparse.Namespace) -> int:
    frist = time.monotonic() + args.frist
    bisheriger_status = None
    while time.monotonic() < frist:
        anwendung = _get("")
        rollouts = _get("/rollouts?limit=5")
        rollout = next(
            (r for r in rollouts if r.get("target_configuration", {}).get("image", "").endswith(f":{args.tag}")),
            None,
        )
        status = rollout.get("status") if rollout else "wartet"
        if status != bisheriger_status:
            print(f"Container-Rollout {args.tag}: {status}", flush=True)
            bisheriger_status = status
        if status == "completed" and anwendung.get("configuration", {}).get("image", "").endswith(f":{args.tag}"):
            return 0
        if status == "failed":
            print("Container-Rollout fehlgeschlagen", file=sys.stderr)
            return 1
        time.sleep(5)
    print(f"Container-Rollout nicht innerhalb {args.frist:.0f}s abgeschlossen", file=sys.stderr)
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="befehl", required=True)
    sub.add_parser("konto")
    sub.add_parser("instanzen")
    sub.add_parser("neuester-tag")
    pw = sub.add_parser("warten")
    pw.add_argument("--tag", required=True, help="Bild-Tag, z. B. aus 'rollout_warten.py neuester-tag'")
    pw.add_argument("--frist", type=float, default=600)
    args = p.parse_args()
    if args.befehl == "konto":
        return cmd_konto(args)
    if args.befehl == "instanzen":
        return cmd_instanzen(args)
    if args.befehl == "neuester-tag":
        return cmd_neuester_tag(args)
    return cmd_warten(args)


if __name__ == "__main__":
    sys.exit(main())
