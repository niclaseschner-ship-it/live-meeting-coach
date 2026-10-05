"""Coach: verbindet Zuhören (Transkription), Denken (Analyse, Entscheider) und Ausgabe."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from . import analyse, ergebnisse, kosten, regeln, themen, transkription
from .assistent import Assistent
from .config import EINST, WURZEL, hat_openai_schluessel, openai_schluessel, schluessel_info
from .entscheider import Entscheider
from .zustand import Agendapunkt, Meeting, Segment

STIMMEN = ("cedar", "marin", "coral", "sage", "verse", "alloy", "ash", "ballad", "echo", "shimmer")

log = logging.getLogger("coach")
NUTZUNG = WURZEL / "logs" / "nutzung.jsonl"
KOSTEN = kosten.Zaehler(NUTZUNG)


def nutzung_loggen(eintrag: dict) -> None:
    """Nur Mengen und Modelle, keine Inhalte (Lastenheft Kap. 14). Mit geschätzten Kosten in Dollar."""
    NUTZUNG.parent.mkdir(exist_ok=True)
    zeile = {"zeit": time.strftime("%Y-%m-%dT%H:%M:%S"), **eintrag, "usd": round(kosten.dollar(eintrag), 5)}
    with NUTZUNG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(zeile, ensure_ascii=False) + "\n")
    KOSTEN.buchen(eintrag)


def hintergrund(coro) -> asyncio.Task:
    """Task starten und Ausnahmen ins Log schreiben statt sie zu verschlucken."""
    task = asyncio.create_task(coro)

    def fertig(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            log.error("Hintergrundaufgabe fehlgeschlagen", exc_info=t.exception())

    task.add_done_callback(fertig)
    return task


def fehlertext(e: Exception) -> str:
    """Nur Typ und Statuscode – Fehlermeldungen der API können Kennungen enthalten."""
    status = getattr(e, "status_code", None)
    return f"{type(e).__name__}" + (f" (HTTP {status})" if status else "")


def gleichzeitig_regel(regeln: list[str]) -> str | None:
    """Ältere Einrichtungen ohne Regelauswahl: passende eigene Regel im Freitext finden."""
    for r in regeln:
        if any(w in r.lower() for w in ("ausreden", "ins wort", "gleichzeitig", "unterbrech")):
            return r
    return None


class Coach:
    def __init__(self) -> None:
        self.meeting = Meeting()
        self.entscheider = Entscheider(EINST.cooldown_sekunden)
        self.referenzen: dict[str, str] = {}  # Name -> data-URL eines kurzen WAV
        self.monolog_sekunden = EINST.monolog_sekunden
        self.fehler: str | None = None
        self.simulation_laeuft = False
        self.beobachter: list = []  # async Callbacks, z. B. WebSocket-Broadcast
        self.direkt: list = []  # async Callbacks für Einzelnachrichten (Sprachausgabe)
        self._client = None
        self.client_neu()
        self._sperre = asyncio.Lock()
        self._sim_task: asyncio.Task | None = None
        # Version 2: Ströme
        self.hoerstrom = None
        self.onepager_am_ende = True
        self.auto_wechsel = False  # Abspielmodus: Agenda-Vorschläge wie von der Moderation bestätigt übernehmen
        self.protokoll: list[dict] = []  # Ereignisse für den Testbericht (Wechsel, Ampeln, Doku)
        self._abschnitt: list[Segment] = []
        self._themen_sperre = asyncio.Lock()
        # Live-Bild (One-Pager, FR-10): gezeichnet von Claude über das Abo
        self.onepager_svg: str | None = None
        self.onepager_png: bytes | None = None  # Live-Bild von OpenAI (Rasterbild)
        # Recherche als Folie: letztes Rechercheergebnis und die daraus gebaute Folie
        self.letzte_recherche: dict | None = None
        self.folie: dict | None = None
        self.folie_version = 0
        self._folie_laeuft = False
        self.karten: list[dict] = []  # Nestor-Karten (Pop-ups), bleiben im Verlauf abrufbar
        self.onepager_analyse: str | None = None
        self.onepager_version = 0
        self.onepager_stand: float | None = None
        self.onepager_fehler: str | None = None
        self._onepager_laeuft = False
        self._onepager_letzter_start: float | None = None
        self._onepager_nachholen = False
        self._onepager_fokus_wunsch: str | None = None
        self.onepager_fokus: str | None = None  # Fokus des angezeigten Bildes (auf Zuruf), sonst Gesamtbild
        self._onepager_voll: dict | None = None  # letztes Gesamtbild – Grundlage der Fortschreibung
        self.assistent = Assistent(self)
        self.stumm = False  # Mikro stumm (Knopf in der Kopfleiste)
        self.aeusserungen: list = []  # Regel 1: Äußerungen mit Sprecherabschnitten und Pegel (unterbrechung.py)
        self._unterbrechungen_gemeldet: set[float] = set()

    @property
    def karenz_bloecke(self) -> int:
        """FR-05: Karenzzeit in Abschnitten der Themen-Zuordnung (mindestens einer)."""
        return max(1, round(EINST.fokus_karenz_sekunden / EINST.abschnitt_sekunden))

    # --- Einrichtung (FR-01) -----------------------------------------------
    def einrichten(self, daten: dict) -> None:
        """Von außen (Formular): eine laufende Simulation wird dabei beendet."""
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
        self._einrichten(daten)

    def _einrichten(self, daten: dict) -> None:
        self.meeting = Meeting(
            titel=daten.get("titel", "").strip(),
            ziel=daten.get("ziel", "").strip(),
            agenda=[
                Agendapunkt(p["titel"].strip(), p.get("ziel", "").strip(), float(p.get("minuten") or 10))
                for p in daten.get("agenda", [])
                if p.get("titel", "").strip()
            ],
            regeln=[r.strip() for r in daten.get("regeln", []) if r.strip()],
            regel_ids=regeln.gueltige(daten["regel_ids"]) if "regel_ids" in daten else list(regeln.STANDARD),
            teilnehmende=[t.strip() for t in daten.get("teilnehmende", []) if t.strip()],
        )
        self.entscheider = Entscheider(EINST.cooldown_sekunden)
        self.assistent = Assistent(self)
        self.assistent.aktiv = bool(daten.get("assistent", True))
        self.referenzen = {n: u for n, u in self.referenzen.items() if n in self.meeting.teilnehmende}
        self.monolog_sekunden = EINST.monolog_sekunden
        self.fehler = None
        self.protokoll = []
        self._abschnitt = []
        self.onepager_svg = self.onepager_analyse = self.onepager_stand = self.onepager_fehler = None
        self.onepager_png = None
        self.onepager_fokus = self._onepager_voll = None
        self.aeusserungen = []
        self._unterbrechungen_gemeldet = set()
        self._onepager_letzter_start = None
        self.letzte_recherche = self.folie = None
        self.folie_version = 0
        self.karten = []

    def client_neu(self) -> None:
        """OpenAI-Client mit dem aktuellen Schlüssel (im Dashboard eingetragen oder aus der Umgebung)."""
        self._client = None
        if hat_openai_schluessel():
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=openai_schluessel())
            if EINST.ki == "codex":
                from .ki_abo import AboClient

                self._client = AboClient(self._client)

    def kosten_stand(self) -> dict:
        m = self.meeting
        live = self.hoerstrom.live if self.hoerstrom else None
        return KOSTEN.stand(live_sekunden=live.gesendete_sekunden if live and live._ws is not None else 0.0,
                            live_modell=EINST.live_modell,
                            meeting_sekunden=m.jetzt() if m.gestartet_um is not None else 0.0,
                            geplant_minuten=sum(p.minuten for p in m.agenda))

    def schnappschuss(self) -> dict:
        daten = self.meeting.schnappschuss(EINST.zeit_rot_prozent)
        ampeln = analyse.prozess_ampeln(
            self.meeting,
            monolog_sekunden=self.monolog_sekunden,
            karenz_bloecke=self.karenz_bloecke,
            zeit_rot_prozent=EINST.zeit_rot_prozent,
            ueberlappung_min=EINST.ueberlappung_min_sekunden,
            ueberlappung_halte=EINST.ueberlappung_halte_sekunden,
            themen_aktiv=self._client is not None,
            zickzack_fenster=EINST.zickzack_fenster_sekunden,
            zickzack_wechsel=EINST.zickzack_wechsel,
        )
        daten.update(
            {
                "regel_status": self.regel_status(ampeln),
                "stumm": self.stumm,
                "einstellungen": self.einstellungen(),
                "referenzen": list(self.referenzen),
                "fehler": self.fehler,
                "schluessel_vorhanden": self._client is not None,
                "schluessel": schluessel_info(),
                "kosten": self.kosten_stand(),
                "simulation": self.simulation_laeuft,
                "block_sekunden": EINST.block_sekunden,
                "ampeln": ampeln,
                "hoeren": self.hoerstrom is not None,
                "onepager_version": self.onepager_version,
                "onepager_stand": self.onepager_stand,
                "onepager_laeuft": self._onepager_laeuft,
                "onepager_fehler": self.onepager_fehler,
                "onepager_minuten": EINST.onepager_minuten,
                "onepager_fokus": self.onepager_fokus,
                "onepager_format": "png" if self.onepager_png else "svg",
                "folie": self.folie,
                "folie_version": self.folie_version,
                "folie_laeuft": self._folie_laeuft,
                "recherche_da": self.letzte_recherche is not None,
                "karten": self.karten[-50:],
                "assistent": self.assistent.schnappschuss(),
            }
        )
        return daten

    def regel_status(self, ampeln: list[dict]) -> list[dict]:
        """Eine Ampel je gewählter Regel – die frühere Ampelleiste und die Regelliste in einem.

        „Zeit einhalten“ fehlt bewusst: Zeit steht nur an einer Stelle (Zeit-Karte), sonst wird es doppelt rot.
        """
        m = self.meeting
        jetzt = m.jetzt()
        a = {x["name"]: x for x in ampeln}
        juengst = lambda art, sek: [h for h in m.hinweise if h.art == art and h.zeit >= jetzt - sek]  # noqa: E731
        aus: list[dict] = []
        for rid in m.regel_ids:
            r = regeln.NACH_ID.get(rid)
            if r is None or rid == "zeit":
                continue
            farbe, detail = "gruen", ""
            if rid == "kurz":
                dauer = analyse.monolog_live(m, self.monolog_sekunden)[1] if m.laeuft else 0.0
                farbe = "rot" if dauer >= 1.5 * self.monolog_sekunden else "gelb" if dauer >= self.monolog_sekunden else "gruen"
                detail = (f"{analyse.mmss(dauer)} von {analyse.mmss(self.monolog_sekunden)} am Stück" if dauer >= 10
                          else "Gespräch im Wechsel")
            elif rid == "ausreden":
                n = sum(1 for t in self._unterbrechungen_gemeldet if t >= jetzt - 300)
                ueber = a.get("Sprecherüberlappung", {})
                farbe = "rot" if n >= 3 else "gelb" if n or ueber.get("farbe") == "gelb" else "gruen"
                detail = f"{n}× ins Wort gefallen (5 min)" if n else ueber.get("detail", "")
            elif rid == "thema":
                fokus = a.get("Fokus", {})
                farbe, detail = fokus.get("farbe", "grau"), fokus.get("detail", "")
            elif rid == "ton":
                stellen = [e for e in self.protokoll if e["art"] == "ton" and e["zeit"] >= jetzt - 120]
                if stellen:
                    farbe = "rot"
                    detail = ("persönlicher Angriff" if any(e["ton"] == "angriff" for e in stellen) else "Kraftausdruck")
                    detail += f" ({len(stellen)}×)" if len(stellen) > 1 else ""
                else:
                    detail = "respektvoll"
            elif rid == "alle":
                h = juengst("alle", 300)
                farbe = "gelb" if h else "gruen"
                detail = "nicht alle kommen zu Wort" if h else "alle beteiligt"
            elif rid == "ergebnisse":
                h = juengst("ergebnisse", 180)
                farbe = "gelb" if h else "gruen"
                detail = "Ergebnis oder Zuständigkeit fehlt" if h else "Ergebnisse festgehalten"
            if not m.laeuft and not m.segmente:
                farbe = "grau"
            aus.append({"id": rid, "titel": r.titel.split(" – ")[0], "farbe": farbe, "detail": detail})
        return aus

    def status_kurz(self) -> dict:
        """Aktueller Stand für Nestor im Gespräch (Werkzeug status_abfragen) – damit er nicht rät."""
        m = self.meeting
        akt = m.agenda[m.aktiver_punkt] if 0 <= m.aktiver_punkt < len(m.agenda) else None
        if self._onepager_laeuft:
            bild = f"wird gerade gezeichnet (seit {analyse.mmss(m.jetzt() - (self._onepager_letzter_start or 0))} min)"
        elif self.onepager_version:
            bild = f"fertig, Stand {analyse.mmss(self.onepager_stand or 0)}" + (
                f", Fokus: {self.onepager_fokus}" if self.onepager_fokus else "")
        else:
            bild = "noch keins gezeichnet"
        return {
            "laufzeit": analyse.mmss(m.jetzt()),
            "aktueller_punkt": f"{m.aktiver_punkt + 1}. {akt.titel}" if akt else None,
            "restzeit_punkt": analyse.mmss(akt.minuten * 60 - m.genutzt(m.aktiver_punkt)) if akt else None,
            "live_bild": bild,
            "ergebnisse": {f"{i + 1}": e.get("ergebnis") for i, e in m.ergebnisse.items()},
            "letzte_hinweise": [h.text for h in m.hinweise[-3:]],
            "folie": ("wird gerade erstellt" if self._folie_laeuft else
                      f"fertig: {self.folie['titel']}" if self.folie else "keine"),
            "letzte_recherche": self.letzte_recherche["frage"] if self.letzte_recherche else None,
        }

    def einstellungen(self) -> dict:
        return {"assistent": self.assistent.aktiv, "modus": EINST.assistent_modus, "stimme": EINST.stimme,
                "bild_anbieter": EINST.bild_anbieter, "live_art": EINST.live_art,
                "bild_minuten": EINST.onepager_minuten, "monolog_sekunden": self.monolog_sekunden}

    def einstellen(self, daten: dict) -> None:
        """Einstellungen zur Laufzeit (Dashboard-Kopfleiste). Nur bekannte Felder, geprüfte Werte."""
        if "assistent" in daten:
            self.assistent.aktiv = bool(daten["assistent"])
        if daten.get("modus") in ("gespraech", "text"):
            object.__setattr__(EINST, "assistent_modus", daten["modus"])
        if daten.get("live_art") in ("schnell", "sparsam"):
            object.__setattr__(EINST, "live_art", daten["live_art"])  # gilt ab dem nächsten Meetingstart
        if daten.get("bild_anbieter") in ("openai", "claude"):
            object.__setattr__(EINST, "bild_anbieter", daten["bild_anbieter"])
            self._onepager_voll = None  # Fortschreibung nur innerhalb eines Anbieters
        if daten.get("stimme") in STIMMEN:
            object.__setattr__(EINST, "stimme", daten["stimme"])
        if "bild_minuten" in daten:
            object.__setattr__(EINST, "onepager_minuten", max(0.0, min(60.0, float(daten["bild_minuten"]))))
        if "monolog_sekunden" in daten:
            self.monolog_sekunden = max(20.0, min(300.0, float(daten["monolog_sekunden"])))

    async def stumm_schalten(self, an: bool) -> None:
        """Mikro stumm: nichts geht an OpenAI, nichts wird ausgewertet; ein offenes Gespräch mit Nestor endet."""
        self.stumm = an
        if an and self.assistent.gespraech:
            await self.assistent.gespraech.schliessen()
        await self.melden()

    async def melden(self) -> None:
        for b in list(self.beobachter):
            await b()

    async def direkt_senden(self, nachricht: dict) -> None:
        for b in list(self.direkt):
            await b(nachricht)

    # --- Takt: Countdown und Zeitwarnung (FR-04) ---------------------------
    def takt(self) -> None:
        m = self.meeting
        if not m.laeuft:
            return
        # Monolog live: der Hinweis kommt, sobald die hochgezählte Rede die Schwelle erreicht
        if analyse.monolog_live(m, self.monolog_sekunden)[0]:
            self._monolog_hinweis()
        # Live-Bild alle N Minuten (FR-10); gezählt ab dem letzten Start, damit Läufe sich nicht stapeln
        if self.hoerstrom and EINST.onepager_minuten > 0 and m.transkript and not self._onepager_laeuft:
            seit = m.jetzt() - (self._onepager_letzter_start or 0)
            if seit >= EINST.onepager_minuten * 60:
                self.onepager_starten()
        self.assistent.takt()
        if "alle" in m.regel_ids:
            self._alle_pruefen()
        if not 0 <= m.aktiver_punkt < len(m.agenda):
            return
        i = m.aktiver_punkt
        p = m.agenda[i]
        farbe = p.ampel(m.genutzt(i), EINST.zeit_rot_prozent)
        if farbe in ("gelb", "rot"):
            self.entscheider.einmalig(
                m, f"zeit-{i}-gelb", "zeit", "hinweis", "gruppe",
                f"„{p.titel}“: Zeitfenster erreicht. Weiterarbeiten oder zum nächsten Punkt wechseln?"
                + regeln.vereinbart(m.regel_ids, "zeit"),
            )
        if farbe == "rot":
            ueber = m.genutzt(i) - p.minuten * 60
            self.entscheider.einmalig(
                m, f"zeit-{i}-rot", "zeit", "warnung", "gruppe",
                f"„{p.titel}“ ist {analyse.mmss(ueber)} Min. über dem Zeitfenster.",
            )

    # --- Zuhören -----------------------------------------------------------
    def vokabel_prompt(self) -> str:
        """Kontext für die Transkription: Fachwörter und Namen aus der Einrichtung, dazu der letzte Satz."""
        m = self.meeting
        teile = ["Besprechung auf Deutsch."]
        if self.assistent.aktiv:
            teile.append(f"Der Moderationsassistent heißt {EINST.assistent_name}.")
        if m.titel:
            teile.append(f"Thema: {m.titel}.")
        if m.agenda:
            teile.append("Agenda: " + "; ".join(p.titel + (f" ({p.ziel})" if p.ziel else "") for p in m.agenda) + ".")
        if m.teilnehmende:
            teile.append("Teilnehmende: " + ", ".join(m.teilnehmende) + ".")
        if m.transkript:
            teile.append(m.transkript[-1].text)
        return " ".join(teile)[-800:]

    async def block_verarbeiten(self, wav: bytes, start: float) -> None:
        async with self._sperre:
            if self._client is None:
                self.fehler = "Kein OpenAI-Schlüssel – in den Einstellungen eintragen."
                await self.melden()
                return
            dauer, pegel = transkription.wav_info(wav)
            if pegel < transkription.STILLE_RMS:
                self.meeting.letztes_block_ende = max(self.meeting.letztes_block_ende, start + dauer)
                return
            try:
                spur, saetze, text_sekunden = await transkription.transkribieren(
                    self._client, EINST.transkriptions_modell, EINST.text_modell, wav,
                    self.referenzen, EINST.sprache, self.vokabel_prompt(),
                )
            except Exception as e:  # noqa: BLE001 – Fehler sichtbar machen, nicht abstürzen
                log.warning("Transkription fehlgeschlagen: %s", fehlertext(e))
                self.fehler = f"Transkription fehlgeschlagen: {fehlertext(e)}"
                await self.melden()
                return
            self.fehler = None
            nutzung_loggen({"art": "sprecherspur", "modell": EINST.transkriptions_modell, "sekunden_audio": round(dauer, 1)})
            nutzung_loggen({"art": "text", "modell": EINST.text_modell, "sekunden_audio": round(text_sekunden, 1)})
            self.meeting.letztes_block_ende = max(self.meeting.letztes_block_ende, start + dauer)
            spur_segmente = [Segment(r["sprecher"], "", start + r["start"], start + r["ende"]) for r in spur]
            saetze_segmente = [Segment(r["sprecher"], r["text"], start + r["start"], start + r["ende"]) for r in saetze]
            await self._segmente_verarbeiten(spur_segmente, saetze_segmente)

    # --- Denken ------------------------------------------------------------
    async def _segmente_verarbeiten(self, spur: list[Segment], saetze: list[Segment] | None = None) -> None:
        """spur: wer spricht wann; saetze: Text mit Sprecher (in der Simulation identisch mit spur)."""
        m = self.meeting
        saetze = spur if saetze is None else saetze
        m.segmente_hinzufuegen(spur, saetze)
        self._ueberlappung_pruefen()
        self._monolog_pruefen()
        await self.melden()  # Transkript und regelbasierte Ampeln sofort zeigen, nicht erst nach der KI-Analyse
        if saetze:
            text = "\n".join(f"{s.sprecher}: {s.text}" for s in saetze)
            await self._themen_pruefen(text)
            m.block_texte.append(text)
        await self.melden()

    def _monolog_pruefen(self) -> None:
        """FR-03: Hinweis ohne Namensnennung – beobachtet wird das Phänomen, nicht die Person."""
        if analyse.monolog_live(self.meeting, self.monolog_sekunden)[0]:
            self._monolog_hinweis()

    def _monolog_hinweis(self) -> None:
        # Wartezeit je Person: ein neuer Monolog einer anderen Person wird sofort gemeldet (Benchmark 05.10.)
        rede = analyse.laufende_rede(self.meeting.segmente)
        self.entscheider.vorschlagen(
            self.meeting, "monolog", "hinweis", "gruppe",
            "Längerer Redeanteil – Raum für Rückfragen oder weitere Perspektiven?"
            + regeln.vereinbart(self.meeting.regel_ids, "kurz"),
            schluessel=f"monolog-{rede[0] if rede else ''}",
        )

    def _alle_pruefen(self) -> None:
        """Regel „Alle kommen zu Wort“: nur beobachten, nicht bewerten (Lastenheft)."""
        m = self.meeting
        t = m.jetzt()
        if t < EINST.alle_still_minuten * 60:
            return
        # Angemeldete ohne erkannte Stimme (Personen mit ≥ 10 s Redezeit gelten als erkannt)
        erkannt = sum(1 for d in m.redeanteile().values() if d >= 10)
        still = len(m.teilnehmende) - erkannt
        if still > 0:
            self.entscheider.einmalig(
                m, f"alle-still-{still}", "alle", "hinweis", "gruppe",
                f"{still} von {len(m.teilnehmende)} Teilnehmenden {'hat' if still == 1 else 'haben'} "
                "noch nicht gesprochen." + regeln.vereinbart(m.regel_ids, "alle"))
        # Eine Person mit mehr als dem vereinbarten Anteil der Redezeit im gleitenden Fenster
        fenster = EINST.dominanz_fenster_minuten * 60
        anteile = m.redeanteile(seit=t - fenster)
        gesamt = sum(anteile.values())
        if gesamt >= fenster * 0.3 and max(anteile.values()) > EINST.dominanz_anteil * gesamt:
            self.entscheider.vorschlagen(
                m, "alle", "hinweis", "gruppe",
                f"In den letzten {EINST.dominanz_fenster_minuten:.0f} Minuten hatte eine Person mehr als "
                f"{EINST.dominanz_anteil * 100:.0f} % der Redezeit." + regeln.vereinbart(m.regel_ids, "alle"),
                schluessel="alle-dominanz")

    def sprache_melden(self) -> None:
        """Mikrofon meldet gerade Sprache (vom Browser, etwa jede Sekunde)."""
        self.meeting.sprache_bis = self.meeting.jetzt()

    def _ueberlappung_pruefen(self) -> None:
        """FR-06: technisches Signal, keine Bewertung von Unterbrechungen."""
        m = self.meeting
        seit = m.jetzt() - EINST.ueberlappung_halte_sekunden
        if any(t >= seit for t in m.mischungen) or analyse.ueberlappung_erkannt(
            m.segmente,
            seit,
            EINST.ueberlappung_min_sekunden,
            EINST.zickzack_fenster_sekunden,
            EINST.zickzack_wechsel,
        ):
            zusatz = regeln.vereinbart(m.regel_ids, "ausreden")
            if not zusatz and (eigene := gleichzeitig_regel(m.regeln)):
                zusatz = f" Vereinbart war: „{eigene}“."
            text = "Mehrere Personen sprechen gleichzeitig." + zusatz
            self.entscheider.vorschlagen(m, "ueberlappung", "hinweis", "gruppe", text)

    async def _themen_pruefen(self, text: str, karenz: int | None = None) -> None:
        """FR-05: Abgleich Gespräch ↔ aktueller Agendapunkt per Sprachmodell."""
        m = self.meeting
        if not m.agenda:
            return
        if self._client is None:
            self.entscheider.einmalig(
                m, "info-kein-schluessel", "info", "hinweis", "moderation",
                "Fokus-Erkennung ist aus: kein OpenAI-Schlüssel bzw. Offline-Modus.",
            )
            return
        try:
            ergebnis, nutzung = await themen.zuordnen(
                self._client, EINST.analyse_modell, m, text, EINST.analyse_aufwand, ton="ton" in m.regel_ids
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Themen-Zuordnung fehlgeschlagen: %s", fehlertext(e))
            self.fehler = f"Themen-Zuordnung fehlgeschlagen: {fehlertext(e)}"
            return
        nutzung_loggen({"art": "themen", "modell": EINST.analyse_modell, **nutzung})
        analyse.themen_auswerten(m, self.entscheider, ergebnis, karenz or self.karenz_bloecke)
        self._ton_melden(ergebnis.get("ton", []))

    def punkt_wechseln(self, i: int) -> None:
        """Agendapunkt wechseln (Moderation, Vorschlag, Abspielmodus); Regel 10 prüft den abgeschlossenen Punkt."""
        m = self.meeting
        alt = m.aktiver_punkt
        m.punkt_wechseln(i)
        if alt != m.aktiver_punkt and "ergebnisse" in m.regel_ids:
            hintergrund(self._ergebnis_pruefen(alt))

    async def _ergebnis_pruefen(self, i: int) -> None:
        m = self.meeting
        saetze = m.punkt_transkript(i)
        if self._client is None or not 0 <= i < len(m.agenda) or sum(s.dauer for s in saetze) < 20:
            return  # zu wenig Gesprochenes für eine sinnvolle Prüfung
        p = m.agenda[i]
        text = "\n".join(f"{s.sprecher}: {s.text}" for s in saetze)
        try:
            erg, nutzung = await ergebnisse.pruefen(self._client, EINST.analyse_modell, p.titel, p.ziel, text,
                                                    EINST.analyse_aufwand)
        except Exception as e:  # noqa: BLE001
            log.warning("Ergebnis-Prüfung fehlgeschlagen: %s", fehlertext(e))
            return
        nutzung_loggen({"art": "ergebnisse", "modell": EINST.analyse_modell, **nutzung})
        m.ergebnisse[i] = erg
        self.protokoll.append({"zeit": m.jetzt(), "art": "ergebnis", "punkt": i, **erg})
        for n, text in enumerate(ergebnisse.hinweise(p.titel, erg)):
            self.entscheider.einmalig(m, f"ergebnis-{i}-{n}", "ergebnisse", "hinweis", "gruppe",
                                      text + regeln.vereinbart(m.regel_ids, "ergebnisse"))
        await self.melden()

    def _ton_melden(self, stellen: list[dict]) -> None:
        """Regel 7: nur an die Moderation, ohne Namen und ohne Wertung (Lastenheft: keine Personenbewertung)."""
        m = self.meeting
        for t in stellen:
            # jede Stelle zählt, auch wenn der Hinweis wegen der Wartezeit nicht erneut erscheint
            self.protokoll.append({"zeit": m.jetzt(), "art": "ton", "ton": t["art"], "zitat": t["zitat"]})
            n = sum(1 for e in self.protokoll if e["art"] == "ton" and e["zeit"] >= m.jetzt() - 300)
            zaehler = f" ({n}. Stelle in den letzten 5 Minuten)" if n > 1 else ""
            text = (f"Eine Äußerung könnte als persönlicher Angriff ankommen: „{t['zitat']}“"
                    if t["art"] == "angriff" else f"Kraftausdruck gefallen: „{t['zitat']}“") + zaehler
            self.entscheider.vorschlagen(m, "ton", "hinweis", "moderation",
                                         text + regeln.vereinbart(m.regel_ids, "ton"), schluessel=f"ton-{t['art']}")

    # --- Version 2: Hörstrom ------------------------------------------------
    async def hoeren_starten(self, virtuell: bool = True) -> None:
        """Meeting starten und den Hörstrom öffnen (Live-Mikro oder Abspielmodus)."""
        from .hoeren import Hoerstrom

        self.meeting.starten(virtuell=True)  # Meetinguhr folgt der Audiozeit
        KOSTEN.neues_meeting()
        self.hoerstrom = Hoerstrom(self, mit_text=self._client is not None)
        try:
            await self.hoerstrom.starten()
        except Exception as e:  # noqa: BLE001
            log.warning("Live-Text nicht verbunden: %s", fehlertext(e))
            self.fehler = f"Live-Text nicht verbunden: {fehlertext(e)}"
            self.hoerstrom.live = None
        await self.melden()
        if self.assistent.aktiv and self._client is not None:
            hintergrund(self.assistent.begruessen())

    async def hoeren_zufuehren(self, pcm24k: bytes) -> None:
        if self.hoerstrom:
            await self.hoerstrom.zufuehren(pcm24k)
            if self.hoerstrom.live and self.hoerstrom.live.fehler:
                self.fehler = f"Live-Text: {self.hoerstrom.live.fehler}"

    async def hoeren_beenden(self) -> None:
        if not self.hoerstrom:
            return
        hs, self.hoerstrom = self.hoerstrom, None
        await hs.beenden()
        if self._abschnitt:
            await self._abschnitt_auswerten()
        self.meeting.teiltext = ""
        self.meeting.beenden()
        if self.assistent.gespraech:
            await self.assistent.gespraech.schliessen()
        if "ergebnisse" in self.meeting.regel_ids and self.meeting.agenda:
            hintergrund(self._ergebnis_pruefen(self.meeting.aktiver_punkt))  # Regel 10 auch für den letzten Punkt
        if self.onepager_am_ende:
            self.onepager_starten()  # Abschlussbild (FR-13); entsteht gerade eins, wird es danach nachgeholt
        await self.melden()

    async def teiltext(self, text: str) -> None:
        self.meeting.teiltext = text
        self.assistent.teiltext(text)
        await self.melden()

    async def sprecher_abschnitt(self, abschnitte: list[Segment], ende: float, mischung: list[float]) -> None:
        """Strom 2: Personen einer Äußerung bekannt (kommt vor dem Text); mehrere bei Sprecherwechsel ohne Pause."""
        m = self.meeting
        m.letztes_block_ende = max(m.letztes_block_ende, ende)
        abschnitte = [a for a in abschnitte if not self.assistent.eigene_sprache(a.start, a.ende)]
        if abschnitte:
            m.segmente.extend(abschnitte)
            m.segmente.sort(key=lambda s: s.start)
        if mischung:
            m.mischungen.extend(mischung)
            self.protokoll.append({"zeit": mischung[0], "art": "ueberlappung"})
        self._ueberlappung_pruefen()
        self._monolog_pruefen()
        await self.melden()

    async def satz(self, seg: Segment) -> None:
        """Strom 1: fertiger Satz mit Sprecher. Sammelt Text für die Themen-Zuordnung (Strom 4)."""
        m = self.meeting
        if self.assistent.eigene_sprache(seg.start, seg.ende):
            return  # der Coach hört sich selbst über den Lautsprecher – nicht ins Transkript
        m.transkript.append(seg)
        m.transkript.sort(key=lambda s: s.start)
        m.teiltext = ""
        self._abschnitt.append(seg)
        ziel = analyse.angekuendigter_punkt(seg.text, [p.titel for p in m.agenda], m.aktiver_punkt) if m.laeuft else None
        if ziel is not None:
            # Ausdrückliche Ansage mit Ziel: sofort wechseln, ohne auf die Themen-Zuordnung zu warten
            self.protokoll.append({"zeit": seg.ende, "art": "wechsel", "von": m.aktiver_punkt, "nach": ziel,
                                   "durch": "ansage"})
            self.punkt_wechseln(ziel)
            m.vorschlag = None
            # Was davor gesagt wurde, gehört zum alten Punkt – nicht gegen den neuen prüfen (sonst „zurück zu …“)
            self._abschnitt = [seg]
        elif analyse.ankuendigung(seg.text) or sum(s.dauer for s in self._abschnitt) >= EINST.abschnitt_sekunden:
            hintergrund(self._abschnitt_auswerten())
        await self.melden()
        await self.assistent.satz(seg.text, seg.ende)

    async def _abschnitt_auswerten(self) -> None:
        saetze, self._abschnitt = self._abschnitt, []
        if not saetze:
            return
        text = "\n".join(f"{s.sprecher}: {s.text}" for s in saetze)
        ueberleitung = any(analyse.ankuendigung(s.text) for s in saetze)
        if ueberleitung:
            text += "\n[Im Abschnitt wird ausdrücklich ein Punkt angekündigt – ordne nach dem angekündigten Inhalt.]"
        async with self._themen_sperre:  # Reihenfolge der Abschnitte einhalten
            await self._themen_pruefen(text, karenz=1 if ueberleitung else None)
            m = self.meeting
            m.block_texte.append(text)
            if m.themen_verlauf:
                v = m.themen_verlauf[-1]
                self.protokoll.append({"zeit": saetze[-1].ende, "art": "thema", "zuordnung": v["art"],
                                       "punkt": v["punkt"], "konfidenz": v["konfidenz"],
                                       "begruendung": v["begruendung"], "aktiv": m.aktiver_punkt})
            if self.auto_wechsel and m.vorschlag:
                ziel = m.vorschlag["punkt"]
                self.protokoll.append({"zeit": m.jetzt(), "art": "wechsel", "von": m.aktiver_punkt, "nach": ziel})
                self.punkt_wechseln(ziel)
        await self.melden()

    async def assistent_aktion(self, aktion: dict) -> None:
        """Aktion aus einer Antwort des Sprachassistenten ausführen."""
        m = self.meeting
        if aktion["typ"] == "bild":
            self.assistent._bild_ansage = True
            self.onepager_starten(fokus=None if aktion["fokus"].lower() in ("gesamt", "alles") else aktion["fokus"])
        elif aktion["typ"] == "weiter":
            ziel = aktion["ziel"]
            if ziel.startswith("naechst") or ziel.startswith("nächst"):
                i = m.aktiver_punkt + 1
            else:
                zahl = re.search(r"\d+", ziel)
                i = int(zahl.group()) - 1 if zahl else -1
            if 0 <= i < len(m.agenda):
                self.protokoll.append({"zeit": m.jetzt(), "art": "wechsel", "von": m.aktiver_punkt, "nach": i,
                                       "durch": "assistent"})
                self.punkt_wechseln(i)
        elif aktion["typ"] == "folie":
            self.folie_starten()
        elif aktion["typ"] == "pause":
            self.assistent.zustand = "pausiert"
        elif aktion["typ"] == "recherche" and aktion.get("frage"):
            hintergrund(self.assistent.recherche_vorlesen(aktion["frage"]))
        await self.melden()

    async def einwand_umsetzen(self) -> None:
        """Jemand hat der Begrüßung widersprochen: nichts behalten, nicht weiter zuhören."""
        m = self.meeting
        m.transkript.clear()
        m.segmente.clear()
        m.block_texte.clear()
        m.mischungen.clear()
        m.teiltext = ""
        self._abschnitt = []
        if self.hoerstrom:
            from .stimmen import Personenregister
            self.hoerstrom.stimmen.register = Personenregister(EINST.stimm_schwelle)
        self.protokoll.append({"zeit": m.jetzt(), "art": "einwand"})
        await self.melden()

    def aeusserung_merken(self, ae) -> None:
        """Regel 1 „Ausreden lassen“ (docs/messung_unterbrechung.md): Wechsel ohne Pause, nach denen die
        neue Person das Wort behält. Hinweis an die Gruppe erst ab 3 Stellen in 5 Minuten, ohne Namen."""
        if self.assistent.eigene_sprache(ae.start, ae.ende):
            return
        self.aeusserungen.append(ae)
        m = self.meeting
        if "ausreden" not in m.regel_ids:
            return
        from . import unterbrechung

        jetzt = m.jetzt()
        letzte = [a for a in self.aeusserungen if a.ende >= jetzt - 420]  # 5 min Fenster + Vorlauf
        for u in unterbrechung.unterbrechungen(letzte):
            if u.zeit not in self._unterbrechungen_gemeldet:
                self._unterbrechungen_gemeldet.add(u.zeit)
                self.protokoll.append({"zeit": u.zeit, "art": "unterbrechung", "vorher": round(u.vorher, 1),
                                       "nachher": round(u.nachher, 1)})
        n = sum(1 for t in self._unterbrechungen_gemeldet if t >= jetzt - 300)
        if n >= 3:
            self.entscheider.einmalig(m, f"ausreden-{int(jetzt // 300)}", "ausreden", "hinweis", "gruppe",
                                      unterbrechung.hinweistext(n, 5) + regeln.vereinbart(m.regel_ids, "ausreden"))

    def live_text_kosten(self, sekunden: float) -> None:
        nutzung_loggen({"art": "live-text", "modell": EINST.live_modell, "sekunden_audio": round(sekunden, 1)})

    def _karte_ablegen(self, karte: dict) -> None:
        self.karten.append({"id": len(self.karten) + 1, "zeit": self.meeting.jetzt(), "quellen": [], **karte})

    def antwort_karte(self, frage: str, antwort: str, aktion: dict | None, quellen: list[dict]) -> None:
        """Nestors gesprochene Antwort zusätzlich als Karte: Recherche immer, sonst nur, wenn es etwas zu zeigen
        gibt. Bei Aktionen (Bild, Wechsel, Pause, Folie) zeigt das Dashboard das Ergebnis selbst – keine Karte."""
        if aktion and aktion.get("typ") in ("bild", "weiter", "pause", "folie"):
            return
        hintergrund(self._karte_bauen(frage, antwort, quellen))

    async def _karte_bauen(self, frage: str, antwort: str, quellen: list[dict]) -> None:
        from . import karten
        from .folie import quelle_kurz

        recherche = bool(quellen)
        if recherche and self.letzte_recherche:
            frage = self.letzte_recherche["frage"]
        karte, nutzung = await karten.verdichten(self._client, frage, antwort)
        if nutzung:
            nutzung_loggen({"art": "karte", "modell": EINST.assistent_modell, **nutzung})
        if karte is None and recherche:
            karte = {"titel": frage, "punkte": karten.saetze(antwort)}
        if karte is None:
            return
        self._karte_ablegen({"art": "recherche" if recherche else "antwort", "frage": frage, **karte,
                             "quellen": [quelle_kurz(q) for q in quellen][:5]})
        await self.melden()

    def recherche_merken(self, frage: str, erg: dict) -> None:
        """Grundlage für die Folie – nur Frage, vorlesbarer Text und Quellen."""
        self.letzte_recherche = {"frage": frage, "text": erg["text"], "quellen": erg["quellen"],
                                 "zeit": self.meeting.jetzt()}

    def folie_starten(self) -> bool:
        """Letzte Recherche mit Quellen als Folie zusammenstellen (Zuruf an Nestor oder Knopf)."""
        if self.letzte_recherche is None or self._client is None or self._folie_laeuft:
            return False
        self._folie_laeuft = True
        hintergrund(self._folie_bauen())
        return True

    async def _folie_bauen(self) -> None:
        from . import folie

        await self.melden()
        try:
            self.folie, nutzung = await folie.erstellen(self._client, self.letzte_recherche)
            self.folie_version += 1
            nutzung_loggen({"art": "folie", "modell": EINST.assistent_modell, **nutzung})
            self.protokoll.append({"zeit": self.meeting.jetzt(), "art": "folie", "titel": self.folie["titel"]})
            self._karte_ablegen({"art": "folie", "titel": self.folie["titel"], "frage": self.folie["frage"],
                                 "punkte": self.folie["punkte"], "quellen": self.folie["quellen"], "folie": self.folie})
            self.assistent.ansagen("Die Folie mit den Quellen ist fertig, ihr seht sie im Dashboard.")
        except Exception as e:  # noqa: BLE001
            log.warning("Folie fehlgeschlagen: %s", fehlertext(e))
        finally:
            self._folie_laeuft = False
            await self.melden()

    def onepager_starten(self, fokus: str | None = None) -> bool:
        """Live-Bild neu zeichnen lassen (Knopf, alle N Minuten, Meetingende, Zuruf mit Fokus).

        False, wenn schon eins entsteht – dann wird es danach nachgeholt.
        """
        if not self.meeting.transkript:
            return False
        if self._onepager_laeuft:
            self._onepager_nachholen = True  # nach dem laufenden Bild noch einmal zeichnen
            self._onepager_fokus_wunsch = fokus
            return False
        self._onepager_nachholen = False
        self._onepager_fokus_wunsch = None
        self._onepager_laeuft = True
        self._onepager_letzter_start = self.meeting.jetzt()
        hintergrund(self._onepager_zeichnen(fokus))
        return True

    async def _onepager_zeichnen(self, fokus: str | None = None) -> None:
        from . import onepager

        m = self.meeting
        stand = m.jetzt()
        t0 = time.monotonic()
        await self.melden()
        try:
            # Fortschreibung immer vom letzten Gesamtbild; ein Bild mit Fokus steht für sich
            vorher = None if fokus else self._onepager_voll
            if EINST.bild_anbieter == "openai" and self._client is not None:
                from . import bild_gpt
                erg = await bild_gpt.erzeugen(self._client, m, vorher, fokus)
                self.onepager_png, self.onepager_svg = erg["png"], None
            else:
                erg = await onepager.erzeugen(m, vorher, fokus)
                self.onepager_svg, self.onepager_png = erg["svg"], None
            self.onepager_analyse = erg["analyse"]
            self.onepager_fokus = fokus
            if not fokus:
                self._onepager_voll = {k: erg.get(k) for k in ("analyse", "svg", "png")}
            self.onepager_version += 1
            self.onepager_stand = stand
            self.onepager_fehler = None
            nutzung_loggen({"art": "onepager", "anbieter": "openai" if self.onepager_png else "claude-abo",
                            "fortschreibung": vorher is not None,
                            "sekunden": round(time.monotonic() - t0), "schritte": erg.get("messung")})
            self.protokoll.append({"zeit": stand, "art": "onepager", "version": self.onepager_version, "fokus": fokus})
            if self.assistent._bild_ansage:
                self.assistent._bild_ansage = False
                self.assistent.ansagen("Das Bild ist fertig, ihr seht es jetzt im Dashboard.")
        except Exception as e:  # noqa: BLE001
            log.warning("Live-Bild fehlgeschlagen: %s", fehlertext(e))
            self.onepager_fehler = f"Live-Bild fehlgeschlagen: {str(e)[:160] or fehlertext(e)}"
        finally:
            self._onepager_laeuft = False
            if self._onepager_nachholen:
                self.onepager_starten(self._onepager_fokus_wunsch)
            await self.melden()

    async def abspielen(self, pfad: Path, tempo: float = 1.0, auto_wechsel: bool = True) -> None:
        """Abspielmodus: eine Aufnahme (WAV 24 kHz mono) läuft durch genau dieselbe Pipeline wie das Mikro."""
        import wave

        einrichtung = pfad.with_suffix(".json")
        if einrichtung.is_file():
            self._einrichten(json.loads(einrichtung.read_text(encoding="utf-8")))
        self.auto_wechsel = auto_wechsel
        self.simulation_laeuft = True
        await self.hoeren_starten()
        paket = 2400  # 100 ms
        try:
            with wave.open(str(pfad)) as w:
                if w.getframerate() != 24000 or w.getnchannels() != 1:
                    raise ValueError("Aufnahme muss WAV, 24 kHz, mono sein")
                start = time.monotonic()
                n = 0
                while True:
                    daten = w.readframes(paket)
                    if not daten:
                        break
                    await self.hoeren_zufuehren(daten)
                    n += len(daten) // 2
                    self.takt()
                    soll = start + n / 24000 / tempo
                    await asyncio.sleep(max(0.0, soll - time.monotonic()))
        finally:
            await self.hoeren_beenden()
            self.simulation_laeuft = False
            self.auto_wechsel = False
            await self.melden()

    # --- Simulation: Szenario ohne Audio abspielen -------------------------
    def simulation_starten(self, pfad: Path, tempo: float) -> None:
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
        self._sim_task = hintergrund(self._simulieren(pfad, tempo))

    async def _simulieren(self, pfad: Path, tempo: float) -> None:
        """Spielt ein Szenario in Blöcken ab. Optional mit Agenda-Wechseln ("wechsel": [{zeit, punkt}])."""
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        self._einrichten(daten["setup"])
        self.monolog_sekunden = daten.get("einstellungen", {}).get("monolog_sekunden", EINST.monolog_sekunden)
        segmente = sorted(
            (Segment(s["sprecher"], s["text"], s["start"], s["ende"]) for s in daten["segmente"]),
            key=lambda s: s.start,
        )
        wechsel = sorted(daten.get("wechsel", []), key=lambda w: w["zeit"])
        m = self.meeting
        m.starten(virtuell=True)
        self.simulation_laeuft = True
        block = EINST.block_sekunden
        try:
            t = 0.0
            ende = max(s.ende for s in segmente)
            while t < ende:
                for _ in range(block):
                    m.virtuelle_zeit = (m.virtuelle_zeit or 0) + 1
                    while wechsel and wechsel[0]["zeit"] <= m.virtuelle_zeit:
                        self.punkt_wechseln(wechsel.pop(0)["punkt"] - 1)
                    self.takt()
                    await self.melden()
                    await asyncio.sleep(1 / tempo)
                im_block = [s for s in segmente if t <= s.start < t + block]
                async with self._sperre:
                    m.letztes_block_ende = t + block
                    await self._segmente_verarbeiten(im_block)
                t += block
        finally:
            m.beenden()
            self.simulation_laeuft = False
            await self.melden()
