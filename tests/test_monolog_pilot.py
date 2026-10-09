"""Regressionen für die live hochgezählte Monologanzeige und sichere Hinweise."""

from coach import analyse
from coach.zustand import Agendapunkt, Meeting, Segment


def _meeting(jetzt: float) -> Meeting:
    m = Meeting(agenda=[Agendapunkt("Punkt")])
    m.starten(virtuell=True)
    m.virtuelle_zeit = jetzt
    return m


def _vad(m: Meeting, seit: float, bis: float) -> None:
    m.sprache_seit = seit
    m.sprache_bis = bis


def test_erster_60_sekunden_monolog_ohne_sprechersegment_ist_live_gelb():
    m = _meeting(60)
    _vad(m, 0, 59.5)

    assert analyse.monolog_live(m, 60) == (True, 60)
    ampel = analyse.prozess_ampeln(m, monolog_sekunden=60, karenz_bloecke=1, zeit_rot_prozent=10,
                                   ueberlappung_min=0.5, ueberlappung_halte=30, themen_aktiv=False)
    monolog = next(a for a in ampel if a["name"] == "Monolog")
    assert monolog["farbe"] == "gelb"
    assert monolog["detail"].startswith("Live-Rede (Beta)")


def test_zwei_sekunden_pause_setzt_laufende_vad_phase_nicht_zurueck():
    m = _meeting(62)
    _vad(m, 0, 60)  # letzter VAD-Puls vor einer kurzen Pause

    hinweis, dauer = analyse.monolog_live(m, 60)
    assert hinweis and dauer == 62


def test_echte_pause_beendet_liveanzeige_und_neue_phase_startet_neu():
    m = _meeting(64)
    _vad(m, 0, 60)
    assert analyse.monolog_live(m, 60) == (False, 0.0)

    m.virtuelle_zeit = 65
    _vad(m, 65, 65)
    assert analyse.monolog_live(m, 60) == (False, 0.0)


def test_vad_anzeige_erreicht_schwelle_vor_naechstem_segment_commit():
    m = _meeting(60)
    m.segmente = [Segment("A", "", 0, 55)]
    m.letztes_block_ende = 55
    _vad(m, 0, 59.5)

    # Die sichtbare Uhr läuft bis zur Schwelle; die Warnung wartet auf bestätigte Sprecherdaten.
    assert analyse.monolog_live(m, 60) == (False, 60)
    ampel = analyse.prozess_ampeln(m, monolog_sekunden=60, karenz_bloecke=1, zeit_rot_prozent=10,
                                   ueberlappung_min=0.5, ueberlappung_halte=30, themen_aktiv=False)
    assert next(a for a in ampel if a["name"] == "Monolog")["farbe"] == "gelb"


def test_erster_sprechersegmentbeginn_nach_vad_start_ist_asr_verzug_kein_wechsel():
    m = _meeting(25)
    m.segmente = [Segment("A", "", 0.5, 20)]
    m.letztes_block_ende = 20
    _vad(m, 0, 24.5)
    assert analyse.monolog_live(m, 60) == (False, 25)

    # Weitere VAD-Ticks halten die Anzeigedauer aktuell, obwohl noch kein neuer Block kam.
    m.virtuelle_zeit = 30
    _vad(m, 0, 29.5)
    assert analyse.monolog_live(m, 60) == (False, 30)


def test_bestaetigter_sprecherwechsel_setzt_benannte_kette_zurueck():
    m = _meeting(25)
    m.segmente = [Segment("A", "", 0.5, 20), Segment("B", "", 20.5, 25)]
    m.letztes_block_ende = 25
    _vad(m, 0, 24.5)

    assert analyse.monolog_live(m, 60) == (False, 4.5)
    m.virtuelle_zeit = 30
    _vad(m, 0, 29.5)
    assert analyse.monolog_live(m, 60) == (False, 9.5)

