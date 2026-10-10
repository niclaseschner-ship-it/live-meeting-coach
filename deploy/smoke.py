#!/usr/bin/env python3
"""Deploy-Helfer (Ticket #65): Smoke-Test nach einem Rollout.

Pflicht: `GET <WORKER_URL>/version` – Worker-Route ohne Login und ohne Container (cloudflare/src/index.ts),
muss den gerade deployten GIT_SHA zeigen. Das ist die eigentliche Zusicherung "der Worker trägt diesen Stand".

Optional, "falls erreichbar" (Ticket-Text): `GET <WORKER_URL>/api/version` – die Route liegt auf dem
Container (coach/server.py), der Worker reicht sie aber nur mit gültigem Login/Kopplung weiter (siehe
cloudflare/README.md "Worker-Härtung"). Ohne Sitzungs-Cookie bleibt das nicht prüfbar – deploy.sh ruft diesen
Teil nur auf, wenn `NESTOR_SMOKE_COOKIE` gesetzt ist (ein bestehendes, eingeloggtes `nestor_kunde`-Cookie;
niemals ein neues Login hierfür anlegen). Ohne das Cookie wird der Container-Check übersprungen, NICHT als
Fehler gewertet – das Starten eines Containers allein für den Smoke-Test kostet Geld und Containerplätze.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get(url: str, headers: dict | None = None) -> tuple[int, dict | None]:
    # Cloudflare weist den Standard-User-Agent „Python-urllib/…“ mit 403 ab (gefunden beim ersten Staging-Deploy, #62)
    anfrage = urllib.request.Request(url, headers={"User-Agent": "nestor-deploy-smoke/1", **(headers or {})})
    try:
        with urllib.request.urlopen(anfrage, timeout=15) as antwort:
            return antwort.status, json.loads(antwort.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--worker-url", required=True)
    p.add_argument("--erwarteter-sha", required=True)
    p.add_argument("--kunden-cookie", default="", help="optional: NESTOR_SMOKE_COOKIE, für den Container-Check")
    args = p.parse_args()

    status, daten = _get(args.worker_url.rstrip("/") + "/version")
    if status != 200 or not daten:
        print(f"FEHLER: {args.worker_url}/version antwortet mit HTTP {status}, nicht 200.", file=sys.stderr)
        return 1
    if daten.get("git_sha") != args.erwarteter_sha:
        print(f"FEHLER: Worker zeigt git_sha={daten.get('git_sha')!r}, erwartet {args.erwarteter_sha!r}.", file=sys.stderr)
        return 1
    print(f"OK: Worker /version zeigt {args.erwarteter_sha} (gebaut_am {daten.get('gebaut_am')})")

    if not args.kunden_cookie:
        print("Container /api/version übersprungen (kein NESTOR_SMOKE_COOKIE gesetzt – kein Fehler).")
        return 0
    status, daten = _get(args.worker_url.rstrip("/") + "/api/version", {"Cookie": f"nestor_kunde={args.kunden_cookie}"})
    if status != 200 or not daten:
        print(f"Container /api/version nicht erreichbar (HTTP {status}) – kein Abbruch, nur ein Hinweis.", file=sys.stderr)
        return 0
    if daten.get("git_sha") != args.erwarteter_sha:
        print(f"FEHLER: Container zeigt git_sha={daten.get('git_sha')!r}, erwartet {args.erwarteter_sha!r}.", file=sys.stderr)
        return 1
    print(f"OK: Container /api/version zeigt ebenfalls {args.erwarteter_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
