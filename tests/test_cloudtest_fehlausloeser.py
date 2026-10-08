"""Ticket #28: Im Cloudtest zählt jede Nestor-Äußerung ohne Auslöser laut Referenz und Bedienplan als Fehlauslöser –
mit genau den Sätzen aus dem Premium-Abendlauf 08.10. (logs/cloudtest/abend_premium, Meetinguhr 245–300 s)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
_tmp = os.environ.get("TMPDIR")
import cloudtest as ct  # noqa: E402 – setzt TMPDIR für Chromium; für die übrigen Tests zurück

if _tmp is None:
    os.environ.pop("TMPDIR", None)
else:
    os.environ["TMPDIR"] = _tmp

REFERENZ = {"dauer_s": 330.0, "ereignisse": [], "grenzfaelle": [
    {"id": "1_name_satzende", "erwartet": "antwort", "start": 204.3, "ende": 205.5,
     "teile": [{"text": "Wie viel Zeit haben wir noch, Nestor?", "start": 204.3, "ende": 205.5}]},
    {"id": "1r_rueckfrage_reicht", "erwartet": "antwort", "start": 245.5, "ende": 246.9, "nach": "1_name_satzende",
     "teile": [{"text": "Und reicht das noch für alle Punkte?", "start": 245.5, "ende": 246.9}]},
    {"id": "2_name_dann_frage", "erwartet": "ja_dann_antwort", "start": 273.6, "ende": 281.0,
     "teile": [{"text": "Nestor?", "start": 273.6, "ende": 274.0},
               {"text": "Was haben wir zu Punkt eins beschlossen?", "start": 279.6, "ende": 281.0}]},
    {"id": "2r_rueckfrage_wer", "erwartet": "antwort", "start": 290.0, "ende": 291.2, "nach": "2_name_dann_frage",
     "teile": [{"text": "Und wer übernimmt das?", "start": 290.0, "ende": 291.2}]},
    {"id": "6b_next_week", "erwartet": "kein_fehlausloeser", "start": 300.0, "ende": 301.5,
     "teile": [{"text": "Das schieben wir auf next week.", "start": 300.0, "ende": 301.5}]},
]}
GEFRAGT = [
    {"zeit": 1.1, "frage": "", "antwort": "Hallo zusammen, ich bin Nestor, euer Moderationsassistent."},  # Begrüßung
    {"zeit": 207.3, "frage": "Wie viel Zeit haben wir noch?",
     "antwort": "Ihr habt für diesen Punkt noch knapp zwei Minuten."},
    {"zeit": 214.3, "frage": "Wo stehen wir?", "antwort": "Schau ich mir an, komme gleich zurück. Hier ist sie."},
    {"zeit": 249.1, "frage": "Und reicht das noch für alle Punkte?",
     "antwort": "Ihr habt für alles zusammen noch knapp drei Minuten."},
    {"zeit": 275.1, "frage": "", "antwort": "Ja?"},
    {"zeit": 282.4, "frage": "Was haben wir zu Punkt eins beschlossen?", "antwort": "Zu Punkt eins …"},
    {"zeit": 292.6, "frage": "Und wer übernimmt das?", "antwort": "Das ist noch offen."},
]
UNGEFRAGT = {"zeit": 262.7, "frage": "Heißt das, selbst ein schneller Application Rollback hätte uns nicht gerettet",
             "antwort": "Genau, weil das Datenbankschema schon geändert war und der Rollback nur die App "
                        "zurückgesetzt hat."}
BEDIENUNG = [{"zeit": 212.0, "art": "stand"}, {"zeit": 245.0, "art": "band"}, {"zeit": 299.0, "art": "still"}]


def test_jede_aeusserung_mit_ausloeser_ist_kein_fehlausloeser():
    assert ct.ungefragte_aeusserungen(REFERENZ, GEFRAGT, BEDIENUNG) == []


def test_antwort_auf_die_frage_an_die_kollegen_ist_ein_fehlausloeser():
    """Fall 1: 16 s nach der Rückfrage 1r und 18 s nach dem Band-Knopf – die Äußerung trägt aber die Frage „Heißt
    das …“, die zu keinem Auslöser passt."""
    assert ct.ungefragte_aeusserungen(REFERENZ, GEFRAGT + [UNGEFRAGT], BEDIENUNG) == [UNGEFRAGT]


def test_aeusserung_ohne_frage_ohne_ausloeser_davor_ist_ein_fehlausloeser():
    still = {"zeit": 310.0, "frage": "", "antwort": "Kurz zu „Ursache“: Ich hab notiert …"}
    assert ct.ungefragte_aeusserungen(REFERENZ, GEFRAGT + [still], BEDIENUNG) == [still]


def test_fehlausloeser_in_der_pruefliste_und_in_der_bewertung():
    zustaende = [{"zeit": float(t), "_t": float(t), "segmente": [], "assistent": {}} for t in range(0, 330, 5)]
    liste, _ = ct.pruefpunkte_berechnen(REFERENZ, zustaende, [], [], [], False, aeusserungen=GEFRAGT + [UNGEFRAGT],
                                        bedienung=BEDIENUNG)
    fehl = [p for p in liste if p["name"].startswith("Fehlauslöser")]
    assert [(p["name"], p["status"]) for p in fehl] == [("Fehlauslöser bei 263s", "fehlt")]
    assert "Heißt das, selbst ein schneller Application Rollback" in fehl[0]["detail"]
    import cloudtest_bewerten as cb

    k = cb.kennzahlen_bauen({"messwerte": {"meeting_s": 330}}, [], liste, None)
    assert k["fehlausloeser"] == 1
    ohne, _ = ct.pruefpunkte_berechnen(REFERENZ, zustaende, [], [], [], False, aeusserungen=GEFRAGT,
                                       bedienung=BEDIENUNG)
    assert any(p["name"] == "Keine ungefragten Nestor-Äußerungen" and p["status"] == "ok" for p in ohne)


def test_eingaben_aus_dem_mitschnitt_auf_der_meetinguhr():
    frames = [{"t": 10.0, "richtung": "empfangen", "daten": {"zeit": 250.0}},
              {"t": 22.5, "richtung": "empfangen", "daten": {"typ": "nestor_text", "text": "Genau, weil …", "neu": True,
                                                              "frage": UNGEFRAGT["frage"]}},
              {"t": 23.0, "richtung": "empfangen", "daten": {"zeit": 263.0}}]
    zustaende = ct.zustaende_aus_frames(frames)
    e = ct.ungefragt_eingaben({"takt": {"bedienung": [{"t": 10.2, "art": "band"}]}}, frames, zustaende)
    assert e["aeusserungen"][0]["zeit"] == 263.0 and e["aeusserungen"][0]["frage"] == UNGEFRAGT["frage"]
    assert e["bedienung"][0]["zeit"] == 250.0


def test_verpasste_anschlussfragen_und_ungefragte_antworten_getrennt():
    """Abendlauf 08.10.: 2r (Rückfrage) blieb unbeantwortet, „Heißt das, …“ wurde ungefragt beantwortet."""
    liste = [{"name": "Grenzfall 1r_rueckfrage_reicht", "status": "ok", "detail": ""},
             {"name": "Grenzfall 2_name_dann_frage", "status": "fehlt", "detail": "erwartet: ja_dann_antwort"},
             {"name": "Grenzfall 2r_rueckfrage_wer", "status": "fehlt", "detail": "erwartet: antwort"},
             {"name": "Grenzfall 6b_next_week", "status": "ok", "detail": ""},
             {"name": "Fehlauslöser bei 263s", "status": "fehlt", "detail": "erwartet: kein Auslöser"}]
    assert ct.anschluss_kennzahlen(REFERENZ, liste) == {"anschlussfragen": 2, "verpasste_anschlussfragen": 1,
                                                        "ungefragte_antworten": 1}
