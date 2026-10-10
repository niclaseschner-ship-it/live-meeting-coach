"""Handy-Zugang: vom Laptop alles, über tailscale serve nur gekoppelt, den Schlüssel nie vom Handy.

Dazu der Cloud-Fall (Ticket #5): kein „am Laptop“ mehr, stattdessen das Worker-Geheimnis."""

import os

import pytest
from fastapi.testclient import TestClient

# Isolation (vgl. tests/test_start.py, tests/test_server.py, tests/test_meeting_ende.py): ohne das hier ist
# /api/start seit #60 ohne Schlüssel 503 – diese Datei darf das nicht davon abhängen, dass ein anderes
# Testmodul LMC_OFFLINE schon vorher gesetzt hat.
os.environ.setdefault("LMC_OFFLINE", "1")

from coach import api_abschluss, server, zugang  # noqa: E402
from coach.anbieter import wahl_fuer  # noqa: E402
from coach.config import Einstellungen  # noqa: E402
from coach.server import app  # noqa: E402

TS = {"Tailscale-User-Login": "jemand@example.com", "X-Forwarded-For": "100.70.1.127"}
GEHEIMNIS = "geheim-test-123"


@pytest.fixture(autouse=True)
def eigener_code(tmp_path, monkeypatch):
    monkeypatch.setattr(zugang, "KOPPLUNG_DATEI", tmp_path / "kopplung")


@pytest.fixture
def cloud(monkeypatch):
    """Cloud-Betrieb mit Worker-Geheimnis; patcht EINST dort, wo es gebunden ist (zugang.py und server.py)."""
    einst = Einstellungen(betrieb="cloud", worker_geheimnis=GEHEIMNIS, worker_url="https://nestor.example.workers.dev")
    monkeypatch.setattr(zugang, "EINST", einst)
    monkeypatch.setattr(server, "EINST", einst)
    return einst


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
        with lokal.websocket_connect("/ws?geraet=handy&handy_id=test-handy"), lokal.websocket_connect("/ws/audio?quelle=handy&handy_id=test-handy"):
            assert server.audio["quelle"] == "handy"
            assert laptop.receive()["code"] == 4001                    # Laptop wurde abgelöst
            assert server.mikro_stand()["quelle"] == "handy"
    assert server.audio["quelle"] is None
    with lokal.websocket_connect("/ws") as ws:
        ws.receive_text()                                               # Anfangszustand
        ws.send_text('{"ping": 12.5}')
        assert '"pong"' in ws.receive_text()


def test_audio_websocket_protokolliert_transportmessung(monkeypatch):
    gemessen = []

    async def aufnehmen(_daten):
        return None

    monkeypatch.setattr(server.coach, "hoeren_zufuehren", aufnehmen)
    monkeypatch.setattr(server, "ereignis", lambda art, **daten: gemessen.append((art, daten)))
    lokal = TestClient(app, client=("127.0.0.1", 5000))
    with lokal.websocket_connect("/ws/audio?quelle=laptop") as mikro:
        mikro.send_bytes(bytes(4_800))  # 100 ms PCM, 24 kHz, 16 bit mono
        mikro.send_bytes(bytes(4_800))
    _, daten = next(e for e in gemessen if e[0] == "mikro_weg")
    assert daten["pakete"] == 2
    assert daten["audio_s"] == 0.2
    assert "wand_s" in daten and "drift_s" in daten and daten["luecken"] == 0


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


def test_gemeldetes_handy_behaelt_den_ton():
    import json

    lokal = TestClient(app, client=("127.0.0.1", 5000))

    def ton(ws, erwartet):  # warten, bis ein Zustand diesen Lautsprecher meldet (andere Meldungen überspringen)
        for _ in range(20):
            d = json.loads(ws.receive_text())
            if d.get("lautsprecher", "-") == erwartet:
                return erwartet
        return None

    with lokal.websocket_connect("/ws?geraet=handy&handy_id=test-handy") as handy, lokal.websocket_connect("/ws") as laptop:
        assert lokal.get("/api/zustand").json()["handys"] == 1                # Handy verbunden, auch ohne Mikro
        handy.send_text('{"lautsprecher": true}')
        assert ton(handy, "handy") == "handy"
        laptop.send_text('{"lautsprecher": true}')                     # Laptop-Start: Handy bleibt
        laptop.send_text('{"ping": 1}')
        while json.loads(laptop.receive_text()).get("typ") != "pong":
            pass
        assert lokal.get("/api/zustand").json()["lautsprecher"] == "handy"
        laptop.send_text('{"lautsprecher": true, "erzwingen": true}')  # ausdrücklich „Hier abspielen“
        assert ton(laptop, "laptop") == "laptop"


def test_zweites_handy_und_fremdes_audio_abgewiesen():
    lokal = TestClient(app, client=("127.0.0.1", 5000))
    with lokal.websocket_connect("/ws?geraet=handy&handy_id=erstes") as erstes:
        erstes.receive_text()
        erstes.receive_text()
        with lokal.websocket_connect("/ws?geraet=handy&handy_id=zweites") as zweites:
            assert zweites.receive()["code"] == 4409
        assert lokal.get("/api/zustand").json()["handys"] == 1
        with lokal.websocket_connect("/ws/audio?quelle=handy&handy_id=zweites") as fremd:
            assert fremd.receive()["code"] == 4409
        erstes.send_text('{"ping": 2}')
        assert '"pong"' in erstes.receive_text()
    assert lokal.get("/api/zustand").json()["handys"] == 0


def test_selbes_handy_darf_neu_laden_ohne_zwei_verbindungen():
    lokal = TestClient(app, client=("127.0.0.1", 5000))
    with lokal.websocket_connect("/ws?geraet=handy&handy_id=erstes") as alt:
        alt.receive_text()
        alt.receive_text()
        with lokal.websocket_connect("/ws?geraet=handy&handy_id=erstes") as neu:
            assert alt.receive()["code"] == 4001
            neu.receive_text()
            assert lokal.get("/api/zustand").json()["handys"] == 1
    assert lokal.get("/api/zustand").json()["handys"] == 0


# --- Cloud-Betrieb (Ticket #5): kein „am Laptop“ mehr, dafür das Worker-Geheimnis ------------------------

def test_cloud_ohne_geheimnis_403_fuer_alles(cloud):
    c = TestClient(app, client=("10.1.2.3", 5000))
    assert c.get("/api/zustand").status_code == 403
    assert c.get("/handy").status_code == 403           # in der Cloud auch die sonst offenen Seiten dicht
    assert c.get("/static/handy.js").status_code == 403


def test_cloud_falsches_geheimnis_403(cloud):
    c = TestClient(app, client=("10.1.2.3", 5000))
    assert c.get("/api/zustand", headers={"X-Nestor-Geheimnis": "falsch"}).status_code == 403


def test_cloud_mit_geheimnis_laptop_rechte(cloud):
    c = TestClient(app, client=("10.1.2.3", 5000))
    headers = {"X-Nestor-Geheimnis": GEHEIMNIS, "X-Nestor-Kunde": "testkunde"}
    assert c.get("/api/zustand", headers=headers).status_code == 200
    with c.websocket_connect("/ws", headers=headers) as ws:
        ws.receive_text()  # Anfangszustand – die Verbindung steht


def test_cloud_websocket_ohne_geheimnis_wird_abgewiesen(cloud):
    from starlette.websockets import WebSocketDisconnect

    c = TestClient(app, client=("10.1.2.3", 5000))
    with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/ws"):
        pass
    assert e.value.code == 4403


def test_kopplung_in_der_cloud_holt_ein_signiertes_kopplungstoken_vom_worker(cloud, monkeypatch):
    """Ticket #63: die nackte Meeting-ID steht nicht mehr im QR-Code – der Coach holt sich dafür ein
    kurzlebiges, vom Worker signiertes Kopplungstoken über `/intern/kopplungstoken` (Muster wie
    `worker_melden` für `/intern/meeting-start`, hier gemockt, das Netz ist nicht Teil dieses Tests)."""
    aufgerufen = []

    def _fake_melden(pfad, daten):
        aufgerufen.append((pfad, daten))
        return {"token": "signiertes-token-xyz"}

    monkeypatch.setattr(api_abschluss, "worker_melden", _fake_melden)
    c = TestClient(app, client=("10.1.2.3", 5000), base_url="https://nestor.example.workers.dev")
    r = c.get("/api/kopplung", headers={"X-Nestor-Geheimnis": GEHEIMNIS, "X-Nestor-Kunde": "test", "X-Nestor-Meeting": "abc123"})
    assert r.status_code == 200
    daten = r.json()
    assert daten["adresse"].startswith("https://nestor.example.workers.dev/handy?k=")
    assert daten["adresse"].endswith("&meeting=signiertes-token-xyz")
    assert daten["qr"] is not None
    assert daten["befehl"] is None                        # kein tailscale-Befehl in der Cloud
    assert aufgerufen == [("/intern/kopplungstoken", {"meetingId": "abc123", "kunde": "test"})]

    ohne_meeting = c.get("/api/kopplung", headers={"X-Nestor-Geheimnis": GEHEIMNIS, "X-Nestor-Kunde": "test"})
    assert ohne_meeting.json()["qr"] is None               # ohne Meeting-Kennung vom Worker kein QR-Code


def test_kopplung_in_der_cloud_ohne_token_vom_worker_kein_qr(cloud, monkeypatch):
    """Netzstörung oder abgelehntes Token (worker_melden liefert None) – dann lieber gar kein QR-Code als
    einer mit einer unsignierten/nackten Meeting-ID."""
    monkeypatch.setattr(api_abschluss, "worker_melden", lambda pfad, daten: None)
    c = TestClient(app, client=("10.1.2.3", 5000), base_url="https://nestor.example.workers.dev")
    r = c.get("/api/kopplung", headers={"X-Nestor-Geheimnis": GEHEIMNIS, "X-Nestor-Kunde": "test", "X-Nestor-Meeting": "abc123"})
    assert r.status_code == 200
    assert r.json()["adresse"] is None
    assert r.json()["qr"] is None


def test_cloud_handy_ohne_login_koppelt_per_qr(cloud):
    c = TestClient(app, base_url="https://nestor.example.workers.dev")
    kopf = {"X-Nestor-Geheimnis": GEHEIMNIS, "X-Nestor-Meeting": "abc123"}
    assert c.get("/api/zustand", headers=kopf).status_code == 401
    assert c.get(f"/handy?k={zugang.code()}", headers=kopf).status_code == 200
    assert c.get("/api/zustand", headers=kopf).status_code == 200


def test_start_ohne_handy_abgewiesen(monkeypatch):
    # Isolation (Ticket #60/#64): ohne bestätigte Variante weist /api/start schon vorher ab – erst mit einer
    # Wahl wie in tests/test_meeting_ende.py, tests/test_variantenwahl_pilot.py prüft dieser Test wirklich den
    # Handy-Check.
    monkeypatch.setattr(server.coach, "wahl", wahl_fuer("basis"))
    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setitem(server.audio, "ws", None)
    c = TestClient(app, client=("127.0.0.1", 5000))
    r = c.post("/api/start")
    assert r.status_code == 409
    assert "QR-Code" in r.json()["detail"]


def test_ablage_oeffnen_in_der_cloud_aus(cloud):
    c = TestClient(app, client=("10.1.2.3", 5000))
    r = c.post("/api/ablage/oeffnen", headers={"X-Nestor-Geheimnis": GEHEIMNIS, "X-Nestor-Kunde": "testkunde"})
    assert r.status_code == 404
