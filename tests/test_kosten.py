"""Kostenzähler und eigener OpenAI-Schlüssel – ohne Netzwerk."""

import json

import pytest

from coach import config, kosten


def test_preise_der_einzelnen_funktionen():
    # Live-Text: 60 min × 0,017 $
    assert kosten.dollar({"art": "live-text", "modell": "gpt-live-transcribe", "sekunden_audio": 3600}) == pytest.approx(1.02)
    # Agenda/Ton mit gpt-5.4-mini: 1 Mio. rein + 1 Mio. raus
    assert kosten.dollar({"art": "themen", "modell": "gpt-5.4-mini", "tokens_rein": 1e6, "tokens_raus": 1e6}) == pytest.approx(5.25)
    # Recherche: Tokens plus Websuche
    assert kosten.dollar({"art": "recherche", "modell": "gpt-5.4-mini", "tokens_rein": 0, "tokens_raus": 0}) == pytest.approx(0.01)
    # Live-Bild über OpenAI: Pauschale + Text-Tokens von gpt-5.4; über das Claude-Abo kostenlos
    bild = {"art": "onepager", "anbieter": "openai", "fortschreibung": False,
            "schritte": [{"modell": "gpt-5.4+gpt-image-2", "tokens_rein": 4000, "tokens_raus": 800}]}
    assert kosten.dollar(bild) == pytest.approx(0.05 + 0.01 + 0.012)
    assert kosten.dollar({"art": "onepager", "anbieter": "claude-abo"}) == 0
    # Gespräch: Audio rein ohne Cache, Cache billig, Audio raus teuer
    gespraech = {"art": "gespraech", "details_rein": {"audio_tokens": 1000, "text_tokens": 2000, "cached_tokens": 1500,
                                                      "cached_tokens_details": {"audio_tokens": 500, "text_tokens": 1000}},
                 "details_raus": {"audio_tokens": 1000, "text_tokens": 100}}
    erwartet = (500 * 32 + 1000 * 4 + 1500 * 0.4 + 100 * 16 + 1000 * 64) / 1e6
    assert kosten.dollar(gespraech) == pytest.approx(erwartet)
    assert kosten.dollar({"art": "unbekannt"}) == 0


def test_zaehler_meeting_heute_gesamt_und_laufender_live_text(tmp_path):
    datei = tmp_path / "nutzung.jsonl"
    datei.write_text(json.dumps({"zeit": "2020-01-01T10:00:00", "art": "x", "usd": 0.5}) + "\n", encoding="utf-8")
    z = kosten.Zaehler(datei)
    z.stand()  # liest die alte Datei ein
    z.buchen({"art": "themen", "modell": "gpt-5.4-mini", "tokens_rein": 1e5, "tokens_raus": 0})  # 0,075 $
    s = z.stand(live_sekunden=600, meeting_sekunden=1800, geplant_minuten=60)  # 10 min Live-Text = 0,17 $
    bereiche = {b["id"]: b["usd"] for b in s["bereiche"]}
    assert bereiche["analyse"] == pytest.approx(0.075) and bereiche["live-text"] == pytest.approx(0.17)
    assert s["meeting"] == pytest.approx(0.245)
    assert s["pro_stunde"] == pytest.approx(0.49) and s["hochrechnung"] == pytest.approx(0.49)
    assert s["heute"] == pytest.approx(0.245) and s["gesamt"] == pytest.approx(0.745)
    z.neues_meeting()
    assert z.stand()["meeting"] == 0 and z.stand()["gesamt"] == pytest.approx(0.575)


def test_schluessel_aus_dem_dashboard_hat_vorrang_und_wird_nie_ausgegeben(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCHLUESSEL_DATEI", tmp_path / "k")
    monkeypatch.setattr(config, "_gelesen", False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-aus-der-umgebung-1234567")
    assert config.openai_schluessel() == "sk-aus-der-umgebung-1234567"
    assert config.schluessel_info()["quelle"] == "umgebung"
    config.schluessel_speichern("sk-eigener-schluessel-abcdefgh")
    assert config.openai_schluessel() == "sk-eigener-schluessel-abcdefgh"
    info = config.schluessel_info()
    assert info == {"vorhanden": True, "quelle": "dashboard", "ende": "efgh", "offline": info["offline"]}
    assert "sk-" not in json.dumps(info)
    config.schluessel_speichern(None)
    assert not (tmp_path / "k").exists() and config.openai_schluessel() == "sk-aus-der-umgebung-1234567"


def test_schluessel_endpunkt_prueft_format_und_laeuft_nur_lokal():
    from fastapi.testclient import TestClient

    from coach.server import app

    c = TestClient(app)  # TestClient meldet sich als „testclient“, nicht als 127.0.0.1
    assert c.post("/api/schluessel", json={"schluessel": "sk-x"}).status_code == 403
    lokal = TestClient(app, client=("127.0.0.1", 5000))
    r = lokal.post("/api/schluessel", json={"schluessel": "kein schluessel"})
    assert r.status_code == 400 and "sk-" in r.json()["detail"]
