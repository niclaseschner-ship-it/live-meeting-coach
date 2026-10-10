"""Ticket #60: eine Stufe je Meeting – Anbieter strukturell getrennt.

1. Architektur (statisch): Endpunkte, Clients und WebSockets gibt es nur in coach/anbieter.py; kein Claude-/Codex-
   Aufruf im Produktpfad; niemand liest die Stufenmodelle aus EINST.
2. Je Stufe über alle KI-Einstiege (dynamisch): Endpunkte auf nicht erreichbare Loopback-Ziele umgelenkt, jeder
   Verbindungsaufbau protokolliert (Ebene der Ereignisschleife – auch ein Weg an der Fabrik vorbei fiele auf). Jeder
   Einstieg kontaktiert mindestens ein Ziel und nur Ziele seiner Stufe.
3. Hostwache: ein fremdes Ziel bricht ab, sichtbar und ohne Verbindung.
4. Zustand: Start ohne bestätigte Stufe → 409, Stufenwechsel im Meeting → 409, Container-Neustart ohne gespeicherte
   Wahl bleibt unbestimmt (kein stiller Rückfall auf eine Stufe).
Kein echter Netzverkehr: jede Verbindung wird vor dem Aufbau abgewiesen."""

from __future__ import annotations

import ast
import asyncio
import io
import re
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coach import anbieter
from coach.config import EINST
from coach.zustand import Agendapunkt, Segment

COACH = Path(__file__).resolve().parent.parent / "coach"
QUELLEN = {p.name: p.read_text(encoding="utf-8") for p in sorted(COACH.glob("*.py"))}

# Umgelenkte Endpunkte: Premium und Basis auf verschiedenen, nicht erreichbaren Loopback-Adressen
PREMIUM = {"LMC_OPENAI_URL": "http://127.0.0.2:9/v1", "LMC_OPENAI_WS_URL": "ws://127.0.0.2:9/v1/realtime"}
BASIS = {"LMC_MISTRAL_URL": "http://127.0.0.3:9/v1",
         "LMC_MISTRAL_WS_URL": "ws://127.0.0.3:9/v1/audio/transcriptions/realtime"}
ZIELE = {"premium": {"127.0.0.2:9"}, "basis": {"127.0.0.3:9"}}


# --- 1. Architektur ----------------------------------------------------------------------------------------------
def _ohne_docstrings(baum: ast.AST) -> list[ast.Constant]:
    doc = set()
    for k in ast.walk(baum):
        if isinstance(k, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and k.body:
            erst = k.body[0]
            if isinstance(erst, ast.Expr) and isinstance(erst.value, ast.Constant):
                doc.add(id(erst.value))
    return [k for k in ast.walk(baum) if isinstance(k, ast.Constant) and isinstance(k.value, str) and id(k) not in doc]


def test_endpunkte_nur_in_anbieter_py():
    for name, text in QUELLEN.items():
        if name == "anbieter.py":
            continue
        for literal in ("api.openai.com", "api.mistral.ai", "wss://", "ws://"):
            assert literal not in text, f"{name} enthält {literal!r} – Endpunkte gehören nach coach/anbieter.py"


def test_verbindungen_nur_aus_der_fabrik():
    """websockets, httpx-Clients, das OpenAI-SDK und der MistralClient werden nur in coach/anbieter.py gebaut; der
    MistralClient (coach/mistral.py) bekommt seinen httpx-Client mit Hostwache von dort."""
    for name, text in QUELLEN.items():
        if name == "anbieter.py":
            continue
        assert "websockets" not in text, f"{name}: WebSocket an der Fabrik vorbei"
        assert not re.search(r"httpx2?\.(Async)?Client\(", text), f"{name}: eigener httpx-Client"
        assert "MistralClient(" not in text or name == "mistral.py", f"{name}: MistralClient an der Fabrik vorbei"
        if name != "mistral.py":
            assert "AsyncOpenAI(" not in text and "OpenAI(" not in text, f"{name}: OpenAI-Client an der Fabrik vorbei"
    assert re.search(r"AsyncOpenAI\([^)]*http_client=http\(\)", QUELLEN["mistral.py"])
    assert "urllib.request" not in QUELLEN["anbieter.py"]


def test_kein_claude_oder_codex_im_produktpfad():
    assert not (COACH / "ki_abo.py").exists()
    for name, text in QUELLEN.items():
        baum = ast.parse(text)
        for k in _ohne_docstrings(baum):
            assert not re.search(r"\b(claude|codex)\b", k.value, re.IGNORECASE), f"{name}: {k.value[:60]!r}"
        for k in ast.walk(baum):
            if isinstance(k, ast.Call):
                aufruf = ast.unparse(k.func)
                if re.search(r"subprocess|create_subprocess|os\.system|os\.popen", aufruf):
                    assert not re.search(r"claude|codex", ast.unparse(k), re.IGNORECASE), f"{name}: {aufruf}"


def test_niemand_liest_stufe_oder_stufenmodelle_aus_einst():
    import dataclasses

    felder = {f.name for f in dataclasses.fields(anbieter.Anbieterwahl)} - {"anbieter", "hosts"}
    felder |= {"stufe", "basis_text_modell", "basis_zuordnung_modell", "basis_live_modell", "basis_transkription",
               "basis_stimme_modell", "basis_stimme", "basis_begruessung_modell", "zuordnung_modell"}
    for name, text in QUELLEN.items():
        if name in ("anbieter.py", "config.py"):
            continue
        for k in ast.walk(ast.parse(text)):
            if isinstance(k, ast.Attribute) and isinstance(k.value, ast.Name) and k.value.id == "EINST":
                assert k.attr not in felder, f"{name}: EINST.{k.attr} – die Stufe kommt aus der Anbieterwahl"
    assert not hasattr(EINST, "stufe")


def test_keine_vorgabe_stufe_im_container():
    index = (COACH.parent / "cloudflare" / "src" / "index.ts").read_text(encoding="utf-8")
    assert "LMC_STUFE" not in index
    assert "LMC_STUFE" not in QUELLEN["config.py"]


# --- Anbieterwahl ----------------------------------------------------------------------------------------------------
def test_anbieterwahl_ist_unveraenderlich_und_ohne_vorgabe(monkeypatch):
    import dataclasses

    for k in (*PREMIUM, *BASIS):
        monkeypatch.delenv(k, raising=False)
    w = anbieter.wahl_fuer("premium")
    with pytest.raises(dataclasses.FrozenInstanceError):
        w.stufe = "basis"  # type: ignore[misc]
    with pytest.raises(anbieter.AnbieterFehler):
        w.mit(stufe="basis")
    with pytest.raises(anbieter.AnbieterFehler):
        anbieter.wahl_fuer("basis").mit(stimme="cedar")
    with pytest.raises(ValueError):
        anbieter.wahl_fuer("gold")
    with pytest.raises(TypeError):
        anbieter.wahl_fuer()  # type: ignore[call-arg]  – keine Vorgabe-Stufe
    assert w.hosts == {"api.openai.com:443"} and anbieter.wahl_fuer("basis").hosts == {"api.mistral.ai:443"}
    assert anbieter.client_fuer(None) is None


def test_endpunkte_unverschluesselt_nur_zu_loopback(monkeypatch):
    monkeypatch.setenv("LMC_OPENAI_URL", "http://beispiel.invalid/v1")
    with pytest.raises(anbieter.AnbieterFehler):
        anbieter.wahl_fuer("premium")
    monkeypatch.setenv("LMC_OPENAI_URL", "https://api.mistral.ai/v1")  # Premium-Endpunkt auf Mistral umgebogen
    with pytest.raises(anbieter.AnbieterFehler):
        anbieter.wahl_fuer("premium")


# --- 2. Je Stufe über alle KI-Einstiege ------------------------------------------------------------------------------
@pytest.fixture
def umgelenkt(monkeypatch, tmp_path):
    """Endpunkte auf Loopback, Schlüssel gesetzt, jeder Verbindungsaufbau protokolliert und abgewiesen."""
    import openai._base_client as basis_client

    for k, v in {**PREMIUM, **BASIS}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LMC_OFFLINE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-nur-attrappe-1234567")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test-nur-attrappe")
    ziele: list[str] = []

    async def verbinden(self, protocol_factory, host=None, port=None, *a, **k):
        ziele.append(f"{host}:{port}")
        raise ConnectionRefusedError("Test: kein Netz")

    monkeypatch.setattr(asyncio.base_events.BaseEventLoop, "create_connection", verbinden)
    monkeypatch.setattr(basis_client.BaseClient, "_calculate_retry_timeout", lambda *a, **k: 0)
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)
    monkeypatch.setattr("coach.pipeline._zeit_loggen", lambda e: None)
    neu = {"stimme_aus": False, "floskel_ordner": str(tmp_path / "floskeln"), "bestaetigung": False}
    alt = {feld: getattr(EINST, feld) for feld in neu}
    for feld, wert in neu.items():
        object.__setattr__(EINST, feld, wert)
    yield ziele
    for feld, wert in alt.items():
        object.__setattr__(EINST, feld, wert)


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x10" * 16000)
    return buf.getvalue()


def _coach(stufe: str):
    from coach.pipeline import Coach

    c = Coach()
    c.stufe_setzen(stufe)
    c._einrichten({"titel": "Messeplanung", "agenda": [{"titel": "Budget", "minuten": 10},
                                                       {"titel": "Termine", "minuten": 10}], "regel_ids": ["zeit"]})
    c.meeting.starten(virtuell=True)
    c.meeting.virtuelle_zeit = 60.0
    c.meeting.transkript = [Segment("Person 1", "Wir legen das Budget auf 25.000 Euro fest.", 5, 9),
                            Segment("Person 2", "Ich hole bis Freitag drei Angebote ein.", 10, 14)]
    c.meeting.segmente = list(c.meeting.transkript)
    return c


async def _leer(*_a, **_k):
    return None


def _bogen(c):
    from coach.assistent import Bogen

    return Bogen(1, "frage", "Wo stehen wir beim Budget?", "taste", time.monotonic())


def _live_text(c):
    from coach.livetext import LiveText, LiveTextMistral

    klasse = LiveTextMistral if c.wahl.basis else LiveText
    return klasse(_leer, _leer, wahl=c.wahl, bei_verstoss=c.anbieter_verstoss).verbinden()


def _begruessung(c):
    from coach import begruessung

    if c.wahl.basis:  # Basis: Mistral formuliert die Begrüßung, Sprachausgabe siehe „sprachausgabe“
        return begruessung.basis_formulieren(c._client, c.meeting, False, wahl=c.wahl)
    return begruessung.Begruessung(c.assistent).starten()


def _bild_oder_ueberblick(c):
    from coach import bild_gpt, ueberblick

    if c.wahl.basis:  # Basis: kein Bildmodell, der Überblick als Text
        return ueberblick.erstellen(c._client, c.meeting, wahl=c.wahl)
    return bild_gpt.erzeugen(c._client, c.meeting, wahl=c.wahl)


def _einstiege():
    from coach import agenda_prompt, bogen, folie, karten, knopfdruck, recherche, transkription

    return {
        "live_text": _live_text,
        "text_je_aeusserung": lambda c: transkription.text(c._client, c.wahl.text_modell, _wav(), "de", ""),
        "zuordnung": lambda c: c._themen_pruefen("Person 1: Wir reden über das Budget."),
        "agenda": lambda c: agenda_prompt.agenda_vorschlagen(c._client, c.wahl.analyse_modell, "Budget 10 min", None),
        "assistent": lambda c: c.assistent._antworten(_bogen(c)),
        "nachfrage_einordnung": lambda c: bogen.einordnen(c._client, "Und bis wann?", "Bis Freitag.", wahl=c.wahl),
        "moderationssatz": lambda c: bogen.moderationssatz(c, {"titel": "Stand", "punkte": ["a"]}, "Ersatz"),
        "knopf_stand": lambda c: knopfdruck._stand(c, ""),
        "karte": lambda c: karten.verdichten(c._client, "Wo stehen wir?", "Bei Punkt eins. Das Budget steht.",
                                            kontext="Budget", wahl=c.wahl),
        "recherche": lambda c: recherche.recherchieren(c._client, "Mindestlohn 2027", wahl=c.wahl),
        "folie": lambda c: folie.erstellen(c._client, {"frage": "Mindestlohn", "text": "t", "quellen": [], "zeit": 1},
                                           wahl=c.wahl),
        "sprachausgabe": lambda c: c.assistent._sprechen("Hallo zusammen."),
        "floskel": lambda c: c.assistent.floskeln.erzeugen(c._client, "Moment.", wahl=c.wahl),
        "begruessung": _begruessung,
        "bild_oder_ueberblick": _bild_oder_ueberblick,
        "artefakte_und_protokoll": lambda c: knopfdruck._protokoll(c, ""),
    }


async def _ausfuehren(aufruf) -> BaseException | None:
    try:
        await asyncio.wait_for(aufruf, 20)
    except Exception as e:  # noqa: BLE001 – die Verbindung scheitert absichtlich
        return e
    return None


@pytest.mark.parametrize("stufe", ["premium", "basis"])
def test_jeder_ki_einstieg_kontaktiert_nur_ziele_seiner_stufe(umgelenkt, stufe):
    ziele = umgelenkt
    ergebnis: dict[str, list[str]] = {}

    async def lauf():
        for name, einstieg in _einstiege().items():
            c = _coach(stufe)
            ziele.clear()
            await _ausfuehren(einstieg(c))
            await asyncio.sleep(0)
            ergebnis[name] = list(ziele)
            assert c.fehler is None or "Anbieter-Sperre" not in c.fehler, (name, c.fehler)

    asyncio.run(lauf())
    erlaubt, fremd = ZIELE[stufe], ZIELE["basis" if stufe == "premium" else "premium"]
    for name, kontaktiert in ergebnis.items():
        assert kontaktiert, f"{stufe}/{name}: kein Ziel kontaktiert – Einstieg nicht abgedeckt"
        assert set(kontaktiert) <= erlaubt, f"{stufe}/{name}: {kontaktiert}"
        assert not set(kontaktiert) & fremd


def test_premium_funktionen_gibt_es_in_basis_nicht(umgelenkt):
    """Realtime-Gespräch und Live-Bild: in Basis ein harter Fehler ohne jeden Verbindungsversuch."""
    from coach import bild_gpt
    from coach.gespraech import Gespraech

    ziele = umgelenkt

    async def lauf():
        c = _coach("basis")
        return [await _ausfuehren(Gespraech(c.assistent).starten("Wo stehen wir?")),
                await _ausfuehren(bild_gpt.erzeugen(c._client, c.meeting, wahl=c.wahl))]

    fehler = asyncio.run(lauf())
    assert all(isinstance(e, anbieter.AnbieterFehler) for e in fehler) and ziele == []


# --- 3. Hostwache ------------------------------------------------------------------------------------------------------
def test_hostwache_bricht_fremdes_ziel_sichtbar_ab(umgelenkt):
    ziele = umgelenkt
    archiv = []

    async def lauf():
        c = _coach("premium")
        c.archiv = type("A", (), {"fertig": False, "ereignis": lambda self, art, **d: archiv.append((art, d))})()
        fremd = await _ausfuehren(anbieter.ws_verbinden(c.wahl, BASIS["LMC_MISTRAL_WS_URL"], {},
                                                        c.anbieter_verstoss))
        http = await _ausfuehren(c._client.post(BASIS["LMC_MISTRAL_URL"] + "/chat/completions", cast_to=dict,
                                                body={}))
        return c, fremd, http

    c, fremd, http = asyncio.run(lauf())
    assert isinstance(fremd, anbieter.AnbieterVerstoss)
    assert isinstance(http, anbieter.AnbieterVerstoss) or isinstance(http.__cause__, anbieter.AnbieterVerstoss)
    assert ziele == []  # nie eine Verbindung aufgebaut
    assert "Anbieter-Sperre" in c.fehler and "127.0.0.3:9" in c.fehler
    assert archiv and archiv[0][0] == "anbieter_verstoss" and archiv[0][1]["stufe"] == "premium"


# --- 4. Zustand: Start, Wechsel, Neustart ---------------------------------------------------------------------------
@pytest.fixture
def server_coach(monkeypatch):
    from coach import server

    wahl = server.coach.wahl
    monkeypatch.setenv("LMC_OFFLINE", "1")
    yield server
    monkeypatch.undo()
    server.coach.wahl = wahl
    server.coach.client_neu()


def test_start_ohne_bestaetigte_stufe_409(server_coach, monkeypatch):
    server = server_coach
    monkeypatch.setattr(server.coach, "wahl", None)
    monkeypatch.setattr(server.coach, "hoeren_starten", lambda: pytest.fail("ohne Stufe gestartet"))
    r = TestClient(server.app, client=("127.0.0.1", 5000)).post("/api/start")
    assert r.status_code == 409 and "Variante wählen" in r.json()["detail"]
    assert TestClient(server.app, client=("127.0.0.1", 5000)).get("/api/start").json()["stufe"] is None


def test_start_ohne_schluessel_503_statt_meeting_ohne_ki(server_coach, monkeypatch):
    server = server_coach
    assert TestClient(server.app, client=("127.0.0.1", 5000)).post("/api/stufe", json={"stufe": "premium"}).status_code == 200
    monkeypatch.delenv("LMC_OFFLINE", raising=False)
    monkeypatch.setattr(server.coach, "_client", None)
    monkeypatch.setattr(server.coach, "hoeren_starten", lambda: pytest.fail("ohne Schlüssel gestartet"))
    r = TestClient(server.app, client=("127.0.0.1", 5000)).post("/api/start")
    assert r.status_code == 503 and "nicht verbunden" in r.json()["detail"]


def test_stufenwechsel_im_meeting_409(server_coach, monkeypatch):
    server = server_coach
    web = TestClient(server.app, client=("127.0.0.1", 5000))
    assert web.post("/api/stufe", json={"stufe": "premium"}).status_code == 200
    wahl = server.coach.wahl
    for zustand in ({"startet": True}, {"hoerstrom": object()},
                    {"archiv": type("A", (), {"fertig": False})()}):  # Start läuft, Meeting läuft, Nachlauf
        for k, v in zustand.items():
            monkeypatch.setattr(server.coach, k, v)
        assert web.post("/api/stufe", json={"stufe": "basis"}).status_code == 409
        assert server.coach.wahl is wahl
        monkeypatch.undo()
        monkeypatch.setenv("LMC_OFFLINE", "1")
    from coach.pipeline import WahlGesperrt

    monkeypatch.setattr(server.coach, "hoerstrom", object())
    with pytest.raises(WahlGesperrt):
        server.coach.stufe_setzen("basis")
    with pytest.raises(WahlGesperrt):
        server.coach.client_neu()


def test_container_neustart_ohne_gespeicherte_wahl_bleibt_unbestimmt(server_coach, monkeypatch):
    """Frischer Container (keine Vorgabe-Stufe): ohne Wahl aus dem Worker-Speicher kein Start; mit ihr die Wahl."""
    server = server_coach
    monkeypatch.setattr(server.coach, "wahl", None)
    monkeypatch.setattr(server, "_variantenwahl_wiederhergestellt", False)
    alt_betrieb, alt_geheimnis = EINST.betrieb, EINST.worker_geheimnis
    object.__setattr__(EINST, "betrieb", "cloud")
    object.__setattr__(EINST, "worker_geheimnis", "nur-test")
    try:
        web = TestClient(server.app)
        kopf = {"X-Nestor-Geheimnis": "nur-test", "X-Nestor-Kunde": "test"}
        assert web.get("/api/start", headers=kopf).json()["stufe"] is None
        assert web.post("/api/start", headers=kopf).status_code == 409
        monkeypatch.setattr(server, "_variantenwahl_wiederhergestellt", False)
        gespeichert = {**kopf, "X-Nestor-Stufe": "premium"}
        assert web.get("/api/start", headers=gespeichert).json()["stufe"] == "premium"
    finally:
        object.__setattr__(EINST, "betrieb", alt_betrieb)
        object.__setattr__(EINST, "worker_geheimnis", alt_geheimnis)


def test_agenda_ohne_meeting_bleibt_ohne_verbindung():
    """Ohne Wahl gibt es keinen Client – auch kein stiller Default-Client."""
    from coach.pipeline import Coach

    c = Coach()
    c.meeting.agenda = [Agendapunkt("A")]
    assert c.wahl is None and c._client is None and c.stufe is None
