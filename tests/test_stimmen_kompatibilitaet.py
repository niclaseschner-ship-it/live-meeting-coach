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

def test_premium_lehnt_anderen_bildanbieter_ohne_mutation_ab(premium):
    vorher = premium.assistent.aktiv
    with pytest.raises(ValueError, match="ausschließlich OpenAI"):
        premium.einstellen({"bild_anbieter": "claude", "assistent": not vorher})
    assert premium.assistent.aktiv == vorher
    assert EINST.bild_anbieter == "openai"

def test_legacy_anbieteroptionen_werden_auch_lokal_nicht_aktiviert():
    from coach.config import Einstellungen
    config = Einstellungen(betrieb="lokal", ki="codex", bild_anbieter="claude")
    assert config.ki == "openai" and config.bild_anbieter == "openai"

@pytest.mark.parametrize("stufe", ["basis", "premium"])
def test_client_ist_ausschliesslich_der_gewaehlte_anbieter(premium, monkeypatch, stufe):
    import coach.pipeline as pipeline
    import coach.mistral as mistral
    import openai
    import coach.ki_abo as abo
    alt_stufe, alt_ki = EINST.stufe, EINST.ki
    clients = {"basis": object(), "premium": object()}
    monkeypatch.setattr(pipeline, "ki_verfuegbar", lambda: True)
    monkeypatch.setattr(pipeline, "mistral_schluessel", lambda: "test")
    monkeypatch.setattr(pipeline, "openai_schluessel", lambda: "test")
    monkeypatch.setattr(mistral, "MistralClient", lambda key: clients["basis"])
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: clients["premium"])
    def unerlaubt(*args):
        pytest.fail("Anbieterfremder Abo-Wrapper wurde verwendet")
    monkeypatch.setattr(abo, "AboClient", unerlaubt)
    try:
        object.__setattr__(EINST, "stufe", stufe)
        object.__setattr__(EINST, "ki", "codex")  # selbst eine alte/manipulierte Konfiguration ist wirkungslos
        premium.client_neu()
        assert premium._client is clients[stufe]
    finally:
        object.__setattr__(EINST, "stufe", alt_stufe)
        object.__setattr__(EINST, "ki", alt_ki)
