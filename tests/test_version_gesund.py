"""Ticket #65: /api/version, /api/gesund und die Cloud-Sperre der Demo-/Testendpunkte."""

import json

import pytest
from fastapi.testclient import TestClient

from coach.config import EINST, WURZEL
from coach.server import app

GEHEIMNIS_KOPF = {"X-Nestor-Geheimnis": "nur-test", "X-Nestor-Kunde": "test"}


@pytest.fixture
def client():
    """Mit Laptop-Rechten – ohne Zugangsschutz (Ticket #61-Konvention, siehe tests/test_start.py)."""
    return TestClient(app, client=("127.0.0.1", 5000))


@pytest.fixture
def cloud(monkeypatch):
    """EINST.betrieb umschalten; Anfragen brauchen dann X-Nestor-Geheimnis + X-Nestor-Kunde (GEHEIMNIS_KOPF)."""
    betrieb, geheimnis = EINST.betrieb, EINST.worker_geheimnis
    object.__setattr__(EINST, "betrieb", "cloud")
    object.__setattr__(EINST, "worker_geheimnis", "nur-test")
    yield TestClient(app)
    object.__setattr__(EINST, "betrieb", betrieb)
    object.__setattr__(EINST, "worker_geheimnis", geheimnis)


def test_version_ohne_datei_liefert_leere_felder(client, monkeypatch, tmp_path):
    monkeypatch.setattr("coach.config._VERSIONSDATEI", tmp_path / "version.json")
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"git_sha": None, "gebaut_am": None}


def test_version_liest_von_deploy_sh_erzeugte_datei(client, monkeypatch, tmp_path):
    datei = tmp_path / "version.json"
    datei.write_text(json.dumps({"git_sha": "abc1234", "gebaut_am": "2026-10-10T12:00:00Z"}), encoding="utf-8")
    monkeypatch.setattr("coach.config._VERSIONSDATEI", datei)
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"git_sha": "abc1234", "gebaut_am": "2026-10-10T12:00:00Z"}


def test_gesund_ohne_schluessel_nur_ja_nein(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LMC_MISTRAL_SCHLUESSEL", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("LMC_SCHLUESSEL_DATEI", "/nicht/vorhanden/schluessel")
    r = client.get("/api/gesund")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["schluessel"] == {"premium": False, "basis": False}
    assert "sk-" not in json.dumps(d)  # nie der Schlüssel selbst


def test_gesund_meldet_lokale_modelle(client):
    r = client.get("/api/gesund")
    erwartet = (WURZEL / "modelle" / EINST.vad_modell).exists() and (WURZEL / "modelle" / EINST.stimm_modell).exists()
    assert r.json()["modelle"] == erwartet


@pytest.mark.parametrize("pfad,methode,daten", [
    ("/api/simulation", "post", {"name": "x"}),
    ("/api/abspielen", "post", {"name": "x"}),
    ("/api/onepager", "post", None),
    ("/api/szenarien", "get", None),
    ("/api/aufnahmen", "get", None),
])
def test_demo_endpunkte_in_der_cloud_404(cloud, pfad, methode, daten):
    antwort = cloud.request(methode, pfad, json=daten, headers=GEHEIMNIS_KOPF)
    assert antwort.status_code == 404


def test_demo_endpunkte_lokal_weiter_erreichbar(client):
    """Die Sperre gilt nur für EINST.betrieb == "cloud" – lokal (Laptop, Lastenheft §6) bleibt alles wie zuvor."""
    assert client.get("/api/szenarien").status_code == 200
    assert client.get("/api/aufnahmen").status_code == 200
