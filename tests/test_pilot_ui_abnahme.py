"""#56: selector audit and separate BrowserUI mocks (no KI-/Semantiknachweis).

Setze LMC_UI_TEST_URL auf einen laufenden lokalen Testserver, um die beiden
Startkarten-Mockläufe auszuführen. Die /api/stufe-Antwort wird hier bewusst
abgefangen; daraus darf kein echter Pilot- oder KI-Erfolg abgeleitet werden.
"""

import asyncio
import json
import os
import re
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("skript,seite", [("handy.js", "handy.html"), ("app.js", "index.html")])
def test_alle_direkten_ui_ids_existieren_in_der_zugehoerigen_seite(skript, seite):
    source = (ROOT / "static" / skript).read_text()
    markup = (ROOT / "static" / seite).read_text()
    dynamic = source + (ROOT / "static/agenda.js").read_text()
    for ident in set(re.findall(r'\$\("([^"\n]+)"\)', source)):
        assert (f'id="{ident}"' in markup or f'id: "{ident}"' in dynamic), ident


def test_ui_selektoren_stehen_alle_in_den_vorgesehenen_html_dateien():
    # Dient als schneller Vertragscheck für UI.py ohne einen Live-Aufruf.
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from pilot_ui_abnahme import UI

    html = {
        "start": (ROOT / "static/start.html").read_text(encoding="utf-8"),
        "dashboard": (ROOT / "static/index.html").read_text(encoding="utf-8"),
        "handy": (ROOT / "static/handy.html").read_text(encoding="utf-8"),
        "abschluss": (ROOT / "static/abschluss.html").read_text(encoding="utf-8"),
    }
    js = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "static").glob("*.js"))
    dokumente = "\n".join(html.values()) + "\n" + js
    for key, selector in UI.items():
        if key == "password":
            source = (ROOT / "cloudflare/src/index.ts").read_text(encoding="utf-8")
            assert 'name="passwort"' in source
            continue
        ids = __import__("re").findall(r"#([A-Za-z][A-Za-z0-9_-]*)", selector)
        assert ids, f"{key} hat keine zentral definierte ID"
        assert all(f'id="{ident}"' in dokumente or f'id: "{ident}"' in dokumente or
                   f'id=\"{ident}\"' in dokumente for ident in ids), \
            f"{key} passt nicht mehr zu static/*.html oder static/*.js"
    agenda_js = (ROOT / "static/agenda.js").read_text(encoding="utf-8")
    assert 'id: "agenda-mikro"' in agenda_js and 'addEventListener("pointerdown", agendaMikroStart)' in agenda_js
    assert '"agenda-senden"' in agenda_js and '"agenda-tabelle"' in agenda_js


def _base_url() -> str:
    return os.environ.get("LMC_UI_TEST_URL", "http://127.0.0.1:8765").rstrip("/")


def _start_mocks(status: int, netzfehler: bool = False, halte: asyncio.Event | None = None):
    anfragen: list[dict] = []

    async def route_handler(route):
        anfragen.append(route.request.post_data_json)
        if halte:
            await halte.wait()
        if netzfehler:
            await route.abort("failed")
        else:
            await route.fulfill(status=status, content_type="application/json", body='{"detail":"Mock"}')

    return anfragen, route_handler


async def _startkarten_mock(status: int, netzfehler: bool = False, doppel: bool = False) -> tuple[list[dict], str, bool, str]:
    base = _base_url()
    anfragen: list[dict] = []
    gate = asyncio.Event() if doppel else None
    anfragen, route_handler = _start_mocks(status, netzfehler, gate)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True,
                                           args=["--no-sandbox"])
        page = await browser.new_page()
        await page.route("**/api/start", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"basis_bereit":true,"premium_bereit":true}'))
        await page.route("**/api/stufe", route_handler)
        await page.goto(base + "/", wait_until="domcontentloaded")
        card = page.locator("#karte-basis")
        await card.wait_for(state="visible")
        if doppel:
            # Native Doppelklick-Geste während der ersten Netzwerkantwort. Die UI
            # muss die zweite Auswahl blocken, solange der erste Klick aussteht.
            box = await card.bounding_box()
            assert box is not None
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await page.mouse.down()
            await page.mouse.up()
            await page.wait_for_function("() => document.getElementById('karte-basis')?.disabled")
            await page.mouse.down()
            await page.mouse.up()
            await asyncio.sleep(0.2)
            assert len(anfragen) == 1
            gate.set()
        else:
            await card.click()
        erwarteter_fehler = "Server nicht erreichbar" if netzfehler else "Mock"
        await page.wait_for_function("erwartet => !document.getElementById('stufe-fehlt')?.hidden && "
                                     "document.getElementById('stufe-fehlt')?.textContent.includes(erwartet)",
                                     arg=erwarteter_fehler, timeout=10_000)
        meldung = await page.locator("#stufe-fehlt").inner_text()
        url = page.url
        enabled = not await card.is_disabled()
        await browser.close()
    return anfragen, meldung, enabled, url


def test_startkarte_verarbeitet_http409_ueber_die_ui():
    anfragen, meldung, enabled, url = asyncio.run(_startkarten_mock(409))
    assert len(anfragen) == 1
    assert anfragen[0] == {"stufe": "basis", "nur_knopfdruck": False}
    assert meldung == "Mock"
    assert enabled
    assert url.endswith("/")


def test_startkarte_bleibt_bei_netzwerkfehler_auf_der_startseite():
    anfragen, meldung, enabled, url = asyncio.run(_startkarten_mock(0, netzfehler=True))
    assert len(anfragen) == 1
    assert anfragen[0]["stufe"] == "basis"
    assert "Server nicht erreichbar" in meldung
    assert enabled
    assert url.endswith("/")


def test_startkarte_doppelclick_waehrend_anfrage_blockiert_zweite_auswahl():
    anfragen, meldung, enabled, url = asyncio.run(_startkarten_mock(409, doppel=True))
    assert len(anfragen) == 1
    assert all(x == {"stufe": "basis", "nur_knopfdruck": False} for x in anfragen)
    assert meldung == "Mock"
    assert enabled
    assert url.endswith("/")


async def _agenda_mikro_mock_hold() -> None:
    base = _base_url()
    sent: list[bool] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True,
                                           args=["--no-sandbox", "--use-fake-ui-for-media-stream",
                                                 "--use-fake-device-for-media-stream"])
        context = await browser.new_context(permissions=["microphone"])
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import cloudtest_takt as takt
        await context.add_init_script(takt.INIT_SCRIPT)
        page = await context.new_page()

        async def agenda_route(route):
            sent.append(True)
            assert "multipart/form-data" in (route.request.headers.get("content-type") or "")
            await route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "status": "ok", "eingabe": "Mocksprache", "antwort": "Mock-Antwort",
                "titel": "Mockmeeting", "ziel": "Mockziel", "teilnehmende": [],
                "punkte": [{"titel": "Mockpunkt", "ziel": "UI-Test", "minuten": 5}],
            }))

        # Nur für diesen expliziten Frontend-Mock wird der gelesene WS-Stand mit
        # einem vorhandenen Agenda-Schlüssel gespiegelt; keine POST-API an den
        # Produktserver wird aufgerufen, und es gibt keinen KI-/Semantikstatus.
        async def route_ws(route):
            server_ws = route.connect_to_server()

            def vom_server(nachricht):
                try:
                    stand = json.loads(nachricht)
                except (TypeError, ValueError):
                    route.send(nachricht)
                    return
                if isinstance(stand, dict) and "typ" not in stand:
                    stand["schluessel_vorhanden"] = True
                    stand["schluessel"] = {**(stand.get("schluessel") or {}), "offline": False}
                route.send(json.dumps(stand))

            server_ws.on_message(vom_server)
            route.on_message(lambda nachricht: server_ws.send(nachricht))

        await page.route_web_socket("**/ws", route_ws)
        await page.route("**/api/agenda/sprache", agenda_route)
        await page.goto(base + "/meeting", wait_until="domcontentloaded")
        button = page.locator("#agenda-mikro")
        await button.wait_for(state="visible", timeout=10_000)
        await page.wait_for_function("() => !document.getElementById('agenda-mikro')?.disabled", timeout=10_000)
        box = await button.bounding_box()
        assert box is not None
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.mouse.down()
        held = await page.wait_for_function(
            "() => document.getElementById('agenda-mikro')?.classList.contains('haelt')", timeout=5000)
        await asyncio.sleep(0.7)
        await page.mouse.up()
        await page.wait_for_function("() => document.getElementById('agenda-antwort')?.textContent.includes('Mock-Antwort')",
                                     timeout=10_000)
        assert held is not None
        assert sent == [True]
        assert await page.locator('#agenda-tabelle .agenda-zeile input[placeholder="Punkt"]').first.input_value() == "Mockpunkt"
        await browser.close()


def test_agenda_mikro_pointer_hold_und_release_sind_getrennter_frontend_mock():
    asyncio.run(_agenda_mikro_mock_hold())
