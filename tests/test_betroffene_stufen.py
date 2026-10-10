"""Ticket #62: Zuordnung Diff → betroffene Stufen für Stufe C und Bedarf an Stufe D (Gate in deploy/deploy.sh)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "betroffene_stufen", Path(__file__).resolve().parent.parent / "scripts" / "betroffene_stufen.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)


def test_ohne_vergleichsstand_beide_und_d():
    e = bs.einordnen(None)
    assert e["stufen"] == ["basis", "premium"] and e["d"] is True


def test_nur_mistral_betrifft_nur_basis():
    e = bs.einordnen(["coach/mistral.py", "tests/test_basis.py"])
    assert e["stufen"] == ["basis"] and e["d"] is False


def test_nur_gespraech_betrifft_nur_premium():
    assert bs.einordnen(["coach/gespraech.py"])["stufen"] == ["premium"]


def test_unbekanntes_im_zweifel_beide():
    assert bs.einordnen(["coach/pipeline.py"])["stufen"] == ["basis", "premium"]
    assert bs.einordnen(["Dockerfile"])["stufen"] == ["basis", "premium"]
    assert bs.einordnen(["scripts/modelle_laden.py"])["stufen"] == ["basis", "premium"]


def test_nur_doku_und_tests_betrifft_keine_stufe():
    e = bs.einordnen(["docs/abnahme_manuell.md", "tests/e2e/lauf.py", "cloudflare/src/router.test.ts"])
    assert e["stufen"] == [] and e["d"] is False


def test_handy_und_audio_brauchen_d():
    for pfad in ("static/handy.js", "static/handy.html", "static/sw.js", "static/basis.js", "coach/stimmen.py"):
        assert bs.einordnen([pfad])["d"] is True, pfad
    assert bs.einordnen(["static/app.js"])["d"] is False
