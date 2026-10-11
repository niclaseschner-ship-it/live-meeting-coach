"""Ticket #79 (Nacharbeit): Syntax/Ladbarkeit des Stufe-B-Drehbuchs und der neuen Werkzeugaufruf-Simulation in
tests/e2e/fake_anbieter.py – ein reiner Unit-/Trockenlauf ohne Browser, ohne Server, ohne Stufe B selbst zu
fahren (die läuft zentral, scripts/pipeline.sh b). Prüft nur, was `scripts/pipeline.sh a` schon mitlesen kann."""

from __future__ import annotations

import json

from tests.e2e.fake_anbieter import DREHBUCH, Drehbuch, realtime_regel


def test_drehbuch_json_ist_gueltig_und_hat_die_bekannten_abschnitte():
    d = json.loads(DREHBUCH.read_text(encoding="utf-8"))
    for schluessel in ("audio", "chat", "realtime", "tts", "begruessung_premium"):
        assert schluessel in d


def test_zuruf_ergebnis_entfernen_liefert_den_werkzeugaufruf_nicht_sprache():
    """Die Regel „zuruf_ergebnis_entfernen“ (tests/e2e/schritte.py: zuruf_ergebnis_entfernen_pruefen löst sie mit
    genau diesem Satz aus) muss einen Werkzeugaufruf liefern, keinen gesprochenen Text."""
    regel = realtime_regel(Drehbuch(), "Nestor, nimm den Testpunkt von der Liste.")
    assert regel["id"] == "zuruf_ergebnis_entfernen"
    assert regel["werkzeug"] == {"name": "ergebnis_entfernen", "argumente": {"nummer": 1}}
    assert "antwort_text" not in regel


def test_zuruf_entfernen_regel_nennt_ein_werkzeug_das_es_wirklich_gibt():
    """Regressionsschutz gegen Drift: der Werkzeugname im Drehbuch muss im echten Katalog (coach/gespraech.py)
    stehen, sonst liefe die Stufe-B-Probe gegen ein Phantom-Werkzeug."""
    from coach.gespraech import WERKZEUGE

    regel = realtime_regel(Drehbuch(), "Nestor, nimm den Testpunkt von der Liste.")
    assert regel["werkzeug"]["name"] in {w["name"] for w in WERKZEUGE}


def test_andere_realtime_saetze_bleiben_gesprochen():
    """Regression: die neue Regel darf bestehende Realtime-Antworten (hier „ansprache_budget“) nicht verdecken."""
    regel = realtime_regel(Drehbuch(), "Nestor, wie viel Budget haben wir für das Sommerfest beschlossen?")
    assert regel["id"] == "ansprache_budget" and "antwort_text" in regel and "werkzeug" not in regel
