"""Datenspende im Cloud-Betrieb: Ablage in R2 statt auf der lokalen Platte.

Der Container hat keinen eigenen Zugriff auf Cloudflare R2 – er schickt jede Datei EINZELN an eine Route des
eigenen Worker (`cloudflare/src/index.ts`), die sich mit demselben Geheimnis ausweist wie der Worker beim Coach
(`X-Nestor-Geheimnis`, Secret `LMC_WORKER_GEHEIMNIS`) und den Körper ohne Umweg über `formData()`/`arrayBuffer()`
in den Bucket `nestor-spenden` (Jurisdiktion `eu`) streamt. Ein abschließender `POST .../abschluss` fasst das
Ergebnis zusammen und löst dort die einzige Telegram-Meldung aus (ohne Dateiinhalte – nur Größe/Status/Dauer
je Datei).

Eine Datei bis `_TEIL_SCHWELLE_BYTES` geht als ein einzelner `PUT /intern/spende/<name>/<datei>`, von der Platte
gestreamt (nie ganz in den Speicher gelesen – `http.client` sendet ein Dateiobjekt in Blöcken). Darüber (eine
Cloudflare-Anfrage ist auf rund 100 MB begrenzt) lädt sie in festen Teilen über R2s Multipart-API: ein Start-
Request holt die Upload-ID, dann ein `PUT ...?teil=<n>&upload=<id>` je Teil (mit 1–2 Wiederholungen bei einem
gescheiterten Teil), zuletzt `POST ...?teile=fertig` mit der Liste der Teile. Scheitert eine Datei vollständig
(typischerweise die große, optionale Aufnahme), laufen die übrigen trotzdem weiter – die Spende gilt dann als
teilweise angekommen statt insgesamt zu scheitern. Timeout je Anfrage ist nach ihrer Größe gestaffelt statt fix.

`R2Ablage` erfüllt die `Ablage`-Schnittstelle aus `coach/abschluss.py`; `coach/api_abschluss.py` wählt sie im
Cloud-Betrieb und ruft sie in einem Thread auf. Ohne eigene Abhängigkeit (kein httpx im Projekt): weiterhin
`urllib.request`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from .abschluss import Ablage, SpendeDatei, SpendeErgebnis, SpendeTeilergebnis
from .config import EINST, WORKER_USER_AGENT

# Sockel-Zeit plus ein Zuschlag je MB. Bewusst großzügig nach oben begrenzt – ein zu früher Timeout ist
# schlimmer als ein paar Sekunden mehr Geduld.
_TIMEOUT_SOCKEL_SEKUNDEN = 20.0
_TIMEOUT_JE_MB_SEKUNDEN = 2.0
_TIMEOUT_MAX_SEKUNDEN = 300.0
# Meldung an den Worker, dass die Spende abgeschlossen ist – unabhängig von der Dateigröße, kurz.
_ABSCHLUSS_TIMEOUT_SEKUNDEN = 10.0

# Muss zur Worker-Härtung passen (cloudflare/src/index.ts, SPENDE_TEIL_MAX_BYTES/-ANZAHL): je Teil höchstens
# _TEIL_GROESSE_BYTES, höchstens _TEIL_MAX_ANZAHL Teile. Ab dieser Schwelle lohnt sich Multipart – Cloudflare
# begrenzt den Körper einer einzelnen Anfrage auf rund 100 MB, deutlich unter der 300-MB-Gesamtobergrenze.
_TEIL_GROESSE_BYTES = 50 * 1024 * 1024
_TEIL_MAX_ANZAHL = 6
_TEIL_SCHWELLE_BYTES = _TEIL_GROESSE_BYTES
_TEIL_WIEDERHOLUNGEN = 2


class AblageFehler(RuntimeError):
    pass


def _timeout_fuer(groesse_bytes: int) -> float:
    return min(_TIMEOUT_MAX_SEKUNDEN, _TIMEOUT_SOCKEL_SEKUNDEN + _TIMEOUT_JE_MB_SEKUNDEN * (groesse_bytes / (1024 * 1024)))


def _anfrage(url: str, methode: str, koerper: bytes, laenge: int, geheimnis: str,
             content_type: str, timeout: float) -> dict[str, Any] | None:
    """Eine einzelne Anfrage an den Worker – `None` statt einer Ausnahme bei jedem Netz-/Zeitfehler, damit die
    Aufrufer entscheiden, ob sie es noch einmal versuchen oder die Datei als gescheitert werten."""
    anfrage = urllib.request.Request(
        url, data=koerper, method=methode,
        headers={"Content-Type": content_type, "Content-Length": str(laenge),
                 "User-Agent": WORKER_USER_AGENT, "X-Nestor-Geheimnis": geheimnis},
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None


def _teile_lesen(datei: SpendeDatei, teilgroesse: int) -> Iterator[bytes]:
    """Liefert eine Datei in festen Blöcken – von der Platte gelesen (nie ganz im Speicher) oder aus `inhalt`
    geschnitten, je nachdem, was `SpendeDatei` trägt."""
    if datei.pfad is not None:
        with open(datei.pfad, "rb") as f:
            while True:
                block = f.read(teilgroesse)
                if not block:
                    break
                yield block
    else:
        inhalt = datei.inhalt or b""
        for i in range(0, len(inhalt), teilgroesse):
            yield inhalt[i:i + teilgroesse]


def _einzeln_hochladen(url: str, datei: SpendeDatei, geheimnis: str) -> SpendeTeilergebnis:
    """Lädt eine Datei in einem Stück hoch – Text kommt als `bytes`, die Aufnahme wird vom Datenträger gestreamt
    (`http.client` liest ein Dateiobjekt blockweise), nie ganz in den Speicher gelesen."""
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


def _mehrteilig_hochladen(url: str, datei: SpendeDatei, geheimnis: str) -> SpendeTeilergebnis:
    """Lädt eine große Datei in festen Teilen hoch: Start → je Teil ein PUT (mit Wiederholungen) → Abschluss.
    Scheitert ein Teil auch nach den Wiederholungen, gilt die ganze Datei als gescheitert – ein unvollständiger
    Multipart-Upload bleibt dann im Bucket liegen, bis R2 ihn selbst aufräumt."""
    groesse = datei.groesse()
    leerer_koerper = b"{}"
    start_antwort = _anfrage(f"{url}?teile=start", "POST", leerer_koerper, len(leerer_koerper), geheimnis,
                              "application/json", _ABSCHLUSS_TIMEOUT_SEKUNDEN)
    upload_id = start_antwort.get("uploadId") if start_antwort else None
    if not upload_id:
        return SpendeTeilergebnis(datei.name, groesse, False)

    teile: list[dict[str, Any]] = []
    for nr, block in enumerate(_teile_lesen(datei, _TEIL_GROESSE_BYTES), start=1):
        ergebnis = None
        for _ in range(_TEIL_WIEDERHOLUNGEN):
            ergebnis = _anfrage(f"{url}?teil={nr}&upload={upload_id}", "PUT", block, len(block), geheimnis,
                                 "application/octet-stream", _timeout_fuer(len(block)))
            if ergebnis is not None:
                break
        if ergebnis is None or not ergebnis.get("etag"):
            return SpendeTeilergebnis(datei.name, groesse, False)
        teile.append({"partNumber": nr, "etag": ergebnis["etag"]})

    koerper = json.dumps({"uploadId": upload_id, "teile": teile}).encode("utf-8")
    fertig = _anfrage(f"{url}?teile=fertig", "POST", koerper, len(koerper), geheimnis,
                       "application/json", _ABSCHLUSS_TIMEOUT_SEKUNDEN)
    return SpendeTeilergebnis(datei.name, groesse, fertig is not None)


def _datei_hochladen(url: str, datei: SpendeDatei, geheimnis: str) -> SpendeTeilergebnis:
    if datei.groesse() > _TEIL_SCHWELLE_BYTES:
        return _mehrteilig_hochladen(url, datei, geheimnis)
    return _einzeln_hochladen(url, datei, geheimnis)


def _abschluss_melden(url: str, teile: list[SpendeTeilergebnis], dauer_sekunden: float, geheimnis: str) -> None:
    """Best-effort: löst beim Worker die eine Telegram-Meldung aus. Schlägt nur dieser Ruf fehl, bleibt die
    Spende trotzdem stehen – das ist keine Ablage-Panne, nur eine fehlende Benachrichtigung."""
    body = json.dumps({
        "ergebnisse": [{"datei": t.datei, "bytes": t.bytes, "ok": t.ok} for t in teile],
        "dauerMs": round(dauer_sekunden * 1000),
    }).encode("utf-8")
    _anfrage(url, "POST", body, len(body), geheimnis, "application/json", _ABSCHLUSS_TIMEOUT_SEKUNDEN)


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
