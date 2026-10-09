"""Begrüßung wie ein Mensch (Ticket #23): frei formuliert, unterbrechbar, Pflichtinhalte geprüft.

Premium: Die Begrüßung läuft als Realtime-Gespräch (gpt-realtime, dieselbe Technik wie coach/gespraech.py). Das
Modell bekommt die Pflichtinhalte als Liste, nicht als Wortlaut, und formuliert frei. Anders als im späteren
Gespräch antwortet es hier selbst auf Zwischenrufe (semantic VAD mit create_response und interrupt_response):
„Passt, leg los“ kürzt die Begrüßung ab, eine Frage wird kurz beantwortet.

Die Einwilligung darf nie fehlen. Deshalb wird das Ausgabe-Transkript geprüft – und zwar nur der Teil, der
wirklich zu hören war: Das Modell liefert den Ton schneller als Echtzeit, wer dazwischenruft, schneidet den Rest
ab. Fehlen „ich höre mit“ oder die Nein-Möglichkeit (auch später als „Nestor, nein“, dann wird gelöscht), sagt
Nestor einen festen Nachsatz. Kommt kein Ton zustande, gilt die feste Fassung (assistent.begruessungstext).

Ein „Nein“ während der Begrüßung läuft über die bestehende Einwand-Logik (Assistent._einwand_erhalten): über den
Live-Text wie bisher und zusätzlich über die Transkription des Mikrofons in dieser Sitzung, weil der Echo-Filter
des Live-Texts Sätze verwirft, die in Nestors Sprechzeit fallen.

Basis (Mistral): optional formuliert mistral-small denselben Inhalt frei, mit derselben Prüfung; kommt der Text
nicht binnen LMC_BASIS_BEGRUESSUNG_FRIST oder fehlt ein Pflichtpunkt, gilt die feste Fassung.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from .assistent import NAMEN_BITTE
from .config import EINST
from .gespraech import RATE, Gespraech

log = logging.getLogger("coach.begruessung")

# --- Pflichtinhalte -----------------------------------------------------------------------------------------
MITHOEREN_RE = re.compile(r"\bh[öo]r\w*\s+(?:\w+\s+){0,5}?(?:mit|zu)\b|\bmith[öo]r|\bmitzuh[öo]r|\bzuh[öo]r",
                          re.IGNORECASE)
NEIN_RE = re.compile(r"\bnein\b", re.IGNORECASE)
LOESCHEN_RE = re.compile(r"l[öo]sch|\balles\s+(?:\w+\s+)?weg\b", re.IGNORECASE)  # „lösche ich alles“, „ist alles weg“
NAME_NEIN_RE = re.compile(rf"\b(?:{EINST.assistent_muster})\W+nein\b", re.IGNORECASE)
PUNKT_EINS_RE = re.compile(r"punkt (?:eins|1)\b|ersten punkt|erste[nm]? (?:agenda)?punkt", re.IGNORECASE)
NAME_RE = re.compile(rf"\b(?:{EINST.assistent_muster})\b", re.IGNORECASE)


def pflicht_fehlt(text: str) -> list[str]:
    """Welche Teile der Einwilligung fehlen im Gesagten? Leer = alles da.

    mithoeren: „ich höre mit“ (auch „hör zu“, „mithören“); nein: ein „Nein“ genügt; spaeter: „Nestor, nein“;
    loeschen: dass dann gelöscht wird."""
    fehlt = []
    if not MITHOEREN_RE.search(text):
        fehlt.append("mithoeren")
    if not NEIN_RE.search(text):
        fehlt.append("nein")
    if not NAME_NEIN_RE.search(text):
        fehlt.append("spaeter")
    if not LOESCHEN_RE.search(text):
        fehlt.append("loeschen")
    return fehlt


def basis_text_vollstaendig(text: str, vorstellung: bool) -> bool:
    """Basis prüft strenger: neben der Einwilligung auch Name und Start (bzw. die Bitte um die Namen)."""
    if pflicht_fehlt(text) or not NAME_RE.search(text):
        return False
    if vorstellung:
        return bool(re.search(r"\bnamen?\b", text, re.IGNORECASE))
    return bool(PUNKT_EINS_RE.search(text))


def nachsatz(fehlend: list[str] | None = None) -> str:
    """Fester Nachsatz, wenn in der freien Begrüßung ein Teil der Einwilligung fehlte."""
    name = EINST.assistent_name
    if fehlend == ["spaeter"]:
        return f"Auch später könnt ihr widersprechen: „{name}, nein“. Dann lösche ich alles."
    return (f"Eins noch, damit es klar ist: Ich höre mit. Wer nicht einverstanden ist, sagt einfach Nein – "
            f"das geht auch später noch, dann mit meinem Namen: „{name}, nein“. Dann lösche ich alles.")


def _woerter(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3]


KURZES_NEIN_RE = re.compile(r"^\W*(?:nein|neun|nee|ne|nö|noe)\W*$", re.IGNORECASE)


def nein_gehoert(gehoert: str, gesagt: str, frisch: bool) -> bool:
    """Ist das, was das Mikrofon in der Begrüßungssitzung hörte, ein Nein? Dieselben Muster wie der Live-Text
    (assistent.einwand, im Fenster der Begrüßung; danach nur „Nestor, nein“). Ein langer Satz, der fast nur aus
    Nestors eigenen Worten besteht („Wer nicht einverstanden ist, sagt einfach Nein …“), ist sein Echo und zählt
    nicht. Ein kurzes „Nein“ oder „Ich bin nicht einverstanden“ zählt immer – lieber einmal zu viel gelöscht."""
    from .assistent import echo, einwand, spaetes_nein

    # Ein kurzes „Nein“ kam in der Probe 08.10. als „Neun“ an; „Nee“/„Nö“ sind auch ein Nein
    kurz = frisch and bool(KURZES_NEIN_RE.match(gehoert))
    if not ((frisch and einwand(gehoert)) or spaetes_nein(gehoert) or kurz):
        return False
    return not (len(_woerter(gehoert)) >= 6 and echo(gehoert, gesagt))


def hoerbar(antwort: dict) -> str:
    """Der Teil einer Antwort, der wirklich zu hören war: beim Ins-Wort-Fallen anteilig nach der Spielzeit."""
    text = antwort.get("text", "")
    gekuerzt = antwort.get("gekuerzt")
    if gekuerzt is None:
        return text
    dauer = antwort.get("bytes", 0) / 2 / RATE
    if dauer <= 0:
        return ""
    return text[: int(len(text) * min(1.0, max(0.0, gekuerzt) / dauer))]


# --- Anweisungen ------------------------------------------------------------------------------------------
def _regeln(meeting) -> str:
    from .regeln import NACH_ID

    regeln = [NACH_ID[r].titel.split(" – ")[0] for r in meeting.regel_ids if r in NACH_ID]
    weitere = [r.strip() for r in meeting.regeln if r.strip()]
    teile = []
    if regeln:
        teile.append("; ".join(regeln))
    if weitere:
        teile.append("dazu eigene Regeln der Runde (nicht deine): " + "; ".join(weitere[:3])
                     + (f" und {len(weitere) - 3} weitere, die auf dem Bildschirm stehen" if len(weitere) > 3 else ""))
    return " – ".join(teile)


def pflichtinhalte(meeting, basis: bool = False, vorstellung: bool = False) -> str:
    """Die Pflichtinhalte als nummerierte Liste (Ticket #23) – für Realtime (Premium) und Mistral (Basis)."""
    name = EINST.assistent_name
    regeln = _regeln(meeting)
    z = [f"1. Wer du bist: {name}, du begleitest heute ihr Meeting als Moderationsassistent.",
         ("2. Die Regeln, die sich die Runde vorgenommen hat, kurz und ohne sie vorzulesen: " + regeln) if regeln
         else "2. (Es sind keine Regeln gewählt – lass das weg.)",
         "3. Dass du mithörst. Sag ausdrücklich „ich höre mit“.",
         f"4. Bei „Nein“ löschst du alles. Sag vollständig und wörtlich: „Ich höre mit. Nicht einverstanden? "
         f"Sagt Nein – auch später mit „{name}, nein“. Dann lösche ich alles.“ Mit Punkt 3 verbinden, nicht doppelt "
         "erklären. Diesen Punkt nie weglassen oder abschwächen."]
    z.append(start_inhalte(meeting, basis, ab=5))
    if vorstellung:  # Ticket #27: die Begrüßung sagt alles und endet mit der Bitte um die Namen – kein Startsatz danach
        z.append(f"{len(z) + 1 + z[-1].count(chr(10))}. Ganz zum Schluss, als letzter Satz: „{NAMEN_BITTE}“")
    return "\n".join(z)


def start_inhalte(meeting, basis: bool = False, ab: int = 1) -> str:
    """Punkte 5–7: Ansprache (Telefon bzw. Funkgerät, Ticket #27), Agenda-Bitte mit Kommentar, Start mit Punkt eins."""
    from .assistent import agenda_bitte

    name = EINST.assistent_name
    if basis:
        wie = ("Wie man mit dir spricht: Du funktionierst wie ein Funkgerät – Taste halten, sprechen, loslassen, du "
               "redest dann aus. Die Taste ist auf dem Bildschirm und am Handy, am Laptop geht auch die Leertaste.")
    else:
        wie = (f"Wie man mit dir spricht: wie am Telefon – „{name}“ und die Frage. Direkt danach geht eine Nachfrage "
               "ohne Namen, und wenn du zu viel redest, dürfen sie einfach reinreden. Von dir aus sagst du nichts, "
               "Hinweise erscheinen still auf dem Bildschirm.")
    z = [f"{ab}. {wie}"]
    agenda = []
    if agenda_bitte(meeting):
        agenda.append("Die Bitte, den Wechsel zum nächsten Agendapunkt kurz anzusagen oder ihn anzuklicken – auf "
                      "Wunsch fasst du vorher zusammen.")
    if agenda:
        z.append(f"{ab + 1}. " + " ".join(agenda))
    erster = f"„Punkt eins: {meeting.agenda[0].titel}“" if meeting.agenda else "„Los geht's“"
    z.append(f"{ab + len(z)}. Zum Schluss der Start: {erster}.")
    return "\n".join(z)


def _agenda(meeting) -> str:
    if not meeting.agenda:
        return "(keine Agenda)"
    return "; ".join(f"{i + 1}. {p.titel} ({p.minuten:.0f} min)" for i, p in enumerate(meeting.agenda))


ANWEISUNG = """\
Du bist {name}, der Moderationsassistent dieser Runde, und eröffnest jetzt ein Präsenzmeeting. Alle sitzen im \
Raum und hören dich über einen Lautsprecher.

So sprichst du: frei, wie ein sympathischer Mensch, nicht vorgelesen. Warm, locker, gern mit einem Schuss Humor, \
natürliches Tempo, kleine Pausen, ein Lächeln in der Stimme. Deutsch. Die Runde sprichst du mit „ihr“ an, eine \
einzelne Person mit „du“ – niemals mit „Sie“. Keine Liste aufsagen, sondern erzählen. Länge: etwa 25 \
Sekunden, höchstens 35 – lieber kürzer. Höchstens 75 Wörter insgesamt: vier bis sechs kurze Sätze, \
zügig und gut verständlich, ohne gehetzt zu klingen. Keine zusätzlichen Beispiele, Agenda-Bewertungen oder \
Schlusserklärungen; Pflichtinhalte knapp verbinden und nichts doppelt erklären. Fang direkt mit der Begrüßung \
an, nicht mit „Alles klar“ oder „Okay“.

Diese Inhalte müssen vorkommen, in eigenen Worten, ungefähr in dieser Reihenfolge:
{pflicht}

Wenn jemand dazwischenredet:
- „Passt“, „leg los“, „alles klar“ oder Ähnliches: Hör auf zu erklären. Hast du Punkt 3 und 4 noch nicht gesagt, \
sag sie jetzt in einem kurzen Satz. Dann geht es direkt los{los}.
- Eine Frage: kurz beantworten, dann knapp weiter.
- „Nein“ oder Widerspruch gegen das Mithören: Ruf sofort das Werkzeug nicht_einverstanden auf und sag nichts \
dazu. Behaupte nie selbst, dass du etwas löschst oder aufhörst – das erledigt das System.

Das Meeting: {titel}{ziel}. Agenda: {agenda}.
"""

BASIS_ANWEISUNG = """\
Du schreibst die Begrüßung, die {name}, ein Moderationsassistent, gleich zu Beginn eines Präsenzmeetings \
spricht. Der Text wird vorgelesen. Locker, warm, menschlich, gern mit etwas Humor, jedes Mal etwas anders. \
Ansprache „ihr“, nie „Sie“. Höchstens 90 Wörter. Formuliere knapp und verbinde Inhalte, statt jeden Punkt \
einzeln zu erklären. Nur der gesprochene Text: keine Überschrift, keine \
Aufzählungszeichen, kein Markdown, keine Regieanweisungen.

Diese Inhalte müssen vorkommen, in eigenen Worten, in dieser Reihenfolge:
{pflicht}

Wörtlich so verwenden: „ich höre mit“, „Nein“, „{name}, nein“ und dass du dann alles löschst.

Das Meeting: {titel}{ziel}. Agenda: {agenda}.
"""


def anweisung(meeting, vorstellung: bool = False) -> str:
    ziel = f" (Ziel: {meeting.ziel})" if meeting.ziel else ""
    los = "" if vorstellung else " mit Punkt eins"
    return ANWEISUNG.format(name=EINST.assistent_name, pflicht=pflichtinhalte(meeting, False, vorstellung),
                            los=los, titel=meeting.titel or "ohne Titel", ziel=ziel, agenda=_agenda(meeting))


EINWAND_WERKZEUG = {
    "type": "function", "name": "nicht_einverstanden",
    "description": "Jemand in der Runde hat Nein gesagt oder ist nicht einverstanden, dass du mithörst. Sofort "
                   "aufrufen, ohne etwas dazu zu sagen. Das System löscht dann alles und schaltet dich stumm.",
    "parameters": {"type": "object", "properties": {}}}


# --- Premium: Begrüßung im Realtime-Gespräch ---------------------------------------------------------------
class Begruessung(Gespraech):
    """Ein Gespräch, das mit der Begrüßung beginnt. Solange sie läuft (`phase`), antwortet das Modell selbst auf
    Zwischenrufe; danach wird die Sitzung zum normalen Gespräch (create_response aus, Werkzeuge, Leerlauf-Ende)."""

    def __init__(self, assistent, vorstellung: bool = False) -> None:
        super().__init__(assistent)
        self.vorstellung = vorstellung
        self.phase = True
        self.ergebnis = ""  # gesagt | abgebrochen | fehler | einwand
        self.fertig = asyncio.Event()
        self.ton_da = asyncio.Event()
        self.antworten: list[dict] = []  # je Antwort: item, beginn, bytes, text, status, gekuerzt
        self.zwischenrufe: list[dict] = []  # was das Mikrofon in der Sitzung hörte (für Probe und Protokoll)
        self.t0 = time.monotonic()
        self._akt: dict | None = None  # Antwort, deren Ton gerade kommt
        self._ende_aufgabe: asyncio.Task | None = None
        self._einwand_aufgabe: asyncio.Task | None = None
        # Kosten: Ungenutzt schließt die Sitzung kurz nach der Begrüßung (bzw. nach dem Start nach der
        # Vorstellungsrunde), auch wenn die Runde weiterredet – sonst bliebe sie das ganze Meeting offen und die
        # nächste Antwort trüge Minuten mitgehörten Tons als Eingabe. Eine Frage an Nestor macht sie zum normalen
        # Gespräch mit dem bisherigen Leerlauf-Ende.
        self.genutzt = False
        self._hart_ende: float | None = None
        self._ende_bis = time.monotonic() + 3600  # Leerlauf-Ende erst nach der Begrüßung

    # --- Auf- und Abbau ---
    async def starten(self, frage: str | None = None) -> None:
        import websockets

        from .config import openai_schluessel
        from .gespraech import URL

        if EINST.stufe == "basis":
            raise RuntimeError("Realtime-Begrüßung gibt es nur in Nestor Premium")
        self._ws = await websockets.connect(URL.format(modell=EINST.realtime_modell),
                                            additional_headers={"Authorization": f"Bearer {openai_schluessel()}"},
                                            max_size=None)
        await self._senden({"type": "session.update", "session": {
            "type": "realtime",
            "instructions": anweisung(self.coach.meeting, self.vorstellung),
            "output_modalities": ["audio"],
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": RATE},
                          "transcription": {"model": EINST.begruessung_transkription, "language": "de",
                                            "prompt": f"{EINST.assistent_name}. Nein. {EINST.assistent_name}, nein. "
                                                      "Passt, leg los."},
                          # eagerness high: ein kurzes „Nein“ oder „Passt“ beendet den Turn sofort (Probe 08.10.: mit
                          # „auto“ kam das Nein erst ~5 s später an)
                          "turn_detection": {"type": "semantic_vad", "eagerness": "high", "create_response": True,
                                             "interrupt_response": True}},
                "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": EINST.stimme},
            },
            "tools": [EINWAND_WERKZEUG], "tool_choice": "auto",
        }})
        self.offen = True
        self._empfang = asyncio.create_task(self._empfangen())
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "message", "role": "system",
            "content": [{"type": "input_text", "text": "Das Meeting beginnt jetzt. Begrüße die Runde."}]}})
        self._antwort_laeuft = True
        await self._senden({"type": "response.create"})

    async def schliessen(self) -> None:
        if self.phase:
            self.phase = False
            if self._akt:  # Verbindung mitten in einer Antwort weg: gesagt ist, was schon ankam
                self.antworten.append(self._akt)
                self._akt = None
            if not self.ergebnis:
                self.ergebnis = "abgebrochen" if any(a.get("bytes") for a in self.antworten) else "fehler"
            self.fertig.set()
        if self._ende_aufgabe:
            self._ende_aufgabe.cancel()
        await super().schliessen()

    def gesagt(self) -> str:
        """Was hörbar gesagt wurde – Grundlage der Pflichtpunkt-Prüfung."""
        return " ".join(t for t in (hoerbar(a) for a in self.antworten) if t)

    # --- Während der Begrüßung ---
    async def audio(self, pcm24k: bytes) -> None:
        await super().audio(pcm24k)
        if (self.offen and not self.genutzt and self._hart_ende is not None and time.monotonic() > self._hart_ende
                and not self._antwort_laeuft):
            await self.schliessen()

    async def _antworten_lassen(self) -> None:
        if not self.phase:
            self.genutzt = True  # jemand hat Nestor nach der Begrüßung etwas gefragt
        await super()._antworten_lassen()

    def _ende_planen(self, sekunden: float) -> None:
        if self._ende_aufgabe:
            self._ende_aufgabe.cancel()

        async def spaeter():
            await asyncio.sleep(max(0.0, sekunden))
            await self._phase_beenden()

        self._ende_aufgabe = asyncio.ensure_future(spaeter())

    async def _phase_beenden(self) -> None:
        """Begrüßung fertig gespielt: ab jetzt normales Gespräch (der Coach entscheidet, wann Nestor spricht)."""
        if not self.phase:
            return
        self.phase = False
        await self._senden({"type": "session.update", "session": self.sitzung()})
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden
        self._antwort_ende = self.a.sprechzeiten[-1][1] if self.a.sprechzeiten else self.coach.meeting.jetzt()
        self._hart_ende = self._ende_bis  # ungenutzt schließt die Sitzung kurz nach der Begrüßung
        self.ergebnis = self.ergebnis or "gesagt"
        self.fertig.set()

    async def _ereignis(self, typ: str, e: dict) -> bool:
        c, m = self.coach, self.coach.meeting
        if typ == "conversation.item.input_audio_transcription.completed":
            text = (e.get("transcript") or "").strip()
            if text:
                self.zwischenrufe.append({"zeit": round(time.monotonic() - self.t0, 1), "text": text})
                a = self.a
                frisch = self.phase or (a._einwand_bis is not None and m.jetzt() <= a._einwand_bis)
                if not a.pausiert and self.ergebnis != "einwand" and nein_gehoert(text, self.gesagt() + " " + (self._akt or {}).get("text", ""),
                                                   frisch):
                    self.ergebnis = "einwand"
                    log.info("Begrüßung: Nein gehört")
                    # schließt diese Sitzung – deshalb nicht im Empfang warten; Verweis halten, sonst kann die
                    # Aufgabe vor dem Ende eingesammelt werden
                    self._einwand_aufgabe = asyncio.ensure_future(a._einwand_erhalten())
            return False
        if typ == "response.function_call_arguments.done" and e.get("name") == "nicht_einverstanden":
            # Zweiter Weg für das Nein: das Modell hat es verstanden, auch wenn die Transkription es verfehlte
            if not self.a.pausiert and self.ergebnis != "einwand":
                self.ergebnis = "einwand"
                log.info("Begrüßung: Nein (Werkzeug)")
                self._einwand_aufgabe = asyncio.ensure_future(self.a._einwand_erhalten())
            return True
        if typ == "error":
            log.warning("Begrüßung: Fehler vom Modell: %s", str(e.get("error", {}).get("message", ""))[:200])
            return True
        if not self.phase:
            return False
        if typ == "response.created":
            self._antwort_laeuft = True
            if self._ende_aufgabe:
                self._ende_aufgabe.cancel()
            return True
        if typ in ("response.output_audio.delta", "response.audio.delta"):
            await self._ton(e["delta"])
            if self._akt is None:
                self._akt = {"item": e.get("item_id"), "beginn": self._ton_beginn, "bytes": 0, "text": ""}
            self._akt["bytes"] += len(e["delta"]) * 3 // 4
            self.ton_da.set()
            return True
        if typ in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
            if self._akt is not None:
                self._akt["text"] += e.get("delta", "")
            return False  # der Standardweg sammelt den Antworttext
        if typ == "input_audio_buffer.speech_started":
            await self._ins_wort_gefallen()
            return True
        if typ == "input_audio_buffer.speech_stopped":
            self._ende_planen(8.0)  # Rückfall, falls das Modell nicht reagiert; eine neue Antwort hebt das auf
            return True
        return False

    async def _ins_wort_gefallen(self) -> None:
        """Jemand spricht: läuft Nestors Ton noch (auch wenn die Antwort schon fertig erzeugt ist), sofort still,
        dem Modell sagen, wie weit es zu hören war (conversation.item.truncate), und auf seine Reaktion warten."""
        c, a = self.coach, self.a
        jetzt = c.meeting.jetzt()
        laufend = self._akt or (self.antworten[-1] if self.antworten else None)
        spielt = bool(laufend and laufend.get("beginn") is not None
                      and jetzt - laufend["beginn"] < laufend["bytes"] / 2 / RATE)
        if not spielt and not self._antwort_laeuft and self.antworten:
            # Begrüßung ist fertig gesprochen und die Runde legt los: das ist kein Zwischenruf an Nestor.
            # Sonst antwortet das Modell (create_response) mitten ins Meeting (Cloudtest-Probe 08.10., ~80 s).
            await self._phase_beenden()
            return
        if self._ende_aufgabe:
            self._ende_aufgabe.cancel()
        if laufend and laufend.get("beginn") is not None and "gekuerzt" not in laufend:
            dauer = laufend["bytes"] / 2 / RATE
            gespielt = jetzt - laufend["beginn"]
            if gespielt < dauer:
                await c.direkt_senden({"typ": "stimme_stopp"})
                laufend["gekuerzt"] = max(0.0, gespielt)
                if a.sprechzeiten:
                    s, b = a.sprechzeiten[-1]
                    a.sprechzeiten[-1] = (s, min(b, jetzt + 0.5))
                if laufend.get("item"):
                    await self._senden({"type": "conversation.item.truncate", "item_id": laufend["item"],
                                        "content_index": 0, "audio_end_ms": int(max(0.0, gespielt) * 1000)})
                log.info("Begrüßung unterbrochen nach %.1f von %.1f s", gespielt, dauer)
        a.zustand = "angesprochen"
        await c.melden()

    async def _antwort_fertig(self, antwort: dict) -> None:
        if not self.phase:
            await super()._antwort_fertig(antwort)
            return
        c, a = self.coach, self.a
        text = self._antwort_text.strip()
        self._antwort_text = ""
        self._ton_ende(abgebrochen=False)
        self._antwort_laeuft = False
        status = antwort.get("status", "")
        self._nutzung(antwort)
        w, self._akt = self._akt, None
        if w is not None:
            w["text"], w["status"] = text or w["text"], status
            if self.phase:
                self.antworten.append(w)
        if text and a.sprechzeiten:
            a.sprechtexte.append((*a.sprechzeiten[-1], text))  # Echo-Filter nach Inhalt
        c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "begruessung", "status": status,
                            "text": hoerbar(w) if w else text})
        if status == "completed":
            ende = (w["beginn"] + w["bytes"] / 2 / RATE) if w and w.get("beginn") is not None else c.meeting.jetzt()
            self._ende_planen(ende - c.meeting.jetzt() + 0.3)  # erst wenn alles gespielt ist
        elif status != "cancelled":  # failed/incomplete: nicht auf eine Reaktion warten
            self._ende_planen(0.0)
        if a.zustand not in ("pausiert", "angesprochen"):
            a.zustand = "begruessung"
        await c.melden()

    def _nutzung(self, antwort: dict) -> None:
        nutzung = antwort.get("usage") or {}
        if nutzung:
            from .pipeline import nutzung_loggen
            nutzung_loggen({"art": "gespraech", "zweck": "begruessung", "modell": EINST.realtime_modell,
                            "tokens_rein": nutzung.get("input_tokens"), "tokens_raus": nutzung.get("output_tokens"),
                            "details_rein": nutzung.get("input_token_details"),
                            "details_raus": nutzung.get("output_token_details")})

# --- Basis: Text von Mistral, gesprochen per TTS ------------------------------------------------------------
async def basis_formulieren(client, meeting, vorstellung: bool) -> str | None:
    """Freier Begrüßungstext von Mistral; None bei Fehler, Zeitüberschreitung oder fehlendem Pflichtpunkt."""
    ziel = f" (Ziel: {meeting.ziel})" if meeting.ziel else ""
    system = BASIS_ANWEISUNG.format(name=EINST.assistent_name, pflicht=pflichtinhalte(meeting, True, vorstellung),
                                    titel=meeting.titel or "ohne Titel", ziel=ziel, agenda=_agenda(meeting))
    t0 = time.monotonic()
    try:
        antwort = await asyncio.wait_for(client.chat.completions.create(
            model=EINST.basis_begruessung_modell, temperature=0.9,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": "Schreib die Begrüßung."}]), EINST.basis_begruessung_frist)
    except Exception as e:  # noqa: BLE001 – auch TimeoutError: dann die feste Fassung
        log.info("Begrüßung Basis: feste Fassung (%s)", type(e).__name__)
        return None
    nutzung = getattr(antwort, "usage", None)
    if nutzung:
        from .pipeline import nutzung_loggen
        nutzung_loggen({"art": "assistent", "zweck": "begruessung", "modell": EINST.basis_begruessung_modell,
                        "tokens_rein": nutzung.prompt_tokens, "tokens_raus": nutzung.completion_tokens,
                        "sekunden": round(time.monotonic() - t0, 1)})
    text = re.sub(r"\s+", " ", (antwort.choices[0].message.content or "").replace("*", "")).strip()
    if not basis_text_vollstaendig(text, vorstellung):
        log.info("Begrüßung Basis: Pflichtpunkt fehlt – feste Fassung")
        return None
    return text


def in_stuecke(text: str, hoechstens: int = 400) -> list[str]:
    """Für die Sprachausgabe: ganze Sätze, zu Stücken bis etwa `hoechstens` Zeichen gebündelt."""
    from .assistent import saetze_teilen

    saetze, rest = saetze_teilen(text + " ")
    saetze += [rest.strip()] if rest.strip() else []
    stuecke: list[str] = []
    for s in saetze:
        if stuecke and len(stuecke[-1]) + len(s) + 1 <= hoechstens:
            stuecke[-1] += " " + s
        else:
            stuecke.append(s)
    return stuecke

