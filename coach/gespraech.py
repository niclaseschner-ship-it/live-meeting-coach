"""Sprachgespräch mit Nestor über das Realtime-Sprachmodell (die Technik hinter dem ChatGPT-Sprachmodus), Premium.

Wird Nestor angesprochen, öffnet sich eine Sitzung; danach hört das Modell selbst mit – das Mikrofon geht direkt
hinein. Wann es antwortet, entscheidet der Coach (create_response aus): jede Anfrage an Nestor – Name, Sprechtaste,
Knopf mit Freitext, getippt oder ein Gesprächszug im Hörfenster (coach/gespraechszug.py) – kommt als EIN Aufruf mit
dem aktuellen Stand des Meetings. Anweisung, Werkzeuge und ihre Ausführung teilt das Gespräch mit Basis
(coach/kern.py); ob ein Zug ohne Namen überhaupt an Nestor ging, entscheidet das Modell (Werkzeug `nicht_an_mich`).
Schranken im Code: höchstens eine Werkzeugrunde und genau eine Abschlussantwort je Anfrage – nach einem Werkzeug sagt
das Modell, was es getan hat –, Frist bis zum ersten Ton (danach kommt das Ergebnis still als Karte).
Reinreden macht Nestor still – aber nur die Stimme: die Antwort wird fertig erzeugt und kommt als Karte in den
Verlauf. Bild und Recherche sind lange Aufträge im Hintergrund; das Ergebnis kommt still.
Ist eine Weile Ruhe oder sagt die Runde „danke, das war's“, schließt die Sitzung. Kosten nur, solange sie offen ist.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from . import anbieter
from . import gespraechszug as GZ
from . import kern
from .config import EINST
from .werkzeuge import WERKZEUGE  # noqa: F401 – Katalog, auch für Drehbuch-Prüfungen

log = logging.getLogger("coach.gespraech")

RATE = 24000

class GespraechGesperrt(RuntimeError):
    """Ticket #64: Meeting-Kostendeckel erreicht – `starten` verweigert eine neue Realtime-Sitzung. Die
    Aufrufer (coach/assistent.py: `_gespraech_starten`, `_begruessen_frei`) fangen das wie jeden anderen
    Verbindungsfehler ab und weichen auf den Text-Weg aus."""


class Gespraech:
    def __init__(self, assistent) -> None:
        self.a = assistent
        self.coach = assistent.coach
        self.wahl = assistent.coach.wahl  # Anbieterwahl des Meetings (coach/anbieter.py) – fest für diese Sitzung
        self.offen = False
        self._ws = None
        self._empfang: asyncio.Task | None = None
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden + 10
        self._antwort_text = ""
        self._ton_bytes = 0
        self._ton_beginn: float | None = None
        self._frage = ""
        self.beenden_nach_antwort = False
        self._antwort_laeuft = False
        self._antwort_ende = 0.0  # Meetingzeit des letzten Antwortendes (für Rückfragen ohne Namen)
        self._bogen = None  # der Bogen, dessen Antwort gerade entsteht (coach/assistent.py)
        self._fertig = asyncio.Event()  # Antwort des aktuellen Bogens fertig (response.done)
        self._stumm = False  # Nachtrag B: Stimme unterbrochen, die Antwort wird still fertig und kommt als Karte
        # Wiedergabe der letzten Antwort im Dashboard (Item, Beginn in Meetingzeit, Bytes): Hineinreden kürzt sie per
        # conversation.item.truncate auch dann, wenn sie schon fertig erzeugt ist (#20)
        self._wiedergabe: dict | None = None
        self._anfrage_neu()

    def _anfrage_neu(self) -> None:
        """Zustand einer Anfrage: Schranken (eine Werkzeugrunde, eine Abschlussantwort) und ob sie verworfen ist."""
        self._ton_da = asyncio.Event()  # erster Ton dieser Anfrage (Frist)
        self._abschluss = False          # ein Werkzeug will, dass das Modell danach ein bis zwei Sätze sagt
        self._abschluss_laeuft = False   # die Abschlussantwort ist angestoßen – keine weitere Werkzeugrunde
        self._verworfen = False          # nicht_an_mich: schweigen, nichts ablegen
        self._aufgaben: list[asyncio.Future] = []  # Werkzeuge, deren Ergebnis die Abschlussantwort braucht

    def _gesperrt_pruefen(self) -> None:
        """Ticket #64: Meeting-Kostendeckel erreicht – keine neue Realtime-Sitzung mehr (weder Gespräch noch
        Begrüßung, die `starten` beide hier aufrufen). Eine schon offene Sitzung schließt `_kosten_pruefen`
        (coach/pipeline.py) selbst, sobald der Deckel erreicht ist."""
        if self.coach.ki_gesperrt:
            raise GespraechGesperrt("Kostendeckel erreicht – kein neues Gespräch.")

    async def starten(self, frage: str | None, bogen=None) -> None:
        self._gesperrt_pruefen()
        # Realtime-Gespräch ist OpenAI – in Basis wirft die Fabrik AnbieterFehler (Ticket #13/#60)
        url, kopf = anbieter.realtime_ws(self.wahl)
        self._ws = await anbieter.ws_verbinden(self.wahl, url, kopf, self.coach.anbieter_verstoss)
        await self._senden({"type": "session.update", "session": self.sitzung()})
        self.offen = True
        from .pipeline import _zeit_loggen  # Nestors Seite (#83): das Hörfenster öffnet sich

        _zeit_loggen({"ausloeser": "hoerfenster", "ereignis": "geoeffnet",
                      "grund": bogen.quelle if bogen is not None else "begruessung"})
        self._empfang = asyncio.create_task(self._empfangen())
        await self._fragen(frage or "", bogen, stand_senden=False)  # der Stand steckt schon in der Sitzung

    async def frage(self, bogen) -> None:
        """Ein neuer Bogen in der offenen Sitzung: Frage als Text, Antwort anstoßen, warten bis sie fertig ist."""
        self.a.text_neu(bogen.frage)
        await self._fragen(bogen.frage, bogen)
        await self.warten(bogen)

    def anweisung(self) -> str:
        """Bedienlogik und der aktuelle Stand des Meetings – bei jeder Anfrage neu (dieselbe wie in Basis)."""
        return kern.anweisung(self.a)

    async def _fragen(self, frage: str, bogen, stand_senden: bool = True) -> None:
        self._frage = frage
        self._bogen = bogen
        self._stumm = bool(bogen is not None and bogen.abgeloest)
        self._fertig = asyncio.Event()
        self._anfrage_neu()
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden + 30
        if stand_senden and not getattr(self, "phase", False):
            await self._senden({"type": "session.update", "session": {"type": "realtime",
                                                                      "instructions": self.anweisung()}})
        text = GZ.fuer_modell(frage, getattr(bogen, "gerichtet", True)) if frage else "(Frage folgt)"
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
        await self._antworten_lassen()

    def _gerichtet(self) -> bool:
        return getattr(self._bogen, "gerichtet", True)

    async def warten(self, bogen, frist: float = 45.0) -> None:
        """Bis die Antwort dieses Bogens fertig erzeugt und gespielt ist (höchstens `frist` s). Kommt bis zur
        Anfrage-Frist kein Ton, wird die Anfrage still: das Ergebnis kommt als Karte, Nestor spricht nicht mehr
        dazwischen."""
        t0 = time.monotonic()
        ton, fertig = asyncio.ensure_future(self._ton_da.wait()), asyncio.ensure_future(self._fertig.wait())
        _, offen = await asyncio.wait([ton, fertig], timeout=EINST.anfrage_frist_sekunden,
                                      return_when=asyncio.FIRST_COMPLETED)
        for f in offen:
            f.cancel()
        if not self._ton_da.is_set() and not self._fertig.is_set() and not bogen.abgeloest:
            log.info("Gespräch: kein Ton nach %.0f s – Ergebnis still als Karte", EINST.anfrage_frist_sekunden)
            bogen.abgeloest = True
            bogen.frist_ueberschritten = True
            self._stumm = True
            self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "anfrage_frist",
                                         "frage": bogen.frage})
        try:
            await asyncio.wait_for(self._fertig.wait(), max(0.0, frist - (time.monotonic() - t0)))
        except asyncio.TimeoutError:
            log.warning("Gespräch: keine fertige Antwort nach %.0f s", frist)
        # bis der Ton im Dashboard zu Ende ist – erst dann beginnt das Nachfrage-Fenster. Höchstens so lange, wie der
        # Ton noch dauert (plus 1 s): steht die Meetinguhr (kein Mikrofon-Ton mehr), hinge der Bogen sonst
        rest = (self.a.sprechzeiten[-1][1] - 0.8 - self.coach.meeting.jetzt()) if self.a.sprechzeiten else 0.0
        bis = time.monotonic() + max(0.0, rest) + 1.0
        while (not bogen.abgeloest and self.a.sprechzeiten and time.monotonic() < bis
               and self.a.sprechzeiten[-1][1] - 0.8 > self.coach.meeting.jetzt()):
            await asyncio.sleep(0.2)

    def stumm_schalten(self) -> None:
        """Nachtrag B: der Bogen wurde unterbrochen – kein Ton mehr ins Dashboard, die Antwort wird aber fertig
        erzeugt und kommt still als Karte. Was schon gespielt ist, erfährt das Modell beim Ende (truncate)."""
        if self._antwort_laeuft:
            self._stumm = True
        asyncio.ensure_future(self._hineinreden(erzwingen=True))

    def sitzung(self) -> dict:
        """Einstellungen des Gesprächs: der Coach entscheidet, wann Nestor antwortet (create_response aus)."""
        return {
            "type": "realtime",
            "instructions": self.anweisung(),
            "output_modalities": ["audio"],
            "audio": {
                # Nachtrag B: Reinreden stoppt nur die Stimme (coach-seitig), nicht die Antwort – sie kommt als Karte
                "input": {"format": {"type": "audio/pcm", "rate": RATE},
                          "turn_detection": {"type": "semantic_vad", "create_response": False,
                                             "interrupt_response": False}},
                "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": self.wahl.stimme},
            },
            "tools": WERKZEUGE, "tool_choice": "auto",
        }

    async def _antworten_lassen(self) -> None:
        self._antwort_laeuft = True
        await self._senden({"type": "response.create"})
        self.a.zustand = "denkt"
        await self.coach.melden()

    async def audio(self, pcm24k: bytes) -> None:
        """Mikrofon direkt ins Gespräch (Rückfragen, Ins-Wort-Fallen)."""
        if self.offen:
            await self._senden({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm24k).decode()})
            if time.monotonic() > self._ende_bis and not self.a.zustand == "spricht":
                await self.schliessen("zeitueberschreitung")

    async def schliessen(self, grund: str = "beendet") -> None:
        self._fertig.set()  # ein wartender Bogen hängt nicht
        if not self.offen:
            return
        self.offen = False
        from .pipeline import _zeit_loggen  # Nestors Seite (#83): das Hörfenster schließt sich, mit Grund

        _zeit_loggen({"ausloeser": "hoerfenster", "ereignis": "geschlossen", "grund": grund})
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self.a.zustand != "pausiert":
            self.a.zustand = "bereit"
        self.a.gespraech = None
        await self.coach.melden()

    async def _senden(self, ereignis: dict) -> None:
        try:
            await self._ws.send(json.dumps(ereignis))
        except Exception as e:  # noqa: BLE001
            log.warning("Gespräch: Senden fehlgeschlagen (%s)", type(e).__name__)
            self.offen = False

    # --- Ereignisse vom Modell -----------------------------------------------
    async def _empfangen(self) -> None:
        c = self.coach
        try:
            async for roh in self._ws:
                e = json.loads(roh)
                typ = e.get("type", "")
                if await self._ereignis(typ, e):
                    continue  # von einer Unterklasse ganz übernommen (Begrüßung, coach/begruessung.py)
                if typ in ("response.output_audio.delta", "response.audio.delta"):
                    await self._ton(e["delta"], e.get("item_id"))
                elif typ in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
                    self._antwort_text += e.get("delta", "")
                    if not self._stumm:  # unterbrochen: kein Text mehr ohne Ton
                        await self.a.text_senden(e.get("delta", ""), delta=True)  # Text läuft mit (Ticket #21)
                elif typ == "input_audio_buffer.speech_started":
                    # jemand spricht: Nestor sofort still – auch wenn die Antwort schon fertig erzeugt ist und nur
                    # noch im Dashboard läuft (#20); das Modell erfährt, wie weit sie zu hören war
                    if await self._hineinreden():
                        self.a.zustand = "angesprochen"
                    self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden + 30
                    await c.melden()
                elif typ == "input_audio_buffer.speech_stopped":
                    self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden
                    if self.a.zustand == "angesprochen" and not self._antwort_laeuft:
                        self.a.zustand = "gespraech"
                        await c.melden()
                elif typ == "response.function_call_arguments.done":
                    await self._werkzeug(e.get("name", ""), e.get("arguments") or "{}", e.get("call_id"))
                elif typ == "response.done":
                    await self._antwort_fertig(e.get("response", {}))
                elif typ == "error":
                    log.warning("Gespräch: Fehler vom Modell: %s", str(e.get("error", {}).get("message", ""))[:200])
                    if self._bogen is not None:  # Nestors Seite (#83)
                        self._bogen.fehler = str(e.get("error", {}).get("type") or "modell_fehler")
        except Exception as ex:  # noqa: BLE001
            if self.offen:
                log.warning("Gespräch abgebrochen: %s", type(ex).__name__)
            if self._bogen is not None:
                self._bogen.fehler = self._bogen.fehler or type(ex).__name__
        finally:
            if self.offen:
                await self.schliessen("verbindung_beendet")

    async def _ereignis(self, typ: str, e: dict) -> bool:
        """Haken für Unterklassen: True heißt, das Ereignis ist erledigt und der Standardweg entfällt."""
        return False

    async def _ton(self, b64: str, item: str | None = None) -> None:
        c, m = self.coach, self.coach.meeting
        self._ton_da.set()
        if self._stumm:  # unterbrochen oder verworfen: nichts mehr hören lassen, nur mitzählen (für truncate)
            if self._wiedergabe is not None and item == self._wiedergabe.get("item"):
                self._wiedergabe["bytes"] += len(b64) * 3 // 4
            return
        if self._bogen is not None:
            self._bogen.merken("satz")
        if self._ton_beginn is None:
            self._ton_beginn = max(m.jetzt() + 0.4, self.a.sprechzeiten[-1][1] if self.a.sprechzeiten else 0)
            self.a.sprechzeiten.append((self._ton_beginn, self._ton_beginn + 60))
            self.a.zustand = "spricht"
            await c.melden()
        if item and (self._wiedergabe is None or self._wiedergabe["item"] != item):
            self._wiedergabe = {"item": item, "beginn": self._ton_beginn + self._ton_bytes / 2 / RATE, "bytes": 0}
        if item:
            self._wiedergabe["bytes"] += len(b64) * 3 // 4
        self._ton_bytes += len(b64) * 3 // 4
        self.a.sprechzeiten[-1] = (self._ton_beginn, self._ton_beginn + self._ton_bytes / 2 / RATE + 0.8)
        await c.direkt_senden({"typ": "stimme", "pcm": b64})

    def _ton_ende(self, abgebrochen: bool = True) -> None:
        """Antwort-Ton abschließen. Nur beim Abbruch (Ins-Wort-Fallen) endet die Sprechzeit jetzt. Ist die Antwort
        fertig erzeugt (response.done), läuft sie im Dashboard noch: Das Modell liefert den Ton schneller als
        Echtzeit, response.done kam in den Cloud-Läufen 08.10. 6–9 s vor dem Ende der Wiedergabe. Wurde die
        Sprechzeit dort abgeschnitten, begann das Rückfrage-Fenster zu früh – „Und wer kümmert sich darum?“ lag
        10–11 s nach Nestors letztem Wort, aber 16–20 s nach response.done (Ticket #17, Grenzfall 4)."""
        if abgebrochen and self._ton_beginn is not None:
            jetzt = self.coach.meeting.jetzt()
            a, b = self.a.sprechzeiten[-1]
            self.a.sprechzeiten[-1] = (a, min(b, jetzt + 0.5))
        self._ton_beginn, self._ton_bytes = None, 0

    async def _hineinreden(self, erzwingen: bool = False) -> bool:
        """Jemand redet hinein (#20, Ticket #27 Nachtrag B): läuft Nestors Ton noch im Dashboard, sofort still. Die
        Antwort wird weiter erzeugt (interrupt_response aus) und kommt als Karte; dem Modell per
        conversation.item.truncate sagen, wie weit sie zu hören war (bei einer laufenden Antwort erst an ihrem Ende).
        True, wenn Nestor dabei verstummt ist."""
        c, a = self.coach, self.a
        jetzt = c.meeting.jetzt()
        spielt = bool(a.sprechzeiten) and jetzt < a.sprechzeiten[-1][1] - 0.6  # ohne den Nachlauf für den Hall
        if not erzwingen and a.zustand != "spricht" and not spielt and not self._antwort_laeuft:
            return False
        if not erzwingen and not spielt and self._antwort_laeuft and self._ton_beginn is None:
            return False  # die Antwort denkt noch, es ist nichts zu hören – kein Grund zu verstummen
        await c.direkt_senden({"typ": "stimme_stopp"})
        if self._antwort_laeuft:
            self._stumm = True
        w = self._wiedergabe
        if w and w.get("item") and "gekuerzt" not in w:
            dauer = w["bytes"] / 2 / RATE
            gespielt = min(max(0.0, jetzt - w["beginn"]), dauer)
            if gespielt < dauer or self._antwort_laeuft:
                w["gekuerzt"] = gespielt
                if not self._antwort_laeuft:  # fertig erzeugt: jetzt kürzen, sonst am Ende der Antwort
                    await self._kuerzen(w)
                log.info("Gespräch: unterbrochen nach %.1f s", gespielt)
        if a.sprechzeiten:
            s_, b = a.sprechzeiten[-1]
            a.sprechzeiten[-1] = (s_, min(b, jetzt + 0.5))
        self._ton_beginn, self._ton_bytes = None, 0
        return True

    async def _kuerzen(self, w: dict) -> None:
        await self._senden({"type": "conversation.item.truncate", "item_id": w["item"], "content_index": 0,
                            "audio_end_ms": int(w["gekuerzt"] * 1000)})

    async def _werkzeug(self, name: str, argumente: str, call_id: str | None) -> None:
        """Ein Werkzeugaufruf des Modells: im Kern ausführen (coach/kern.py), Ergebnis zurück. Keine eigene Antwort
        anstoßen – die eine Abschlussantwort stößt `_antwort_fertig` an, sobald alle Ergebnisse da sind."""
        try:
            arg = json.loads(argumente)
        except json.JSONDecodeError:
            arg = {}
        if self._abschluss_laeuft:  # Schranke: nur eine Werkzeugrunde je Anfrage
            if self._bogen is not None:
                self._bogen.werkzeuge.append({"name": name, "argumente": arg, "fehler": "zweite_runde"})
            await self._ausgabe(call_id, {"ok": False, "fehler": "Nur eine Werkzeugrunde je Anfrage – sag kurz, was "
                                                                  "noch zu tun wäre."})
            return
        if name == "nicht_an_mich":
            ausgabe = await kern.ausfuehren(self.a, self._bogen, name, arg, gerichtet=self._gerichtet())
            if ausgabe.get("schweigen"):  # schweigen: begonnenen Ton verwerfen, nichts ablegen
                self._verworfen = True
                if self._ton_beginn is not None:
                    await self.coach.direkt_senden({"typ": "stimme_stopp"})
                    self._ton_ende(abgebrochen=True)
                self._stumm = True
            else:
                self._abschluss = True  # direkt angesprochen: das Modell antwortet doch
            await self._ausgabe(call_id, ausgabe)
            return
        self._floskel_falls_still()
        self._abschluss = True
        if name in ("gespraech_beenden", "zuhoeren_pausieren"):
            self.beenden_nach_antwort = True
        self._aufgaben.append(asyncio.ensure_future(self._werkzeug_lauf(name, arg, call_id)))

    async def _werkzeug_lauf(self, name: str, arg: dict, call_id: str | None) -> None:
        ausgabe = await kern.ausfuehren(self.a, self._bogen, name, arg, gerichtet=self._gerichtet())
        await self._ausgabe(call_id, ausgabe)

    def _system_sagt(self, satz: str) -> None:
        """Das System bestätigt selbst (Floskel) – im laufenden Bogen, damit er erst danach endet."""
        aufgabe = asyncio.ensure_future(self.a.floskel_sagen(satz, self._bogen))
        if self._bogen is not None:
            self._bogen.zusatz.append(aufgabe)

    def _floskel_falls_still(self) -> None:
        """Sofortbestätigung, ausgelöst vom Werkzeugaufruf: nur, wenn für diese Anfrage noch keine kam."""
        b = self._bogen
        if EINST.bestaetigung and b is not None and "floskel" not in b.zeiten and not self._stumm:
            self._system_sagt(self.a.floskeln.kurz())

    async def _abschluss_anstossen(self) -> None:
        if self._aufgaben:
            await asyncio.wait(self._aufgaben, timeout=kern.AUSFUEHREN_FRIST + 1.0)
        if self.offen:
            await self._antworten_lassen()
        else:
            self._fertig.set()

    async def _ausgabe(self, call_id: str | None, ausgabe: dict) -> None:
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": json.dumps(ausgabe, ensure_ascii=False)}})

    async def _antwort_fertig(self, antwort: dict) -> None:
        c = self.coach
        text = self._antwort_text.strip()
        self._antwort_text = ""
        if self._bogen is not None and text and not self._verworfen:
            # vor _ton_ende eintragen: das gibt den Bogen frei, und der schreibt seinen Eintrag in nestor.jsonl
            # womöglich schon beim nächsten await
            self._bogen.gesagt = text
        stumm = self._stumm
        self._ton_ende(abgebrochen=False)
        self._antwort_laeuft = False
        w = self._wiedergabe
        if stumm and w and w.get("item") and "gekuerzt" in w:
            await self._kuerzen(w)  # das Modell soll wissen, wie weit die Antwort zu hören war
        self._stumm = False
        if self._verworfen:  # nicht_an_mich: nichts ablegen, nichts merken
            if text:
                log.info("Gespräch: Antwort trotz nicht_an_mich verworfen")
            c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "nicht_an_mich", "frage": self._frage})
            if self._bogen is not None and text:
                self._bogen.gesagt = f"(verworfen) {text}"  # nestor.jsonl: was das Modell trotzdem sagen wollte
            text = ""
        if text and self.a.sprechzeiten and not stumm:
            # Die Sprechzeit reicht jetzt bis zum Ende der Wiedergabe – mit dem Text entscheidet der Echo-Filter nach
            # dem Inhalt, sonst ginge wer Nestor ins Wort fällt als „eigene Sprache“ verloren (eigene_sprache)
            self.a.sprechtexte.append((*self.a.sprechzeiten[-1], text))
        nutzung = antwort.get("usage") or {}
        if nutzung:
            from .pipeline import nutzung_loggen
            nutzung_loggen({"art": "gespraech", "modell": self.wahl.realtime_modell,
                            "tokens_rein": nutzung.get("input_tokens"), "tokens_raus": nutzung.get("output_tokens"),
                            "details_rein": nutzung.get("input_token_details"),
                            "details_raus": nutzung.get("output_token_details")})
        if text:
            self.a.letzte = {"frage": self._frage, "antwort": text, "zeit": c.meeting.jetzt(),
                             "aktion": getattr(self.a, "letzte_aktion", None)}
            if self._bogen is not None:  # Nestors Seite (#83): fließt am Bogenende in logs/nestor.jsonl
                self._bogen.gesagt, self._bogen.aktion = text, self.a.letzte["aktion"]
            if not (self._bogen is not None and self._bogen.karte):  # eine Werkzeug-Karte steht schon
                c.antwort_karte(self._frage, text, self.a.letzte["aktion"], [], still=stumm)
            self.a.verlauf.append((self._frage, text))
            c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "assistent", "modus": "gespraech",
                                "frage": self._frage, "antwort": text, "aktion": self.a.letzte["aktion"],
                                "unterbrochen": stumm})
            self.a.letzte_aktion = None
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden
        if self._abschluss and not self._abschluss_laeuft and not self._verworfen and not text and self.offen:
            # Schranke: genau eine Abschlussantwort nach der Werkzeugrunde – sobald deren Ergebnisse da sind
            self._abschluss_laeuft = True
            asyncio.ensure_future(self._abschluss_anstossen())
            await c.melden()
            return
        if self.a.zustand not in ("pausiert", "taste") and self.a.bogen is None:
            self.a.zustand = "gespraech"
        self._fertig.set()
        await c.melden()
        if self.beenden_nach_antwort:
            await asyncio.sleep(1.0)
            await self.schliessen("modell_beendet")
