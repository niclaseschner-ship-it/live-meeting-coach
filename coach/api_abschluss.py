"""Abschluss-Endpunkte: Paket, Unterstützung (PayPal/QR), Datenspende und Feedback.

Eigenes Modul mit APIRouter (s. Hinweis im Ticket), in coach/server.py mit einer Zeile eingebunden. Der `coach`
dort ist die eine laufende Instanz; er wird erst bei Gebrauch importiert, damit es beim Hochfahren keinen
Ringimport zwischen server.py und diesem Modul gibt.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import zugang
from .abschluss import OrdnerAblage, paket, spenden_dateien, stufen
from .ablage_r2 import AblageFehler, R2Ablage
from .config import EINST, WORKER_USER_AGENT, schluessel_info, schluessel_speichern

router = APIRouter()
_ablage = R2Ablage() if EINST.betrieb == "cloud" else OrdnerAblage()

# Muss zum Cookie-Namen MEETING_COOKIE in cloudflare/src/index.ts passen (Ticket #12).
_MEETING_COOKIE = "nestor_meeting"


async def _ablegen(dateien: dict[str, bytes]) -> None:
    """Im Thread: der R2-Weg lädt über das Netz hoch und soll die Ereignisschleife nicht aufhalten."""
    try:
        await asyncio.to_thread(_ablage.ablegen, _kurz_id(), dateien)
    except AblageFehler as e:
        raise HTTPException(502, "Die Spende ließ sich gerade nicht ablegen – bitte später noch einmal.") from e


def _kurz_id() -> str:
    return uuid.uuid4().hex[:8]


def worker_melden(pfad: str, daten: dict) -> dict | None:
    """Ruft im Cloud-Betrieb eine `/intern/`-Route des Workers auf (Ticket #12), Muster wie `ablage_r2.py`:
    beweist sich mit `X-Nestor-Geheimnis`. Genutzt für `/intern/meeting-start` (`coach/server.py`, `/api/start`)
    und `/intern/meeting-ende` (hier, `/api/abschluss/fertig`).

    Ohne Worker-Zugang (lokaler Betrieb) oder bei einem Netzfehler liefert sie `None` – ein nicht gemeldetes
    Meeting-Ende blockiert den Abschluss selbst nicht, der Platz im KundenZaehler fällt dann ohnehin nach der
    Verfallszeit (`cloudflare/src/zaehler-logik.ts`, `VERFALL_MS`) frei; ein nicht gemeldeter Start lässt das
    Meeting im Zweifel zu, statt an einer Netzstörung zu scheitern.
    """
    if EINST.betrieb != "cloud" or not EINST.worker_url or not EINST.worker_geheimnis:
        return None
    body = json.dumps(daten).encode("utf-8")
    anfrage = urllib.request.Request(
        f"{EINST.worker_url.rstrip('/')}{pfad}", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Nestor-Geheimnis": EINST.worker_geheimnis,
                 "User-Agent": WORKER_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=10) as r:
            return json.loads(r.read() or b"{}")
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None


def _nach_ende():
    """Der gemeinsame Coach, nur wenn ein Meeting beendet (und damit abgelegt) ist – sonst 409."""
    from .server import coach

    if coach.hoerstrom is not None or coach.archiv is None:
        raise HTTPException(409, "Kein beendetes Meeting vorhanden.")
    return coach


@router.get("/api/abschluss")
async def abschluss():
    coach = _nach_ende()
    kosten_usd = coach.kosten_stand()["meeting"]
    liste = stufen(kosten_usd)
    name = EINST.paypal_me or None
    # Eigener Schlüssel (Angebot auf der Startseite, config.schluessel_info): die KI-Kosten liefen übers eigene
    # OpenAI-Konto, also kein Kostenausgleich mit Stufen – nur der allgemeine Link ohne Betrag.
    eigener = schluessel_info()["quelle"] == "dashboard"
    m = coach.meeting
    # Abschluss-Kopf (Ticket #17 Punkt 3): „Danke! 11 Minuten · 4 Punkte · 2 Entscheidungen“ – Punkte aus der
    # Agenda, Entscheidungen aus den Meeting-Artefakten (Ticket #26, coach/artefakte.py) – beschlossene und vorläufige,
    # keine bloßen Vorschläge; auch ohne Agenda.
    entscheidungen = sum(1 for a in coach.artefakte.liste if a.typ == "entscheidung" and a.status != "vorschlag")
    return {
        "dauer_sekunden": round(m.jetzt(), 1),
        "kosten_usd": round(kosten_usd, 4),
        "kosten_eur": round(kosten_usd * EINST.eur_je_usd, 2),
        "eigener_schluessel": eigener,
        "punkte": len(m.agenda),
        "entscheidungen": entscheidungen,
        "stufen": liste,
        "paypal": ([{**s, "link": f"https://paypal.me/{name}/{s['betrag']}EUR"} for s in liste]
                   if name and not eigener else None),
        "paypal_allgemein": f"https://paypal.me/{name}" if name else None,
        "ablage_fertig": coach.archiv.fertig,
    }


@router.get("/api/abschluss/qr.svg")
async def abschluss_qr(betrag: float = Query(...)):
    _nach_ende()
    if not EINST.paypal_me:
        raise HTTPException(404, "Keine PayPal-Adresse hinterlegt.")
    import segno

    link = f"https://paypal.me/{EINST.paypal_me}/{betrag:g}EUR"
    svg = segno.make(link, error="m").svg_inline(scale=5, dark="#1E1B4B", border=2)
    from fastapi.responses import Response

    return Response(svg, media_type="image/svg+xml",
                     headers={"Cache-Control": "no-store", "Content-Security-Policy": "script-src 'none'"})


@router.get("/api/abschluss/paket.zip")
async def abschluss_paket(aufnahme: int = Query(0)):
    coach = _nach_ende()
    try:
        daten = paket(coach.archiv.ordner, bool(aufnahme))
    except OSError as e:
        raise HTTPException(404, "Ablage noch nicht da – bitte kurz warten.") from e
    from fastapi.responses import Response

    return Response(daten, media_type="application/zip",
                     headers={"Content-Disposition": 'attachment; filename="nestor-paket.zip"'})


@router.post("/api/abschluss/spende")
async def abschluss_spende(daten: dict):
    coach = _nach_ende()
    if daten.get("einverstanden") is not True:
        raise HTTPException(400, "Ohne das Häkchen „alle einverstanden“ keine Datenspende.")
    try:
        dateien = spenden_dateien(coach.archiv.ordner, str(daten.get("feedback") or ""), bool(daten.get("aufnahme")))
    except OSError as e:
        raise HTTPException(404, "Ablage noch nicht da – bitte kurz warten.") from e
    await _ablegen(dateien)
    return {"ok": True}


@router.post("/api/abschluss/feedback")
async def abschluss_feedback(daten: dict):
    _nach_ende()
    text = str(daten.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Kein Feedback-Text.")
    await _ablegen({"feedback.txt": text.encode("utf-8")})
    return {"ok": True}


_FEEDBACK_ARTEN = ("feedback", "funktionswunsch", "fehler")


@router.post("/api/feedback")
async def feedback_jederzeit(daten: dict):
    """Feedback-Knopf auf jeder Seite (Ticket #18, Nachtrag Niclas): jederzeit erlaubt, auch während eines
    laufenden Meetings – anders als `/api/abschluss/feedback` kein beendetes Meeting nötig. Ohne Meetinginhalte,
    über dieselbe Ablage wie die Datenspende (lokal ein Ordner, im Cloud-Betrieb R2)."""
    text = str(daten.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Kein Feedback-Text.")
    art = daten.get("art") if daten.get("art") in _FEEDBACK_ARTEN else "feedback"
    seite = str(daten.get("seite") or "")[:200]
    inhalt = f"Art: {art}\nSeite: {seite}\n\n{text}"
    await _ablegen({"feedback.txt": inhalt.encode("utf-8")})
    return {"ok": True}


@router.post("/api/abschluss/fertig")
async def abschluss_fertig(request: Request, hintergrund: BackgroundTasks):
    coach = _nach_ende()
    ordner = coach.archiv.ordner
    # Cloud-Betrieb: ein im Dashboard eingetragener eigener Schlüssel galt nur für dieses eine Meeting (Angebot
    # auf der Startseite) und wird jetzt entfernt. Lokal bleibt er wie bisher gespeichert.
    if EINST.betrieb == "cloud" and schluessel_info()["quelle"] == "dashboard":
        schluessel_speichern(None)
        coach.client_neu()
    coach.einrichten({})  # auf ein leeres Meeting zurücksetzen (wie eine neue Einrichtung)
    coach.archiv = None
    if not EINST.ablage_behalten:
        import shutil

        shutil.rmtree(ordner, ignore_errors=True)
    await coach.melden()
    if EINST.betrieb != "cloud":
        return {"ok": True}
    # Cloud (Ticket #12): dem Worker das Ende melden – er gibt den Platz im KundenZaehler frei und stoppt den
    # Container. Als Hintergrundaufgabe, damit das erst NACH dieser Antwort an den Browser passiert (die Antwort
    # läuft sonst noch durch genau den Container, der gerade gestoppt wird). Das Meeting-Cookie fällt sofort
    # weg, damit der nächste Aufruf ein neues Meeting bekommt, statt dieses (gleich gestoppte) wiederzuverwenden.
    meeting_id = zugang.meeting_id(request.scope)
    if meeting_id:
        hintergrund.add_task(
            worker_melden, "/intern/meeting-ende", {"meetingId": meeting_id, "kunde": zugang.kunde(request.scope)},
        )
    antwort = JSONResponse({"ok": True}, background=hintergrund)
    antwort.delete_cookie(_MEETING_COOKIE, path="/")
    return antwort
