"""#54: Modellwahl nachvollziehbar exportieren, ohne Schlüssel oder Rohlogs."""
import io
import json
import zipfile
from coach.abschluss import paket, spenden_dateien

def test_technik_ist_im_paket_und_in_datenspende_aber_nicht_geheimnisse(tmp_path):
    technik = {"stufe": "premium", "anbieter": "OpenAI", "stimme": "gpt-4o-mini-tts"}
    (tmp_path / "bericht.json").write_text(json.dumps({"technik": technik, "geheimnis": "nicht-exportieren"}))
    with zipfile.ZipFile(io.BytesIO(paket(tmp_path, False))) as z:
        assert json.loads(z.read("technik.json")) == technik
        assert b"nicht-exportieren" not in z.read("technik.json")
    assert json.loads(spenden_dateien(tmp_path, "", False)["technik.json"]) == technik
