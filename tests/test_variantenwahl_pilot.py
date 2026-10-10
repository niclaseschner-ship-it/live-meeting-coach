"""#54: Neustart-Wiederherstellung nur über den vertrauenswürdigen Worker."""
import pytest
from fastapi.testclient import TestClient
from coach.config import EINST
from coach.server import app, coach

@pytest.fixture
def cloud(monkeypatch):
    from coach import server
    stufe = coach.stufe
    betrieb, geheimnis = EINST.betrieb, EINST.worker_geheimnis
    monkeypatch.setenv("LMC_OFFLINE", "1")
    monkeypatch.setattr(server, "_variantenwahl_wiederhergestellt", False)
    object.__setattr__(EINST, "betrieb", "cloud")
    object.__setattr__(EINST, "worker_geheimnis", "nur-test")
    coach.stufe_setzen("basis")
    yield TestClient(app), {"X-Nestor-Geheimnis": "nur-test", "X-Nestor-Kunde": "test",
                           "X-Nestor-Stufe": "premium"}
    monkeypatch.undo()  # erst den Testzustand (z. B. ein vorgetäuschter Hörstrom), dann die Wahl zurück
    if stufe is None:
        coach.wahl = None
        coach.client_neu()
    else:
        coach.stufe_setzen(stufe)
    object.__setattr__(EINST, "betrieb", betrieb)
    object.__setattr__(EINST, "worker_geheimnis", geheimnis)

def test_worker_stellt_premium_nach_container_neustart_wieder_her(cloud):
    client, headers = cloud
    assert client.get("/api/start", headers=headers).json()["stufe"] == "premium"

def test_alter_header_ueberschreibt_keine_neue_bestaetigte_wahl(cloud):
    client, headers = cloud
    client.get("/api/start", headers=headers)
    assert client.post("/api/stufe", headers=headers, json={"stufe": "basis"}).status_code == 200
    assert client.get("/api/start", headers=headers).json()["stufe"] == "basis"

def test_unbewiesener_header_darf_stufe_nicht_aendern(cloud):
    client, headers = cloud
    headers["X-Nestor-Geheimnis"] = "falsch"
    assert client.get("/api/start", headers=headers).status_code == 403
    assert coach.stufe == "basis"

def test_laufendes_meeting_nicht_aus_wahl_header_umstellen(cloud, monkeypatch):
    client, headers = cloud
    monkeypatch.setattr(coach, "hoerstrom", object())
    assert client.get("/api/start", headers=headers).json()["stufe"] == "basis"

def test_start_verweigert_falsche_erwartete_variante(cloud):
    client, headers = cloud
    headers["X-Nestor-Erwartete-Stufe"] = "basis"
    r = client.post("/api/start", headers=headers)
    assert r.status_code == 409 and "Variante" in r.json()["detail"]

def test_api_stufe_verweigert_fehlenden_schluessel_ohne_fallback(cloud, monkeypatch):
    from coach import anbieter
    client, headers = cloud
    headers.pop("X-Nestor-Stufe")
    monkeypatch.delenv("LMC_OFFLINE")
    monkeypatch.setattr(anbieter, "openai_schluessel", lambda: "")
    r = client.post("/api/stufe", headers=headers, json={"stufe": "premium"})
    assert r.status_code == 503
    assert coach.stufe == "basis"
