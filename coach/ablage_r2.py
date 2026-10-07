"""Datenspende im Cloud-Betrieb: Ablage in R2 statt auf der lokalen Platte (Ticket #5).

Der Container hat keinen eigenen Zugriff auf Cloudflare R2 – er schickt die Dateien an eine Route des
eigenen Worker (`POST /intern/spende/<name>`, `cloudflare/src/index.ts`), die sich mit demselben Geheimnis
ausweist wie der Worker beim Coach (`X-Nestor-Geheimnis`, Secret `LMC_WORKER_GEHEIMNIS`). Der Worker schreibt
dann in den Bucket `nestor-spenden` (Jurisdiktion `eu`).

`R2Ablage.ablegen(name, dateien)` ist ein kleiner Vorgriff auf die `Ablage`-Schnittstelle, die im
Abschluss-Ticket (#3) entstehen soll – das Ticket existiert in diesem Stand noch nicht. Die Form
(`ablegen(name, dateien)`, `dateien` als Name → Inhalt) ist bewusst so knapp gehalten, dass eine lokale
Variante (Schreiben nach `meetings/<name>/spende/`) und diese Cloud-Variante dieselbe Schnittstelle erfüllen
können; welche Form das Abschluss-Ticket tatsächlich wählt, entscheidet es selbst – diese Klasse ist ein
Angebot, kein Vertrag.

Ohne eigene Abhängigkeit (kein httpx im Projekt): der Multipart-Körper wird von Hand gebaut, der Aufruf läuft
über `urllib.request` in einem Thread, damit er die Ereignisschleife nicht blockiert.
"""

from __future__ import annotations

import asyncio
import secrets
import urllib.error
import urllib.request

from .config import EINST


class AblageFehler(RuntimeError):
    pass


def _multipart(dateien: dict[str, bytes]) -> tuple[bytes, str]:
    grenze = secrets.token_hex(16)
    teile: list[bytes] = []
    for name, inhalt in dateien.items():
        kopf = (
            f"--{grenze}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        )
        teile.append(kopf.encode("utf-8") + inhalt + b"\r\n")
    teile.append(f"--{grenze}--\r\n".encode("utf-8"))
    return b"".join(teile), grenze


def _hochladen(url: str, body: bytes, grenze: str, geheimnis: str) -> None:
    anfrage = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={grenze}",
                 "X-Nestor-Geheimnis": geheimnis, "Content-Length": str(len(body))},
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=30):
            pass
    except urllib.error.URLError as e:
        raise AblageFehler(f"Spende nicht hochgeladen: {e}") from e


class R2Ablage:
    """Datenspende über den Worker nach R2 (`nestor-spenden`, Jurisdiktion eu). Nur im Cloud-Betrieb nutzbar."""

    async def ablegen(self, name: str, dateien: dict[str, bytes]) -> None:
        if not EINST.worker_url or not EINST.worker_geheimnis:
            raise AblageFehler("LMC_WORKER_URL/LMC_WORKER_GEHEIMNIS fehlen – keine Spende ohne Worker.")
        if not dateien:
            return
        body, grenze = _multipart(dateien)
        url = f"{EINST.worker_url.rstrip('/')}/intern/spende/{name}"
        await asyncio.to_thread(_hochladen, url, body, grenze, EINST.worker_geheimnis)
