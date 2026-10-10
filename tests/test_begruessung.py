"""Begrüßung wie ein Mensch (Ticket #23): Pflichtpunkt-Prüfung, Nachsatz, Unterbrechung, Nein und Rückfall –
ohne Netz, mit einer Attrappe der Realtime-Verbindung."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from coach import assistent as A
from coach import begruessung as B
from coach.anbieter import wahl_fuer
from coach.config import EINST
from coach.gespraech import RATE
from coach.pipeline import Coach

VOLL = ("Hallo ihr, ich bin Nestor und begleite heute euer Meeting. Ihr wollt die Zeit einhalten. Dafür höre ich "
        "mit. Wer das nicht möchte, sagt einfach Nein, auch später noch mit Nestor, nein. Dann lösche ich alles. "
        "Los geht's mit Punkt eins: Standkonzept.")
OHNE_EINWILLIGUNG = "Hallo ihr, ich bin Nestor. Ihr wollt die Zeit einhalten. Los geht's mit Punkt eins: Standkonzept."


_STUFE = ["premium"]  # Stufe der nächsten Coach-Attrappe (_coach)


@pytest.fixture(autouse=True)
def premium():
    _STUFE[0] = "premium"
    alt = {k: getattr(EINST, k) for k in ("assistent_modus", "begruessung", "vorstellung_sekunden",
                                          "begruessung_frist_ton", "basis_begruessung_frei", "stimme_aus")}
    for k, v in {"assistent_modus": "gespraech", "begruessung": "frei",
                 "vorstellung_sekunden": 0.0, "begruessung_frist_ton": 1.0, "stimme_aus": True}.items():
        object.__setattr__(EINST, k, v)
    yield
    for k, v in alt.items():
        object.__setattr__(EINST, k, v)


# --- Prüfung der Pflichtpunkte -----------------------------------------------------------------------------
def test_vollstaendige_einwilligung_wird_erkannt():
    assert B.pflicht_fehlt(VOLL) == []
    assert B.pflicht_fehlt(B.nachsatz()) == []
    frei = ("Kurz zu mir: Ich hör die ganze Zeit mit. Passt euch das nicht, reicht ein einfaches Nein – auch "
            "später, dann mit „Nestor, nein“, und ich lösche alles.")
    assert B.pflicht_fehlt(frei) == []


def test_fehlende_teile_der_einwilligung_werden_benannt():
    assert B.pflicht_fehlt(OHNE_EINWILLIGUNG) == ["mithoeren", "nein", "spaeter", "loeschen"]
    ohne_spaeter = "Ich höre mit. Wer nicht einverstanden ist, sagt Nein, dann lösche ich alles."
    assert B.pflicht_fehlt(ohne_spaeter) == ["spaeter"]
    ohne_loeschen = "Ich höre mit. Wer nicht will, sagt Nein, auch später mit Nestor, nein."
    assert B.pflicht_fehlt(ohne_loeschen) == ["loeschen"]


def test_nur_der_hoerbare_teil_zaehlt():
    """Das Modell liefert schneller als Echtzeit: Beim Abbruch steht die Einwilligung im Transkript, war aber
    noch nicht zu hören."""
    antwort = {"text": VOLL, "bytes": RATE * 2 * 20}  # 20 s Ton
    assert B.hoerbar(antwort) == VOLL
    antwort["gekuerzt"] = 5.0  # nach 5 s ins Wort gefallen
    assert B.pflicht_fehlt(B.hoerbar(antwort)) != []
    assert len(B.hoerbar(antwort)) == len(VOLL) // 4


def test_nein_in_der_begruessungssitzung():
    assert B.nein_gehoert("Nein.", VOLL, frisch=True)
    assert B.nein_gehoert("Ich bin nicht einverstanden.", VOLL, frisch=True)
    assert B.nein_gehoert("Nestor, nein.", VOLL, frisch=False)
    assert not B.nein_gehoert("Nein, das sehe ich anders.", VOLL, frisch=False)
    assert not B.nein_gehoert("Passt, leg los.", VOLL, frisch=True)
    # Nestors eigener Satz über den Lautsprecher ist kein Einwand
    assert not B.nein_gehoert("Wer das nicht möchte, sagt einfach Nein, auch später noch.", VOLL, frisch=True)


def test_anweisung_listet_pflichtinhalte_ohne_sie():
    c = _coach()
    text = B.anweisung(c.meeting)
    for teil in ("ich höre mit", "„Nein“", "„Nestor, nein“", "löschst du alles", "Punkt eins: Standkonzept",
                 "Zeit einhalten", "niemals mit „Sie“", "reinreden"):
        assert teil in text, teil
    mit_namen = B.anweisung(c.meeting, vorstellung=True)
    assert A.NAMEN_BITTE in mit_namen and "Punkt eins: Standkonzept" in mit_namen  # Ticket #27: alles, dann Namen
    assert mit_namen.index("Punkt eins: Standkonzept") < mit_namen.index(A.NAMEN_BITTE)
    assert "Ein kurzer, menschlicher Kommentar" not in mit_namen


def test_nachsatz_wiederholt_nicht_die_gesamte_begruessung_wenn_nur_spaeter_fehlt():
    vorher = "Ich höre mit. Wer nicht einverstanden ist, sagt Nein, dann lösche ich alles."
    rest = B.nachsatz(["spaeter"])
    assert len(rest.split()) < 16
    assert B.pflicht_fehlt(vorher + " " + rest) == []


# --- Ablauf mit Attrappe ----------------------------------------------------------------------------------
class Verbindung:
    """Ereignisse vom Modell; ein Eintrag, der eine Funktion ist, bekommt den Coach (z. B. Zeit vorstellen)."""

    def __init__(self, ereignisse, coach):
        self.gesendet: list[dict] = []
        self._ereignisse = list(ereignisse)
        self.coach = coach

    async def send(self, roh):
        self.gesendet.append(json.loads(roh))

    async def close(self):
        self._ereignisse = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        while self._ereignisse:
            e = self._ereignisse.pop(0)
            if callable(e):
                e(self.coach)
                continue
            await asyncio.sleep(0)
            return json.dumps(e)
        await asyncio.sleep(3600)  # Sitzung bleibt offen, bis sie geschlossen wird
        raise StopAsyncIteration


def _coach():
    c = Coach()
    c.stufe_setzen(_STUFE[0])
    c._einrichten({"titel": "Messeplanung", "agenda": [{"titel": "Standkonzept", "minuten": 15},
                                                        {"titel": "Budget", "minuten": 20}],
                   "regel_ids": ["zeit"]})
    c._client = SimpleNamespace()  # nur „vorhanden“ – gesprochen wird über die Attrappe unten
    c.meeting.starten(virtuell=True)
    c.meeting.virtuelle_zeit = 10.0
    return c


def _ton(sekunden):
    return {"type": "response.output_audio.delta", "item_id": "item1",
            "delta": base64.b64encode(bytes(int(RATE * 2 * sekunden))).decode()}


def _antwort(text, sekunden, status="completed"):
    return [{"type": "response.created"}, _ton(sekunden),
            {"type": "response.output_audio_transcript.delta", "delta": text},
            {"type": "response.done", "response": {"status": status}}]


def _ablauf(monkeypatch, ereignisse):
    """begruessen() mit der Attrappe; liefert Coach, Verbindung, gesprochene feste Texte, Dashboard-Nachrichten."""
    c = _coach()
    gesprochen, dashboard = [], []
    ws = Verbindung(ereignisse, c)

    async def starten(self, frage=None):
        self._ws = ws
        self.offen = True
        self._empfang = asyncio.ensure_future(self._empfangen())

    async def sprechen(texte, danach="bereit", stil=None):
        gesprochen.extend(texte)
        c.assistent.zustand = danach
        return 0.0

    async def senden(n):
        dashboard.append(n)

    monkeypatch.setattr(B.Begruessung, "starten", starten)
    monkeypatch.setattr(c.assistent, "_sprechen_texte", sprechen)
    c.direkt.append(senden)

    async def los():
        await c.assistent.begruessen()
        if c.assistent.gespraech:
            await c.assistent.gespraech.schliessen()

    asyncio.run(los())
    return c, ws, gesprochen, dashboard


def test_freie_begruessung_mit_einwilligung_ohne_nachsatz(monkeypatch):
    c, ws, gesprochen, _ = _ablauf(monkeypatch, _antwort(VOLL, 0.25))
    assert gesprochen == []
    pruefung = [e for e in c.protokoll if e["art"] == "begruessung_pruefung"]
    assert pruefung[0]["ergebnis"] == "gesagt" and pruefung[0]["fehlt"] == []
    # danach normales Gespräch: der Coach entscheidet wieder, wann Nestor spricht
    td = ws.gesendet[-1]["session"]["audio"]["input"]["turn_detection"]
    assert ws.gesendet[-1]["type"] == "session.update" and td["create_response"] is False
    assert c.assistent._einwand_bis is not None


def test_fehlende_einwilligung_bekommt_den_festen_nachsatz(monkeypatch):
    c, _, gesprochen, _ = _ablauf(monkeypatch, _antwort(OHNE_EINWILLIGUNG, 0.25))
    assert gesprochen == [B.nachsatz()]


def test_ins_wort_gefallen_vor_der_einwilligung(monkeypatch):
    """„Passt, leg los“ nach 1 von 8 s: Die Einwilligung stand im Transkript, war aber nicht zu hören –
    Dashboard verstummt, Modell erfährt die Kürzung, nach seiner Reaktion kommt der Nachsatz."""
    def zeit(t):
        return lambda c: setattr(c.meeting, "virtuelle_zeit", t)

    ereignisse = (_antwort(VOLL, 8.0)
                  + [zeit(11.4), {"type": "input_audio_buffer.speech_started"},
                     {"type": "input_audio_buffer.speech_stopped"},
                     {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Passt, leg los."}]
                  + _antwort("Alles klar, dann los mit Punkt eins!", 0.25))
    c, ws, gesprochen, dashboard = _ablauf(monkeypatch, ereignisse)
    assert {"typ": "stimme_stopp"} in dashboard
    kuerzung = [e for e in ws.gesendet if e["type"] == "conversation.item.truncate"]
    assert kuerzung and kuerzung[0]["audio_end_ms"] == 1000  # Ton begann bei 10,4 s
    assert gesprochen == [B.nachsatz()]
    assert not [e for e in c.protokoll if e["art"] == "einwand"]


def test_nein_in_der_begruessung_loescht_und_schliesst(monkeypatch):
    ereignisse = [_ton(3.0), {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Nein."}]
    c, ws, gesprochen, dashboard = _ablauf(monkeypatch, [{"type": "response.created"}] + ereignisse)
    assert [e for e in c.protokoll if e["art"] == "einwand"]
    assert c.assistent.pausiert and c.assistent.gespraech is None
    assert {"typ": "stimme_stopp"} in dashboard
    assert len(gesprochen) == 1 and "gelöscht" in gesprochen[0]  # nur die Bestätigung, keine feste Begrüßung


def test_rueckfall_auf_feste_fassung_ohne_verbindung(monkeypatch):
    c = _coach()
    gesprochen = []

    async def starten(self, frage=None):
        raise OSError("keine Verbindung")

    async def sprechen(texte, danach="bereit", stil=None):
        gesprochen.extend(texte)
        return 0.0

    monkeypatch.setattr(B.Begruessung, "starten", starten)
    monkeypatch.setattr(c.assistent, "_sprechen_texte", sprechen)
    asyncio.run(c.assistent.begruessen())
    gruss, start = A.begruessungstext(c.meeting)
    assert gesprochen == [gruss, start]
    assert c.assistent.gespraech is None and c.assistent._einwand_bis is not None


def test_meeting_beendet_waehrend_der_begruessung(monkeypatch):
    """Stopp mitten in der Begrüßung schließt die Sitzung – danach kein Nachsatz und keine feste Fassung."""
    ereignisse = [{"type": "response.created"}, _ton(3.0), lambda c: c.meeting.beenden(),
                  lambda c: asyncio.ensure_future(c.assistent.gespraech.schliessen())]
    _, _, gesprochen, _ = _ablauf(monkeypatch, ereignisse)
    assert gesprochen == []


def test_rueckfall_wenn_kein_ton_kommt(monkeypatch):
    object.__setattr__(EINST, "begruessung_frist_ton", 0.05)
    c, _, gesprochen, _ = _ablauf(monkeypatch, [{"type": "error", "error": {"message": "kaputt"}}])
    gruss, start = A.begruessungstext(c.meeting)
    assert gesprochen == [gruss, start]


def test_fest_eingestellt_oder_basis_spricht_die_feste_fassung(monkeypatch):
    for einstellung in ({"begruessung": "fest"}, {"stufe": "basis"}):
        for k, v in einstellung.items():
            if k == "stufe":
                _STUFE[0] = v
            else:
                object.__setattr__(EINST, k, v)
        c, _, gesprochen, _ = _ablauf(monkeypatch, _antwort(VOLL, 0.25))
        gruss, start = A.begruessungstext(c.meeting, basis=c.wahl.basis)
        assert gesprochen == [gruss, start]
        object.__setattr__(EINST, "begruessung", "frei")
        _STUFE[0] = "premium"


# --- Basis: Mistral formuliert, sonst fest ----------------------------------------------------------------
class _Mistral:
    def __init__(self, text, warten=0.0):
        self.text, self.warten = text, warten
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kw):
        await asyncio.sleep(self.warten)
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))])


def test_basis_freier_text_nur_wenn_vollstaendig_und_schnell():
    c = _coach()
    m = c.meeting
    assert asyncio.run(B.basis_formulieren(_Mistral(VOLL), m, False, wahl=wahl_fuer("basis"))) == VOLL
    assert asyncio.run(B.basis_formulieren(_Mistral(OHNE_EINWILLIGUNG), m, False, wahl=wahl_fuer("basis"))) is None
    object.__setattr__(EINST, "basis_begruessung_frist", 0.05)
    try:
        assert asyncio.run(B.basis_formulieren(_Mistral(VOLL, warten=0.5), m, False, wahl=wahl_fuer("basis"))) is None
    finally:
        object.__setattr__(EINST, "basis_begruessung_frist", 2.0)
    # mit Vorstellungsrunde muss statt des Starts die Bitte um die Namen drin sein
    assert asyncio.run(B.basis_formulieren(_Mistral(VOLL), m, True, wahl=wahl_fuer("basis"))) is None


def test_basis_spricht_den_freien_text(monkeypatch):
    _STUFE[0] = "basis"
    object.__setattr__(EINST, "basis_begruessung_frei", True)
    c = _coach()
    c._client = _Mistral(VOLL)
    gesprochen = []

    async def sprechen(texte, danach="bereit", stil=None):
        gesprochen.extend(texte)
        return 0.0

    monkeypatch.setattr(c.assistent, "_sprechen_texte", sprechen)
    asyncio.run(c.assistent.begruessen())
    assert " ".join(gesprochen) == VOLL


def test_kein_startsatz_nach_der_vorstellungsrunde():
    """Ticket #27: Die Begrüßung sagt alles und endet mit der Bitte um die Namen – danach spricht Nestor nicht mehr
    von sich aus (früher kam nach der Runde ein Startsatz, im Cloudlauf Ton ohne Text)."""
    c = _coach()
    gesprochen = []

    async def sprechen(texte, danach="bereit", stil=None):
        gesprochen.extend(texte)
        return 0.0

    c.assistent._sprechen_texte = sprechen
    c.assistent.vorstellung_bis = 20.0
    c.meeting.virtuelle_zeit = 30.0
    c.assistent.takt()
    assert c.assistent.vorstellung_bis is None and gesprochen == []
    assert not hasattr(B.Begruessung, "start_sagen")


def test_ungenutzte_begruessungssitzung_schliesst_trotz_gespraech_im_raum():
    """Kosten: Redet die Runde nach der Begrüßung einfach los, bleibt die Sitzung nicht das ganze Meeting offen."""
    import time as _t

    async def ablauf(genutzt):
        c = _coach()
        b = B.Begruessung(c.assistent)
        b._ws, b.offen, b.phase, b.genutzt = Verbindung([], c), True, False, genutzt
        c.assistent.gespraech = b
        b._hart_ende = _t.monotonic() - 1
        b._ende_bis = _t.monotonic() + 50  # Sprechen im Raum hätte das Leerlauf-Ende verlängert
        await b.audio(bytes(4800))
        return b.offen

    assert asyncio.run(ablauf(False)) is False
    assert asyncio.run(ablauf(True)) is True  # nach einer Frage gilt das normale Leerlauf-Ende


def test_kurzes_nein_auch_wenn_die_transkription_neun_hoert():
    """Probe 08.10.: Das „Nein.“ kam als „Neun“ an – in der Begrüßung zählt es trotzdem, danach nicht mehr."""
    assert B.nein_gehoert("Neun", VOLL, frisch=True) and B.nein_gehoert("Nee.", VOLL, frisch=True)
    assert not B.nein_gehoert("Neun", VOLL, frisch=False)
    assert not B.nein_gehoert("Neun Punkte sind zu viel.", VOLL, frisch=True)


def test_nein_ueber_das_werkzeug_des_modells(monkeypatch):
    """Zweiter Weg: Hat das Modell das Nein verstanden, ruft es nicht_einverstanden – gelöscht wird trotzdem."""
    ereignisse = [{"type": "response.created"}, _ton(3.0),
                  {"type": "response.function_call_arguments.done", "name": "nicht_einverstanden", "arguments": "{}"}]
    c, ws, gesprochen, _ = _ablauf(monkeypatch, ereignisse)
    assert [e for e in c.protokoll if e["art"] == "einwand"]
    assert c.assistent.pausiert and len(gesprochen) == 1 and "gelöscht" in gesprochen[0]


def test_runde_legt_nach_der_begruessung_los_ohne_dass_nestor_antwortet(monkeypatch):
    """Begrüßung fertig gespielt, dann redet die Runde (kein Zwischenruf an Nestor): sofort normales Gespräch
    (create_response aus), kein Stummschalten, keine Kürzung – Cloudtest-Probe 08.10.: das offene
    Begrüßungsgespräch antwortete sonst mitten in den Monolog."""
    def zeit(t):
        return lambda c: setattr(c.meeting, "virtuelle_zeit", t)

    ereignisse = (_antwort(VOLL, 2.0)
                  + [zeit(13.0), {"type": "input_audio_buffer.speech_started"}])
    c, ws, gesprochen, dashboard = _ablauf(monkeypatch, ereignisse)
    assert {"typ": "stimme_stopp"} not in dashboard
    assert not [e for e in ws.gesendet if e["type"] == "conversation.item.truncate"]
    updates = [e for e in ws.gesendet if e["type"] == "session.update"]
    assert updates[-1]["session"]["audio"]["input"]["turn_detection"]["create_response"] is False
    assert c.assistent.gespraech is None or not c.assistent.gespraech.phase
