"""Zugang fürs Handy: Wer nicht am Laptop selbst sitzt, braucht den Kopplungscode.

Der Coach lauscht weiter nur auf 127.0.0.1. Ins Netz kommt er über `tailscale serve` (HTTPS mit echtem Zertifikat,
nur im eigenen Tailnet). Solche Anfragen kommen ebenfalls von 127.0.0.1, tragen aber die Weiterleitungs-Kopfzeilen –
daran erkennt der Coach, dass sie nicht vom Laptop stammen. Der Code steckt im QR-Code am Laptop; einmal gekoppelt,
merkt sich das Handy ihn als Cookie.

**Cloud-Betrieb** (`LMC_BETRIEB=cloud`, Ticket #5): Hier gibt es kein „am Laptop selbst“ mehr – jede Anfrage kommt
über den Cloudflare-Worker herein, der vorher schon das Kundenpasswort geprüft hat (`cloudflare/`). Der Worker
beweist sich mit der Kopfzeile `X-Nestor-Geheimnis` (Secret `LMC_WORKER_GEHEIMNIS`, auf beiden Seiten gleich).
Passt sie: dieselben Rechte wie „am Laptop“ – der Worker hat die eigentliche Prüfung schon gemacht. Passt sie
nicht (sollte nur bei einem direkten, nicht über den Worker laufenden Zugriff passieren), gibt es 403 für alles,
auch für die sonst offenen Seiten. Das Handy koppelt weiter ganz normal über den Kopplungscode; nur die Adresse
im QR-Code kommt dann aus der Anfrage (`Host`) statt aus `tailscale serve`.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from http.cookies import SimpleCookie
from pathlib import Path

from .config import EINST, SCHLUESSEL_DATEI

KOPPLUNG_DATEI = Path(os.getenv("LMC_KOPPLUNG_DATEI", str(SCHLUESSEL_DATEI.parent / "kopplung")))
COOKIE = "lmc_kopplung"
# ohne Code erreichbar: die Handy-Seite selbst (zeigt dann die Code-Eingabe) und ihre Bausteine
OFFEN = ("/handy", "/handy.webmanifest", "/sw.js")
WEITERGELEITET = (b"x-forwarded-for", b"forwarded", b"tailscale-user-login", b"x-forwarded-host")
_ZEICHEN = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # ohne I, L, O, 0, 1 – am Handy eintippbar

# Cloud-Betrieb: Kopfzeilen, mit denen sich der Worker und das Meeting zu erkennen geben
GEHEIMNIS_KOPFZEILE = b"x-nestor-geheimnis"
KUNDE_KOPFZEILE = b"x-nestor-kunde"
MEETING_KOPFZEILE = b"x-nestor-meeting"


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


def _kopfzeile(scope: dict, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin-1")
    return None


def worker_geheimnis_passt(scope: dict) -> bool:
    """Cloud-Betrieb: Beweis, dass die Anfrage wirklich über den eigenen Worker kam (nicht erraten)."""
    eigenes = EINST.worker_geheimnis
    fremdes = _kopfzeile(scope, GEHEIMNIS_KOPFZEILE)
    return bool(eigenes) and bool(fremdes) and secrets.compare_digest(fremdes, eigenes)


def kunde(scope: dict) -> str | None:
    """Kundenname aus der Worker-Kopfzeile – nur verlässlich, wenn worker_geheimnis_passt(scope)."""
    return _kopfzeile(scope, KUNDE_KOPFZEILE)


def meeting_id(scope: dict) -> str | None:
    """Meeting-Kennung, die der Worker aus seinem Cookie `nestor_meeting` mitgibt (Cloud-Betrieb)."""
    return _kopfzeile(scope, MEETING_KOPFZEILE)


def lokal(scope: dict) -> bool:
    """Anfrage mit Laptop-Rechten: am Laptop selbst (nicht über tailscale serve oder einen anderen Vermittler
    weitergereicht) – oder im Cloud-Betrieb, wo es „am Laptop“ nicht gibt, mit gültigem Worker-Geheimnis
    (der Worker hat die eigentliche Prüfung – das Kundenpasswort – davor schon gemacht)."""
    if EINST.betrieb == "cloud":
        return worker_geheimnis_passt(scope)
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


def _serve_adresse(status: dict, port: int) -> str | None:
    """Aus `tailscale serve status --json` die HTTPS-Adresse, die auf diesen Port weiterleitet (zweites Meeting auf
    8001 → z. B. https://laptop.ts.net:8443)."""
    for host, web in (status.get("Web") or {}).items():
        for h in (web.get("Handlers") or {}).values():
            if str(h.get("Proxy", "")).rstrip("/").endswith(f":{port}"):
                name, _, hport = host.rpartition(":")
                return f"https://{name}" + ("" if hport == "443" else f":{hport}")
    return None


_adresse: str | None = None


def adresse() -> str | None:
    """HTTPS-Adresse im Tailnet: LMC_HANDY_URL, sonst die `tailscale serve`-Freigabe für den eigenen Port.

    Nur im lokalen Betrieb – im Cloud-Betrieb gibt es kein tailscale, die Adresse kommt dort stattdessen aus
    der Anfrage selbst (`adresse_aus_host`, aufgerufen von `/api/kopplung`)."""
    global _adresse
    if EINST.betrieb == "cloud":
        return None
    if os.getenv("LMC_HANDY_URL"):
        return os.getenv("LMC_HANDY_URL").rstrip("/")
    if _adresse:  # gefunden bleibt gefunden; nicht gefunden wird beim nächsten Öffnen neu gesucht
        return _adresse
    try:
        aus = subprocess.run(["tailscale", "serve", "status", "--json"], capture_output=True, timeout=5, check=True).stdout
        _adresse = _serve_adresse(json.loads(aus or b"{}"), EINST.port)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return _adresse


def adresse_aus_host(host: str) -> str:
    """Cloud-Betrieb: Handy-Adresse aus der Anfrage (Host-Kopfzeile) – der Worker terminiert TLS, hier zählt nur der Name."""
    return f"https://{host}"


class Zugangsschutz:
    """ASGI-Middleware für HTTP und WebSocket: vom Laptop alles, von außen nur gekoppelt."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if (EINST.betrieb == "cloud" and scope["type"] in ("http", "websocket")
                and worker_geheimnis_passt(scope) and not kunde(scope)):
            pfad = scope.get("path", "")
            if pfad in OFFEN or pfad.startswith("/static/") or gekoppelt(scope):
                return await self.app(scope, receive, send)
            return await self._verweigern(scope, receive, send, 401, "Nicht gekoppelt – QR-Code erneut scannen.")
        if scope["type"] not in ("http", "websocket") or lokal(scope):
            return await self.app(scope, receive, send)
        if EINST.betrieb == "cloud":
            # Ohne das Worker-Geheimnis ist die Anfrage nicht über den Worker gekommen – 403 für alles, auch
            # für die sonst offenen Seiten; dort schützt in der Cloud ohnehin das Passwort am Worker selbst.
            return await self._verweigern(scope, receive, send, 403, "Nicht über den Worker gekommen.")
        pfad = scope.get("path", "")
        if pfad in OFFEN or pfad.startswith("/static/") or gekoppelt(scope):
            return await self.app(scope, receive, send)
        await self._verweigern(scope, receive, send, 401, "Nicht gekoppelt – Code vom Laptop eingeben.")

    @staticmethod
    async def _verweigern(scope, receive, send, status: int, meldung: str) -> None:
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
            return
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json; charset=utf-8")]})
        await send({"type": "http.response.body", "body": json.dumps({"detail": meldung}).encode()})

