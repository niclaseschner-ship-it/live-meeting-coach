"""Cloudtest, abwechselnd reden (Ticket #25): Abschnitte, Zeitabbildung und die Prüfungen aus #21 Punkt 5.

Nur die reinen Funktionen aus scripts/cloudtest_takt.py – die Browser-Regie braucht einen echten Lauf."""

import base64
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cloudtest_takt as takt  # noqa: E402

RATE = takt.RATE


def _pcm(*teile):
    """teile: ("stille", s) | ("ton", s) → int16-Signal."""
    aus = []
    for art, s in teile:
        n = int(s * RATE)
        aus.append(np.zeros(n, dtype="<i2") if art == "stille" else np.full(n, 3000, dtype="<i2"))
    return np.concatenate(aus)


def _referenz():
    return {"dauer_s": 40.0, "ereignisse": [{"ereignis": "monolog", "zeit_s": 6.0}], "grenzfaelle": [
        {"id": "frage", "erwartet": "antwort", "start": 10.0, "ende": 12.0, "warten": True,
         "teile": [{"text": "Nestor, wie spät?", "start": 10.0, "ende": 12.0}]},
        {"id": "zwei", "erwartet": "ja_dann_antwort", "start": 20.0, "ende": 24.0, "warten": True,
         "teile": [{"text": "Nestor?", "start": 20.0, "ende": 21.0, "warten": True},
                   {"text": "Was gilt?", "start": 22.0, "ende": 24.0}]},
        {"id": "rein", "erwartet": "nestor_verstummt", "start": 30.0, "ende": 31.0, "warten": False,
         "teile": [{"text": "Moment", "start": 30.0, "ende": 31.0}]},
    ]}


def test_schnittpunkte_an_den_satzgrenzen_mit_warten():
    s = takt.schnittpunkte(_referenz())
    assert [(x["id"], x["teil"], x["quelle_s"]) for x in s] == [("frage", 0, 12.0), ("zwei", 0, 21.0),
                                                                 ("zwei", 1, 24.0)]
    # Ticket #28: nach „Nestor?“ wartet der Test nur, bis „Ja?“ gesprochen ist (Nestor bleibt „angesprochen“)
    assert [x["modus"] for x in s] == [True, "ja", True]


def test_warten_standard_nach_erwartung():
    assert takt.warten_von({"erwartet": "antwort"}) is True
    assert takt.warten_von({"erwartet": "folie"}) == "bestaetigung"
    assert takt.warten_von({"erwartet": "kein_fehlausloeser"}) is False
    assert takt.warten_von({"erwartet": "antwort", "warten": False}) is False


def test_abschnitte_ueberspringen_vorlauf_und_antwortpause():
    pcm = _pcm(("stille", 5), ("ton", 7), ("stille", 10), ("ton", 3), ("stille", 2))  # 27 s
    ref = {"dauer_s": 27.0, "grenzfaelle": [{"id": "f", "erwartet": "antwort", "start": 10, "ende": 12,
                                             "teile": [{"text": "x", "start": 10, "ende": 12}]}]}
    a = takt.abschnitte_bauen(ref, pcm)
    assert [(x["von"], x["bis"], bool(x["warten"])) for x in a] == [
        (5 - takt.STILLE_BEHALTEN_S, 12, True), (22 - takt.STILLE_BEHALTEN_S, 27.0, False)]
    # ohne Warten (nur auf Knopfdruck): ein Abschnitt, nur der Vorlauf fällt weg
    assert len(takt.abschnitte_bauen(ref, pcm, ohne_warten=True)) == 1


def test_material_pruefen_meldet_falsche_laenge():
    assert takt.material_pruefen({"dauer_s": 2.0}, _pcm(("ton", 2))) is None
    assert "passt nicht" in takt.material_pruefen({"dauer_s": 30.0}, _pcm(("ton", 2)))


def test_referenz_auf_meetinguhr_verschiebt_alles_nach_einer_pause():
    plan = [{"von": 4.0, "bis": 12.0, "meeting_von": 30.0}, {"von": 15.0, "bis": 40.0, "meeting_von": 60.0}]
    r = takt.referenz_auf_meetinguhr(_referenz(), plan)
    assert r["ereignisse"][0]["zeit_s"] == 32.0  # 6 s Quelle = 2 s nach Abschnittsbeginn
    assert r["grenzfaelle"][0]["ende"] == 38.0
    assert r["grenzfaelle"][1]["start"] == 65.0  # nach der Pause: Abschnitt 2 beginnt bei 60
    assert r["grenzfaelle"][1]["teile"][1]["start"] == 67.0
    assert r["dauer_s"] == 85.0
    assert takt.quelle_zu_meeting(13.0, plan) == 60.0  # übersprungene Stille → Beginn des nächsten Abschnitts


def test_meeting_spur_enthaelt_die_pausen():
    pcm = _pcm(("ton", 2), ("stille", 1), ("ton", 2))
    plan = [{"von": 0.0, "bis": 2.0, "meeting_von": 1.0}, {"von": 3.0, "bis": 5.0, "meeting_von": 10.0}]
    spur = takt.meeting_spur(pcm, plan, 13.0)
    assert spur[int(0.5 * RATE)] == 0 and spur[int(1.5 * RATE)] == 3000
    assert spur[int(5 * RATE)] == 0 and spur[int(11 * RATE)] == 3000


def test_uhr_versatz_median_aus_den_zustaenden():
    z = [{"zeit": t - 9.5, "_t": t, "hoeren": True} for t in (10.0, 11.0, 12.0)] + [{"zeit": 0, "_t": 3.0}]
    assert takt.uhr_versatz(z) == -9.5


def _stimme(t, sek):
    pcm = np.zeros(int(sek * RATE), dtype="<i2").tobytes()
    return {"t": t, "richtung": "empfangen", "daten": {"typ": "stimme", "pcm": base64.b64encode(pcm).decode()}}


def test_stimme_platzieren_wie_der_browser_mit_stopp():
    frames = [_stimme(10.0, 1.0), _stimme(10.1, 1.0), _stimme(10.2, 1.0),  # schneller als Echtzeit: hintereinander
              {"t": 11.5, "richtung": "empfangen", "daten": {"typ": "stimme_stopp"}},
              _stimme(12.0, 0.5)]
    p = takt.stimme_platzieren(frames)
    assert [round(x["pos"], 2) for x in p] == [10.0, 11.0, 12.0, 12.0]
    assert round(p[1]["dauer"], 2) == 0.5 and p[2]["dauer"] == 0.0  # beim Stopp abgeschnitten
    assert p[3]["pos"] == 12.0  # danach wieder ab Ankunft, nicht hinter dem verworfenen Rest


def test_tonspur_abweichung_je_block():
    frames = [_stimme(10.0, 1.0), _stimme(10.1, 1.0), _stimme(30.0, 1.0)]
    zust = [{"_t": t, "zeit": t - 5.0, "hoeren": True} for t in (9.0, 10.0, 29.9, 31.0)]
    abw = takt.tonspur_abweichungen(takt.stimme_platzieren(frames), zust, -5.0)
    assert [a["ankunft"] for a in abw] == [5.0, 25.0]
    assert all(abs(a["abweichung"]) < 1e-6 for a in abw)
    # falsch verschobene Spur fällt auf
    assert abs(takt.tonspur_abweichungen(takt.stimme_platzieren(frames), zust, -3.0)[0]["abweichung"] - 2.0) < 1e-6


def test_ton_und_text_je_antwort():
    bloecke = [{"start_t": 50.0, "ende_t": 54.0}, {"start_t": 100.0, "ende_t": 101.0}]
    texte = [{"t": 55.0, "antwort": "Noch zehn Minuten."}, {"t": 200.0, "antwort": "Nur Text."}]
    ton_ohne, text_ohne = takt.ton_text_paare(bloecke, texte)
    assert [b["start_t"] for b in ton_ohne] == [100.0]
    assert [x["antwort"] for x in text_ohne] == ["Nur Text."]


def test_antwort_texte_aus_assistent_letzte():
    z = [{"_t": 1.0, "assistent": {"letzte": None}},
         {"_t": 2.0, "assistent": {"letzte": {"zeit": 5.0, "antwort": "A", "frage": "?"}}},
         {"_t": 3.0, "assistent": {"letzte": {"zeit": 5.0, "antwort": "A", "frage": "?"}}},
         {"_t": 4.0, "assistent": {"letzte": {"zeit": 9.0, "antwort": "B", "frage": "?"}}}]
    assert [(x["t"], x["antwort"]) for x in takt.antwort_texte(z)] == [(2.0, "A"), (4.0, "B")]


def test_bestaetigung_messen():
    z = [{"_t": 9.0, "assistent": {"zustand": "gespraech"}}, {"_t": 11.2, "assistent": {"zustand": "denkt"}}]
    stimme = [{"_t": 13.0}]
    assert takt.bestaetigung_messen(z, stimme, 10.0, 30.0) == (1.2, 3.0)
    # stand Nestor beim Frage-Ende schon auf „angesprochen“, zählt das sofort
    z2 = [{"_t": 9.0, "assistent": {"zustand": "angesprochen"}}]
    assert takt.bestaetigung_messen(z2, [], 10.0, 30.0) == (0.0, None)


def test_nestor_texte_seit_21():
    def nt(t, text, **kw):
        return {"t": t, "richtung": "empfangen", "daten": {"typ": "nestor_text", "text": text, **kw}}
    frames = [nt(5.0, "Okay, kleinen Moment.", neu=True, frage="Wie spät?"), nt(6.0, "Noch zehn"),
              nt(6.2, " Minuten.", delta=True), nt(20.0, "Gern.", neu=True)]
    texte = takt.nestor_texte(frames)
    assert [(x["t"], x["antwort"]) for x in texte] == [(5.0, "Okay, kleinen Moment. Noch zehn Minuten."),
                                                       (20.0, "Gern.")]
    # der mitlaufende Text zählt als erstes sichtbares Zeichen
    z = [{"_t": 9.0, "assistent": {"zustand": "gespraech"}}, {"_t": 13.0, "assistent": {"zustand": "denkt"}}]
    nachrichten = [{"typ": "nestor_text", "_t": 10.6}, {"typ": "stimme", "_t": 11.0}]
    assert takt.bestaetigung_messen(z, nachrichten, 10.0, 30.0) == (0.6, 1.0)


def test_uhr_versatz_ignoriert_stehende_uhr():
    z = [{"zeit": t - 10.0, "_t": t, "hoeren": True} for t in (11.0, 12.0, 13.0)]
    z += [{"zeit": 3.0, "_t": t, "hoeren": True} for t in range(14, 40)]  # Server steht, gleicher Stand
    assert takt.uhr_versatz(z) == -10.0


def test_takt_pruefpunkte_zeitlimit_und_rueckfrage():
    t = {"pausen": [
        {"art": "begruessung", "modus": True, "t_bezug": 1.0, "t_ende": 40.0, "dauer_s": 39.0, "ergebnis": "fertig",
         "stopps": 0, "ton_dauer_s": 30.0},
        {"art": "grenzfall", "modus": True, "id": "a", "teil": 0, "t_bezug": 100.0, "t_ende": 160.0,
         "dauer_s": 60.0, "ergebnis": "zeitlimit", "stopps": 0, "ton_s": 2.0, "sichtbar_s": 0.5},
        {"art": "grenzfall", "modus": True, "id": "r", "teil": 0, "rueckfrage": True, "t_bezug": 200.0,
         "t_ende": 205.0, "dauer_s": 5.0, "ergebnis": "fertig", "stopps": 0, "ton_s": 1.5, "sichtbar_s": 0.0,
         "weiter_segmente": 3}]}
    punkte, k = takt.takt_pruefpunkte(t, [], [], [], None)
    status = {p["name"]: p["status"] for p in punkte}
    assert status["Takt: Begrüßung ungestört durchgelaufen"] == "ok"
    assert status["Takt: Nestor abgewartet nach a"] == "fehlt"
    assert status["Takt: Rückfrage im Redefluss r"] == "ok"
    assert k["zeitlimits"] == 1 and k["erster_ton_max_s"] == 2.0


# --- Ticket #27: Sprechtaste (Basis) und Bedienung ------------------------------------------------------------------
def test_sprechtaste_um_jede_ansprache_an_nestor():
    r = _referenz()
    r["grenzfaelle"].append({"id": "fehl", "erwartet": "kein_fehlausloeser", "start": 35.0, "ende": 36.0,
                             "teile": [{"text": "Das Nest ist leer.", "start": 35.0, "ende": 36.0}]})
    f = takt.taste_fenster(r)
    assert [(x["id"], x.get("teil"), x["start"], x["ende"]) for x in f] == [
        ("frage", 0, 10.0, 12.0), ("zwei", 0, 20.0, 21.0), ("zwei", 1, 22.0, 24.0), ("rein", 0, 30.0, 31.0)]
    assert f[0]["text"] == "Nestor, wie spät?"  # dieselben Sätze wie in Premium, vorher die Taste


def test_bedienung_mit_nestors_reaktion():
    def frame(t, daten):
        return {"t": t, "richtung": "empfangen", "daten": daten}

    frames = [
        frame(9.0, {"assistent": {"auftraege": []}, "karten": []}),
        frame(10.4, {"typ": "nestor_text", "text": "Bin dran.", "neu": True}),
        frame(10.5, {"typ": "stimme", "pcm": "", "floskel": True}),
        frame(14.0, {"assistent": {"auftraege": []}, "karten": [{"id": 1, "art": "zusammenfassung", "titel": "Z"}]}),
        frame(20.1, {"typ": "stimme_stopp"}),
    ]
    bedienung = [{"t": 8.0, "t_los": 10.0, "art": "taste", "name": "Sprechtaste", "dauer_s": 2.0,
                  "satz": "Nestor, fass zusammen."},
                 {"t": 20.0, "art": "still", "name": "Still"}]
    a, b = takt.bedienung_auswerten(bedienung, frames, versatz=100.0)
    assert a["zeit"] == 108.0 and a["bestaetigung_s"] == 0.4 and a["ton_s"] == 0.5 and a["karte_s"] == 4.0
    assert "zusammenfassung" in a["karte"] and "Bestätigung nach 0.4 s" in takt.bedienung_text(a)
    assert b["ergebnis"] == "Stimme gestoppt"
