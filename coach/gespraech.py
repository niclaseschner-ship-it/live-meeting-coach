"""Sprachgespräch mit Nestor über das Realtime-Sprachmodell (die Technik hinter dem ChatGPT-Sprachmodus), Premium.

Wird Nestor angesprochen, öffnet sich eine Sitzung; danach hört das Modell selbst mit – das Mikrofon geht direkt
hinein. Wann es antwortet, entscheidet der Coach (create_response aus): jede Anfrage an Nestor – Name, Sprechtaste,
Knopf mit Freitext, getippt oder ein Gesprächszug im Hörfenster (coach/gespraechszug.py) – kommt als EIN Aufruf mit
dem aktuellen Stand des Meetings. Vorsortiert wird nichts: welches Werkzeug passt und ob ein Zug ohne Namen
überhaupt an Nestor ging (Werkzeug `nicht_an_mich`), entscheidet das Modell (coach/werkzeuge.py).
Schranken im Code: höchstens eine Werkzeugrunde und eine Abschlussantwort je Anfrage, geprüfte Werkzeug-Argumente,
Frist bis zum ersten Ton (danach kommt das Ergebnis still als Karte).
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
from . import werkzeuge as W
from .config import EINST
from .werkzeuge import WERKZEUGE  # noqa: F401 – Katalog, auch für Drehbuch-Prüfungen

log = logging.getLogger("coach.gespraech")

RATE = 24000

ANWEISUNG = """\
Du bist {name}, Moderationsassistent und Teil dieser Runde in einem Präsenzmeeting. Du sprichst mit der
Gruppe wie ein erfahrener, freundlicher Kollege, der den Überblick behält: natürlich, locker, auf Deutsch, per „ihr“,
nie „Sie“.

So arbeitest du:
- Jede Nachricht der Runde an dich ist eine Anfrage. Du antwortest in einem Bogen: ein, höchstens zwei gesprochene
  Sätze, das Wichtigste zuerst. Einzelheiten gehören auf eine Karte (zusammenfassen, karte, karte_zeigen) – lies
  nie vor, was dort steht.
- Wähle das Werkzeug nach dem, was gemeint ist, nicht nach einzelnen Wörtern. „Fass den Punkt zusammen“ meint den
  aktuellen Agendapunkt, „seit eben“ oder „seit der Pause“ einen Zeitraum, „das Ganze“ das Meeting. Eine Frage,
  in der „nächster Punkt“ vorkommt, ist kein Wunsch, die Agenda zu wechseln. Wer zwei Dinge will (zusammenfassen
  UND den nächsten Schritt nennen), bekommt beides.
- Höchstens eine Werkzeugrunde je Anfrage: rufe alle nötigen Werkzeuge auf einmal auf.
- Erfinde nichts. „Beschlossen“ oder „festgehalten“ sagst du nur, wenn es unten als Entscheidung steht oder
  ausdrücklich so gesagt wurde; ein Vorschlag bleibt ein Vorschlag. Nummern von Ergebnissen und Agendapunkten nur
  aus dem Stand unten.
- Ist unklar, was gemeint ist, frag in einem kurzen Satz nach, statt zu raten.
- Nachrichten, die mit „(Ohne deinen Namen …)“ beginnen, kamen ohne Namen direkt nach deiner Antwort; Zeilen mit
  „Name: …“ stammen von verschiedenen Personen. Ist so eine Nachricht nicht an dich gerichtet (die Runde redet
  untereinander, jemand spricht eine Person an, ein Kommentar zur Sache), ruf nur nicht_an_mich auf und sag nichts.
  Eine Anschlussfrage an deine Antwort oder eine Bitte an dich beantwortest du.
- Gespräche der Gruppe, die du nur mithörst, kommentierst du nie von dir aus.
- Personen heißen im Transkript „Person N“ – sprich stattdessen von „jemandem“. Agendapunkte nennst du mit Nummer und
  Titel aus der Agenda unten, sprechbar: „Punkt zwei, Budget“.

STAND DES MEETINGS (bei jeder Anfrage neu):
{lage}
"""
# Ohne Sofort-Bestätigung (LMC_BESTAETIGUNG=0) sagt das Modell selbst, dass es nachschaut
OHNE_BESTAETIGUNG = ("\nBei " + ", ".join(W.SYSTEM_SPRICHT) + " spricht das System selbst – sag nichts dazu.\n")
# Bestätigung und Wartezeit spricht das System aus vorab erzeugten Floskeln (coach/bestaetigung.py)
MIT_BESTAETIGUNG = ("""
Oft hat das System schon kurz bestätigt („Bin dran“), bevor du drankommst. Fang deshalb nicht mit „Okay“,
„Moment“, „Klar“ oder „Gern“ an, sondern direkt mit dem Inhalt. Bei """ + ", ".join(W.SYSTEM_SPRICHT)
                    + """ spricht das System selbst – ruf das Werkzeug auf, ohne etwas dazu zu sagen.
""")


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
        """Bedienlogik und der aktuelle Stand des Meetings – bei jeder Anfrage neu."""
        return (ANWEISUNG.format(name=EINST.assistent_name, lage=self.a.lage())
                + (MIT_BESTAETIGUNG if EINST.bestaetigung else OHNE_BESTAETIGUNG))

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
        """Ein Werkzeugaufruf des Modells: prüfen, ausführen, Ergebnis zurück. Keine eigene Antwort anstoßen – ob eine
        Abschlussantwort folgt, entscheidet `_antwort_fertig` (höchstens eine je Anfrage)."""
        from . import bestaetigung as B

        c, m = self.coach, self.coach.meeting
        try:
            arg = json.loads(argumente)
        except json.JSONDecodeError:
            arg = {}
        aufruf = {"name": name, "argumente": arg}  # Nestors Seite: jeder Aufruf mit Argumenten in nestor.jsonl
        if self._bogen is not None:
            self._bogen.werkzeuge.append(aufruf)
        if self._abschluss_laeuft:  # Schranke: nur eine Werkzeugrunde je Anfrage
            aufruf["fehler"] = "zweite_runde"
            await self._ausgabe(call_id, {"ok": False, "fehler": "Nur eine Werkzeugrunde je Anfrage – sag kurz, was "
                                                                  "noch zu tun wäre."})
            return
        arg, fehler = W.pruefen(name, arg, nummern={a.id for a in c.artefakte.liste}, agenda=len(m.agenda),
                                aktiver_punkt=m.aktiver_punkt, jetzt=m.jetzt(), gerichtet=self._gerichtet())
        if fehler:
            aufruf["fehler"] = fehler
        if fehler and name not in ("artefakt_eintragen", "ergebnis_entfernen", "ergebnis_aendern"):
            c.protokoll.append({"zeit": m.jetzt(), "art": "werkzeug_abgelehnt", "werkzeug": name, "fehler": fehler})
            await self._ausgabe(call_id, {"ok": False, "fehler": fehler})
            self._abschluss = True  # das Modell sagt kurz, was nicht geht
            return
        if name == "nicht_an_mich":  # schweigen: begonnenen Ton verwerfen, nichts ablegen
            self._verworfen = True
            if self._bogen is not None:
                self._bogen.verworfen = True
            if self._ton_beginn is not None:
                await c.direkt_senden({"typ": "stimme_stopp"})
                self._ton_ende(abgebrochen=True)
            self._stumm = True
            await self._ausgabe(call_id, {"ok": True})
            return
        if name == "artefakt_eintragen":  # Lücke korrigieren: „Notiert“, Karte wird grün
            a = None if fehler else c.artefakte.eintragen(arg)[0]
            if a is not None:
                c.protokoll.append({"zeit": m.jetzt(), "art": "artefakt_eingetragen", "id": a.id, "durch": "stimme"})
                await c.melden()
            satz = self.a.floskeln.variante(B.NOTIERT) if a is not None else "Das konnte ich keinem Eintrag zuordnen."
            self._system_sagt(satz)
            await self._ausgabe(call_id, {"ok": a is not None, "eingetragen": a.kurz() if a else None, "fehler": fehler,
                                          "hinweis": "das System hat „Notiert“ gesagt – sag nichts"})
            return
        if name in ("ergebnis_entfernen", "ergebnis_aendern"):  # sofort ausgeführt, Karte bietet Rückgängig
            nummer = arg.get("nummer")
            if fehler:
                a = None
            elif name == "ergebnis_entfernen":
                a = c.artefakte.entfernen(nummer)
            else:
                a = c.artefakte.aendern(nummer, str(arg.get("text") or ""))
            if a is not None:
                c.protokoll.append({"zeit": m.jetzt(), "art": "artefakt_entfernt" if name == "ergebnis_entfernen"
                                    else "artefakt_geaendert", "id": nummer, "durch": "stimme"})
                await c.melden()
            floskeln = B.ENTFERNT if name == "ergebnis_entfernen" else B.GEAENDERT
            self._system_sagt(self.a.floskeln.variante(floskeln) if a is not None
                              else "Das finde ich in der Liste nicht.")
            await self._ausgabe(call_id, {"ok": a is not None, "fehler": fehler,
                                          "hinweis": "das System hat dazu schon gesprochen – sag nichts"})
            return
        if name == "auftrag_abbrechen":  # das Modell nennt die Art des laufenden Auftrags
            a = self.a.auftraege.ziel_art(arg.get("art"))
            if a is not None:
                self.a.auftrag_abbrechen(a.id)
                await c.melden()
            self._system_sagt(B.ABGEBROCHEN if a is not None else B.NICHTS_OFFEN)
            await self._ausgabe(call_id, {"ok": a is not None, "hinweis": "das System hat es bestätigt – sag nichts"})
            return
        if name in ("recherchieren", "bild_zeichnen"):  # lange Aufträge: kein Bogen, Ergebnis kommt still
            art = "recherche" if name == "recherchieren" else "bild"
            fokus = str(arg.get("fokus") or "")
            fokus = "" if fokus.lower() in ("gesamt", "alles") else fokus
            titel = str(arg.get("frage") or self._frage) if art == "recherche" else self._frage
            aufgabe = asyncio.ensure_future(self.a.lang_annehmen(art, titel, fokus, self._bogen))
            if self._bogen is not None:
                self._bogen.zusatz.append(aufgabe)
            await self._ausgabe(call_id, {"ok": True, "hinweis": "läuft im Hintergrund, das Ergebnis erscheint still "
                                                                 "im Verlauf – sag nichts dazu"})
            return
        if name in ("folie_erstellen", "karte_zeigen"):  # Karten-Bogen: das System spricht selbst
            art = "folie" if name == "folie_erstellen" else str(arg.get("art") or "")
            if art in ("folie", "fehlt", "stand", "festgehalten", "ueberblick"):
                self.a.zusatz_bogen(art)
            await self._ausgabe(call_id, {"ok": True, "hinweis": "die Karte erscheint, das System sagt dazu, was "
                                                                 "auffällt – sag nichts"})
            return
        if name == "karte_neu_aufbereiten":  # letzte Karte per LLM-Aufruf neu aufbereiten
            from .neu_aufbereiten import WIE

            wie = str(arg.get("wie") or "")
            if wie in WIE:
                self.a.zusatz_bogen("neu_aufbereiten", wie)
            await self._ausgabe(call_id, {"ok": wie in WIE, "hinweis": "die neue Karte erscheint, das System sagt "
                                                                      "dazu – sag nichts"})
            return
        if name == "zusammenfassen":  # Karte aus den Ergebnissen des Bereichs, danach ein bis zwei Sätze
            self._floskel_falls_still()
            self._abschluss = True
            self._aufgaben.append(asyncio.ensure_future(self._zusammenfassen(arg, call_id)))
            return
        if name == "karte":  # freie Karte, danach ein bis zwei Sätze
            self._floskel_falls_still()
            self._karte({"art": "antwort", "titel": arg["titel"], "punkte": arg["punkte"]})
            self.a.letzte_aktion = {"typ": "karte", "art": "frei"}
            self._abschluss = True
            await c.melden()
            await self._ausgabe(call_id, {"ok": True, "hinweis": "die Karte steht – sag ein bis zwei Sätze, was "
                                                                 "auffällt, ohne sie vorzulesen"})
            return
        aktion = {"agendapunkt_wechseln": {"typ": "weiter", "ziel": str(arg.get("nummer", ""))},
                  "zuhoeren_pausieren": {"typ": "pause"}}.get(name)
        if aktion:
            await c.assistent_aktion(aktion)
            self.a.letzte_aktion = aktion
            self._abschluss = True  # kurz sagen, was Nestor tut
        if name in ("gespraech_beenden", "zuhoeren_pausieren"):
            self.beenden_nach_antwort = True
        await self._ausgabe(call_id, {"ok": True})

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

    def _karte(self, karte: dict) -> dict:
        b = self._bogen
        frage = (b.frage if b is not None else self._frage) or ""
        return self.coach._karte_ablegen({**karte, "frage": frage[:200], "still": self._stumm,
                                          **({"bogen": b.id} if b is not None else {})})

    async def _zusammenfassen(self, arg: dict, call_id: str | None) -> None:
        from . import bogen as BG

        try:
            karte, _, auszug = await BG.bereich_karte(self.coach, arg["bereich"], arg.get("punkt"), arg.get("seit"))
        except Exception as e:  # noqa: BLE001 – ehrlich sagen statt zu hängen
            log.warning("Zusammenfassen fehlgeschlagen: %s", type(e).__name__)
            await self._ausgabe(call_id, {"ok": False, "fehler": "Die Zusammenfassung hat gerade nicht geklappt."})
            return
        self._karte(karte)
        self.a.letzte_aktion = {"typ": "karte", "art": "zusammenfassen"}
        await self.coach.melden()
        await self._ausgabe(call_id, {
            "ok": True, "karte": {"titel": karte["titel"], "punkte": karte["punkte"]},
            "besprochen": auszug or "(in diesem Bereich noch nichts gesagt)",
            "hinweis": "Die Karte steht. Sag ein bis zwei Sätze, was auffällt (was beschlossen ist, was offen ist, "
                       "was als Nächstes ansteht) – nicht vorlesen; „beschlossen“ nur, was auf der Karte als "
                       "Entscheidung steht."})

    async def _abschluss_anstossen(self) -> None:
        if self._aufgaben:
            await asyncio.wait(self._aufgaben, timeout=10.0)
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
