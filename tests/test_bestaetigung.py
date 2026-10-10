"""Ticket #21/#27 ohne Netz: Sofort-Bestätigung aus dem Zwischenspeicher, Text vor dem Ton, lange Aufträge abbrechen,
Hineinreden während der Wiedergabe (#20)."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from coach import bestaetigung as B
from coach.config import EINST
from coach.gespraech import RATE, Gespraech
from coach.pipeline import Coach
from coach.zustand import Segment


@pytest.fixture(autouse=True)
def bestaetigung_an(tmp_path, monkeypatch):
    """Bestätigung an, Floskeln in einem eigenen Ordner, Text-Weg; Nutzung nicht protokollieren."""
    alt = {k: getattr(EINST, k) for k in ("bestaetigung", "floskel_ordner", "assistent_modus", "stimme_aus")}
    object.__setattr__(EINST, "bestaetigung", True)
    object.__setattr__(EINST, "floskel_ordner", str(tmp_path / "floskeln"))
    object.__setattr__(EINST, "assistent_modus", "text")
    object.__setattr__(EINST, "stimme_aus", False)
    monkeypatch.setattr("coach.pipeline.nutzung_loggen", lambda e: None)
    yield
    for k, v in alt.items():
        object.__setattr__(EINST, k, v)


class _Strom:
    def __init__(self, teile):
        self.teile = teile

    def __aiter__(self):
        async def gen():
            for t in self.teile:
                await asyncio.sleep(0)
                yield SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=t))])
        return gen()


class _Ton:
    def __init__(self, zaehler):
        self.zaehler = zaehler

    async def __aenter__(self):
        self.zaehler.append(1)
        return self

    async def __aexit__(self, *x):
        return False

    async def iter_bytes(self, n):
        yield b"\x00\x00" * 200 + b"\x00\x30" * 4800 + b"\x00\x00" * 4000  # Stille, 0,2 s Ton, Stille


def _attrappe(antwort_teile, tts_aufrufe):
    async def create(**kw):
        return _Strom(antwort_teile)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(
            create=lambda **kw: _Ton(tts_aufrufe)))))


def _coach(antwort_teile=("AKTION: keine\nIhr seid bei Punkt eins.",)):
    c = Coach()
    c.stufe_setzen("premium")
    tts = []
    c._client = _attrappe(list(antwort_teile), tts)
    c.meeting.regel_ids = []
    c.meeting.starten(virtuell=True)
    gesendet: list[dict] = []

    async def senden(n):
        gesendet.append(n)
    c.direkt.append(senden)
    return c, gesendet, tts


def _vorrat(a, texte=B.ALLE):
    """Floskeln liegen schon im Zwischenspeicher (wie nach dem ersten Meeting mit dieser Stimme)."""
    for t in texte:
        p = a.floskeln.pfad(t)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00\x40" * 12000)  # 0,5 s


# --- Floskeln ------------------------------------------------------------------------------------------------
def test_floskel_wird_einmal_erzeugt_und_danach_aus_dem_speicher_gespielt():
    async def ablauf():
        c, gesendet, tts = _coach()
        a = c.assistent
        await a.floskeln.vorbereiten(c._client)
        erzeugt = len(tts)
        frisch = B.Floskeln(wahl=lambda: c.wahl)  # neuer Prozess: liest von der Platte
        await frisch.vorbereiten(c._client)
        return erzeugt, len(tts), frisch.da(B.LANG)

    erzeugt, danach, pcm = asyncio.run(ablauf())
    assert erzeugt == len(B.ALLE) and danach == erzeugt  # kein zweiter Sprachausgabe-Aufruf
    assert pcm is not None and len(pcm) < (200 + 4800 + 4000) * 2  # Stille vorn und hinten gekürzt


def test_stille_kuerzen_laesst_den_ton_stehen():
    pcm = b"\x00\x00" * 24000 + b"\x00\x30" * 2400 + b"\x00\x00" * 24000
    kurz = B.stille_kuerzen(pcm)
    assert 2400 * 2 <= len(kurz) <= (2400 + int(0.15 * RATE)) * 2


def test_kurze_floskeln_wechseln():
    f = B.Floskeln("/nicht/da")
    folge = [f.kurz() for _ in range(20)]
    assert all(x != y for x, y in zip(folge, folge[1:])) and len(set(folge)) >= 3
    assert all(len(x.split()) <= 2 for x in B.KURZ)
    assert all("gleich zurück" not in x.lower() for x in B.KURZ)


def test_lange_aufgaben_und_kein_auftrag_erkennen():
    assert B.ist_lang("gib uns einen Überblick zu Messeständen in Hannover")
    assert B.ist_lang("zeig uns die Übersicht") and B.ist_lang("mach eine Folie daraus")
    assert B.ist_lang("recherchier mal die Mietpreise")
    assert not B.ist_lang("wo stehen wir gerade?")
    assert not B.bestaetigen("danke, das war's") and not B.bestaetigen("stopp")
    assert B.bestaetigen("was ist beim Budget noch offen?")
    assert B.recherche_auftrag("Recherchier bitte die NIS2-Vorgaben.")
    assert B.recherche_auftrag("Such mal im Netz nach den NIS2-Vorgaben.")
    assert B.recherche_auftrag("Schau bitte kurz nach, was NIS2 verlangt.")
    assert not B.recherche_auftrag("Was verlangt NIS2?")


def test_explizite_recherche_umgeht_die_aktionswahl_des_modells():
    async def ablauf():
        c, _, _ = _coach(["AKTION: keine\nDazu weiß ich nichts."])
        gestartet = []

        async def lang(art, titel, fokus="", bogen=None):
            gestartet.append((art, titel))
            return True

        c.assistent.lang_annehmen = lang
        c.assistent.frage_beantworten("Recherchier bitte die NIS2-Vorgaben.", "taste")
        await c.assistent.bogen.task
        return gestartet

    assert asyncio.run(ablauf()) == [("recherche", "Recherchier bitte die NIS2-Vorgaben.")]


# --- Text-Weg (Basis und Premium „Kurzantwort“) ----------------------------------------------------------------
def test_bestaetigung_kommt_vor_der_antwort_und_ihr_text_vor_dem_ton():
    async def ablauf():
        c, gesendet, tts = _coach()
        _vorrat(c.assistent)
        await c.satz(Segment("Person 1", "Nestor, wie viel Zeit bleibt uns noch?", 1, 3))
        await c.assistent.bogen.task
        return gesendet, tts

    gesendet, tts = asyncio.run(ablauf())
    typen = [(n["typ"], n.get("floskel", False)) for n in gesendet]
    assert typen[0] == ("nestor_text", False) and gesendet[0]["neu"]
    assert gesendet[0]["frage"] == "wie viel Zeit bleibt uns noch?"
    assert gesendet[0]["text"] in B.KURZ
    assert typen[1] == ("stimme", True)  # Floskel aus dem Speicher – vor dem ersten Satz der Antwort
    erster_satz = next(i for i, n in enumerate(gesendet) if n["typ"] == "nestor_text" and "Punkt eins" in n["text"])
    assert gesendet[erster_satz + 1]["typ"] == "stimme" and not gesendet[erster_satz + 1].get("floskel")
    assert len(tts) == 1  # nur die Antwort ging an die Sprachausgabe, die Floskel nicht


def test_lange_aufgabe_sagt_die_wartezeit_an():
    async def ablauf():
        c, gesendet, _ = _coach(["AKTION: recherche Mindestlohn 2027\n"])
        _vorrat(c.assistent)

        async def langsam(*a, **k):
            await asyncio.sleep(30)
        import coach.recherche
        coach.recherche.recherchieren, alt = langsam, coach.recherche.recherchieren
        try:
            # Frage klingt nicht nach Recherche: die lange Ansage kommt mit der Aktionszeile
            await c.satz(Segment("Person 1", "Nestor, was gilt beim Mindestlohn ab 2027?", 1, 3))
            await c.assistent.bogen.task
            await asyncio.sleep(0.05)
            auftraege = c.assistent.auftraege.schnappschuss()
            for a in list(c.assistent.auftraege.liste):
                c.assistent.auftrag_abbrechen(a.id)
            await asyncio.sleep(0)
        finally:
            coach.recherche.recherchieren = alt
        return [n["text"] for n in gesendet if n["typ"] == "nestor_text"], auftraege

    texte, auftraege = asyncio.run(ablauf())
    assert texte[0] in B.KURZ and texte[1] in B.LANGE and len(texte) == 2  # das Modell sagt nichts dazu
    assert [(x["art"], x["zustand"]) for x in auftraege] == [("recherche", "laeuft")]


def test_danke_wird_nicht_bestaetigt():
    async def ablauf():
        c, gesendet, _ = _coach(["AKTION: keine\nGern."])
        _vorrat(c.assistent)
        await c.satz(Segment("Person 1", "Nestor, danke dir sehr.", 1, 3))
        await c.assistent.bogen.task
        return gesendet

    assert not any(n.get("floskel") for n in asyncio.run(ablauf()))


# --- Aufträge abbrechen --------------------------------------------------------------------------------------
def test_recherche_per_stimme_abbrechen_und_weitere_wartet():
    async def ablauf():
        c, gesendet, _ = _coach()
        a = c.assistent
        _vorrat(a)
        import coach.recherche

        async def langsam(*x, **k):
            await asyncio.sleep(30)
        coach.recherche.recherchieren, alt = langsam, coach.recherche.recherchieren
        try:
            await a.lang_annehmen("recherche", "Mindestlohn 2027")
            await a.lang_annehmen("recherche", "Mietpreise Hannover")
            erste, zweite = [x.task for x in a.auftraege.liste]
            await asyncio.sleep(0.05)
            vorher = a.auftraege.schnappschuss()
            await c.satz(Segment("Person 1", "Nestor, lass die Recherche.", 5, 7))
            await asyncio.sleep(0.05)
            mitte = a.auftraege.schnappschuss()
            await c.satz(Segment("Person 1", "Nestor, vergiss die Recherche.", 8, 9))
            await asyncio.sleep(0.05)
            return vorher, mitte, a.auftraege.schnappschuss(), erste.cancelled(), zweite.cancelled(), gesendet
        finally:
            coach.recherche.recherchieren = alt

    vorher, mitte, nachher, erste_weg, zweite_weg, gesendet = asyncio.run(ablauf())
    assert [x["zustand"] for x in vorher] == ["laeuft", "wartet"]
    assert [(x["titel"], x["zustand"]) for x in mitte] == [("Mindestlohn 2027", "laeuft")]  # die jüngste zuerst weg
    assert nachher == [] and erste_weg and zweite_weg
    assert [n["text"] for n in gesendet if n["typ"] == "nestor_text"].count(B.ABGEBROCHEN) == 2


def test_bild_auftrag_laeuft_wartet_und_ist_per_x_abbrechbar():
    async def ablauf():
        c, _, _ = _coach()
        a = c.assistent
        gezeichnet = []

        async def bild_erstellen(fokus=None):
            gezeichnet.append(fokus)
            await asyncio.sleep(30)
        c.bild_erstellen = bild_erstellen
        await a.lang_annehmen("bild", "zeig uns die Übersicht")
        await a.lang_annehmen("bild", "und nur das Budget", "Budget")
        erstes, zweites = list(a.auftraege.liste)
        await asyncio.sleep(0.01)
        stand = a.auftraege.schnappschuss()
        a.auftrag_abbrechen(zweites.id)  # ✕ am wartenden: es wird nie gezeichnet
        a.auftrag_abbrechen(erstes.id)  # ✕ am laufenden: Aufgabe abgebrochen
        await asyncio.sleep(0.01)
        return stand, erstes.task.cancelled(), zweites.task.cancelled(), gezeichnet, a.auftraege.liste

    stand, erstes_weg, zweites_weg, gezeichnet, rest = asyncio.run(ablauf())
    assert [(x["art"], x["zustand"]) for x in stand] == [("bild", "laeuft"), ("bild", "wartet")]
    assert erstes_weg and zweites_weg and gezeichnet == [None] and rest == []


def test_abbruch_ohne_offenen_auftrag_sagt_das():
    async def ablauf():
        c, gesendet, _ = _coach()
        _vorrat(c.assistent)
        await c.satz(Segment("Person 1", "Nestor, lass die Recherche.", 1, 3))
        return gesendet

    assert [n["text"] for n in asyncio.run(ablauf()) if n["typ"] == "nestor_text"] == [B.NICHTS_OFFEN]


def test_abbruchwunsch_erkennen():
    assert B.abbruch_wunsch("Nestor, lass die Recherche") and B.abbruch_art("Nestor, lass die Recherche") == "recherche"
    assert B.abbruch_wunsch("Nestor, brich das Bild ab") and B.abbruch_art("brich das Bild ab") == "bild"
    assert B.abbruch_wunsch("Nestor, die Folie brauchen wir nicht")
    assert not B.abbruch_wunsch("Nestor, lass uns über das Budget reden")
    assert not B.abbruch_wunsch("Nestor, zeig uns das Bild")


# --- Realtime-Gespräch -----------------------------------------------------------------------------------------
class _Verbindung:
    def __init__(self, ereignisse=()):
        self.gesendet: list[dict] = []
        self._ereignisse = list(ereignisse)

    async def send(self, roh):
        self.gesendet.append(json.loads(roh))

    async def close(self):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._ereignisse:
            raise StopAsyncIteration
        return json.dumps(self._ereignisse.pop(0))


def _gespraech(ereignisse=()):
    c, gesendet, _ = _coach()
    _vorrat(c.assistent)
    g = Gespraech(c.assistent)
    g._ws = _Verbindung(ereignisse)
    g.offen = True
    c.assistent.gespraech = g
    return c, g, g._ws, gesendet


def test_hineinreden_kuerzt_die_fertige_antwort_waehrend_der_wiedergabe():
    """#20: response.done ist längst da, der Ton läuft im Dashboard noch – jemand redet hinein: still und truncate."""
    async def ablauf():
        c, g, ws, gesendet = _gespraech([{"type": "input_audio_buffer.speech_started"}])
        c.meeting.virtuelle_zeit = 100.0
        g._antwort_laeuft = True
        await g._ton(base64.b64encode(bytes(RATE * 2 * 8)).decode(), "item_1")  # 8 s Ton
        g._antwort_text = "Ihr seid bei Punkt zwei. Offen ist noch der Puffer."
        await g._antwort_fertig({})
        assert c.assistent.zustand == "gespraech"  # fertig erzeugt, aber noch hörbar
        c.meeting.virtuelle_zeit = 103.4
        await g._empfangen()
        return c, ws, gesendet

    c, ws, gesendet = asyncio.run(ablauf())
    assert any(n["typ"] == "stimme_stopp" for n in gesendet)
    kuerzen = [e for e in ws.gesendet if e["type"] == "conversation.item.truncate"]
    assert kuerzen and kuerzen[0]["item_id"] == "item_1" and kuerzen[0]["audio_end_ms"] == 3000
    assert c.assistent.sprechzeiten[-1][1] == pytest.approx(103.9)


def test_nach_der_wiedergabe_kein_abbruch():
    async def ablauf():
        c, g, ws, gesendet = _gespraech([{"type": "input_audio_buffer.speech_started"}])
        c.meeting.virtuelle_zeit = 100.0
        await g._ton(base64.b64encode(bytes(RATE * 2 * 2)).decode(), "item_1")
        g._antwort_text = "Kurz."
        await g._antwort_fertig({})
        c.meeting.virtuelle_zeit = 110.0
        await g._empfangen()
        return ws, gesendet

    ws, gesendet = asyncio.run(ablauf())
    assert not any(n["typ"] == "stimme_stopp" for n in gesendet)
    assert not any(e["type"] == "conversation.item.truncate" for e in ws.gesendet)


def test_transkript_laeuft_als_text_mit():
    async def ablauf():
        c, g, ws, gesendet = _gespraech([
            {"type": "response.output_audio_transcript.delta", "delta": "Ihr seid "},
            {"type": "response.output_audio.delta", "delta": base64.b64encode(bytes(4800)).decode(), "item_id": "i"},
            {"type": "response.output_audio_transcript.delta", "delta": "bei Punkt zwei."}])
        c.assistent.text_neu("wo stehen wir?")
        await g._empfangen()
        return gesendet

    texte = [n for n in asyncio.run(ablauf()) if n["typ"] == "nestor_text"]
    assert [t["text"] for t in texte] == ["Ihr seid ", "bei Punkt zwei."]
    assert texte[0]["neu"] and texte[0]["frage"] == "wo stehen wir?" and texte[0]["delta"]


def test_langes_werkzeug_sagt_die_wartezeit_an_ohne_zweite_antwort():
    async def ablauf():
        c, g, ws, gesendet = _gespraech()
        c.meeting.transkript.append(Segment("Person 1", "Wir planen den Stand.", 0, 2))
        async def nichts(fokus=None):
            await asyncio.sleep(0)
        c.bild_erstellen = nichts
        await g._werkzeug("bild_zeichnen", json.dumps({"fokus": "gesamt"}), "call_1")
        await asyncio.sleep(0.01)
        return ws, gesendet

    ws, gesendet = asyncio.run(ablauf())
    texte = [n["text"] for n in gesendet if n["typ"] == "nestor_text"]
    assert len(texte) == 1 and texte[0] in B.LANGE
    assert [e["type"] for e in ws.gesendet] == ["conversation.item.create"]  # Ergebnis ans Modell, kein response.create


def test_recherche_im_gespraech_abbrechen():
    async def ablauf():
        c, g, ws, gesendet = _gespraech()
        import coach.recherche

        async def langsam(*x, **k):
            await asyncio.sleep(30)
        coach.recherche.recherchieren, alt = langsam, coach.recherche.recherchieren
        try:
            await g._werkzeug("recherchieren", json.dumps({"frage": "Mindestlohn 2027"}), "call_7")
            await asyncio.sleep(0.05)
            assert not g._antwort_laeuft  # die Runde kann Nestor währenddessen weiter fragen
            nr = c.assistent.auftraege.liste[0].id
            c.assistent.auftrag_abbrechen(nr)
            await asyncio.sleep(0.05)
        finally:
            coach.recherche.recherchieren = alt
        return c, ws

    c, ws = asyncio.run(ablauf())
    ausgabe = [e for e in ws.gesendet if e["type"] == "conversation.item.create"]
    assert ausgabe and "Hintergrund" in ausgabe[-1]["item"]["output"]
    assert not any(e["type"] == "response.create" for e in ws.gesendet) and c.assistent.auftraege.liste == []
