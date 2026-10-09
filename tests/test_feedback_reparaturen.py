"""Regressionen aus dem Pilotfeedback; keine privaten Meetinginhalte."""
import asyncio

from coach.pipeline import Coach
from coach.zustand import Agendapunkt, Segment
from coach.ueberblick import material
from coach import artefakte as A
from coach.mistral import websuche_lesen


def test_ueberblick_aktueller_punkt_filtert_quellen():
    c = Coach()
    m = c.meeting
    m.agenda = [Agendapunkt("Budget"), Agendapunkt("Termin")]
    m.aktiver_punkt = 1
    m.punkt_beginne = [(0, 0), (1, 20)]
    m.transkript = [Segment("Lea", "Alte vertrauliche Budgetdiskussion", 2, 5),
                    Segment("Jonas", "Der Termin ist Mittwoch", 22, 25)]
    m.ergebnisse = {0: {"ergebnis": "Altbeschluss"}, 1: {"ergebnis": "Neuer Termin"}}
    stoff = material(m, "aktueller Agendapunkt")
    assert "Mittwoch" in stoff and "Neuer Termin" in stoff
    assert "Budgetdiskussion" not in stoff and "Altbeschluss" not in stoff
    assert "Budgetdiskussion" in material(m, "gesamtes Meeting")


def test_assistentenaudio_zaehlt_nicht_als_ueberlappung():
    c = Coach()
    c.assistent.sprechzeiten = [(10, 15)]
    asyncio.run(c.sprecher_abschnitt([], 20, [9, 11, 16], [(8, 17)]))
    assert c.meeting.mischungen == [9, 16]
    assert c.meeting.ueberlappungen == [[8, 10], [15, 17]]


def test_recherche_quellen_auch_aus_markdown_und_keine_script_links():
    erg = websuche_lesen({"outputs": [{"type": "message.output", "content": [
        {"type": "text", "text": "Details bei [Hersteller](https://example.org/info)."},
        {"type": "tool_reference", "url": "javascript:alert(1)", "title": "falsch"}]}]})
    assert erg["quellen"] == [{"titel": "Hersteller", "url": "https://example.org/info"}]


def test_explizit_gemeinsame_verantwortung_aber_nicht_vages_jemand():
    c = Coach()
    saetze = [Segment("Lea", "Alle sind gemeinsam verantwortlich", 1, 3)]
    e = A.normalisieren({"typ": "aufgabe", "was": "Bericht senden", "wer": "alle", "bis": "Freitag", "gemeinsam": True})
    a = c.artefakte.uebernehmen(e, 1, saetze)
    assert a.vollstaendig and a.gemeinsam
    e = A.normalisieren({"typ": "aufgabe", "was": "Kostenübersicht erstellen", "wer": "jemand", "bis": "Freitag", "gemeinsam": True})
    a = c.artefakte.uebernehmen(e, 1, [Segment("Lea", "Jemand sollte die Kostenübersicht erstellen", 1, 3)])
    assert "wer" in a.luecken()


def test_gemeinsame_frist_und_spaetere_ausnahme():
    c = Coach()
    a = c.artefakte.anlegen("aufgabe", "Bericht senden", wer="Lea")
    b = c.artefakte.anlegen("aufgabe", "Plan senden", wer="Jonas")
    for x in (a, b):
        e = A.normalisieren({"nummer": x.id, "bis": "2026-10-10"})
        c.artefakte.uebernehmen(e, 1)
    assert a.bis == b.bis == "2026-10-10"
    c.artefakte.uebernehmen(A.normalisieren({"nummer": b.id, "bis": "2026-10-12"}), 2)
    assert a.bis == "2026-10-10" and b.bis == "2026-10-12"


def test_ausdrueckliche_berichtigung_ersetzt_falsches_artefakt():
    c = Coach()
    a = c.artefakte.anlegen("aufgabe", "Falscher Lieferumfang", wer="Lea")
    c.artefakte.uebernehmen(A.normalisieren({"nummer": a.id, "was": "Richtiger Lieferumfang", "korrigiert": True}),
                           2, [Segment("Lea", "Ich korrigiere den Lieferumfang", 2, 4)])
    assert a.was == "Richtiger Lieferumfang" and len(c.artefakte.liste) == 1


def test_relative_frist_hat_meetingdatum_im_prompt():
    c = Coach()
    c.meeting.gestartet_um = 1791532800
    assert "Meetingdatum (Europe/Berlin):" in A.nachricht(c.meeting, [], [], [])


def test_letzte_transkription_wird_abgewartet_oder_meldet_timeout():
    from types import SimpleNamespace
    from coach.hoeren import Hoerstrom

    async def lauf():
        h = object.__new__(Hoerstrom)
        h.knopfdruck = False
        h.vad = SimpleNamespace(ende=lambda: [])
        h._offen = {1: {}}
        async def fertig():
            await asyncio.sleep(0.01)
            h._offen.pop(1)
        t = asyncio.create_task(fertig())
        await h.text_abwarten(1)
        await t
        h._offen[2] = {}
        try:
            await h.text_abwarten(0)
        except TimeoutError:
            return
        raise AssertionError("Timeout muss statt alter Antwort sichtbar werden")
    asyncio.run(lauf())
