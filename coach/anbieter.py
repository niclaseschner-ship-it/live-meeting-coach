"""Anbieter (Ticket #60): die einzige Stelle mit Endpunkten der KI-Anbieter und die Fabrik für alle KI-Verbindungen.

Nestor Premium spricht ausschließlich mit OpenAI, Nestor Basis ausschließlich mit Mistral. Damit das nicht nur
Konvention ist, gilt hier dreierlei:

1. **Eine Wahl je Meeting.** `Anbieterwahl` ist unveränderlich (frozen) und enthält Stufe, Anbieter, die
   erlaubten Ziele und alle Modelle der Stufe. Es gibt keine Vorgabe-Stufe: ohne bestätigte Wahl kein Client und kein
   Meetingstart (coach/server.py). Während eines Meetings lässt sich die Wahl nicht wechseln (coach/pipeline.py).
2. **Nur die Fabrik baut Verbindungen.** `client_fuer` (REST, OpenAI-SDK bzw. MistralClient) und `ws_verbinden`
   (WebSockets) bekommen die Wahl; kein anderes Modul kennt Endpunkte oder öffnet selbst Verbindungen
   (tests/test_anbieter.py prüft das statisch).
3. **Hostwache.** Jede ausgehende Anfrage – httpx-Transport und jeder WebSocket-Aufbau – wird vorher gegen die Ziele
   der Wahl geprüft. Ein Verstoß ist ein harter Fehler (`AnbieterVerstoss`) mit Meldung an den Coach; es gibt keinen
   Rückfall auf einen anderen Anbieter.

Endpunkte lassen sich für Tests und Attrappen umlenken (`LMC_OPENAI_URL`, `LMC_OPENAI_WS_URL`, `LMC_MISTRAL_URL`,
`LMC_MISTRAL_WS_URL`); unverschlüsselt (`http://`, `ws://`) nur zu Loopback-Adressen. Die erlaubten Ziele einer Stufe
leiten sich aus genau diesen Endpunkten ab (Host und Port).
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

try:  # openai 3.x bringt httpx2 mit, ältere Versionen httpx – beide haben dieselbe Schnittstelle
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx  # type: ignore[no-redef]

from .config import EINST, mistral_schluessel, openai_schluessel

log = logging.getLogger("coach.anbieter")

STUFEN = ("basis", "premium")
ANBIETER = {"premium": "openai", "basis": "mistral"}


# --- Endpunkte -------------------------------------------------------------------------------------------------------
def openai_url() -> str:
    return os.getenv("LMC_OPENAI_URL") or "https://api.openai.com/v1"


def openai_ws_url() -> str:
    return os.getenv("LMC_OPENAI_WS_URL") or "wss://api.openai.com/v1/realtime"


def mistral_url() -> str:
    return os.getenv("LMC_MISTRAL_URL") or "https://api.mistral.ai/v1"


def mistral_ws_url() -> str:
    return os.getenv("LMC_MISTRAL_WS_URL") or "wss://api.mistral.ai/v1/audio/transcriptions/realtime"


class AnbieterFehler(RuntimeError):
    """Diese Funktion gibt es in der gewählten Stufe nicht, oder die Wahl/Konfiguration ist ungültig."""


class AnbieterVerstoss(AnbieterFehler):
    """Eine Verbindung sollte zu einem Ziel außerhalb der gewählten Stufe gehen – abgebrochen, kein Rückfall."""


_STANDARDPORT = {"https": 443, "wss": 443, "http": 80, "ws": 80}


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ziel(url: str) -> str:
    """„host:port“ einer URL – die Einheit, gegen die die Hostwache prüft."""
    teile = urlsplit(url)
    host = (teile.hostname or "").lower()
    port = teile.port or _STANDARDPORT.get(teile.scheme, 0)
    return f"{host}:{port}"


def _endpunkte(anbieter: str) -> tuple[str, ...]:
    return (openai_url(), openai_ws_url()) if anbieter == "openai" else (mistral_url(), mistral_ws_url())


def ziele_fuer(anbieter: str) -> frozenset[str]:
    """Erlaubte Ziele eines Anbieters, abgeleitet aus seinen Endpunkten. Unverschlüsselt nur zu Loopback."""
    aus = set()
    for url in _endpunkte(anbieter):
        teile = urlsplit(url)
        if teile.scheme not in _STANDARDPORT or not teile.hostname:
            raise AnbieterFehler(f"Ungültiger Endpunkt für {anbieter}.")
        if teile.scheme in ("http", "ws") and not _loopback(teile.hostname):
            raise AnbieterFehler(f"Unverschlüsselter Endpunkt für {anbieter} nur zu Loopback erlaubt.")
        aus.add(ziel(url))
    return frozenset(aus)


# --- Die Wahl ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Anbieterwahl:
    """Stufe, Anbieter, erlaubte Ziele und alle Modelle eines Meetings – einmal gebaut, nie verändert.
    Felder, die es in einer Stufe nicht gibt (Realtime, Bild in Basis), sind None."""

    stufe: str
    anbieter: str
    hosts: frozenset[str]
    live_modell: str
    text_modell: str
    analyse_modell: str
    analyse_aufwand: str
    zuordnung_modell: str
    assistent_modell: str
    assistent_aufwand: str
    recherche_modell: str
    recherche_aufwand: str
    einordnen_aufwand: str
    stimme_modell: str
    stimme: str
    assistent_modus: str  # „gespraech“ (Realtime, nur Premium) oder „text“
    bild_anbieter: str  # „openai“ (Live-Bild) oder „text“ (Überblick als Text, Basis)
    nachfrage_sekunden: float
    realtime_modell: str | None = None
    bild_modell: str | None = None
    bild_text_modell: str | None = None
    begruessung_transkription: str | None = None
    begruessung_modell: str | None = None  # Basis: frei formulierte Begrüßung (Mistral)

    @property
    def basis(self) -> bool:
        return self.stufe == "basis"

    @property
    def premium(self) -> bool:
        return self.stufe == "premium"

    def mit(self, **aenderungen) -> "Anbieterwahl":
        """Laufzeitwahl innerhalb desselben Anbieters (Premium: Stimme, Gesprächsart). Stufe, Anbieter und Ziele
        bleiben – alles andere ist eine neue Wahl zwischen zwei Meetings."""
        erlaubt = {"stimme", "assistent_modus"}
        if not self.premium or set(aenderungen) - erlaubt:
            raise AnbieterFehler("Nur Stimme und Gesprächsart von Premium sind zur Laufzeit änderbar.")
        return replace(self, **aenderungen)


def premium_vorlieben() -> dict:
    """Ausgangswerte der Premium-Laufzeitwahl (Stimme, Gesprächsart) aus der Umgebung."""
    return {"stimme": EINST.stimme, "assistent_modus": EINST.assistent_modus}


def wahl_fuer(stufe: str, *, stimme: str | None = None,
              assistent_modus: str | None = None) -> Anbieterwahl:
    """Die einzige Stelle, an der aus einer Stufe Anbieter, Ziele und Modelle werden. Premium: die Werte aus der
    Umgebung (coach/config.py); Basis: die Mistral-Gegenstücke (`basis_*`)."""
    if stufe not in STUFEN:
        raise ValueError(f"Unbekannte Stufe: {stufe}")
    anbieter = ANBIETER[stufe]
    ziele = ziele_fuer(anbieter)
    andere = ziele_fuer("mistral" if anbieter == "openai" else "openai")
    gemeinsam = ziele & andere
    if gemeinsam and not all(_loopback(z.rsplit(":", 1)[0]) for z in gemeinsam):
        raise AnbieterFehler("OpenAI- und Mistral-Endpunkte zeigen auf dasselbe Ziel – Stufen wären nicht getrennt.")
    e = EINST
    if stufe == "basis":
        # Nestor antwortet über Text + Sprachausgabe (kein Realtime-Gespräch); Funkgerät (Ticket #27): Sprechtaste
        # statt Name, kein Rückfrage-Fenster; statt des Live-Bilds der Überblick als Text (kein Bildmodell).
        # Mistral kennt keinen Denkaufwand „low“ – leer.
        return Anbieterwahl(
            stufe=stufe, anbieter=anbieter, hosts=ziele,
            live_modell=e.basis_live_modell, text_modell=e.basis_transkription,
            analyse_modell=e.basis_text_modell, analyse_aufwand="", zuordnung_modell=e.basis_zuordnung_modell,
            assistent_modell=e.basis_text_modell, assistent_aufwand="",
            recherche_modell=e.basis_text_modell, recherche_aufwand="", einordnen_aufwand="",
            stimme_modell=e.basis_stimme_modell, stimme=e.basis_stimme, assistent_modus="text",
            bild_anbieter="text", nachfrage_sekunden=0.0, begruessung_modell=e.basis_begruessung_modell)
    return Anbieterwahl(
        stufe=stufe, anbieter=anbieter, hosts=ziele,
        live_modell=e.live_modell, text_modell=e.text_modell,
        analyse_modell=e.analyse_modell, analyse_aufwand=e.analyse_aufwand,
        zuordnung_modell=e.zuordnung_modell or e.analyse_modell,
        assistent_modell=e.assistent_modell, assistent_aufwand=e.assistent_aufwand,
        recherche_modell=e.recherche_modell, recherche_aufwand=e.recherche_aufwand,
        einordnen_aufwand=e.einordnen_aufwand,
        stimme_modell=e.stimme_modell, stimme=stimme or e.stimme,
        assistent_modus=assistent_modus or e.assistent_modus,
        bild_anbieter="openai", nachfrage_sekunden=e.nachfrage_sekunden,
        realtime_modell=e.realtime_modell, bild_modell=e.bild_modell, bild_text_modell=e.bild_text_modell,
        begruessung_transkription=e.begruessung_transkription)


# --- Schlüssel ---------------------------------------------------------------------------------------------------------
def schluessel(wahl: Anbieterwahl) -> str | None:
    return openai_schluessel() if wahl.anbieter == "openai" else mistral_schluessel()


def bereit(stufe: str) -> bool:
    """Gibt es für die Stufe einen Schlüssel auf dem Server? (LMC_OFFLINE=1: beide wählbar, es geht nichts hinaus)"""
    if os.getenv("LMC_OFFLINE") == "1":
        return True
    return bool(openai_schluessel() if ANBIETER.get(stufe) == "openai" else mistral_schluessel())


def ki_verfuegbar(wahl: Anbieterwahl | None) -> bool:
    """Schlüssel der gewählten Stufe vorhanden und Offline-Modus aus?"""
    return wahl is not None and os.getenv("LMC_OFFLINE") != "1" and bool(schluessel(wahl))


# --- Hostwache -----------------------------------------------------------------------------------------------------------
# Ticket #62 (Stufe C): was die Hostwache in diesem Prozess gesehen hat – je Ziel Stufe, Anzahl und ob erlaubt. Nur
# Host und Port, nie Pfade, Inhalte oder Schlüssel. Im Cloud-Betrieb ist ein Container genau ein Meeting, das Protokoll
# gilt also je Meeting. Lesbar über /api/intern/anbieter-protokoll (nur mit Worker-Geheimnis) und in technik.json.
_GESEHEN: dict[tuple[str, str], dict] = {}


def _merken(z: str, wahl: Anbieterwahl, erlaubt: bool) -> None:
    eintrag = _GESEHEN.setdefault((wahl.stufe, z), {"ziel": z, "stufe": wahl.stufe, "erlaubt": erlaubt, "anzahl": 0})
    eintrag["anzahl"] += 1


def gesehen() -> list[dict]:
    """Alle Ziele, die die Hostwache bisher geprüft hat (erlaubte wie abgewiesene), sortiert."""
    return [dict(e) for _, e in sorted(_GESEHEN.items())]


def pruefen(wahl: Anbieterwahl, url: str, bei_verstoss=None) -> None:
    """Vor jeder Verbindung: Ziel der URL muss zur Wahl gehören. Sonst Meldung und `AnbieterVerstoss`."""
    z = ziel(url)
    _merken(z, wahl, z in wahl.hosts)
    if z in wahl.hosts:
        return
    log.error("Anbieter-Sperre: %s ist in Nestor %s nicht erlaubt", z, wahl.stufe)
    if bei_verstoss is not None:
        try:
            bei_verstoss(z, wahl)
        except Exception:  # noqa: BLE001 – die Sperre selbst darf an der Meldung nicht scheitern
            log.exception("Meldung des Anbieter-Verstoßes fehlgeschlagen")
    raise AnbieterVerstoss(f"Verbindung zu {z} ist in Nestor {wahl.stufe.capitalize()} nicht erlaubt.")


class Hostwache(httpx.AsyncBaseTransport):
    """httpx-Transport, der jede Anfrage vor dem Senden gegen die Ziele der Wahl prüft."""

    def __init__(self, wahl: Anbieterwahl, bei_verstoss=None, innen: httpx.AsyncBaseTransport | None = None) -> None:
        self.wahl = wahl
        self._bei_verstoss = bei_verstoss
        self._innen = innen or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        pruefen(self.wahl, str(request.url), self._bei_verstoss)
        return await self._innen.handle_async_request(request)

    async def aclose(self) -> None:
        await self._innen.aclose()


def http_client(wahl: Anbieterwahl, bei_verstoss=None, **optionen) -> httpx.AsyncClient:
    """httpx-Client mit Hostwache (für den MistralClient und die Websuche)."""
    return httpx.AsyncClient(transport=Hostwache(wahl, bei_verstoss), **optionen)


# --- Fabrik --------------------------------------------------------------------------------------------------------------
def client_fuer(wahl: Anbieterwahl | None, bei_verstoss=None):
    """Der KI-Client einer Wahl: Premium → OpenAI-SDK, Basis → MistralClient (gleiche Schnittstelle). Nie beides.
    Ohne Wahl, ohne Schlüssel oder mit LMC_OFFLINE=1: None."""
    if not ki_verfuegbar(wahl):
        return None
    if wahl.anbieter == "mistral":
        from .mistral import MistralClient

        return MistralClient(schluessel(wahl), basis_url=mistral_url(),
                             http=lambda **optionen: http_client(wahl, bei_verstoss, **optionen))
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient

    return AsyncOpenAI(api_key=schluessel(wahl), base_url=openai_url(),
                       http_client=DefaultAsyncHttpxClient(transport=Hostwache(wahl, bei_verstoss)))


async def openai_schluessel_pruefen(neu: str) -> None:
    """Eigenen OpenAI-Schlüssel mit einem kostenlosen Aufruf prüfen (Dashboard/Startseite) – über die Hostwache von
    Premium. Ausnahmen des SDK gehen an den Aufrufer."""
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient

    wahl = wahl_fuer("premium")
    await AsyncOpenAI(api_key=neu, base_url=openai_url(), max_retries=0, timeout=15,
                      http_client=DefaultAsyncHttpxClient(transport=Hostwache(wahl))).models.list()


def _mit_abfrage(url: str, abfrage: str) -> str:
    return url + ("&" if "?" in url else "?") + abfrage


def live_ws(wahl: Anbieterwahl) -> tuple[str, dict]:
    """URL und Kopfzeilen des Live-Texts: Premium OpenAI Realtime-Transkription, Basis Voxtral Realtime."""
    kopf = {"Authorization": f"Bearer {schluessel(wahl)}"}
    if wahl.anbieter == "openai":
        return _mit_abfrage(openai_ws_url(), "intent=transcription"), kopf
    return _mit_abfrage(mistral_ws_url(), f"model={wahl.live_modell}"), kopf


def realtime_ws(wahl: Anbieterwahl, modell: str | None = None) -> tuple[str, dict]:
    """Realtime-Sprachmodell (Gespräch, freie Begrüßung) – nur Premium. In Basis ein harter Fehler."""
    if wahl.anbieter != "openai" or not (modell or wahl.realtime_modell):
        raise AnbieterFehler("Das Realtime-Gespräch gibt es nur in Nestor Premium.")
    return (_mit_abfrage(openai_ws_url(), f"model={modell or wahl.realtime_modell}"),
            {"Authorization": f"Bearer {schluessel(wahl)}"})


async def ws_verbinden(wahl: Anbieterwahl, url: str, kopf: dict, bei_verstoss=None, **optionen):
    """Der einzige WebSocket-Aufbau zu einem KI-Anbieter: erst die Hostwache, dann verbinden."""
    pruefen(wahl, url, bei_verstoss)
    import websockets

    return await websockets.connect(url, additional_headers=kopf, max_size=None, **optionen)
