"""Ein Ergebnis-Modell: Die Paketdateien eines Meetings nennen in beiden Stufen dieselben Ergebnisse – die Artefakte
sind die einzige Quelle, protokoll.md, ueberblick.md, meeting.json/meeting.md und tasks.json sind Ansichten darauf."""

import asyncio
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from coach.config import EINST
from coach.zustand import Segment
from tests.e2e.schritte import PAKET_DATEIEN, _abschnitt, paket_abweichungen, paket_nennungen

ARTEFAKTE = [
    {"typ": "entscheidung", "was": "Budget höchstens 25.000 Euro", "status": "endgueltig", "wer": "die Runde",
     "zeit": "0:15", "konfidenz": 0.9},
    {"typ": "aufgabe", "was": "Drei Angebote einholen", "wer": "Lea", "bis": "Ende Oktober", "zeit": "0:30",
     "konfidenz": 0.9},
    {"typ": "offen", "was": "Wer bucht die Hotels?", "zeit": "0:40", "konfidenz": 0.9},
    {"typ": "entscheidung", "was": "Messestand mieten", "status": "vorschlag", "zeit": "0:45", "konfidenz": 0.9},
]
# Die Analyse hinter dem Live-Bild nennt bewusst etwas anderes – sie darf nirgends als Ergebnis auftauchen.
BILDANALYSE = "## Entscheidungen\n- Messe absagen\n## Aufgaben\n- Plakate drucken"


class FakeClient:
    """Eine Antwort für alle Textaufrufe: Artefakte für die Erkennung, Kernsatz für den Überblick."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        inhalt = {"kernaussage": "Budget steht", "ausserhalb": [], "artefakte": ARTEFAKTE}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(inhalt)))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def _meeting_ablegen(stufe: str, tmp_path, monkeypatch):
    import coach.pipeline as P
    from coach.pipeline import Coach

    object.__setattr__(EINST, "archiv", str(tmp_path))
    schlafen = asyncio.sleep

    async def kurz(s, *a):  # Wartezeit für die Ergebnisprüfung im Test abkürzen
        await schlafen(min(s, 0.01))

    monkeypatch.setattr(P.asyncio, "sleep", kurz)

    async def lauf():
        c = Coach()
        c.stufe_setzen(stufe)
        c._client = None
        c.archiv_aktiv = True
        c.onepager_am_ende = False  # kein Abschlussbild (Premium) – der Überblick kommt unten ausdrücklich
        c._einrichten({"titel": "Messeplanung", "agenda": [{"titel": "Budget", "minuten": 10}], "regel_ids": ["zeit"]})
        await c.hoeren_starten()
        await c.hoeren_zufuehren(bytes(24000 * 2))
        c.meeting.transkript = [Segment("Person 1", "Beschlossen: höchstens 25.000 Euro Budget.", 10, 16),
                                Segment("Lea", "Ich hole bis Ende Oktober drei Angebote ein.", 28, 33),
                                Segment("Person 2", "Wer bucht eigentlich die Hotels?", 38, 41),
                                Segment("Person 1", "Wir könnten einen Messestand mieten.", 43, 47)]
        c._client = FakeClient()
        c.onepager_analyse = BILDANALYSE
        await c.ueberblick_bauen(karte=False)
        await c.hoeren_beenden()
        for _ in range(300):
            if c.archiv.fertig:
                break
            await schlafen(0.02)
        return c

    return asyncio.run(lauf())


@pytest.mark.parametrize("stufe", ["basis", "premium"])
def test_paketdateien_nennen_dieselben_ergebnisse(stufe, tmp_path, monkeypatch):
    from coach.abschluss import paket

    alt = EINST.archiv
    try:
        c = _meeting_ablegen(stufe, tmp_path, monkeypatch)
    finally:
        object.__setattr__(EINST, "archiv", alt)
    assert c.archiv.fertig
    z = zipfile.ZipFile(io.BytesIO(paket(c.archiv.ordner, False)))
    lies = lambda n: z.read(n).decode("utf-8")  # noqa: E731
    meeting = json.loads(lies("meeting.json"))
    aufgaben = json.loads(lies("tasks.json"))
    protokoll, ueberblick, meeting_md = lies("protokoll.md"), lies("ueberblick.md"), lies("meeting.md")

    dateien = {n: lies(n) for n in PAKET_DATEIEN}
    assert paket_abweichungen(dateien) == []  # dieselbe Prüfung wie in Stufe B/C (tests/e2e/schritte.py)
    nennungen = paket_nennungen(dateien)
    erwartet = sorted(a["was"] for a in ARTEFAKTE)
    assert all(nennungen[d] == erwartet for d in ("protokoll.md", "ueberblick.md", "meeting.json", "meeting.md"))
    assert aufgaben and [a["was"] for a in aufgaben] == ["Drei Angebote einholen"]
    assert [a["id"] for a in aufgaben] == [a["id"] for a in meeting["aufgaben"]]  # dieselben Nummern
    gruppen = ("entscheidungen", "aufgaben", "offene_punkte", "risiken", "parkplatz")
    assert sorted(c.ueberblick["ids"]) == sorted(e["id"] for g in gruppen for e in meeting[g])
    assert _abschnitt(ueberblick, "Offen") == ["Wer bucht die Hotels?", "Messestand mieten (nur Vorschlag)"]

    # Dieselben Begriffe: ein bloßer Vorschlag heißt überall „nur Vorschlag“
    assert "Messestand mieten · nur Vorschlag" in protokoll and "Messestand mieten · nur Vorschlag" in meeting_md
    assert "Budget höchstens 25.000 Euro · beschlossen" in protokoll and "endgueltig" not in meeting_md
    # Die Bildanalyse ist nur Bildbeschreibung: sie erscheint in keiner Ergebnisdatei
    for text in (protokoll, ueberblick, meeting_md, json.dumps(meeting, ensure_ascii=False)):
        assert "Messe absagen" not in text and "Plakate drucken" not in text


def test_paketpruefung_findet_abweichende_datei():
    dateien = {"meeting.json": json.dumps({"entscheidungen": [{"was": "A"}], "aufgaben": [{"was": "B"}]}),
               "tasks.json": json.dumps([{"was": "B"}]), "protokoll.md": "- A · beschlossen\n- B · wer: X\n",
               "ueberblick.md": "## ✅ Entschieden\n- A\n## 📌 Aufgaben\n- C (wer: offen, bis: offen)\n"}
    abw = paket_abweichungen(dateien, "A B")
    assert len(abw) == 1 and abw[0].startswith("ueberblick.md")
    assert paket_abweichungen({"meeting.json": "{}"}) == ["fehlt im Paket: protokoll.md, tasks.json"]
