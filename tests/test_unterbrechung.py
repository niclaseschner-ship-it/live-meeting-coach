"""Regel 1 „Ausreden lassen“: Unterbrechungserkennung auf der Sprecherspur (ohne Audio und Netzwerk)."""

import numpy as np

from coach.unterbrechung import (
    Aeusserung, hinweistext, je_10_min, laeufe, pause_an, pegel_db, unterbrechungen,
)


def ae(start, abschnitte, pegel=None):
    ende = start + max(b for _, b, _ in abschnitte)
    return Aeusserung(start, ende, abschnitte, pegel if pegel is not None else [])


def gleichmaessig(dauer, db=-20.0):
    return [db] * int(dauer / 0.25)


def test_wechsel_ohne_pause_ist_unterbrechung():
    spur = [ae(10.0, [(0, 6, 0), (6, 11, 1)], gleichmaessig(11))]
    u = unterbrechungen(spur)
    assert len(u) == 1
    assert (u[0].zeit, u[0].von_person, u[0].zu_person) == (16.0, 0, 1)
    assert u[0].vorher == 6 and u[0].nachher == 5


def test_rueckmeldung_zaehlt_nicht():
    # B sagt kurz etwas (< 3 s), A redet weiter
    spur = [ae(0.0, [(0, 6, 0), (6, 7.5, 1), (7.5, 15, 0)], gleichmaessig(15))]
    assert unterbrechungen(spur) == []


def test_regulaere_uebergabe_mit_pause_zaehlt_nicht():
    # A endet, VAD-Pause, B beginnt in der nächsten Äußerung
    spur = [ae(0.0, [(0, 8, 0)]), ae(8.6, [(0, 6, 1)])]
    assert unterbrechungen(spur) == []


def test_kurze_pause_im_pegel_ist_uebergabe():
    pegel = gleichmaessig(12)
    pegel[23] = -55.0  # 5,75 s: kurzer Einbruch kurz vor dem Wechsel bei 6 s
    spur = [ae(0.0, [(0, 6, 0), (6, 12, 1)], pegel)]
    assert unterbrechungen(spur) == []
    assert len(unterbrechungen(spur, pause_db=None)) == 1


def test_a_sprach_zu_kurz():
    spur = [ae(0.0, [(0, 2, 0), (2, 9, 1)], gleichmaessig(9))]
    assert unterbrechungen(spur) == []
    assert len(unterbrechungen(spur, min_vorher=1.5)) == 1


def test_b_behaelt_das_wort_ueber_aeusserungsgrenzen():
    # B spricht im ersten Stück nur 1,5 s, setzt aber nach kurzer Lücke fort → Lauf ≥ 3 s
    spur = [ae(0.0, [(0, 5, 0), (5, 6.5, 1)], gleichmaessig(6.5)), ae(6.8, [(0, 4, 1)])]
    assert [u.zeit for u in unterbrechungen(spur)] == [5.0]
    assert len(laeufe(spur)) == 2


def test_stabil_bei_wachsender_spur():
    spur = [ae(0.0, [(0, 5, 0), (5, 9, 1)], gleichmaessig(9)), ae(9.6, [(0, 4, 1), (4, 9, 2)], gleichmaessig(9))]
    gesamt = [u.zeit for u in unterbrechungen(spur)]
    assert gesamt == [5.0, 13.6]
    assert [u.zeit for u in unterbrechungen(spur[:1])] == [5.0]


def test_pause_an_ohne_pegel():
    assert pause_an(Aeusserung(0, 5, [(0, 5, 0)]), 2.0) is False


def test_rate_und_hinweis():
    spur = [ae(0.0, [(0, 6, 0), (6, 12, 1), (12, 18, 0)], gleichmaessig(18))]
    u = unterbrechungen(spur)
    assert len(u) == 2
    assert je_10_min(u, 0, 300) == 4.0
    assert je_10_min(u, 10, 310) == 2.0
    assert je_10_min(u, 5, 5) == 0.0
    text = hinweistext(3, 5)
    assert "3-mal" in text and "5 Minuten" in text and "Person" not in text
    assert "einmal" in hinweistext(1, 5)


def test_pegel_db():
    proben = np.full(16000, 0.1, dtype=np.float32)
    p = pegel_db(proben)
    assert len(p) == 4
    assert abs(p[0] - (-20.0)) < 0.01
