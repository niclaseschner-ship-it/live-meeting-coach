"""Datenspende im Cloud-Betrieb: Ablage in R2 statt auf der lokalen Platte (Ticket #5, #82).

Der Container hat keinen eigenen Zugriff auf Cloudflare R2 – er schickt jede Datei EINZELN an eine Route des
eigenen Worker (`PUT /intern/spende/<name>/<datei>`, `cloudflare/src/index.ts`), die sich mit demselben
Geheimnis ausweist wie der Worker beim Coach (`X-Nestor-Geheimnis`, Secret `LMC_WORKER_GEHEIMNIS`) und
`request.body` ohne Umweg über `formData()`/`arrayBuffer()` in den Bucket `nestor-spenden` (Jurisdiktion `eu`)
streamt. Ein abschließender `POST .../abschluss` fasst das Ergebnis zusammen und löst dort die einzige
Telegram-Meldung aus (ohne Dateiinhalte – nur Größe/Status/Dauer je Datei).

Ticket #82 (Befund aus dem Pilot vom 10.10.): vormals EIN Multipart-Körper mit allen Dateien, von Hand gebaut
und per `urllib` mit `timeout=30` verschickt – im Worker verdoppelte `formData()`/`arrayBuffer()` eine 45-MB-
Aufnahme auf 90–135 MB bei einer festen 128-MB-Grenze je Isolate. Jetzt: je Datei ein eigener PUT, von der
Platte gestreamt (nie ganz in den Speicher gelesen – `http.client` sendet ein Dateiobjekt in Blöcken), Timeout
nach Dateigröße gestaffelt. Scheitert eine Datei (typischerweise die große, optionale Aufnahme), laufen die
übrigen trotzdem weiter – die Spende gilt dann als teilweise angekommen statt insgesamt zu scheitern.

`R2Ablage` erfüllt die `Ablage`-Schnittstelle aus `coach/abschluss.py`; `coach/api_abschluss.py` wählt sie im
Cloud-Betrieb und ruft sie in einem Thread auf. Ohne eigene Abhängigkeit (kein httpx im Projekt): weiterhin
`urllib.request`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .abschluss import Ablage, SpendeDatei, SpendeErgebnis, SpendeTeilergebnis
from .config import EINST, WORKER_USER_AGENT

# Sockel-Zeit plus ein Zuschlag je MB (Ticket #82: feste 30 s reichten für eine stockende 45-MB-Aufnahme über
# die Edge nicht zuverlässig – das war der wahrscheinlichste Grund des gescheiterten ersten Versuchs). Bewusst
# großzügig nach oben begrenzt – ein zu früher Timeout ist schlimmer als ein paar Sekunden mehr Geduld.
_TIMEOUT_SOCKEL_SEKUNDEN = 20.0
_TIMEOUT_JE_MB_SEKUNDEN = 2.0
_TIMEOUT_MAX_SEKUNDEN = 300.0
# Meldung an den Worker, dass die Spende abgeschlossen ist – unabhängig von der Dateigröße, kurz.
_ABSCHLUSS_TIMEOUT_SEKUNDEN = 10.0


class AblageFehler(RuntimeError):
    pass


def _timeout_fuer(groesse_bytes: int) -> float:
    return min(_TIMEOUT_MAX_SEKUNDEN, _TIMEOUT_SOCKEL_SEKUNDEN + _TIMEOUT_JE_MB_SEKUNDEN * (groesse_bytes / (1024 * 1024)))


def _datei_hochladen(url: str, datei: SpendeDatei, geheimnis: str) -> SpendeTeilergebnis:
    """Lädt eine Datei per PUT hoch – Text kommt als `bytes`, die Aufnahme wird vom Datenträger gestreamt
    (`http.client` liest ein Dateiobjekt blockweise, siehe Moduldoc), nie ganz in den Speicher gelesen."""
    groesse = datei.groesse()
    koerper = datei.inhalt if datei.inhalt is not None else open(datei.pfad, "rb")  # type: ignore[arg-type]
    try:
        anfrage = urllib.request.Request(
            url, data=koerper, method="PUT",
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(groesse),
                     "User-Agent": WORKER_USER_AGENT, "X-Nestor-Geheimnis": geheimnis},
        )
        with urllib.request.urlopen(anfrage, timeout=_timeout_fuer(groesse)):
            pass
        return SpendeTeilergebnis(datei.name, groesse, True)
    except (urllib.error.URLError, OSError, TimeoutError):
        return SpendeTeilergebnis(datei.name, groesse, False)
    finally:
        if koerper is not datei.inhalt:
            koerper.close()  # type: ignore[union-attr]


def _abschluss_melden(url: str, teile: list[SpendeTeilergebnis], dauer_sekunden: float, geheimnis: str) -> None:
    """Best-effort: löst beim Worker die eine Telegram-Meldung aus. Schlägt nur dieser Ruf fehl, bleibt die
    Spende trotzdem stehen – das ist keine Ablage-Panne, nur eine fehlende Benachrichtigung."""
    body = json.dumps({
        "ergebnisse": [{"datei": t.datei, "bytes": t.bytes, "ok": t.ok} for t in teile],
        "dauerMs": round(dauer_sekunden * 1000),
    }).encode("utf-8")
    anfrage = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body)),
                 "User-Agent": WORKER_USER_AGENT, "X-Nestor-Geheimnis": geheimnis},
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=_ABSCHLUSS_TIMEOUT_SEKUNDEN):
            pass
    except (urllib.error.URLError, OSError, TimeoutError):
        pass


class R2Ablage(Ablage):
    """Datenspende über den Worker nach R2 (`nestor-spenden`, Jurisdiktion eu). Nur im Cloud-Betrieb nutzbar."""

    def ablegen(self, name: str, dateien: list[SpendeDatei]) -> SpendeErgebnis:
        if not EINST.worker_url or not EINST.worker_geheimnis:
            raise AblageFehler("LMC_WORKER_URL/LMC_WORKER_GEHEIMNIS fehlen – keine Spende ohne Worker.")
        if not dateien:
            return SpendeErgebnis([], 0.0)
        basis = EINST.worker_url.rstrip("/")
        start = time.monotonic()
        # Texte zuerst, Aufnahme zuletzt (Reihenfolge kommt bereits aus spenden_dateien): scheitert die letzte,
        # große Datei, sind die vorherigen trotzdem schon oben.
        teile = [
            _datei_hochladen(f"{basis}/intern/spende/{name}/{datei.name}", datei, EINST.worker_geheimnis)
            for datei in dateien
        ]
        dauer = time.monotonic() - start
        _abschluss_melden(f"{basis}/intern/spende/{name}/abschluss", teile, dauer, EINST.worker_geheimnis)
        return SpendeErgebnis(teile, dauer)
