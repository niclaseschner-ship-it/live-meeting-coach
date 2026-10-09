from coach import aktionen
from coach.config import Einstellungen
from coach.pipeline import Coach
from coach.zustand import Agendapunkt, Segment
from coach.bogen import karten_art


def test_aktionsumfang_passt_zum_verhalten():
    c = Coach()
    erg = aktionen.katalog(c, Einstellungen())
    assert "Bisher Festgehaltenes" in erg['aktionen']['zusammenfassen']['umfang']
    assert "Aktueller Punkt" in erg['aktionen']['ueberblick']['umfang']
    assert "Download" in erg['aktionen']['protokoll']['umfang']
    assert "lokal" in erg['aktionen']['protokoll']['kosten']
    assert "keine Gesamtpreise" in erg['kostenhinweis']


def test_unbekanntes_modell_verspricht_keine_nullkosten():
    erg = aktionen.katalog(Coach(), Einstellungen(assistent_modell="unbekannt"))
    assert erg['aktionen']['stand']['kosten'] == "Text: variabel"


def test_kosten_steigen_mit_kontext_und_unterscheiden_umfang():
    c = Coach()
    c.meeting.agenda = [Agendapunkt("Alt", "", 5), Agendapunkt("Jetzt", "", 5)]
    c.meeting.aktiver_punkt = 1
    c.meeting.transkript = [Segment("A", "a" * 9000, 0, 10), Segment("B", "b" * 20, 22, 25)]
    c.meeting.wechsel = [(0, 0), (20, 1)]
    erg = aktionen.katalog(c, Einstellungen())['aktionen']['ueberblick']
    assert erg['kosten'] != erg['kosten_gesamt']
    assert 'US-ct' in erg['kosten']


def test_neue_buttonnamen_auch_als_gesprochener_auftrag():
    assert karten_art("Ergebnisse bündeln") == "zusammenfassen"
    assert karten_art("Lücken klären") == "fehlt"
    assert karten_art("Gesamtprotokoll") == "festgehalten"


def test_beide_oberflaechen_nutzen_sichtbare_hilfe():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for name in ('app', 'handy'):
        code = (root / 'static' / f'{name}.js').read_text()
        assert 'aktionshilfeRendern(' in code
    assert 'h-ueberblick-umfang' in (root / 'static' / 'handy.html').read_text()
