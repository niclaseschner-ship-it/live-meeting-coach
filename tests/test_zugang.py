"""Handy-Zugang: vom Laptop alles, über tailscale serve nur gekoppelt, den Schlüssel nie vom Handy."""

import pytest
from fastapi.testclient import TestClient

from coach import zugang
from coach.server import app

TS = {"Tailscale-User-Login": "jemand@example.com", "X-Forwarded-For": "100.70.1.127"}


@pytest.fixture(autouse=True)
def eigener_code(tmp_path, monkeypatch):
    monkeypatch.setattr(zugang, "KOPPLUNG_DATEI", tmp_path / "kopplung")


def test_code_bleibt_und_ist_eintippbar():
    c = zugang.code()
    assert len(c) == 8 and c == zugang.code() and not set(c) & set("IL0O1")
    assert zugang.code_passt(c[:4].lower() + "-" + c[4:])


def test_laptop_darf_alles_weitergeleitet_nur_gekoppelt():
    lokal = TestClient(app, client=("127.0.0.1", 5000))
    assert lokal.get("/api/zustand").status_code == 200
    assert lokal.get("/api/zustand", headers=TS).status_code == 401      # über tailscale serve: nicht lokal
    assert lokal.get("/handy", headers=TS).status_code == 200            # Seite mit Code-Eingabe ist offen
    assert lokal.get("/static/handy.js", headers=TS).status_code == 200


def test_koppeln_setzt_cookie_und_falscher_code_nicht():
    c = TestClient(app, client=("127.0.0.1", 5000), base_url="https://laptop.ts.net", follow_redirects=False)
    r = c.get("/handy?k=FALSCH00", headers=TS)
    assert r.status_code == 303 and r.headers["location"].endswith("falsch=1") and "set-cookie" not in r.headers
    r = c.get(f"/handy?k={zugang.code()}", headers=TS)
    assert r.status_code == 303 and r.headers["location"] == "/handy" and zugang.COOKIE in r.headers["set-cookie"]
    assert c.get("/api/zustand", headers=TS).status_code == 200          # Cookie trägt
    # gekoppelt heißt nicht „am Laptop“: Schlüssel und QR-Code bleiben dort
    assert c.post("/api/schluessel", json={"schluessel": "sk-x"}, headers=TS).status_code == 403
    assert c.get("/api/kopplung", headers=TS).status_code == 403


def test_websocket_ohne_kopplung_abgewiesen():
    from starlette.websockets import WebSocketDisconnect

    c = TestClient(app, client=("127.0.0.1", 5000))
    with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/ws", headers=TS):
        pass
    assert e.value.code == 4401


def test_ein_mikrofon_zur_zeit_und_laufzeitmessung():
    from coach import server

    lokal = TestClient(app, client=("127.0.0.1", 5000))
    with lokal.websocket_connect("/ws/audio?quelle=laptop") as laptop:
        assert server.audio["quelle"] == "laptop"
        with lokal.websocket_connect("/ws/audio?quelle=handy"):
            assert server.audio["quelle"] == "handy"
            assert laptop.receive()["code"] == 4001                    # Laptop wurde abgelöst
            assert server.mikro_stand()["quelle"] == "handy"
    assert server.audio["quelle"] is None
    with lokal.websocket_connect("/ws") as ws:
        ws.receive_text()                                               # Anfangszustand
        ws.send_text('{"ping": 12.5}')
        assert '"pong"' in ws.receive_text()


def test_zweiter_start_und_umrichten_waehrend_des_meetings_abgewiesen(monkeypatch):
    from coach import server

    monkeypatch.setattr(server.coach, "hoerstrom", object())
    lokal = TestClient(app, client=("127.0.0.1", 5000))
    assert lokal.post("/api/start").status_code == 409
    assert lokal.post("/api/einrichten", json={"titel": "x"}).status_code == 409
    monkeypatch.setattr(server.coach, "hoerstrom", None)
    assert lokal.get("/api/zustand").json()["lautsprecher"] is None


def test_adresse_passt_zum_eigenen_port():
    status = {"Web": {"laptop.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}},
                      "laptop.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8001"}}}}}
    assert zugang._serve_adresse(status, 8000) == "https://laptop.ts.net"
    assert zugang._serve_adresse(status, 8001) == "https://laptop.ts.net:8443"
    assert zugang._serve_adresse(status, 8002) is None
