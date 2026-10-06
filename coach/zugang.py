"""Zugang fürs Handy: Wer nicht am Laptop selbst sitzt, braucht den Kopplungscode.

Der Coach lauscht weiter nur auf 127.0.0.1. Ins Netz kommt er über `tailscale serve` (HTTPS mit echtem Zertifikat,
nur im eigenen Tailnet). Solche Anfragen kommen ebenfalls von 127.0.0.1, tragen aber die Weiterleitungs-Kopfzeilen –
daran erkennt der Coach, dass sie nicht vom Laptop stammen. Der Code steckt im QR-Code am Laptop; einmal gekoppelt,
merkt sich das Handy ihn als Cookie.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from functools import lru_cache
from http.cookies import SimpleCookie
from pathlib import Path

from .config import SCHLUESSEL_DATEI

KOPPLUNG_DATEI = Path(os.getenv("LMC_KOPPLUNG_DATEI", str(SCHLUESSEL_DATEI.parent / "kopplung")))
COOKIE = "lmc_kopplung"
# ohne Code erreichbar: die Handy-Seite selbst (zeigt dann die Code-Eingabe) und ihre Bausteine
OFFEN = ("/handy", "/handy.webmanifest", "/sw.js")
WEITERGELEITET = (b"x-forwarded-for", b"forwarded", b"tailscale-user-login", b"x-forwarded-host")
_ZEICHEN = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # ohne I, L, O, 0, 1 – am Handy eintippbar


def code() -> str:
    """Kopplungscode (8 Zeichen), bleibt über Neustarts gleich, damit gekoppelte Handys gekoppelt bleiben."""
    try:
        c = KOPPLUNG_DATEI.read_text(encoding="utf-8").strip()
        if c:
            return c
    except OSError:
        pass
    c = "".join(secrets.choice(_ZEICHEN) for _ in range(8))
    KOPPLUNG_DATEI.parent.mkdir(parents=True, exist_ok=True)
    KOPPLUNG_DATEI.write_text(c, encoding="utf-8")
    if os.name != "nt":
        os.chmod(KOPPLUNG_DATEI, 0o600)
    return c


def normalisieren(eingabe: str) -> str:
    return "".join(z for z in eingabe.upper() if z.isalnum())


def code_passt(eingabe: str | None) -> bool:
    return bool(eingabe) and secrets.compare_digest(normalisieren(eingabe), code())


def lokal(scope: dict) -> bool:
    """Anfrage vom Laptop selbst – nicht über tailscale serve oder einen anderen Vermittler weitergereicht."""
    host = (scope.get("client") or ("", 0))[0]
    if host not in ("127.0.0.1", "::1", "localhost"):
        return False
    return not any(k in WEITERGELEITET for k, _ in scope.get("headers", []))


def _cookie(scope: dict) -> str | None:
    for k, v in scope.get("headers", []):
        if k == b"cookie":
            c = SimpleCookie()
            try:
                c.load(v.decode("latin-1"))
            except Exception:  # noqa: BLE001 – kaputte Cookies anderer Seiten ignorieren
                continue
            if COOKIE in c:
                return c[COOKIE].value
    return None


def gekoppelt(scope: dict) -> bool:
    return code_passt(_cookie(scope))


@lru_cache(maxsize=1)
def adresse() -> str | None:
    """HTTPS-Adresse im Tailnet (LMC_HANDY_URL oder der MagicDNS-Name dieses Rechners)."""
    if os.getenv("LMC_HANDY_URL"):
        return os.getenv("LMC_HANDY_URL").rstrip("/")
    try:
        aus = subprocess.run(["tailscale", "status", "--json"], capture_output=True, timeout=5, check=True).stdout
        name = (json.loads(aus).get("Self") or {}).get("DNSName", "").rstrip(".")
        return f"https://{name}" if name else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class Zugangsschutz:
    """ASGI-Middleware für HTTP und WebSocket: vom Laptop alles, von außen nur gekoppelt."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or lokal(scope):
            return await self.app(scope, receive, send)
        pfad = scope.get("path", "")
        if pfad in OFFEN or pfad.startswith("/static/") or gekoppelt(scope):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 4401})
            return
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json; charset=utf-8")]})
        await send({"type": "http.response.body",
                    "body": json.dumps({"detail": "Nicht gekoppelt – Code vom Laptop eingeben."}).encode()})

