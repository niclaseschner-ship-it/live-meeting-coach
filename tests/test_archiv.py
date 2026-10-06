"""Meeting-Ablage: Ordner mit Bericht, Aufnahme und Debug-Daten; Einwand löscht die Aufnahme."""

import asyncio
import json
import wave

import pytest

from coach.config import EINST
from coach.pipeline import Coach


@pytest.fixture
def ablage(tmp_path):
    alt = EINST.archiv
    object.__setattr__(EINST, "archiv", str(tmp_path))  # Einstellungen sind eingefroren
    yield tmp_path
    object.__setattr__(EINST, "archiv", alt)


def _meeting(einwand: bool = False):
    async def lauf():
        c = Coach()
        c._client = None
        c.archiv_aktiv = True
        c.einrichten({"titel": "Team Runde", "agenda": [{"titel": "Start", "minuten": 5}]})
        await c.hoeren_starten()
        await c.hoeren_zufuehren(bytes(24000 * 2))  # 1 s Stille
        if einwand:
            await c.einwand_umsetzen()
        await c.hoeren_zufuehren(bytes(24000 * 2))
        await c.hoeren_beenden()
        c.archiv.schreiben(endgueltig=True)
        return c
    return asyncio.run(lauf())


def test_meeting_wird_abgelegt(ablage):
    c = _meeting()
    ordner = c.archiv.ordner
    assert ordner.parent == ablage and ordner.name.endswith("_team_runde")
    b = json.loads((ordner / "bericht.json").read_text(encoding="utf-8"))
    assert b["titel"] == "Team Runde" and "transkript" in b and b["agenda"][0]["titel"] == "Start"
    with wave.open(str(ordner / "aufnahme.wav")) as w:
        assert w.getframerate() == 24000 and abs(w.getnframes() - 48000) < 10
    arten = [json.loads(z)["art"] for z in (ordner / "debug" / "ereignisse.jsonl").read_text(encoding="utf-8").splitlines()]
    assert arten[0] == "start" and "stopp" in arten and arten[-1] == "abgelegt"
    assert (ordner / "debug" / "coach.log").exists() and c.schnappschuss()["archiv"]["fertig"]


def test_einwand_loescht_aufnahme_und_nimmt_nicht_weiter_auf(ablage):
    c = _meeting(einwand=True)
    assert not (c.archiv.ordner / "aufnahme.wav").exists()
    assert not c.archiv.aufnahme


def test_ohne_server_keine_ablage(ablage):
    async def lauf():
        c = Coach()
        c._client = None
        await c.hoeren_starten()
        await c.hoeren_beenden()
        return c
    assert asyncio.run(lauf()).archiv is None and not any(ablage.iterdir())
