"""Abschluss: Paket, Unterstützung, Datenspende und Feedback (Lastenheft 2 Schritt 5, 4.4–4.6)."""

import asyncio
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from coach.abschluss import OrdnerAblage, meeting_html, meeting_markdown, paket, spenden_dateien, stufen
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
    assert {"transkript.md", "agenda.md", "hinweise.md", "meeting.md", "meeting.html",
            "meeting-mit-regelanalyse.html"} <= namen
    assert "bericht.json" not in namen
    assert "aufnahme.wav" not in namen
    assert not any(n.startswith("debug/") for n in namen)
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        agenda = z.read("agenda.md").decode("utf-8")
    assert "Start" in agenda


def test_meeting_dokument_ist_kopierbar_und_markiert_luecken():
    daten = {
        "kopf": {"titel": "Planung & Start", "datum": "2026-10-09", "dauer_sekunden": 125},
        "entscheidungen": [{"was": "Loslegen", "status": "beschlossen", "wer": ""}],
        "aufgaben": [], "offene_punkte": [], "risiken": [], "parkplatz": [], "agenda": [],
    }
    md = meeting_markdown(daten, {"redeanteile": {"Alex": 12.4}, "hinweise": []})
    assert "# Planung & Start" in md
    assert "Loslegen · beschlossen · ⚠ fehlt" in md
    assert "## Regelanalyse" in md and "Alex: 12 s" in md
    html = meeting_html(daten)
    assert "<!doctype html>" in html
    assert "Planung &amp; Start" in html
    assert "<script" not in html


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
    monkeypatch.setattr(server.coach, "meeting", c.meeting)  # Abschluss-Kopf braucht Agenda/Ergebnisse dieses Meetings
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
        # Abschluss-Kopf (Ticket #17 Punkt 3): Punkte aus der Agenda, Entscheidungen aus den Ergebnissen
        assert z["punkte"] == 1  # Fixture-Agenda: ein Punkt „Start“
        assert z["entscheidungen"] == 0  # keine Ergebnisprüfung gelaufen
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


def test_feedback_knopf_jederzeit_auch_ohne_beendetes_meeting(monkeypatch, tmp_path):
    """Ticket #18 Nachtrag: der Feedback-Knopf auf jeder Seite braucht kein beendetes Meeting – anders als
    `/api/abschluss/feedback`."""
    from coach import api_abschluss, server

    monkeypatch.setattr(server.coach, "archiv", None)
    monkeypatch.setattr(server.coach, "hoerstrom", object())  # Meeting läuft noch
    ziel = tmp_path / "spenden"
    monkeypatch.setattr(api_abschluss, "_ablage", OrdnerAblage(ziel))
    r = _lokal().post("/api/feedback", json={"art": "funktionswunsch", "text": "Bitte Dunkelmodus", "seite": "/meeting"})
    assert r.status_code == 200
    [ordner] = list(ziel.iterdir())
    inhalt = (ordner / "feedback.txt").read_text(encoding="utf-8")
    assert "funktionswunsch" in inhalt and "Bitte Dunkelmodus" in inhalt and "/meeting" in inhalt


def test_feedback_knopf_ohne_text_400_und_unbekannte_art_wird_feedback(monkeypatch, tmp_path):
    from coach import api_abschluss

    ziel = tmp_path / "spenden"
    monkeypatch.setattr(api_abschluss, "_ablage", OrdnerAblage(ziel))
    assert _lokal().post("/api/feedback", json={"text": "  "}).status_code == 400
    r = _lokal().post("/api/feedback", json={"art": "unsinn", "text": "Hallo"})
    assert r.status_code == 200
    [ordner] = list(ziel.iterdir())
    assert "Art: feedback" in (ordner / "feedback.txt").read_text(encoding="utf-8")


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


def test_rueckkehrfrist_behaelt_paket_und_verlaengert_sich_nicht(beendetes_meeting):
    from coach import api_abschluss
    with _lokal() as client:
        r = client.post("/api/abschluss/schliessen")
        assert r.status_code == 200
        deadline = r.json()["rueckkehr_bis"]
        assert client.get("/api/abschluss/paket.zip").status_code == 200
        assert client.post("/api/abschluss/schliessen").json()["rueckkehr_bis"] == deadline
        assert client.get("/api/abschluss").json()["rueckkehr_bis"] == deadline
        assert client.post("/api/abschluss/fertig").status_code == 200
    assert api_abschluss._rueckkehr_bis is None


def test_rueckkehrfrist_loescht_automatisch(beendetes_meeting, monkeypatch):
    from coach import api_abschluss, server
    monkeypatch.setattr(api_abschluss, "RUECKKEHR_SEKUNDEN", 0.02)
    alt = EINST.ablage_behalten
    object.__setattr__(EINST, "ablage_behalten", False)
    ordner = server.coach.archiv.ordner
    try:
        with _lokal() as client:
            assert client.post("/api/abschluss/schliessen").status_code == 200
            import time
            deadline = time.monotonic() + 2
            while ordner.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not ordner.exists()
            assert server.coach.archiv is None
    finally:
        object.__setattr__(EINST, "ablage_behalten", alt)


def test_neues_meeting_hebt_alte_loeschfrist_nicht_auf(beendetes_meeting, monkeypatch):
    from coach import api_abschluss, server
    neu = _abgelegtes_meeting()
    alter_ordner = server.coach.archiv.ordner
    neuer_ordner = neu.archiv.ordner
    monkeypatch.setattr(api_abschluss, "RUECKKEHR_SEKUNDEN", 0.15)
    alt = EINST.ablage_behalten
    object.__setattr__(EINST, "ablage_behalten", False)
    try:
        with _lokal() as client:
            assert client.post("/api/abschluss/schliessen").status_code == 200
            server.coach.archiv = neu.archiv
            server.coach.meeting.titel = "Neues Meeting"
            import time
            deadline = time.monotonic() + 2
            while alter_ordner.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not alter_ordner.exists() and neuer_ordner.exists()
            assert server.coach.meeting.titel == "Neues Meeting"
            assert api_abschluss._rueckkehr_archiv is None
    finally:
        object.__setattr__(EINST, "ablage_behalten", alt)
