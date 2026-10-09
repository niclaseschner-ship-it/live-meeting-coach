"""#58: Stimmen und Gesprächsarten atomar prüfen, ohne KI-Aufruf."""
import pytest
from coach.config import EINST
from coach.pipeline import Coach

@pytest.fixture
def premium():
    old = {k: getattr(EINST, k) for k in ("stufe", "assistent_modus", "stimme")}
    for key, value in {"stufe": "premium", "assistent_modus": "gespraech", "stimme": "cedar"}.items():
        object.__setattr__(EINST, key, value)
    yield Coach()
    for key, value in old.items():
        object.__setattr__(EINST, key, value)

def test_nova_und_kurzantwort_gehen_zusammen(premium):
    premium.einstellen({"modus": "text", "stimme": "nova"})
    assert EINST.stimme == "nova" and EINST.assistent_modus == "text"

def test_nova_in_realtime_wird_ohne_teilmutation_abgewiesen(premium):
    vorher = premium.assistent.aktiv
    with pytest.raises(ValueError, match="Nova"):
        premium.einstellen({"assistent": not vorher, "stimme": "nova"})
    assert premium.assistent.aktiv == vorher
    assert EINST.stimme == "cedar" and EINST.assistent_modus == "gespraech"

def test_moduswechsel_bei_nova_erfordert_explizite_neue_stimme(premium):
    premium.einstellen({"modus": "text", "stimme": "nova"})
    with pytest.raises(ValueError, match="Nova"):
        premium.einstellen({"modus": "gespraech"})
    assert EINST.assistent_modus == "text" and EINST.stimme == "nova"
    premium.einstellen({"modus": "gespraech", "stimme": "cedar"})
    assert EINST.stimme == "cedar" and EINST.assistent_modus == "gespraech"
