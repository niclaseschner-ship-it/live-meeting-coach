"""Abschluss: Paket, Unterstützung, Datenspende und Feedback (Lastenheft 2 Schritt 5, 4.4–4.6)."""

import asyncio
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from coach.abschluss import OrdnerAblage, paket, spenden_dateien, stufen
from coach.config import EINST
from coach.pipeline import Coach
from coach.server import app


@pytest.fixture
def archiv_pfad(tmp_path):
    alt = EINST.archiv
    object.__setattr__(EINST, "archiv", str(tmp_path))  # Einstellungen sind eingefroren
    yield tmp_path
    object.__setattr__(EINST, "archiv", alt)


def _abgelegtes_meeting() -> Coach:
    """Ein beendetes, endgültig abgelegtes Meeting – wie in test_archiv.py."""
    async def lauf():
        c = Coach()
        c._client = None
        c.archiv_aktiv = True
        c.einrichten({"titel": "Team Runde", "agenda": [{"titel": "Start", "minuten": 5}]})
        await c.hoeren_starten()
        await c.hoeren_zufuehren(bytes(24000 * 2))  # 1 s Stille
        await c.hoeren_beenden()
        c.archiv.schreiben(endgueltig=True)
        return c
    return asyncio.run(lauf())


# --- stufen() -----------------------------------------------------------------------------------

def test_stufen_fuer_sehr_kleine_kosten():
    # 0,05 $ × 0,92 €/$ = 0,046 €; alle drei Faktoren liegen unter 1 € → Mindestbetrag 2 € und dann streng steigend
    assert stufen(0.05) == [
        {"id": "deckung", "bedeutung": "Kosten sicher gedeckt", "betrag": 2},
        {"id": "fair", "bedeutung": "plus Anteil an Entwicklung und Betrieb", "betrag": 3},
        {"id": "foerderer", "bedeutung": "ermöglicht neue Funktionen", "betrag": 4},
    ]


def test_stufen_fuer_mittlere_kosten():
    # 0,80 $ × 0,92 = 0,736 €; ×2/×4/×8 aufgerundet: 2/3/6
    betraege = [s["betrag"] for s in stufen(0.80)]
    assert betraege == [2, 3, 6]


def test_stufen_fuer_groessere_kosten():
    # 2,40 $ × 0,92 = 2,208 €; ×2/×4/×8 aufgerundet: 5/9/18
    betraege = [s["betrag"] for s in stufen(2.40)]
    assert betraege == [5, 9, 18]


def test_stufen_immer_streng_steigend_und_mindestens_zwei():
    for kosten_usd in (0.0, 0.01, 0.05, 0.3, 0.8, 2.4, 10.0):
        betraege = [s["betrag"] for s in stufen(kosten_usd)]
        assert betraege[0] >= 2
        assert betraege == sorted(betraege) and len(set(betraege)) == 3


# --- paket() --------------------------------------------------------------------------------------

def test_paket_ohne_aufnahme_ohne_debug_und_ohne_bericht(archiv_pfad):
    c = _abgelegtes_meeting()
    daten = paket(c.archiv.ordner, mit_aufnahme=False)
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        namen = set(z.namelist())
    assert {"transkript.md", "agenda.md", "hinweise.md"} <= namen
    assert "bericht.json" not in namen
    assert "aufnahme.wav" not in namen
    assert not any(n.startswith("debug/") for n in namen)
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        agenda = z.read("agenda.md").decode("utf-8")
    assert "Start" in agenda


def test_paket_mit_aufnahme_enthaelt_wav(archiv_pfad):
    c = _abgelegtes_meeting()
    daten = paket(c.archiv.ordner, mit_aufnahme=True)
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        assert "aufnahme.wav" in z.namelist()


# --- Ablage ---------------------------------------------------------------------------------------

def test_ordnerablage_legt_dateien_unter_datum_und_kurz_id_ab(tmp_path):
    ablage = OrdnerAblage(tmp_path)
    ablage.ablegen("abc12345", {"feedback.txt": b"Danke"})
    [ordner] = list(tmp_path.iterdir())
    assert ordner.name.endswith("_abc12345")
    assert (ordner / "feedback.txt").read_bytes() == b"Danke"


def test_spenden_dateien_enthaelt_erwartete_teile(archiv_pfad):
    c = _abgelegtes_meeting()
    dateien = spenden_dateien(c.archiv.ordner, "Gut gemacht", mit_aufnahme=False)
    assert set(dateien) == {"transkript.md", "hinweise.md", "agenda.md", "dynamik.json", "feedback.txt"}
    assert dateien["feedback.txt"] == b"Gut gemacht"
    dateien2 = spenden_dateien(c.archiv.ordner, "", mit_aufnahme=True)
    assert "aufnahme.wav" in dateien2


# --- Endpunkte -------------------------------------------------------------------------------------

@pytest.fixture
def beendetes_meeting(monkeypatch, archiv_pfad):
    """server.coach auf ein beendetes, abgelegtes Meeting setzen (ohne den echten Server laufen zu lassen)."""
    from coach import server

    c = _abgelegtes_meeting()
    monkeypatch.setattr(server.coach, "archiv", c.archiv)
    monkeypatch.setattr(server.coach, "hoerstrom", None)
    monkeypatch.setattr(server.coach, "kosten_stand", lambda: {"meeting": 0.80})
    return c


def _lokal() -> TestClient:
    return TestClient(app, client=("127.0.0.1", 5000))


def test_abschluss_409_ohne_beendetes_meeting(monkeypatch):
    from coach import server

    monkeypatch.setattr(server.coach, "archiv", None)
    monkeypatch.setattr(server.coach, "hoerstrom", None)
    c = _lokal()
    assert c.get("/api/abschluss").status_code == 409
    monkeypatch.setattr(server.coach, "hoerstrom", object())
    assert c.get("/api/abschluss").status_code == 409
    assert c.post("/api/abschluss/fertig").status_code == 409


def test_get_abschluss_mit_kosten_stufen_und_ablage_stand(beendetes_meeting):
    alt = EINST.paypal_me
    object.__setattr__(EINST, "paypal_me", "niclaseschner")
    try:
        r = _lokal().get("/api/abschluss")
        assert r.status_code == 200
        z = r.json()
        assert [s["betrag"] for s in z["stufen"]] == [2, 3, 6]
        assert z["paypal"][0]["link"] == "https://paypal.me/niclaseschner/2EUR"
        assert z["ablage_fertig"] is True
    finally:
        object.__setattr__(EINST, "paypal_me", alt)


def test_get_abschluss_ohne_paypal_me_zeigt_keine_unterstuetzung(beendetes_meeting):
    alt = EINST.paypal_me
    object.__setattr__(EINST, "paypal_me", "")
    try:
        z = _lokal().get("/api/abschluss").json()
        assert z["paypal"] is None
    finally:
        object.__setattr__(EINST, "paypal_me", alt)


def test_paket_zip_endpunkt(beendetes_meeting):
    r = _lokal().get("/api/abschluss/paket.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        namen = z.namelist()
    assert "transkript.md" in namen and "aufnahme.wav" not in namen


def test_spende_ohne_haekchen_400(beendetes_meeting):
    r = _lokal().post("/api/abschluss/spende", json={"einverstanden": False, "aufnahme": False, "feedback": "x"})
    assert r.status_code == 400


def test_spende_legt_erwartete_dateien_ab(monkeypatch, beendetes_meeting, tmp_path):
    from coach import api_abschluss

    ziel = tmp_path / "spenden"
    monkeypatch.setattr(api_abschluss, "_ablage", OrdnerAblage(ziel))
    r = _lokal().post("/api/abschluss/spende",
                       json={"einverstanden": True, "aufnahme": False, "feedback": "Gut gemacht"})
    assert r.status_code == 200
    [ordner] = list(ziel.iterdir())
    dateien = {p.name for p in ordner.iterdir()}
    assert {"transkript.md", "hinweise.md", "agenda.md", "dynamik.json", "feedback.txt"} <= dateien
    assert "aufnahme.wav" not in dateien
    assert (ordner / "feedback.txt").read_text(encoding="utf-8") == "Gut gemacht"


def test_feedback_allein_ohne_meetingdaten(monkeypatch, beendetes_meeting, tmp_path):
    from coach import api_abschluss

    ziel = tmp_path / "spenden"
    monkeypatch.setattr(api_abschluss, "_ablage", OrdnerAblage(ziel))
    r = _lokal().post("/api/abschluss/feedback", json={"text": "Danke!"})
    assert r.status_code == 200
    [ordner] = list(ziel.iterdir())
    assert {p.name for p in ordner.iterdir()} == {"feedback.txt"}
    assert (ordner / "feedback.txt").read_text(encoding="utf-8") == "Danke!"
    assert _lokal().post("/api/abschluss/feedback", json={"text": "  "}).status_code == 400


def test_fertig_setzt_leeres_meeting_und_behaelt_ablage_standardmaessig(beendetes_meeting):
    from coach import server

    ordner = server.coach.archiv.ordner
    r = _lokal().post("/api/abschluss/fertig")
    assert r.status_code == 200
    assert server.coach.archiv is None
    assert server.coach.meeting.titel == ""
    assert ordner.exists()  # LMC_ABLAGE_BEHALTEN Standard wahr: lokales Verhalten wie heute


def test_fertig_loescht_ablage_wenn_nicht_behalten(beendetes_meeting):
    from coach import server

    alt = EINST.ablage_behalten
    object.__setattr__(EINST, "ablage_behalten", False)
    try:
        ordner = server.coach.archiv.ordner
        assert _lokal().post("/api/abschluss/fertig").status_code == 200
        assert not ordner.exists()
    finally:
        object.__setattr__(EINST, "ablage_behalten", alt)
