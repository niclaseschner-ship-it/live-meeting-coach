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


# --- Grenzfall-Katalog des Gesprächs (drehbuch.json „_grenzfaelle“) ---------------------------------------------
GRENZFAELLE = [  # (getippter Satz, erwartete Regel, Werkzeug)
    ("Nestor, fass den aktuellen Punkt zusammen.", "grenzfall_zusammenfassen_punkt", "zusammenfassen"),
    ("Nestor, zeig uns die Möglichkeiten beim Vereinsbus als Karte.", "grenzfall_karte_frei", "karte"),
    ("Nestor, bereite die Karte kürzer auf.", "grenzfall_karte_neu_aufbereiten", "karte_neu_aufbereiten"),
    ("Nestor, mach eine kurze Recherche. Zu Förderprogrammen für Vereinsbusse.", "grenzfall_recherche_zwei_saetze",
     "recherchieren"),
]


def _wie_im_gespraech(satz: str, gerichtet: bool = True) -> str:
    """So kommt eine Anfrage beim Realtime-Fake an: Name entfernt, ohne Namen mit dem Hörfenster-Hinweis."""
    from coach.assistent import frage_aus
    from coach.gespraechszug import fuer_modell

    return fuer_modell(frage_aus(satz) if gerichtet else satz, gerichtet)


def test_grenzfaelle_liefern_den_erwarteten_werkzeugaufruf_mit_gueltigen_argumenten():
    """Jeder getippte Grenzfall (tests/e2e/schritte.py: grenzfaelle_gespraech_pruefen) trifft genau seine Regel, das
    Werkzeug steht im Katalog, und seine Argumente bestehen die Werkzeug-Prüfung im Meeting des Drehbuchs (zwei
    Agendapunkte, Ergebnisse #1 und #2)."""
    from coach import werkzeuge as W

    for satz, regel_id, werkzeug in GRENZFAELLE:
        regel = realtime_regel(Drehbuch(), _wie_im_gespraech(satz))
        assert regel["id"] == regel_id, satz
        assert regel["werkzeug"]["name"] == werkzeug and werkzeug in W.NAMEN
        _, fehler = W.pruefen(werkzeug, regel["werkzeug"]["argumente"], nummern={1, 2}, agenda=2, aktiver_punkt=0,
                              jetzt=300.0)
        assert fehler is None, (satz, fehler)


def test_satz_fuenf_im_hoerfenster_bleibt_still_und_die_ansprache_bleibt_gesprochen():
    satz5 = Drehbuch().saetze[4]
    regel = realtime_regel(Drehbuch(), _wie_im_gespraech(satz5, gerichtet=False))
    assert regel["id"] == "grenzfall_hoerfenster_nicht_an_mich" and regel["werkzeug"]["name"] == "nicht_an_mich"
    assert realtime_regel(Drehbuch(), _wie_im_gespraech("Nachher reden wir noch.", False))["id"] == "hoerfenster_still"
    # die Budget-Frage mit Namen (Satz 4) bleibt die gesprochene Antwort, auch wenn Satz 5 im selben Zug landet
    satz4 = Drehbuch().saetze[3]
    assert realtime_regel(Drehbuch(), _wie_im_gespraech(satz4))["id"] == "ansprache_budget"
    assert realtime_regel(Drehbuch(), _wie_im_gespraech(f"{satz4} {satz5}"))["id"] == "ansprache_budget"


def test_neu_aufbereiten_hat_eine_chat_regel():
    """Sonst meldet der Fake „unbekannter Prompt“ und Stufe B wird rot."""
    from coach.neu_aufbereiten import AUFTRAG, WIE_TEXT

    auftrag = AUFTRAG.format(wie=WIE_TEXT["kürzer"], titel="Möglichkeiten Vereinsbus", inhalt="- Leasen")
    regel = Drehbuch().chat([{"role": "user", "content": auftrag}])
    assert regel is not None and regel["id"] == "neu_aufbereiten"
