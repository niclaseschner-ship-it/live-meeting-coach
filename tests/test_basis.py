"""Nestor Basis (Ticket #13): Stufe Basis/Premium, Mistral-Anbindung, Überblick als Text, Knöpfe, Halten zum Sprechen.
Ohne Netz: Mistral- und OpenAI-Aufrufe sind durch Attrappen ersetzt."""

import asyncio
import io
import json
import os
import wave
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LMC_OFFLINE", "1")

from coach import assistent as A  # noqa: E402
from coach import kosten, mistral, ueberblick  # noqa: E402
from coach.anbieter import wahl_fuer  # noqa: E402
from coach.config import EINST  # noqa: E402
from coach.livetext import NACHLAUF_TEXT, TextZuordnung  # noqa: E402
from coach.zustand import Agendapunkt, Meeting, Segment  # noqa: E402


@pytest.fixture(autouse=True)
def premium_danach(monkeypatch):
    """Jeder Test endet in Premium (globale Einstellungen) und schreibt keine Protokolldateien."""
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)
    monkeypatch.setattr("coach.pipeline._zeit_loggen", lambda e: None)
    yield
    from coach.server import coach

    monkeypatch.undo()  # erst den Testzustand (z. B. ein vorgetäuschter Hörstrom) zurück, dann die Wahl
    coach.stufe_setzen("premium")


# --- Stufe -----------------------------------------------------------------------------------------------------
def test_stufe_basis_hat_fuer_jedes_modell_das_mistral_gegenstueck():
    import dataclasses

    premium, basis = wahl_fuer("premium"), wahl_fuer("basis")
    assert basis.stufe == "basis" and basis.anbieter == "mistral" and premium.anbieter == "openai"
    for f in ("analyse_modell", "assistent_modell", "recherche_modell"):
        assert getattr(basis, f) == "mistral-medium-latest"
    assert basis.live_modell.startswith("voxtral") and basis.text_modell.startswith("voxtral")
    assert basis.stimme_modell.startswith("voxtral") and basis.stimme == mistral.NOVA_EUPHORISCH
    assert basis.assistent_modus == "text" and basis.bild_anbieter == "text" and basis.nachfrage_sekunden == 0
    assert basis.realtime_modell is None and basis.bild_modell is None  # gibt es in Basis nicht
    # kein einziges OpenAI-Modell in Basis, kein Mistral-Modell in Premium
    werte = lambda w: [str(getattr(w, f.name)) for f in dataclasses.fields(w)]  # noqa: E731
    assert not any(v.startswith(("gpt", "o4")) for v in werte(basis))
    assert not any(v.startswith(("mistral", "voxtral")) for v in werte(premium))
    assert premium.live_modell == EINST.live_modell  # Premium: Werte aus der Umgebung, unverändert


def test_basis_client_ist_mistral(monkeypatch):
    from coach.pipeline import Coach

    monkeypatch.delenv("LMC_OFFLINE", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-schluessel-ohne-wert")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = Coach()
    c.stufe_setzen("basis")
    assert isinstance(c._client, mistral.MistralClient)
    c.stufe_setzen("premium")
    assert c._client is None  # kein OpenAI-Schlüssel in dieser Umgebung
    monkeypatch.setenv("LMC_OFFLINE", "1")


def test_api_stufe_und_startdaten():
    from coach.server import app, coach

    web = TestClient(app, client=("127.0.0.1", 5000))
    r = web.post("/api/stufe", json={"stufe": "basis"})
    assert r.status_code == 200 and r.json() == {"ok": True, "stufe": "basis"}
    d = web.get("/api/start").json()
    assert d["stufe"] == "basis"
    assert d["richtwert_basis_eur"] == EINST.richtwert_basis_eur and "basis_bereit" in d and "premium_bereit" in d
    assert web.get("/api/zustand").json()["stufe"] == "basis"
    assert web.post("/api/stufe", json={"stufe": "gold"}).status_code == 400
    coach.hoerstrom = object()
    try:
        assert web.post("/api/stufe", json={"stufe": "premium"}).status_code == 409
    finally:
        coach.hoerstrom = None


def test_startseite_nennt_mistral_und_openai():
    from coach.server import app

    text = TestClient(app, client=("127.0.0.1", 5000)).get("/").text
    # Ticket #18: Premium (OpenAI) ist der Standard, Basis (Mistral) das Downgrade für DSGVO-Nähe/weniger Kosten.
    assert "KI nur bei Mistral (Frankreich), Verarbeitung in der EU" in text
    assert "US-Anbieter (OpenAI)" in text
    assert "Nur auf Knopfdruck" not in text  # Ticket #71: der Modus ist vollständig ausgebaut
    assert "Wie ein Telefon" in text and "Wie ein Funkgerät" in text


def test_begruessung_basis_ohne_rueckfragen_ohne_namen():
    m = Meeting(agenda=[Agendapunkt("Budget", "", 10), Agendapunkt("Termine", "", 10)])
    _, start_basis = A.begruessungstext(m, basis=True)
    _, start_premium = A.begruessungstext(m, basis=False)
    assert "ohne Namen" not in start_basis and "redet einfach rein" not in start_basis
    assert "Funkgerät" in start_basis and "Taste halten, sprechen, loslassen" in start_basis  # Ticket #27
    assert "ohne Namen" in start_premium and "Telefon" in start_premium


def test_systemanweisung_basis_bild_ist_uebersicht():
    s = A.system_text(wahl_fuer("basis"))
    assert "AKTION: bild" in s and "Übersicht" in s and "nach wenigen Sekunden im Verlauf" in s
    assert "nach wenigen Sekunden im Verlauf" not in A.system_text(wahl_fuer("premium"))


# --- Live-Text Voxtral: Text den Äußerungen zuordnen --------------------------------------------------------------
def test_textzuordnung_trennt_aeusserungen_nach_audiozeit():
    z = TextZuordnung()
    z.text(1.5, "Nestor, wo", 100.0)
    z.text(2.4, " stehen wir?", 100.1)
    z.commit({"id": 1}, ende=2.0, wand=100.2)
    # Satzzeichen am Ende und kurz nichts Neues: gleich ausgeben
    assert z.faellig(pos=2.5, wand=100.3) == [({"id": 1}, "Nestor, wo stehen wir?")]
    # Text der nächsten Äußerung (kommt nach Ende + Nachlauf) bleibt für sie stehen
    z.text(4.0, " Gut,", 101.0)
    z.commit({"id": 2}, ende=3.0, wand=101.0)
    z.text(3.0 + NACHLAUF_TEXT + 0.5, " danke", 101.5)
    assert z.faellig(pos=3.0 + NACHLAUF_TEXT + 0.6, wand=101.6) == [({"id": 2}, "Gut,")]
    assert z.teiltext() == "danke"


def test_textzuordnung_ohne_satzzeichen_wartet_auf_nachlauf_oder_frist():
    z = TextZuordnung()
    z.text(1.0, "und dann", 10.0)
    z.commit({"id": 1}, ende=1.2, wand=10.0)
    assert z.faellig(pos=1.5, wand=10.5) == []
    assert z.faellig(pos=1.5, wand=12.0) == [({"id": 1}, "und dann")]  # Wanduhr-Frist (z. B. stumm)


# --- Mistral-Client -----------------------------------------------------------------------------------------------
def test_f32_zu_s16():
    a = np.array([0.0, 0.5, -1.0, 2.0], dtype="<f4").tobytes()
    assert list(np.frombuffer(mistral.f32_zu_s16(a), dtype="<i2")) == [0, 16383, -32767, 32767]


def test_429_wird_wiederholt_dann_ueberlast(monkeypatch):
    async def nicht_warten(_v):
        return None

    monkeypatch.setattr(mistral, "_warten", nicht_warten)
    versuche = []

    async def zweimal_voll():
        versuche.append(1)
        if len(versuche) < 3:
            raise mistral.HttpFehler(429)
        return "ok"

    assert asyncio.run(mistral.mit_wiederholung(zweimal_voll)) == "ok" and len(versuche) == 3

    async def immer_voll():
        raise mistral.HttpFehler(429)

    with pytest.raises(mistral.Ueberlast):
        asyncio.run(mistral.mit_wiederholung(immer_voll))

    async def anderer_fehler():
        raise mistral.HttpFehler(500)

    with pytest.raises(mistral.HttpFehler):
        asyncio.run(mistral.mit_wiederholung(anderer_fehler))


def test_chat_ohne_openai_eigenheiten():
    c = mistral.MistralClient("x", basis_url="http://127.0.0.1:9/v1", http=lambda **optionen: None)
    gesehen = {}

    async def create(**kw):
        gesehen.update(kw)
        return "antwort"

    c._oa = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    c.chat.completions._oa = c._oa
    assert asyncio.run(c.chat.completions.create(model="mistral-medium-latest", reasoning_effort="low",
                                                 messages=[])) == "antwort"
    assert "reasoning_effort" not in gesehen


def test_kontextwoerter_einzeln_ohne_leerzeichen():
    assert mistral.kontextwoerter(["Nestor", "Termin und Messestand", "Budget", "Lea Kramer", "Budget"]) == [
        "Nestor", "Termin", "Messestand", "Budget", "Lea", "Kramer"]


def test_websuche_lesen():
    roh = {"outputs": [{"type": "tool.execution", "name": "web_search"},
                       {"type": "message.output", "content": [
                           {"type": "text", "text": "Hotels kosten während Messen deutlich mehr."},
                           {"type": "tool_reference", "title": "SWR", "url": "https://swr.de/a"},
                           {"type": "tool_reference", "title": "SWR doppelt", "url": "https://swr.de/a"}]}],
           "usage": {"prompt_tokens": 900, "completion_tokens": 160, "connector_tokens": 5000}}
    e = mistral.websuche_lesen(roh)
    assert e["text"].startswith("Hotels") and e["quellen"] == [{"titel": "SWR", "url": "https://swr.de/a"}]
    assert e["tokens_rein"] == 5900 and e["suchen"] == 1


def test_kosten_mistral():
    assert kosten.dollar({"art": "stimme", "modell": "voxtral-mini-tts-latest", "zeichen": 1000}) == pytest.approx(0.016)
    assert kosten.dollar({"art": "live-text", "modell": "voxtral-mini-transcribe-realtime-2602",
                          "sekunden_audio": 3600}) == pytest.approx(0.36)
    assert kosten.dollar({"art": "assistent", "modell": "mistral-medium-latest", "tokens_rein": 1_000_000,
                          "tokens_raus": 0}) == pytest.approx(1.5)
    assert kosten.dollar({"art": "recherche", "modell": "mistral-medium-latest", "suchen": 1}) == pytest.approx(0.03)
    assert kosten.dollar({"art": "ueberblick", "modell": "mistral-medium-latest", "tokens_rein": 0,
                          "tokens_raus": 1_000_000}) == pytest.approx(7.5)


# --- Überblick als Text ----------------------------------------------------------------------------------------
def _meeting() -> Meeting:
    m = Meeting(titel="Messeplanung 2027", agenda=[Agendapunkt("Budget", "Obergrenze", 10),
                                                   Agendapunkt("Aufgaben", "", 10)])
    m.starten(virtuell=True)
    m.virtuelle_zeit = 125.0
    m.transkript = [Segment("Person 2", "Ich schlage 25.000 Euro als Obergrenze vor.", 10, 14),
                    Segment("Person 1", "Gut, dann ist beschlossen: höchstens 25.000 Euro.", 15, 19),
                    Segment("Person 2", "Ich hole bis Ende Oktober drei Angebote ein.", 60, 64)]
    m.ergebnisse[0] = {"ergebnis": "höchstens 25.000 Euro", "entscheidungen": [{"was": "Obergrenze", "ergebnis": "25.000 Euro"}],
                       "aufgaben": []}
    return m


class FakeClient:
    def __init__(self, antwort: dict) -> None:
        self.antwort = antwort
        self.auftrag = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.auftrag = kw["messages"][-1]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.antwort)))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


def test_ueberblick_zahlen_aus_dem_material_und_keine_personen():
    antwort = {"kernaussage": "Budget steht, Aufgaben laufen",
               "entschieden": [{"punkt": 1, "was": "Obergrenze 25.000 Euro"},
                               {"punkt": 1, "was": "Obergrenze 55.000 Euro"}],  # erfunden → fliegt raus
               "offen": [{"punkt": 2, "was": "Wer bucht die Hotels?"}],
               "aufgaben": [{"was": "Drei Angebote einholen", "wer": "Person 2", "bis": "Ende Oktober"}],
               "ausserhalb": [], "neu": ["Person 2 holt Angebote"]}
    u, nutzung = asyncio.run(ueberblick.erstellen(FakeClient(antwort), _meeting(), vorher={"entschieden": []},
                                                  wahl=wahl_fuer("basis")))
    assert [e["was"] for e in u["entschieden"]] == ["Obergrenze 25.000 Euro"]
    assert u["aufgaben"] == [{"was": "Drei Angebote einholen", "wer": None, "bis": "Ende Oktober"}]
    assert u["neu"] == ["jemand holt Angebote"]
    assert u["titel"] == "Messeplanung 2027" and u["laufzeit"] == "2:05" and u["punkt"] == "1. Budget"
    assert nutzung["tokens_rein"] == 100
    md = ueberblick.als_markdown(u)
    assert "✅ Entschieden" in md and "📌 Aufgaben" in md and "25.000" in md


def test_ueberblick_bekommt_festgestellte_ergebnisse():
    c = FakeClient({"entschieden": [], "offen": [], "aufgaben": [], "ausserhalb": [], "neu": []})
    asyncio.run(ueberblick.erstellen(c, _meeting(), wahl=wahl_fuer("basis")))
    assert "Festgestellte Ergebnisse" in c.auftrag and "höchstens 25.000 Euro" in c.auftrag


def test_basis_bild_aktion_macht_ueberblick(monkeypatch):
    from coach.pipeline import Coach

    c = Coach()
    c.stufe_setzen("basis")
    c._client = FakeClient({"kernaussage": "x", "entschieden": [], "offen": [], "aufgaben": [], "ausserhalb": [],
                            "neu": []})
    c.meeting = _meeting()

    async def lauf():
        import time

        from coach.assistent import Bogen

        b = Bogen(1, "frage", "zeig uns die Übersicht", "taste", time.monotonic())
        await c.assistent.aktion_ausfuehren({"typ": "bild", "fokus": "gesamt"}, b)

    object.__setattr__(EINST, "stimme_aus", True)
    try:
        asyncio.run(lauf())
    finally:
        object.__setattr__(EINST, "stimme_aus", False)
    assert c.ueberblick and c.ueberblick_version == 1 and c.onepager_version == 0
    assert c.karten[-1]["art"] == "ueberblick" and c.karten[-1]["ueberblick"] == c.ueberblick


# --- Halten zum Sprechen ---------------------------------------------------------------------------------------
def _wav(sekunden: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(np.zeros(int(24000 * sekunden), "<i2").tobytes())
    return buf.getvalue()


def test_frage_audio_wird_transkribiert_und_beantwortet(monkeypatch):
    from coach.server import app, coach

    web = TestClient(app, client=("127.0.0.1", 5000))
    beantwortet = []

    async def transkribieren(**kw):
        assert kw["file"][2] == "audio/wav"
        return SimpleNamespace(text="Nestor, wer bucht die Hotels?")

    monkeypatch.setattr(coach, "_client", SimpleNamespace(audio=SimpleNamespace(
        transcriptions=SimpleNamespace(create=transkribieren))))
    monkeypatch.setattr(coach, "hoerstrom", object())
    monkeypatch.setattr(coach.assistent, "frage_beantworten", lambda f, a="": beantwortet.append((f, a)))
    assert web.post("/api/frage/halten", json={"an": True}).status_code == 200
    r = web.post("/api/frage/audio", content=_wav(), headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json() == {"ok": True, "frage": "wer bucht die Hotels?"}
    assert beantwortet == [("wer bucht die Hotels?", "taste")]
    assert web.post("/api/frage/audio", content=b"kurz").status_code == 400


def test_gehaltene_frage_zaehlt_nicht_noch_einmal_als_zuruf():
    from coach.pipeline import Coach

    c = Coach()
    c.meeting.starten(virtuell=True)
    c.meeting.virtuelle_zeit = 50.0
    gestartet = []
    c.assistent.annehmen = lambda frage, quelle, sprecher=None: gestartet.append(frage)
    c.assistent.halten_start()
    c.meeting.virtuelle_zeit = 53.0
    c.assistent.halten_ende()
    asyncio.run(c.assistent.satz("Nestor, wer bucht eigentlich die Hotels?", 52.5))
    assert gestartet == []
    asyncio.run(c.assistent.satz("Nestor, wer bucht eigentlich die Hotels?", 80.0))
    assert len(gestartet) == 1


def test_knoepfe_auch_ohne_knopfdruck_regeln_aus_ampeln():
    from coach import knopfdruck
    from coach.pipeline import Coach

    c = Coach()
    c.meeting = _meeting()
    c.meeting.regel_ids = ["kurz", "ton"]
    c.hoerstrom = SimpleNamespace(live=None)
    c._client = object()
    karte = asyncio.run(knopfdruck._regeln(c, ""))  # live: ohne KI-Aufruf
    assert karte["art"] == "regeln" and len(karte["punkte"]) == 2
    knopfdruck.reservieren(c, "ueberblick")
    assert c.knopf.laeuft == "ueberblick"


# --- Ticket #15: Überblick auf Zuruf und im Takt, Protokoll am Ende ---------------------------------------------
_LEER = {"kernaussage": "x", "entschieden": [], "offen": [], "aufgaben": [], "ausserhalb": [], "neu": []}


def test_visuelle_uebersicht_ist_keine_folie():
    """Cloud-Lauf 08.10.: nach einer Recherche machte Mistral aus „mach uns die visuelle Übersicht“ eine Folie."""
    assert A.aktion_pruefen({"typ": "folie"}, "mach uns die visuelle Übersicht.") == {"typ": "bild", "fokus": "gesamt"}
    assert A.aktion_pruefen({"typ": "folie"}, "Ja, mach uns dazu eine Folie.") == {"typ": "folie"}
    assert A.aktion_pruefen({"typ": "folie"}, "ja gerne") == {"typ": "folie"}  # Antwort auf „Soll ich eine Folie …?“
    assert A.aktion_pruefen({"typ": "recherche", "frage": "x"}, "gib uns einen Überblick zu Messeständen") == {
        "typ": "recherche", "frage": "x"}
    s = A.system_text(wahl_fuer("basis"))
    assert "visuelle Übersicht" in s and "Eine Übersicht über das Meeting ist keine Folie" in s


def test_zuruf_mit_folie_aktion_zeigt_in_basis_den_ueberblick():
    from coach.pipeline import Coach

    c = Coach()
    c.stufe_setzen("basis")
    fake = FakeClient(_LEER)

    class Strom:
        def __aiter__(self):
            async def gen():
                yield SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(
                    content="AKTION: folie\nDie Folie erscheint gleich im Dashboard."))])
            return gen()

    async def create(**kw):
        return Strom() if kw.get("stream") else await fake._create(**kw)

    c._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    c.meeting = _meeting()
    c.letzte_recherche = {"frage": "Messestand", "text": "t", "quellen": [], "zeit": 1.0}

    async def lauf():
        c.assistent.frage_beantworten("Nestor, mach uns die visuelle Übersicht.", "taste")  # Funkgerät: Sprechtaste
        await c.assistent.bogen.task
        for _ in range(50):
            if c.ueberblick:
                break
            await asyncio.sleep(0.02)

    object.__setattr__(EINST, "stimme_aus", True)
    try:
        asyncio.run(lauf())
    finally:
        object.__setattr__(EINST, "stimme_aus", False)
    assert c.ueberblick and c.folie is None
    assert c.assistent.letzte["aktion"] == {"typ": "bild", "fokus": "gesamt"}


def test_kein_ueberblick_und_kein_bild_mehr_im_takt():
    """Ticket #27: Überblick (Basis) und Live-Bild (Premium) nur auf Anfrage und am Ende – nicht mehr alle 10 min."""
    from coach.pipeline import Coach

    for stufe in ("basis", "premium"):
        c = Coach()
        c.stufe_setzen(stufe)
        c._client = FakeClient(_LEER)
        c.meeting = _meeting()
        c.hoerstrom = object()  # nur „Meeting läuft mit Ton“ für den Takt
        gestartet = []
        c.ueberblick_starten = lambda fokus=None, nachholen=False: gestartet.append(c.meeting.jetzt())
        c.onepager_starten = lambda fokus=None: gestartet.append(c.meeting.jetzt())
        for t in (290.0, 299.0, 300.0, 600.0, 899.0, 900.0):
            c.meeting.virtuelle_zeit = t
            c.takt()
        assert gestartet == []


def test_basis_ueberblick_am_ende_wird_nachgeholt():
    from coach.pipeline import Coach

    c = Coach()
    c.stufe_setzen("basis")
    c._client = FakeClient(_LEER)
    c.meeting = _meeting()

    async def lauf():
        assert c.ueberblick_starten()  # Zuruf kurz vor Schluss
        assert not c.ueberblick_starten(nachholen=True)  # Meetingende, während der erste noch entsteht
        for _ in range(100):
            if c.ueberblick_version >= 2 and not c._ueberblick_laeuft:
                break
            await asyncio.sleep(0.02)

    asyncio.run(lauf())
    assert c.ueberblick_version == 2


def test_basis_paket_mit_protokoll_und_ueberblick(tmp_path, monkeypatch):
    """Cloud-Lauf 08.10.: das Paket in Basis hatte kein protokoll.md (Premium nimmt die Analyse des Abschlussbilds)."""
    import zipfile

    import coach.pipeline as P
    from coach.abschluss import paket
    from coach.pipeline import Coach

    alt_archiv = EINST.archiv
    object.__setattr__(EINST, "archiv", str(tmp_path))
    schlafen = asyncio.sleep

    async def kurz(s, *a):  # die Wartezeit für die Ergebnisprüfung (8 s) im Test abkürzen
        await schlafen(min(s, 0.01))

    monkeypatch.setattr(P.asyncio, "sleep", kurz)

    async def lauf():
        c = Coach()
        c.stufe_setzen("basis")
        c._client = None  # ohne Live-Text starten (kein Netz)
        c.archiv_aktiv = True
        c._einrichten({"titel": "Messeplanung 2027", "agenda": [{"titel": "Budget", "minuten": 10}],
                       "regel_ids": ["zeit"]})
        await c.hoeren_starten()
        await c.hoeren_zufuehren(bytes(24000 * 2))
        c.meeting.transkript = list(_meeting().transkript) + [
            Segment("Person 1", "Damit ist das Budget beschlossen, wir schauen nächste Woche wieder drauf.", 30, 52)]
        c._client = FakeClient({**_LEER, "artefakte": [
            {"typ": "entscheidung", "was": "höchstens 25.000 Euro", "status": "endgueltig", "wer": "die Runde",
             "zeit": "0:15", "konfidenz": 0.9}]})
        await c.hoeren_beenden()
        for _ in range(300):
            if c.archiv.fertig:
                break
            await schlafen(0.02)
        return c

    try:
        c = asyncio.run(lauf())
        assert c.archiv.fertig
        namen = zipfile.ZipFile(io.BytesIO(paket(c.archiv.ordner, False))).namelist()
        assert "protokoll.md" in namen and "ueberblick.md" in namen
        assert "meeting.json" in namen and "tasks.json" in namen  # Ticket #26: Grundlage für den Export (#22)
        protokoll = (c.archiv.ordner / "protokoll.md").read_text(encoding="utf-8")
        assert "am Meetingende" in protokoll and "höchstens 25.000 Euro" in protokoll
        assert not any(k["art"] == "protokoll" for k in c.karten)  # am Ende keine Karte
    finally:
        object.__setattr__(EINST, "archiv", alt_archiv)
