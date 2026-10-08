"""Sprachgespräch mit Nestor über das Realtime-Sprachmodell (die Technik hinter dem ChatGPT-Sprachmodus).

Wird Nestor angesprochen, öffnet sich eine Sitzung: Persona und Meeting-Kontext als Anweisung, die erste Frage
als Text (sie ist schon transkribiert), danach hört das Modell selbst mit – das Mikrofon geht direkt hinein.
Wann es antwortet, entscheidet aber der Coach (create_response aus): nur bei seinem Namen im Live-Text oder bei
einer Rückfrage („…?“) kurz nach seiner letzten Antwort. Abspieltest 05.10.: Mit eigener Entscheidung des
Modells kommentierte Nestor ungefragt das laufende Gespräch („Alles klar, Vorschlag: maximal 2000 Euro“).
Damit geht, was eine reine Text-Pipeline nicht kann: natürliche Stimme mit Betonung, Rückfragen ohne
Namen, Ins-Wort-Fallen (das Modell bricht ab, das Dashboard verstummt sofort). Ist eine Weile Ruhe oder
sagt die Runde „danke, das war's“, schließt die Sitzung; Nestor hört dann wieder nur auf seinen Namen.
Kosten nur, solange die Sitzung offen ist.
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
     "description": "Visuelle Übersicht (Live-Bild) zeichnen lassen, dauert ein bis zwei Minuten.",
     "parameters": {"type": "object", "properties": {"fokus": {
         "type": "string", "description": "gesamt, ein Agendapunkt, was noch ansteht, wo Entscheidungen fehlen …"}},
         "required": ["fokus"]}},
    {"type": "function", "name": "agendapunkt_wechseln",
     "description": "Zum genannten Agendapunkt wechseln – nur, wenn die Gruppe das ausdrücklich möchte.",
     "parameters": {"type": "object", "properties": {"nummer": {"type": "integer"}}, "required": ["nummer"]}},
    {"type": "function", "name": "recherchieren",
     "description": "Im Internet recherchieren, z. B. „gib uns einen Überblick zu …“ oder aktuelle Fakten. Dauert "
                    "5–15 Sekunden – sag vorher kurz, dass du nachschaust. Formuliere die Frage ohne Namen und "
                    "ohne Interna aus dem Meeting.",
     "parameters": {"type": "object", "properties": {"frage": {"type": "string"}}, "required": ["frage"]}},
    {"type": "function", "name": "folie_erstellen",
     "description": "Das letzte Rechercheergebnis mit Quellen als Folie im Dashboard zusammenstellen. Nur nach "
                    "einer Recherche und wenn die Gruppe das möchte (z. B. „ja, mach eine Folie“). Dauert wenige "
                    "Sekunden; das Dashboard meldet, wenn sie fertig ist.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "status_abfragen",
     "description": "Aktuellen Stand abfragen: Laufzeit, aktueller Agendapunkt und Restzeit, ob das Live-Bild noch "
                    "gezeichnet wird oder fertig ist, Ergebnisse, letzte Hinweise. Immer nutzen, bevor du etwas "
                    "sagst, das sich seit Gesprächsbeginn geändert haben kann – nie raten.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "zuhoeren_pausieren",
     "description": "Die Gruppe möchte, dass du nicht mehr zuhörst. Wieder an nur über den Knopf im Dashboard.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "gespraech_beenden",
     "description": "Die Gruppe braucht dich gerade nicht mehr („danke, das war's“). Du hörst dann wieder nur auf "
                    "deinen Namen.", "parameters": {"type": "object", "properties": {}}},
]

ANWEISUNG = """\
Du bist {name}, Moderationsassistent und Teil dieser Runde in einem Präsenzmeeting. Du sprichst mit der
Gruppe wie ein erfahrener, freundlicher Kollege, der den Überblick behält: natürlich, locker, kurz – meist
ein bis drei Sätze, auf Deutsch, per „ihr“. Das Wichtigste zuerst; wenn mehr gewünscht ist, fragen sie nach.
Du bewertest keine Personen, ergreifst keine Partei und erfindest nichts. „Festgehalten“ oder „entschieden“
sagst du nur, wenn es ausdrücklich beschlossen wurde. Personen heißen im Transkript „Person N“ – sprich
stattdessen von „jemandem“. Agendapunkte nennst du mit Nummer und Titel aus der Agenda unten.
Der Stand unten ist vom Beginn dieses Gesprächs. Ob das Bild fertig ist, wie viel Zeit bleibt oder bei welchem
Punkt ihr seid, fragst du vor der Antwort mit status_abfragen ab – rate das nie.
Du hörst über ein Raummikrofon; Gespräche der Gruppe untereinander, die nicht an dich gerichtet sind,
beantwortest du nicht – dann bleibst du still. Für Bild, Agendawechsel, Pause und Ende hast du Werkzeuge;
sag kurz dazu, was du tust.

STAND DES MEETINGS (zu Beginn dieses Gesprächs):
{kontext}
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
        self._recherche_laeuft = False
        self._wartet_auf_commit = False
        self._letztes_commit = 0.0  # Meetingzeit, bis zu der das Modell das Audio als Turn übernommen hat
        self._antwort_ende = 0.0  # Meetingzeit des letzten Antwortendes (für Rückfragen ohne Namen)

    async def starten(self, frage: str | None) -> None:
        import websockets

        if EINST.stufe == "basis":  # Realtime-Gespräch ist OpenAI – in Basis nie (Ticket #13), Rückfall Text-Weg
            raise RuntimeError("Realtime-Gespräch gibt es nur in Nestor Premium")
        kopf = {"Authorization": f"Bearer {openai_schluessel()}"}
        self._ws = await websockets.connect(URL.format(modell=EINST.realtime_modell), additional_headers=kopf,
                                            max_size=None)
        await self._senden({"type": "session.update", "session": self.sitzung()})
        self.offen = True
        self._empfang = asyncio.create_task(self._empfangen())
        self._frage = frage or ""
        text = frage or "(Jemand hat dich gerade angesprochen; die eigentliche Frage folgt gleich. Sag nur kurz „Ja?“.)"
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
        await self._antworten_lassen()

    def sitzung(self) -> dict:
        """Einstellungen des Gesprächs: der Coach entscheidet, wann Nestor antwortet (create_response aus)."""
        kontext = self.a.kontext("").rsplit("\n\nFrage an dich:", 1)[0]
        return {
            "type": "realtime",
            "instructions": ANWEISUNG.format(name=EINST.assistent_name, kontext=kontext),
            "output_modalities": ["audio"],
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": RATE},
                          "turn_detection": {"type": "semantic_vad", "create_response": False,
                                             "interrupt_response": True}},
                "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": EINST.stimme},
            },
            "tools": WERKZEUGE, "tool_choice": "auto",
        }

    async def _antworten_lassen(self) -> None:
        self._antwort_laeuft = True
        await self._senden({"type": "response.create"})
        self.a.zustand = "denkt"
        await self.coach.melden()

    async def satz(self, text: str, ende: float) -> None:
        """Fertiger Satz aus dem Live-Text, während die Sitzung offen ist: Ist er an Nestor gerichtet?"""
        from .assistent import angesprochen

        rueckfrage = text.rstrip().endswith("?") and ende - self._antwort_ende <= EINST.nachfrage_sekunden
        if not (angesprochen(text) or rueckfrage) or self._antwort_laeuft:
            return
        self._frage = text.strip()
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden + 30
        if self._letztes_commit >= ende - 0.8:
            await self._antworten_lassen()
        else:
            self._wartet_auf_commit = True  # das Modell hat den Turn noch nicht übernommen – gleich danach

    async def audio(self, pcm24k: bytes) -> None:
        """Mikrofon direkt ins Gespräch (Rückfragen, Ins-Wort-Fallen)."""
        if self.offen:
            await self._senden({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm24k).decode()})
            if time.monotonic() > self._ende_bis and not self.a.zustand == "spricht":
                await self.schliessen()

    async def schliessen(self) -> None:
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
                    await self._ton(e["delta"])
                elif typ in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
                    self._antwort_text += e.get("delta", "")
                elif typ == "input_audio_buffer.speech_started":
                    # jemand spricht: laufende Antwort sofort verstummen lassen (das Modell bricht selbst ab)
                    if self.a.zustand == "spricht":
                        await c.direkt_senden({"typ": "stimme_stopp"})
                        self._ton_ende()
                    self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden + 30
                    self.a.zustand = "angesprochen"
                    await c.melden()
                elif typ == "input_audio_buffer.speech_stopped":
                    self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden
                    if self.a.zustand == "angesprochen" and not self._antwort_laeuft:
                        self.a.zustand = "gespraech"
                        await c.melden()
                elif typ == "input_audio_buffer.committed":
                    self._letztes_commit = c.meeting.jetzt()
                    if self._wartet_auf_commit:
                        self._wartet_auf_commit = False
                        await self._antworten_lassen()
                elif typ == "conversation.item.input_audio_transcription.completed":
                    self._frage = e.get("transcript", "") or self._frage
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

    async def _ton(self, b64: str) -> None:
        c, m = self.coach, self.coach.meeting
        if self._ton_beginn is None:
            self._ton_beginn = max(m.jetzt() + 0.4, self.a.sprechzeiten[-1][1] if self.a.sprechzeiten else 0)
            self.a.sprechzeiten.append((self._ton_beginn, self._ton_beginn + 60))
            self.a.zustand = "spricht"
            await c.melden()
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
        if name == "recherchieren":
            # läuft nebenher, damit der Empfang weiterläuft („ich schau kurz nach“ wird noch gesprochen)
            asyncio.create_task(self._recherche(str(arg.get("frage") or self._frage), call_id))
            return
        aktion = {"bild_zeichnen": {"typ": "bild", "fokus": str(arg.get("fokus") or "gesamt")},
                  "agendapunkt_wechseln": {"typ": "weiter", "ziel": str(arg.get("nummer", ""))},
                  "zuhoeren_pausieren": {"typ": "pause"},
                  "folie_erstellen": {"typ": "folie"}}.get(name)
        if aktion:
            await self.coach.assistent_aktion(aktion)
            self.a.letzte_aktion = aktion
        if name in ("gespraech_beenden", "zuhoeren_pausieren"):
            self.beenden_nach_antwort = True
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": json.dumps({"ok": True})}})
        if name != "gespraech_beenden":
            await self._antworten_lassen()  # nach dem Werkzeug weitersprechen

    async def ansagen(self, text: str) -> None:
        """Ansage des Coaches (z. B. Bild fertig) im laufenden Gespräch – wartet, bis Nestor ausgeredet hat."""
        for _ in range(60):
            if not self._antwort_laeuft:
                break
            await asyncio.sleep(0.5)
        if not self.offen:
            await self.a._sprechen_texte([text])
            return
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "message", "role": "system", "content": [{"type": "input_text", "text": f"Neu: {text}"}]}})
        self._antwort_laeuft = True
        await self._senden({"type": "response.create", "response": {
            "instructions": f"Sag der Runde kurz und natürlich, in einem Satz: {text}"}})

    async def _recherche(self, frage: str, call_id: str | None) -> None:
        from .recherche import recherchieren

        c = self.coach
        self._antwort_laeuft = self._recherche_laeuft = True
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden + 60
        self.a.zustand = "recherchiert"
        await c.melden()
        try:
            erg = await recherchieren(c._client, frage, c.meeting.titel)
            ausgabe = {"zusammenfassung": erg["text"], "quellen": [q["titel"] for q in erg["quellen"]]}
            self.a.letzte_quellen = erg["quellen"]
            c.recherche_merken(frage, erg)
            from .pipeline import nutzung_loggen
            nutzung_loggen({"art": "recherche", "modell": EINST.recherche_modell, "tokens_rein": erg["tokens_rein"],
                            "tokens_raus": erg["tokens_raus"], "sekunden": erg["sekunden"]})
            c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "recherche", "frage": frage,
                                "quellen": erg["quellen"], "sekunden": erg["sekunden"]})
        except Exception as e:  # noqa: BLE001
            log.warning("Recherche fehlgeschlagen: %s", type(e).__name__)
            ausgabe = {"fehler": "Die Recherche hat nicht geklappt."}
        await self._senden({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": json.dumps(ausgabe, ensure_ascii=False)}})
        await self._senden({"type": "response.create", "response": {
            "instructions": "Fasse das Rechercheergebnis für die Runde gesprochen zusammen: 3 bis 5 Sätze, das "
                            "Wichtigste zuerst, keine Links. Biete am Ende kurz an, das Ergebnis mit den Quellen "
                            "auf einer Folie zusammenzustellen. Sagt die Gruppe ja, nutze folie_erstellen."}})
        self._recherche_laeuft = False
        self.a.zustand = "denkt"
        await c.melden()

    async def _antwort_fertig(self, antwort: dict) -> None:
        c = self.coach
        text = self._antwort_text.strip()
        self._antwort_text = ""
        self._ton_ende(abgebrochen=False)
        if self._recherche_laeuft:  # „ich schau kurz nach“ ist fertig, das Ergebnis folgt noch
            self._antwort_text = text + " "
            return
        self._antwort_laeuft = False
        self._antwort_ende = self.a.sprechzeiten[-1][1] if text and self.a.sprechzeiten else c.meeting.jetzt()
        if text and self.a.sprechzeiten:
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
                             "aktion": getattr(self.a, "letzte_aktion", None), "quellen": self.a.letzte_quellen}
            c.antwort_karte(self._frage, text, self.a.letzte["aktion"], self.a.letzte_quellen)
            self.a.letzte_quellen = []
            self.a.verlauf.append((self._frage, text))
            c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "assistent", "modus": "gespraech",
                                "frage": self._frage, "antwort": text, "aktion": self.a.letzte["aktion"]})
            self.a.letzte_aktion = None
        self._ende_bis = time.monotonic() + EINST.gespraech_ende_sekunden
        if self.a.zustand not in ("pausiert",):
            self.a.zustand = "gespraech"
        await c.melden()
        if self.beenden_nach_antwort:
            await asyncio.sleep(1.0)
            await self.schliessen()
