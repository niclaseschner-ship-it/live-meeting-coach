"""Ticket #67: Klick-E2E für die Abschlussseite (Reihenfolge der vier Karten, Datenspende nach Zurück-Navigation).

Läuft gegen einen echten, lokal gestarteten Server (LMC_OFFLINE=1, keine echten KI-/Zahlungs-Aufrufe) und treibt
echte Browserklicks – Muster wie tests/test_pilot_ui_abnahme.py. Das beendete Meeting wird wie in test_abschluss.py
(_abgelegtes_meeting) direkt auf dem Coach gesetzt statt über Mikrofon/Handy-Kopplung simuliert – das Kopplungs- und
Mikrofonprotokoll selbst ist nicht Gegenstand dieses Tickets und wird anderswo getestet (test_server.py).

Browserprofil unter ~/.cache/lmc-e2e statt /tmp (RAM-Disk auf dem Pi, siehe Betriebsnotizen).
"""

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from coach.config import EINST
from coach.pipeline import Coach

PROFIL = Path.home() / ".cache" / "lmc-e2e"
VIER_KARTEN = ["ab-datenspende", "ab-unterstuetzung", "ab-protokoll", "ab-paket"]


def _abgelegtes_meeting() -> Coach:
    """Ein beendetes, endgültig abgelegtes Meeting – wie in test_abschluss.py."""
    async def lauf():
        c = Coach()
        c._client = None
        c.archiv_aktiv = True
        c.einrichten({"titel": "Team Runde", "agenda": [{"titel": "Start", "minuten": 5}]})
        await c.hoeren_starten()
        await c.hoeren_zufuehren(bytes(24000 * 2))  # 1 s Stille
        await c.hoeren_beenden()
        c.archiv.schreiben(endgueltig=True)
        return c
    return asyncio.run(lauf())


@pytest.fixture
def laufender_server(tmp_path, monkeypatch):
    """Echter uvicorn-Server im Hintergrundthread (nicht als Subprozess) – so bleibt der Coach aus diesem Prozess
    direkt ansprechbar, um ein beendetes Meeting zu hinterlegen, ohne Mikrofon/Handy-Kopplung durchspielen zu
    müssen."""
    monkeypatch.setenv("LMC_OFFLINE", "1")
    alt_archiv, alt_spenden, alt_paypal = EINST.archiv, EINST.spenden, EINST.paypal_me
    object.__setattr__(EINST, "archiv", str(tmp_path / "archiv"))
    object.__setattr__(EINST, "spenden", str(tmp_path / "spenden"))
    # "Nestor unterstützen" ist nur bei hinterlegtem PayPal-Link sichtbar – für die Kartenreihenfolge (#67
    # Punkt 1) müssen hier alle vier Karten zu sehen sein.
    object.__setattr__(EINST, "paypal_me", "nestor-test")

    from coach import api_abschluss, server
    from coach.abschluss import OrdnerAblage

    meeting = _abgelegtes_meeting()
    monkeypatch.setattr(server.coach, "archiv", meeting.archiv)
    monkeypatch.setattr(server.coach, "meeting", meeting.meeting)
    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setattr(server.coach, "kosten_stand", lambda: {"meeting": 0.80})
    # Eigene Ablage statt des Modul-Standards (der schon vor diesem Test mit dem alten EINST.spenden entstand) –
    # sonst landen die Testspenden außerhalb von tmp_path.
    monkeypatch.setattr(api_abschluss, "_ablage", OrdnerAblage(tmp_path / "spenden"))

    config = uvicorn.Config(server.app, host="127.0.0.1", port=0, log_level="warning")
    uv_server = uvicorn.Server(config)
    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not getattr(uv_server, "started", False) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert uv_server.started, "uvicorn-Testserver startet nicht"
    port = uv_server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        uv_server.should_exit = True
        thread.join(timeout=5)
        object.__setattr__(EINST, "archiv", alt_archiv)
        object.__setattr__(EINST, "spenden", alt_spenden)
        object.__setattr__(EINST, "paypal_me", alt_paypal)


def _kartenreihenfolge(page) -> list[str]:
    return page.eval_on_selector("#ab-inhalt", "el => [...el.children].map(c => c.id)")


def _kartenreihenfolge_sichtbar(page) -> list[str]:
    """Reihenfolge nach tatsächlicher vertikaler Position auf der Seite (CSS könnte DOM-Reihenfolge umwerfen)."""
    rects = page.eval_on_selector_all(
        "#ab-inhalt > .karte", "els => els.map(e => ({id: e.id, top: e.getBoundingClientRect().top}))")
    return [r["id"] for r in sorted(rects, key=lambda r: r["top"])]


def test_abschlussseite_reihenfolge_und_datenspende_nach_zurueck_navigation(laufender_server):
    base = laufender_server
    PROFIL.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(PROFIL), executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"],
        )
        page = context.new_page()
        page.on("dialog", lambda d: d.accept())  # #37: Bestätigung der endgültigen Löschung beim Abschließen

        # Erste Station in der Historie, damit "Zurück" später etwas Echtes anzuspringen hat.
        page.goto(base + "/", wait_until="domcontentloaded")
        page.goto(base + "/abschluss", wait_until="networkidle")
        page.wait_for_selector("#ab-inhalt:not([hidden])", timeout=10_000)

        # --- Punkt 1: Reihenfolge Datenspende → Nestor unterstützen → Meeting-Dokument → Euer Paket -------------
        for breite, hoehe in ((390, 844), (1280, 900)):  # Handy-Breite und Desktop (Ticket #67 Punkt 1)
            page.set_viewport_size({"width": breite, "height": hoehe})
            assert _kartenreihenfolge(page) == VIER_KARTEN, f"DOM-Reihenfolge bei {breite}px"
            assert _kartenreihenfolge_sichtbar(page) == VIER_KARTEN, f"sichtbare Reihenfolge bei {breite}px"

        # Keine Funktion verloren: Protokoll-Karte und Paket-Download weiter vorhanden und bedienbar.
        assert page.locator("#btn-kopieren").is_visible()
        assert page.locator("#btn-paket").is_enabled()  # #ablage_fertig True → nicht mehr "wird fertiggestellt"

        # --- Sperre des Abschlusses während des Uploads (#43) -----------------------------------------------
        from coach import api_abschluss

        class _LangsameAblage:
            def ablegen(self, name, dateien):
                time.sleep(1.2)

        alte_ablage = api_abschluss._ablage
        api_abschluss._ablage = _LangsameAblage()
        try:
            page.check("#sp-einverstanden")
            page.click("#btn-spende")
            page.wait_for_function(
                "() => document.getElementById('btn-spende').textContent.includes('hochgeladen')", timeout=2_000)
            # Während des Uploads darf auch "Abschließen" nicht klickbar sein.
            assert page.eval_on_selector("#btn-fertig", "el => el.disabled") is True
            page.wait_for_function(
                "() => document.getElementById('sp-danke').hidden === false", timeout=5_000)
            assert "erfolgreich gespeichert" in page.locator("#sp-danke").inner_text()
        finally:
            api_abschluss._ablage = alte_ablage

        # --- Punkt 2: "Fertig" → Zurück-Navigation → Datenspende funktioniert weiter -------------------------
        page.set_viewport_size({"width": 1280, "height": 900})
        page.click("#btn-fertig")
        page.wait_for_function("() => document.getElementById('btn-fertig').disabled === true", timeout=5_000)

        page.go_back()
        page.wait_for_load_state("domcontentloaded")
        assert page.url.rstrip("/") == base

        page.go_forward()
        page.wait_for_selector("#ab-inhalt:not([hidden])", timeout=10_000)
        # Ob frisch nachgeladen oder aus dem Verlauf wiederhergestellt: die Rückkehrfrist muss als laufend
        # erscheinen, nicht wie ein druckfrischer, noch nicht abgeschlossener Stand.
        page.wait_for_function("() => document.getElementById('btn-fertig').disabled === true", timeout=5_000)

        assert page.eval_on_selector("#ab-leer", "el => el.hidden") is True, \
            "nach Zurück-Navigation darf nicht „Kein beendetes Meeting gefunden“ erscheinen"
        assert page.eval_on_selector("#ab-datenspende", "el => el.hidden") is not True
        assert page.eval_on_selector("#btn-fertig", "el => el.disabled") is True, \
            "die Rückkehrfrist muss nach der Zurück-Navigation weiter als laufend angezeigt werden"

        # Zweite, unabhängige Datenspende beweist: die Karte ist nach der Zurück-Navigation nicht nur sichtbar,
        # sondern tatsächlich wieder benutzbar (nicht an einem alten, zwischengespeicherten Stand hängen geblieben).
        page.check("#sp-einverstanden")
        assert page.eval_on_selector("#btn-spende", "el => el.disabled") is False
        page.click("#btn-spende")
        page.wait_for_function(
            "() => document.getElementById('sp-danke').hidden === false", timeout=5_000)
        assert "erfolgreich gespeichert" in page.locator("#sp-danke").inner_text()

        context.close()
