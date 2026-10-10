"""#58: Stimmen und Gesprächsarten atomar prüfen, ohne KI-Aufruf. #60: Laufzeitwahl nur innerhalb des Anbieters."""
import pytest
from coach.config import EINST
from coach.pipeline import Coach

@pytest.fixture
def premium():
    old = {k: getattr(EINST, k) for k in ("assistent_modus", "stimme")}
    for key, value in {"assistent_modus": "gespraech", "stimme": "cedar"}.items():
        object.__setattr__(EINST, key, value)
    c = Coach()
    c.stufe_setzen("premium")
    yield c
    for key, value in old.items():
        object.__setattr__(EINST, key, value)

def test_nova_und_kurzantwort_gehen_zusammen(premium):
    premium.einstellen({"modus": "text", "stimme": "nova"})
    assert premium.wahl.stimme == "nova" and premium.wahl.assistent_modus == "text"
    assert premium.wahl.anbieter == "openai"  # gleicher Anbieter, gleiche Ziele

def test_nova_in_realtime_wird_ohne_teilmutation_abgewiesen(premium):
    vorher = premium.assistent.aktiv
    with pytest.raises(ValueError, match="Nova"):
        premium.einstellen({"assistent": not vorher, "stimme": "nova"})
    assert premium.assistent.aktiv == vorher
    assert premium.wahl.stimme == "cedar" and premium.wahl.assistent_modus == "gespraech"

def test_moduswechsel_bei_nova_erfordert_explizite_neue_stimme(premium):
    premium.einstellen({"modus": "text", "stimme": "nova"})
    with pytest.raises(ValueError, match="Nova"):
        premium.einstellen({"modus": "gespraech"})
    assert premium.wahl.assistent_modus == "text" and premium.wahl.stimme == "nova"
    premium.einstellen({"modus": "gespraech", "stimme": "cedar"})
    assert premium.wahl.stimme == "cedar" and premium.wahl.assistent_modus == "gespraech"

def test_premium_lehnt_anderen_bildanbieter_ohne_mutation_ab(premium):
    vorher = premium.assistent.aktiv
    with pytest.raises(ValueError, match="ausschließlich OpenAI"):
        premium.einstellen({"bild_anbieter": "claude", "assistent": not vorher})
    assert premium.assistent.aktiv == vorher
    assert premium.wahl.bild_anbieter == "openai"

def test_premium_vorlieben_ueberleben_den_wechsel_nach_basis_und_zurueck(premium):
    premium.einstellen({"modus": "text", "stimme": "nova"})
    premium.stufe_setzen("basis")
    assert premium.wahl.stimme != "nova" and premium.wahl.assistent_modus == "text"
    premium.einstellen({"stimme": "cedar"})  # in Basis fest: wird ignoriert
    premium.stufe_setzen("premium")
    assert premium.wahl.stimme == "nova" and premium.wahl.assistent_modus == "text"

@pytest.mark.parametrize("stufe", ["basis", "premium"])
def test_client_ist_ausschliesslich_der_gewaehlte_anbieter(premium, monkeypatch, stufe):
    import openai
    from coach import mistral
    for name in ("LMC_OFFLINE", "LMC_OPENAI_URL", "LMC_OPENAI_WS_URL", "LMC_MISTRAL_URL", "LMC_MISTRAL_WS_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-nur-attrappe-123")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test-nur-attrappe")
    premium.stufe_setzen(stufe)
    erwartet = mistral.MistralClient if stufe == "basis" else openai.AsyncOpenAI
    assert type(premium._client) is erwartet
    host = "api.mistral.ai" if stufe == "basis" else "api.openai.com"
    assert premium.wahl.hosts == frozenset({f"{host}:443"})
