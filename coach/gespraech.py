"""Sprachgespräch mit Nestor über das Realtime-Sprachmodell (die Technik hinter dem ChatGPT-Sprachmodus), Premium.

Wird Nestor angesprochen, öffnet sich eine Sitzung: Persona und Meeting-Kontext als Anweisung, die erste Frage
als Text (sie ist schon transkribiert), danach hört das Modell selbst mit – das Mikrofon geht direkt hinein.
Wann es antwortet, entscheidet aber der Coach (create_response aus): nur bei seinem Namen im Live-Text oder bei
einer Nachfrage direkt nach seiner Antwort (coach/assistent.py, Ticket #27: nur der erste Satz, nur wenn er an
Nestor gerichtet ist). Abspieltest 05.10.: Mit eigener Entscheidung des Modells kommentierte Nestor ungefragt das
laufende Gespräch („Alles klar, Vorschlag: maximal 2000 Euro“).
Jede Antwort ist ein Antwortbogen (Ticket #27): kurz, ein bis zwei Sätze, Einzelheiten auf der Karte. Reinreden
macht Nestor still – aber nur die Stimme: die Antwort wird fertig erzeugt und kommt als Karte in den Verlauf
(Nachtrag B). Bild und Recherche sind lange Aufträge im Hintergrund; das Ergebnis kommt still.
Ist eine Weile Ruhe oder sagt die Runde „danke, das war's“, schließt die Sitzung. Kosten nur, solange sie offen ist.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from .config import EINST, openai_schluessel

log = logging.getLogger("coach.gespraech")

URL = "wss://api.openai.com/v1/realtime?model={modell}"
RATE = 24000

WERKZEUGE = [
    {"type": "function", "name": "bild_zeichnen",
     "description": "Visuelle Übersicht (Live-Bild) neu zeichnen lassen, dauert etwa eine Minute; das Bild erscheint "
                    "später still im Verlauf. Nicht, wenn die Runde nur ein vorhandenes Bild erklärt haben möchte.",
     "parameters": {"type": "object", "properties": {"fokus": {
         "type": "string", "description": "gesamt, ein Agendapunkt, was noch ansteht, wo Entscheidungen fehlen …"}},
         "required": ["fokus"]}},
    {"type": "function", "name": "agendapunkt_wechseln",
     "description": "Zum genannten Agendapunkt wechseln – nur, wenn die Gruppe das ausdrücklich möchte.",
     "parameters": {"type": "object", "properties": {"nummer": {"type": "integer"}}, "required": ["nummer"]}},
    {"type": "function", "name": "recherchieren",
     "description": "Im Internet recherchieren, z. B. „gib uns einen Überblick zu …“ oder aktuelle Fakten. Läuft im "
                    "Hintergrund; das Ergebnis erscheint später still als Karte mit Quellen. Formuliere die Frage ohne "
                    "Namen und ohne Interna aus dem Meeting.",
     "parameters": {"type": "object", "properties": {"frage": {"type": "string"}}, "required": ["frage"]}},
    {"type": "function", "name": "folie_erstellen",
     "description": "Das letzte Rechercheergebnis mit Quellen als Folie im Dashboard zusammenstellen. Nur nach "
                    "einer Recherche und wenn die Gruppe das möchte (z. B. „ja, mach eine Folie“).",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "karte_zeigen",
     "description": "Eine Karte in den Verlauf stellen, wenn die Runde genau das möchte: zusammenfassen "
                    "(Zusammenfassung des Meetings), fehlt (was noch fehlt, Lücken), stand (wo stehen wir), "
                    "festgehalten (Protokoll, Liste des Festgehaltenen), ueberblick (Überblick als Text). Das System "
                    "sagt selbst dazu, was auffällt – sag nichts.",
     "parameters": {"type": "object", "properties": {"art": {
         "type": "string", "enum": ["zusammenfassen", "fehlt", "stand", "festgehalten", "ueberblick"]}},
         "required": ["art"]}},
    {"type": "function", "name": "status_abfragen",
     "description": "Aktuellen Stand abfragen: Laufzeit, aktueller Agendapunkt und Restzeit, ob das Live-Bild noch "
                    "gezeichnet wird oder fertig ist, Ergebnisse, letzte Hinweise. Immer nutzen, bevor du etwas "
                    "sagst, das sich seit Gesprächsbeginn geändert haben kann – nie raten.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "artefakt_eintragen",
     "description": "Eine Aufgabe, Entscheidung, einen offenen Punkt oder ein Risiko eintragen oder ergänzen, wenn die "
                    "Gruppe es dir sagt („Sofie übernimmt die Statusseite bis Freitag“, „halt fest: wir nehmen Variante "
                    "B“). Nummer aus „Festgehaltene Artefakte“ bzw. status_abfragen, für Neues weglassen. Nur Felder, "
                    "die gesagt wurden. Das System bestätigt mit „Notiert“ – sag nichts dazu.",
     "parameters": {"type": "object", "properties": {
         "nummer": {"type": "integer", "description": "Nummer eines festgehaltenen Artefakts; weglassen für Neues"},
         "typ": {"type": "string", "enum": ["aufgabe", "entscheidung", "offen", "risiko"]},
         "was": {"type": "string"}, "wer": {"type": "string"}, "bis": {"type": "string"},
         "status": {"type": "string", "enum": ["endgueltig", "vorlaeufig"]},
         "reaktion": {"type": "string"}}}},
    {"type": "function", "name": "zuhoeren_pausieren",
     "description": "Die Gruppe möchte, dass du nicht mehr zuhörst. Wieder an nur über den Knopf im Dashboard.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "gespraech_beenden",
     "description": "Die Gruppe braucht dich gerade nicht mehr („danke, das war's“). Du hörst dann wieder nur auf "
                    "deinen Namen.", "parameters": {"type": "object", "properties": {}}},
]

ANWEISUNG = """\
Du bist {name}, Moderationsassistent und Teil dieser Runde in einem Präsenzmeeting. Du sprichst mit der
Gruppe wie ein erfahrener, freundlicher Kollege, der den Überblick behält: natürlich, locker, kurz – ein Satz,
höchstens zwei, auf Deutsch, per „ihr“, nie „Sie“. Das Wichtigste zuerst; Einzelheiten erscheinen danach als Karte
auf dem Bildschirm – lies nie vor, was dort steht.
Du bewertest keine Personen, ergreifst keine Partei und erfindest nichts. „Festgehalten“ oder „entschieden“
sagst du nur, wenn es ausdrücklich beschlossen wurde. Personen heißen im Transkript „Person N“ – sprich
stattdessen von „jemandem“. Agendapunkte nennst du mit Nummer und Titel aus der Agenda unten.
Der Stand unten ist vom Beginn dieses Gesprächs. Ob das Bild fertig ist, wie viel Zeit bleibt oder bei welchem
Punkt ihr seid, fragst du vor der Antwort mit status_abfragen ab – rate das nie.
Du hörst über ein Raummikrofon; Gespräche der Gruppe untereinander, die nicht an dich gerichtet sind,
beantwortest du nicht – dann bleibst du still. Für Bild, Recherche, Karten, Agendawechsel, Pause und Ende hast du
Werkzeuge; bei Agendawechsel und Pause sag kurz dazu, was du tust.

STAND DES MEETINGS (zu Beginn dieses Gesprächs):
{kontext}
"""
# Ohne Sofort-Bestätigung (LMC_BESTAETIGUNG=0) sagt das Modell selbst, dass es nachschaut
OHNE_BESTAETIGUNG = ("\nBei bild_zeichnen, recherchieren, folie_erstellen, karte_zeigen und artefakt_eintragen spricht "
                     "das System selbst – sag nichts dazu.\n")
# Ticket #21: Bestätigung und Wartezeit spricht das System aus vorab erzeugten Floskeln (coach/bestaetigung.py)
MIT_BESTAETIGUNG = """
Oft hat das System schon kurz bestätigt („Bin dran“), bevor du drankommst. Fang deshalb nicht mit „Okay“,
„Moment“, „Klar“ oder „Gern“ an, sondern direkt mit dem Inhalt. Bei bild_zeichnen, recherchieren, folie_erstellen,
karte_zeigen und artefakt_eintragen spricht das System selbst – ruf das Werkzeug auf, ohne etwas dazu zu sagen.
"""


class Gespraech:
    def __init__(self, assistent) -> None:
        self.a = assistent
        self.coach = assistent.coach
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

    async def starten(self, frage: str | None, bogen=None) -> None:
        import websockets

        if EINST.stufe == "basis":  # Realtime-Gespräch ist OpenAI – in Basis nie (Ticket #13), Rückfall Text-Weg
            raise RuntimeError("Realtime-Gespräch gibt es nur in Nestor Premium")
        kopf = {"Authorization": f"Bearer {openai_schluessel()}"}
        self._ws = await websockets.connect(URL.format(modell=EINST.realtime_modell), additional_headers=kopf,
                                            max_size=None)
        await self._senden({"type": "session.update", "session": self.sitzung()})
        self.offen = True
        self._empfang = asyncio.create_task(self._empfangen())
        await self._fragen(frage or "", bogen)

    async def frage(self, bogen) -> None:
        """Ein neuer Bogen in der offenen Sitzung: Frage als Text, Antwort anstoßen, warten bis sie fertig ist."""
        self.a.text_neu(bogen.frage)
        await self._fragen(bogen.frage, bogen)
        await self.warten(bogen)

    async def _fragen(self, frage: str, bogen) -> None:
        self._frage = frage
        self._bogen = bogen
        self._stumm = bool(bogen is not None and bogen.abgeloest)
        self._fertig = asyncio.Event()
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden + 30
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": frage or "(Frage folgt)"}]}})
        await self._antworten_lassen()

    async def warten(self, bogen, frist: float = 45.0) -> None:
        """Bis die Antwort dieses Bogens fertig erzeugt und gespielt ist (höchstens `frist` s)."""
        try:
            await asyncio.wait_for(self._fertig.wait(), frist)
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
        kontext = self.a.kontext("").rsplit("\n\nFrage an dich:", 1)[0]
        return {
            "type": "realtime",
            "instructions": ANWEISUNG.format(name=EINST.assistent_name, kontext=kontext)
            + (MIT_BESTAETIGUNG if EINST.bestaetigung else OHNE_BESTAETIGUNG),
            "output_modalities": ["audio"],
            "audio": {
                # Nachtrag B: Reinreden stoppt nur die Stimme (coach-seitig), nicht die Antwort – sie kommt als Karte
                "input": {"format": {"type": "audio/pcm", "rate": RATE},
                          "turn_detection": {"type": "semantic_vad", "create_response": False,
                                             "interrupt_response": False}},
                "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": EINST.stimme},
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
                await self.schliessen()

    async def schliessen(self) -> None:
        self._fertig.set()  # ein wartender Bogen hängt nicht
        if not self.offen:
            return
        self.offen = False
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
        except Exception as ex:  # noqa: BLE001
            if self.offen:
                log.warning("Gespräch abgebrochen: %s", type(ex).__name__)
        finally:
            if self.offen:
                await self.schliessen()

    async def _ereignis(self, typ: str, e: dict) -> bool:
        """Haken für Unterklassen: True heißt, das Ereignis ist erledigt und der Standardweg entfällt."""
        return False

    async def _ton(self, b64: str, item: str | None = None) -> None:
        c, m = self.coach, self.coach.meeting
        if self._stumm:  # unterbrochen: nichts mehr hören lassen, nur mitzählen (für truncate)
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
        try:
            arg = json.loads(argumente)
        except json.JSONDecodeError:
            arg = {}
        if name == "status_abfragen":
            await self._senden({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": call_id,
                "output": json.dumps(self.coach.status_kurz(), ensure_ascii=False)}})
            await self._antworten_lassen()
            return
        if name == "artefakt_eintragen":  # Lücke korrigieren (Ticket #27 Nachtrag A): „Notiert“, Karte wird grün
            a, kurz = self.coach.artefakte.eintragen(arg if isinstance(arg, dict) else {})
            if a is not None:
                self.coach.protokoll.append({"zeit": self.coach.meeting.jetzt(), "art": "artefakt_eingetragen",
                                             "id": a.id, "durch": "stimme"})
                await self.coach.melden()
            from . import bestaetigung as B

            satz = self.a.floskeln.variante(B.NOTIERT) if a is not None else "Das konnte ich keinem Eintrag zuordnen."
            aufgabe = asyncio.ensure_future(self.a.floskel_sagen(satz, self._bogen))
            if self._bogen is not None:
                self._bogen.zusatz.append(aufgabe)
            await self._ausgabe(call_id, {"ok": a is not None, "eingetragen": a.kurz() if a else None,
                                          "hinweis": "das System hat „Notiert“ gesagt – sag nichts"})
            return
        if name in ("recherchieren", "bild_zeichnen"):  # lange Aufträge: kein Bogen, Ergebnis kommt still (Ticket #27)
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
            if art in ("folie", "zusammenfassen", "fehlt", "stand", "festgehalten", "ueberblick"):
                self.a.zusatz_bogen(art)
            await self._ausgabe(call_id, {"ok": True, "hinweis": "die Karte erscheint, das System sagt dazu, was "
                                                                 "auffällt – sag nichts"})
            return
        aktion = {"agendapunkt_wechseln": {"typ": "weiter", "ziel": str(arg.get("nummer", ""))},
                  "zuhoeren_pausieren": {"typ": "pause"}}.get(name)
        if aktion:
            await self.coach.assistent_aktion(aktion)
            self.a.letzte_aktion = aktion
        if name in ("gespraech_beenden", "zuhoeren_pausieren"):
            self.beenden_nach_antwort = True
        await self._ausgabe(call_id, {"ok": True})
        if name != "gespraech_beenden":
            await self._antworten_lassen()  # nach dem Werkzeug weitersprechen

    async def _ausgabe(self, call_id: str | None, ausgabe: dict) -> None:
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": json.dumps(ausgabe, ensure_ascii=False)}})

    async def _antwort_fertig(self, antwort: dict) -> None:
        c = self.coach
        text = self._antwort_text.strip()
        self._antwort_text = ""
        stumm = self._stumm
        self._ton_ende(abgebrochen=False)
        self._antwort_laeuft = False
        w = self._wiedergabe
        if stumm and w and w.get("item") and "gekuerzt" in w:
            await self._kuerzen(w)  # das Modell soll wissen, wie weit die Antwort zu hören war
        self._stumm = False
        if text and self.a.sprechzeiten and not stumm:
            # Die Sprechzeit reicht jetzt bis zum Ende der Wiedergabe – mit dem Text entscheidet der Echo-Filter nach
            # dem Inhalt, sonst ginge wer Nestor ins Wort fällt als „eigene Sprache“ verloren (eigene_sprache)
            self.a.sprechtexte.append((*self.a.sprechzeiten[-1], text))
        nutzung = antwort.get("usage") or {}
        if nutzung:
            from .pipeline import nutzung_loggen
            nutzung_loggen({"art": "gespraech", "modell": EINST.realtime_modell,
                            "tokens_rein": nutzung.get("input_tokens"), "tokens_raus": nutzung.get("output_tokens"),
                            "details_rein": nutzung.get("input_token_details"),
                            "details_raus": nutzung.get("output_token_details")})
        if text:
            self.a.letzte = {"frage": self._frage, "antwort": text, "zeit": c.meeting.jetzt(),
                             "aktion": getattr(self.a, "letzte_aktion", None)}
            c.antwort_karte(self._frage, text, self.a.letzte["aktion"], [], still=stumm)
            self.a.verlauf.append((self._frage, text))
            c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "assistent", "modus": "gespraech",
                                "frage": self._frage, "antwort": text, "aktion": self.a.letzte["aktion"],
                                "unterbrochen": stumm})
            self.a.letzte_aktion = None
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden
        if self.a.zustand not in ("pausiert", "taste") and self.a.bogen is None:
            self.a.zustand = "gespraech"
        self._fertig.set()
        await c.melden()
        if self.beenden_nach_antwort:
            await asyncio.sleep(1.0)
            await self.schliessen()
