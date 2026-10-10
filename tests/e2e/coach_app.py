"""Coach für die lokale Klick-E2E (Ticket #61): `coach.server:app` mit zwei Testnähten – alle hier, nichts in coach/.

1. **Netzwächter.** Jede Namensauflösung außerhalb von Loopback wird verweigert und protokolliert
   (`LMC_E2E_NETZLOG`, JSONL). Damit kann die Pipeline nie einen echten Anbieter erreichen, auch nicht bei einem
   vergessenen Endpunkt – ein solcher Versuch steht im Bericht als Fehler.
2. **Umlenkung auf die Fakes** geschieht allein über die Umgebung (`LMC_OPENAI_URL`, `LMC_OPENAI_WS_URL`,
   `LMC_MISTRAL_URL`, `LMC_MISTRAL_WS_URL`, coach/anbieter.py aus #60) – hier gibt es dafür keine Naht.
3. **Host wie hinter dem Worker.** Der lokale Worker (`LOKAL_COACH_URL`, cloudflare/src/index.ts) erreicht den Coach
   per `fetch`, der den Host aus der Ziel-URL nimmt; die ursprüngliche Adresse kommt als `X-Forwarded-Host`. In der
   Cloud sieht der Container den echten Host – das stellt diese Middleware nach, aber nur für Anfragen mit dem
   Worker-Geheimnis. Außerdem vertraut der Rückruf an den Worker (`/intern/…`) dem selbstsignierten Zertifikat von
   `wrangler dev`, und zwar ausschließlich für localhost.

Start (macht tests/e2e/lauf.py):  uvicorn tests.e2e.coach_app:app --host 127.0.0.1 --port 18000
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import time
import urllib.request
from pathlib import Path

ERLAUBT = {"localhost", "127.0.0.1", "::1", "ip6-localhost"}
_netzlog = Path(os.environ["LMC_E2E_NETZLOG"]) if os.getenv("LMC_E2E_NETZLOG") else None
_getaddrinfo = socket.getaddrinfo


def _loopback(host) -> bool:
    if host is None:
        return True
    h = host.decode() if isinstance(host, bytes) else str(host)
    return h in ERLAUBT or h.startswith("127.")


def _waechter(host, *args, **kwargs):
    if not _loopback(host):
        if _netzlog:
            import traceback

            aufrufer = [f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}" for f in traceback.extract_stack()[-8:-1]
                        if "/coach/" in f.filename]
            with _netzlog.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": round(time.time(), 3), "host": str(host), "aufrufer": aufrufer}) + "\n")
        raise OSError(f"E2E-Netzwächter: Verbindung zu {host!r} verweigert (nur Loopback erlaubt)")
    return _getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = _waechter


def _worker_tls() -> None:
    """wrangler dev --local-protocol https hat ein selbstsigniertes Zertifikat. Ohne Prüfung ist das hier vertretbar,
    weil der Netzwächter ohnehin nur Loopback-Ziele zulässt."""
    unsicher = ssl.create_default_context()
    unsicher.check_hostname = False
    unsicher.verify_mode = ssl.CERT_NONE
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPSHandler(context=unsicher)))


class HostWieHinterWorker:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            kopf = dict(scope.get("headers") or [])
            fwd = kopf.get(b"x-forwarded-host")
            geheim = os.getenv("LMC_WORKER_GEHEIMNIS", "").encode()
            if fwd and geheim and kopf.get(b"x-nestor-geheimnis") == geheim:
                neu = [(k, v) for k, v in scope["headers"] if k not in (b"host", b"x-forwarded-host")]
                neu.append((b"host", fwd))
                scope = {**scope, "headers": neu}
        await self.app(scope, receive, send)


_worker_tls()

from coach.server import app as _coach_app  # noqa: E402 – erst nach Wächter und Umlenkung

app = HostWieHinterWorker(_coach_app)
