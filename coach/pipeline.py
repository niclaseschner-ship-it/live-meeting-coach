"""Coach: verbindet Zuhören (Transkription), Denken (Analyse, Entscheider) und Ausgabe."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from . import aktionen, analyse, anbieter, ki_fehler, konfidenz, kosten, regeln, themen
from .artefakte import Artefakte
from .assistent import Assistent
from .config import EINST, WURZEL, schluessel_info
from .entscheider import Entscheider
from .knopfdruck import KNOPF_REGELN, Knopfstand, einverstaendnis
from .zustand import Agendapunkt, Meeting, Segment

VORLAUF_MAX = 40  # so viele schon eingeordnete Sätze bleiben für Fensteranfang und Kontext der Zuordnung
# Namen aus der Vorstellungsrunde (Ticket #27): Ähnlichkeit Vorstellung ↔ Person, Abstand zur zweitbesten Person,
# so viel Sprechzeit braucht eine Person, und so lange wartet ein genannter Name auf seine Stimme
NAME_SCHWELLE = 0.45
NAME_ABSTAND = 0.08
NAME_MIN_SEKUNDEN = 2.0
NAME_WARTEN_SEKUNDEN = 600.0
FENSTER_LUECKE = 10.0  # Sätze, die so lange vor dem ersten neuen Satz endeten, gehören nicht mehr ins Fenster
KONTEXT_SEKUNDEN = 30.0  # so viel Gesprochenes vor dem Fenster geht als Kontext mit (wie früher zwei Abschnitte)

STIMMEN = ("nova", "cedar", "marin", "coral", "sage", "verse", "alloy", "ash", "ballad", "echo", "shimmer")
REALTIME_STIMMEN = tuple(s for s in STIMMEN if s != "nova")

log = logging.getLogger("coach")
NUTZUNG = WURZEL / "logs" / "nutzung.jsonl"
NESTOR_ZEITEN = WURZEL / "logs" / "nestor_zeiten.jsonl"  # ohne Inhalte: nur Auslöser und Sekunden


def _zeit_loggen(eintrag: dict) -> None:
    try:
        NESTOR_ZEITEN.parent.mkdir(parents=True, exist_ok=True)
        with NESTOR_ZEITEN.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"zeit": time.strftime("%Y-%m-%dT%H:%M:%S"), **eintrag}) + "\n")
    except OSError:
        pass
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


def hintergrund_leise(coro) -> None:
    """Aufräumen nebenbei (Client schließen) – auch außerhalb einer laufenden Ereignisschleife."""
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()


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


class WahlGesperrt(RuntimeError):
    """Stufe/Modus lassen sich nur zwischen zwei Meetings wechseln (Ticket #60)."""


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
        # Ticket #60: die bestätigte Anbieterwahl (coach/anbieter.py) – ohne sie kein Client und kein Start. Es gibt
        # keine Vorgabe-Stufe. Der Client entsteht nur aus ihr (client_neu); im Meeting ist sie fest.
        self.wahl: anbieter.Anbieterwahl | None = None
        self._client = None
        self.startet = False  # /api/start läuft (Worker-Meldung): Wahl schon gesperrt, Hörstrom noch nicht offen
        # Premium-Stimme und Gesprächsart (Dashboard), auch über einen Wechsel nach Basis und zurück
        self._premium_vorlieben = anbieter.premium_vorlieben()
        self._sperre = asyncio.Lock()
        self._sim_task: asyncio.Task | None = None
        # Version 2: Ströme
        self.hoerstrom = None
        self.onepager_am_ende = True
        self.archiv_aktiv = False  # nur der Server legt Meetings ab (coach/archiv.py), Testskripte nicht
        self.archiv = None
        self.auto_wechsel = False  # Abspielmodus: Agenda-Vorschläge wie von der Moderation bestätigt übernehmen
        self.protokoll: list[dict] = []  # Ereignisse für den Testbericht (Wechsel, Ampeln, Doku)
        self._abschnitt: list[Segment] = []  # neue Sätze seit der letzten Themen-Zuordnung
        self._vorlauf: list[Segment] = []  # schon eingeordnete Sätze: Anfang des nächsten Fensters und Kontext
        self._fenster_ab = 0.0  # frühere Sätze gehören nicht mehr ins Fenster (Punktwechsel, Rückkehr-Ansage)
        self._rueckkehr_ab: float | None = None  # Beginn der letzten Rückkehr-Ansage („zurück zur Datenbank“)
        self._themen_sperre = asyncio.Lock()
        # Live-Bild (One-Pager, FR-10): Premium zeichnet mit OpenAI (coach/bild_gpt.py), Basis schreibt den Überblick
        self.onepager_svg: str | None = None
        self.onepager_png: bytes | None = None  # Live-Bild von OpenAI (Rasterbild)
        # Recherche als Folie: letztes Rechercheergebnis und die daraus gebaute Folie
        self.letzte_recherche: dict | None = None
        self.folie: dict | None = None
        self.folie_version = 0
        self._folie_laeuft = False
        self.karten: list[dict] = []  # Verlauf (Ticket #27): jede Antwort, Zusammenfassung, Recherche, Bild … als Karte
        self.namen: dict[str, str] = {}  # „Person 2“ -> „Lea“ aus der Vorstellungsrunde
        self.namen_offen: list[dict] = []  # genannte Namen, deren Stimme noch nicht sicher zugeordnet ist
        self.bilder: dict[int, bytes | str] = {}  # Live-Bild je Version (für die Bild-Karten im Verlauf)
        self._taste_hinweis_zeit = -1e9
        self.onepager_analyse: str | None = None
        self.onepager_version = 0
        self.onepager_stand: float | None = None
        self.onepager_fehler: str | None = None
        self._onepager_laeuft = False
        self._onepager_letzter_start: float | None = None
        self._onepager_nachholen = False
        self._onepager_fokus_wunsch: str | None = None
        self.onepager_fokus: str | None = None  # Fokus des angezeigten Bildes (auf Zuruf), sonst Gesamtbild
        # Überblick als Text (coach/ueberblick.py, Ticket #13): in Basis statt des Live-Bilds, in Premium daneben
        self.ueberblick: dict | None = None
        self.ueberblick_version = 0
        self._ueberblick_laeuft = False
        self._ueberblick_nachholen = False  # Meetingende, während noch ein Überblick entsteht: danach noch einmal
        self._protokoll_laeuft = False  # Basis: Protokoll am Meetingende (für protokoll.md im Paket)
        self._onepager_voll: dict | None = None  # letztes Gesamtbild – Grundlage der Fortschreibung
        self.assistent = Assistent(self)
        self.stumm = False  # Mikro stumm (Knopf in der Kopfleiste)
        # Startseite (Ticket #1): "live" oder "knopfdruck". Knopfdruck (Ticket #6): ohne Knopf kein KI-Aufruf –
        # die Weichen stehen an jeder Stelle, die sonst von selbst einen KI-Dienst ruft (Suche: `self.knopfdruck`).
        self.modus = "live"
        self.knopf = Knopfstand()  # Knopf-Analysen (coach/knopfdruck.py)
        self.aeusserungen: list = []  # Regel 1: Äußerungen mit Sprecherabschnitten und Pegel (unterbrechung.py)
        self._unterbrechungen_gemeldet: set[float] = set()
        self.artefakte = Artefakte(self)  # Ticket #26: Aufgaben, Entscheidungen, offene Punkte, Risiken
        # Ticket #64: Kostenbremse – je Meeting einmal gesperrt bzw. geordnet beendet, nicht mehrfach ausgelöst.
        self._kosten_gedeckelt = False
        self._hoechstdauer_beendet = False
        # Cloud-Betrieb: Meeting-Kennung und Kunde für die Telegram-Meldung bei Kostendeckel (Ticket #64), vom
        # Server beim echten /api/start gesetzt (coach/server.py) – der Coach selbst sieht keine Anfrage mehr,
        # sobald der Takt mitten im Meeting läuft.
        self._cloud_meeting: dict | None = None

    @property
    def knopfdruck(self) -> bool:
        return self.modus == "knopfdruck"

    @property
    def karenz_bloecke(self) -> int:
        """FR-05: Karenzzeit in Fenstern der Themen-Zuordnung (mindestens eines). Die Fenster überlappen: k Fenster
        umfassen etwa abschnitt_sekunden + (k − 1) · abschnitt_schritt_sekunden Sprache (20 s Karenz → 1 Fenster)."""
        rest = max(0.0, EINST.fokus_karenz_sekunden - EINST.abschnitt_sekunden)
        return 1 + int(rest // EINST.abschnitt_schritt_sekunden)

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
        self._abschnitt_zuruecksetzen()
        self.onepager_svg = self.onepager_analyse = self.onepager_stand = self.onepager_fehler = None
        self.onepager_png = None
        self.onepager_fokus = self._onepager_voll = None
        self.aeusserungen = []
        self._unterbrechungen_gemeldet = set()
        self._onepager_letzter_start = None
        self.letzte_recherche = self.folie = None
        self.folie_version = 0
        self.ueberblick = None
        self.ueberblick_version = 0
        self.karten = []
        self.namen = {}
        self.namen_offen = []
        self.bilder = {}
        self.knopf = Knopfstand()
        self.artefakte = Artefakte(self)
        self._kosten_gedeckelt = False
        self._hoechstdauer_beendet = False

    @property
    def stufe(self) -> str | None:
        """Stufe der bestätigten Wahl – None, solange keine gewählt ist (keine Vorgabe, Ticket #60)."""
        return self.wahl.stufe if self.wahl else None

    @property
    def bild_als_text(self) -> bool:
        """Basis (und ohne Wahl): kein Bildmodell, stattdessen der Überblick als Text."""
        return self.wahl is None or self.wahl.bild_anbieter == "text"

    @property
    def wahl_gesperrt(self) -> bool:
        """Im Meeting – vom Start bis die Ablage fertig ist – bleibt die Wahl fest (Ticket #60)."""
        return (self.startet or self.hoerstrom is not None
                or (self.archiv is not None and not self.archiv.fertig))

    @property
    def ki_gesperrt(self) -> bool:
        """Ticket #64: Meeting-Kostendeckel erreicht – keine neue KI-Verbindung mehr, auch keine, die ohne
        `self._client` läuft (Realtime-Gespräch/-Begrüßung, coach/gespraech.py, coach/begruessung.py; beide
        prüfen das vor jedem `anbieter.ws_verbinden`). Laufende Live-Text- und Gesprächsverbindungen schließt
        `_kosten_pruefen` beim Erreichen selbst – diese Eigenschaft verweigert nur neue."""
        return self._kosten_gedeckelt

    def stufe_setzen(self, stufe: str, nur_knopfdruck: bool = False) -> None:
        """Nestor Basis (nur Mistral) oder Premium (OpenAI) für das nächste Meeting. „Nur auf Knopfdruck“ ist ein
        Schalter in Basis (Ticket #13: der frühere Modus „Auf Knopfdruck“), in Premium gibt es ihn nicht.
        Baut eine neue, unveränderliche Anbieterwahl und den Client dazu; im Meeting `WahlGesperrt`."""
        if self.wahl_gesperrt:
            raise WahlGesperrt("Während des Meetings nicht wechselbar.")
        modus = "knopfdruck" if stufe == "basis" and nur_knopfdruck else "live"
        self.wahl = anbieter.wahl_fuer(stufe, modus, **(self._premium_vorlieben if stufe == "premium" else {}))
        self.modus = modus
        self.client_neu()

    def client_neu(self) -> None:
        """KI-Client der Wahl, gebaut von der Fabrik (coach/anbieter.py): Premium → OpenAI (Schlüssel aus dem
        Dashboard oder der Umgebung), Basis → Mistral. Ohne Wahl, ohne Schlüssel oder mit LMC_OFFLINE=1: keiner."""
        if self.hoerstrom is not None:
            raise WahlGesperrt("Während des Meetings bleibt der Client fest.")
        alt, self._client = self._client, None
        if alt is not None and hasattr(alt, "schliessen"):
            hintergrund_leise(alt.schliessen())
        self._client = anbieter.client_fuer(self.wahl, self.anbieter_verstoss)

    def anbieter_verstoss(self, ziel: str, wahl) -> None:
        """Hostwache (coach/anbieter.py) hat eine Verbindung außerhalb der Stufe gestoppt: sichtbar machen."""
        self.fehler = (f"Anbieter-Sperre: Verbindung zu {ziel} ist in Nestor {wahl.stufe.capitalize()} nicht erlaubt "
                       "– abgebrochen, kein Wechsel des Anbieters.")
        if self.archiv is not None and not self.archiv.fertig:
            self.archiv.ereignis("anbieter_verstoss", ziel=ziel, stufe=wahl.stufe)
        try:
            asyncio.get_running_loop().create_task(self.melden())
        except RuntimeError:
            pass

    def kosten_stand(self) -> dict:
        m = self.meeting
        # getattr statt `self.hoerstrom.live`: Ticket #64 ruft das jetzt aus Coach.takt heraus (_kosten_pruefen),
        # wo einzelne Tests den Hörstrom nur als knappe Attrappe setzen (vgl. tests/test_basis.py).
        live = getattr(self.hoerstrom, "live", None)
        return KOSTEN.stand(live_sekunden=live.gesendete_sekunden if live and live._ws is not None else 0.0,
                            live_modell=self.wahl.live_modell if self.wahl else "",
                            meeting_sekunden=m.jetzt() if m.gestartet_um is not None else 0.0,
                            geplant_minuten=sum(p.minuten for p in m.agenda))

    def phase(self) -> str:
        """Ticket #66: die eine Phase, nach der Desktop und Handy schalten (static/phase.js) – abgeleitet, kein
        eigener Zustand. live = Meeting oder Wiedergabe läuft; abschluss = ein Meeting wurde gestartet und ist vorbei
        (bis /api/einrichten ein neues anlegt); sonst vorbereitung."""
        if self.meeting.laeuft or self.simulation_laeuft:
            return "live"
        return "abschluss" if self.meeting.gestartet_um is not None else "vorbereitung"

    def schnappschuss(self) -> dict:
        daten = self.meeting.schnappschuss(EINST.zeit_rot_prozent)
        ampeln = analyse.prozess_ampeln(
            self.meeting,
            monolog_sekunden=self.monolog_sekunden,
            karenz_bloecke=self.karenz_bloecke,
            zeit_rot_prozent=EINST.zeit_rot_prozent,
            ueberlappung_min=EINST.ueberlappung_min_sekunden,
            ueberlappung_halte=EINST.ueberlappung_halte_sekunden,
            themen_aktiv=self._client is not None and not self.knopfdruck,
            zickzack_fenster=EINST.zickzack_fenster_sekunden,
            zickzack_wechsel=EINST.zickzack_wechsel,
        )
        daten.update(
            {
                "phase": self.phase(),
                "regel_status": self.regel_status(ampeln),
                "dynamik": self.dynamik(),
                "stumm": self.stumm,
                "modus": self.modus,
                "stufe": self.stufe,
                "einstellungen": self.einstellungen(),
                "referenzen": list(self.referenzen),
                "fehler": self.fehler,
                "schluessel_vorhanden": self._client is not None,
                "schluessel": schluessel_info(),
                "kosten": self.kosten_stand(),
                "aktionshilfe": aktionen.katalog(self, self.wahl),
                "simulation": self.simulation_laeuft,
                "block_sekunden": EINST.block_sekunden,
                "ampeln": ampeln,
                "hoeren": self.hoerstrom is not None,
                "onepager_version": self.onepager_version,
                "onepager_stand": self.onepager_stand,
                "onepager_laeuft": self._onepager_laeuft,
                "archiv": self.archiv.stand() if self.archiv else None,
                "onepager_fehler": self.onepager_fehler,
                "onepager_minuten": EINST.onepager_minuten,
                "onepager_fokus": self.onepager_fokus,
                "onepager_format": "png" if self.onepager_png else "svg",
                "ueberblick": self.ueberblick,
                "ueberblick_version": self.ueberblick_version,
                "ueberblick_laeuft": self._ueberblick_laeuft,
                "folie": self.folie,
                "folie_version": self.folie_version,
                "folie_laeuft": self._folie_laeuft,
                "recherche_da": self.letzte_recherche is not None,
                "karten": self.karten[-50:],
                "assistent": self.assistent.schnappschuss(),
                "artefakte": self.artefakte.schnappschuss(),
                # Einstufung verlässlich/experimentell für Regeln und Signale, eine Quelle (Lastenheft 4.3,
                # Ticket „Konfidenz“) statt verstreuter Badges.
                "signale": konfidenz.katalog(),
                # Knöpfe gibt es in beiden Stufen (Ticket #13); „offen“ (nicht Transkribiertes) nur bei Knopfdruck
                "knopf": self.knopf.schnappschuss(self.hoerstrom if self.knopfdruck else None),
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
                detail = (f"{analyse.mmss(dauer)} am Stück · Hinweis ab {analyse.mmss(self.monolog_sekunden)}" if dauer > 0
                          else f"Gespräch im Wechsel · Hinweis ab {analyse.mmss(self.monolog_sekunden)}")
            elif rid == "ausreden":
                n = sum(1 for t in self._unterbrechungen_gemeldet if t >= jetzt - 300)
                ov = len(analyse.ueberlappungs_vorfaelle(m, jetzt - 300))
                ueber = a.get("Sprecherüberlappung", {})
                farbe = "rot" if n >= 3 else "gelb" if n or ov >= 3 or ueber.get("farbe") == "gelb" else "gruen"
                teile = ([f"{n}× ins Wort"] if n else []) + ([f"{ov}× gleichzeitig"] if ov else [])
                detail = (", ".join(teile) + " (5 min)") if teile else "normale Sprecherwechsel"
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
                # Ticket #26: gelb, sobald nach einer Lücke gefragt wurde und sie noch offen ist (nicht abgelehnt)
                offen = [a for a in self.artefakte.liste if a.nachgefragt and not a.abgelehnt and a.luecken()]
                farbe = "gelb" if offen else "gruen"
                n = len(self.artefakte.liste)
                detail = (f"{len(offen)} Lücke{'n' if len(offen) > 1 else ''} offen" if offen
                          else f"{n} festgehalten" if n else "noch nichts festgehalten")
            if self.knopfdruck and rid in KNOPF_REGELN:
                # Diese Regeln brauchen den Text – im Modus Knopfdruck nur der Stand des letzten Knopfs
                k = self.knopf.regeln.get(rid)
                farbe, detail = (k["farbe"], k["detail"]) if k else ("grau", "auf Knopfdruck")
            if not m.laeuft and not m.segmente:
                farbe = "grau"
            aus.append({"id": rid, "titel": r.titel.split(" – ")[0], "farbe": farbe, "detail": detail,
                        "stufe": r.stufe, "kurzsatz": r.kurzsatz if r.stufe == "experimentell" else None})
        # Verlässliche Regeln zuerst (Lastenheft 4.3), experimentelle ans Ende – stabile Sortierung behält
        # sonst die Katalog-Reihenfolge.
        aus.sort(key=lambda d: d["stufe"] == "experimentell")
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
            "artefakte": [a.kurz() for a in self.artefakte.liste[-25:]],
            "letzte_hinweise": [h.text for h in m.hinweise[-3:]],
            "folie": ("wird gerade erstellt" if self._folie_laeuft else
                      f"fertig: {self.folie['titel']}" if self.folie else "keine"),
            "letzte_recherche": self.letzte_recherche["frage"] if self.letzte_recherche else None,
        }

    def dynamik(self) -> dict:
        """Wie oft gleichzeitig gesprochen und ins Wort gefallen wurde (gesamt und in 10 min) und das Gesprächsklima."""
        m = self.meeting
        jetzt = m.jetzt()
        ton = [e["zeit"] for e in self.protokoll if e["art"] == "ton"]
        unterbr = sorted(self._unterbrechungen_gemeldet)
        ov = analyse.ueberlappungs_vorfaelle(m)
        return {"ueberlappungen": len(ov), "ueberlappungen_10min": sum(1 for u in ov if u[0] >= jetzt - 600),
                "unterbrechungen": len(unterbr), "unterbrechungen_10min": sum(1 for t in unterbr if t >= jetzt - 600),
                "klima": analyse.klima(m, self.aeusserungen, unterbr, ton) if m.laeuft or m.segmente else None}

    def einstellungen(self) -> dict:
        w = self.wahl
        return {"assistent": self.assistent.aktiv,
                "modus": w.assistent_modus if w else self._premium_vorlieben["assistent_modus"],
                "stimme": w.stimme if w else self._premium_vorlieben["stimme"],
                "stufe": self.stufe,
                "aufnahme": EINST.aufnahme_speichern,
                "bild_anbieter": w.bild_anbieter if w else None, "live_art": EINST.live_art,
                "bild_minuten": EINST.onepager_minuten, "monolog_sekunden": self.monolog_sekunden}

    def einstellen(self, daten: dict) -> None:
        """Einstellungen zur Laufzeit (Dashboard-Kopfleiste). Nur bekannte Felder, geprüfte Werte."""
        # #58: Paarung prüfen, bevor auch nur eine Einstellung verändert wird. Nova ist TTS, keine Realtime-Stimme.
        # Ohne Wahl gelten die Premium-Vorlieben (sie gehen in die nächste Premium-Wahl ein).
        basis = self.wahl is not None and self.wahl.basis
        if not basis:
            modus = daten.get("modus", self._premium_vorlieben["assistent_modus"])
            stimme = daten.get("stimme", self._premium_vorlieben["stimme"])
            if modus not in ("gespraech", "text") or stimme not in STIMMEN:
                raise ValueError("Unbekannte Gesprächsart oder Stimme.")
            if modus == "gespraech" and stimme not in REALTIME_STIMMEN:
                raise ValueError("Nova ist nur für Kurzantworten verfügbar. Wähle eine Gesprächsstimme oder die Gesprächsart Kurzantwort.")
            if daten.get("bild_anbieter", "openai") != "openai":
                raise ValueError("Premium verwendet ausschließlich OpenAI.")
        if "assistent" in daten:
            self.assistent.aktiv = bool(daten["assistent"])
        if basis:
            # Basis: Gesprächsart, Stimme und Bildweg stehen fest (nur Mistral, Custom-Voice, Überblick als Text)
            daten = {k: v for k, v in daten.items() if k not in ("modus", "stimme", "bild_anbieter")}
        else:
            # Premium: Stimme und Gesprächsart gelten sofort – eine neue Wahl desselben Anbieters (gleiche Ziele)
            neu = {k: daten[w] for w, k in (("modus", "assistent_modus"), ("stimme", "stimme")) if w in daten}
            if neu:
                self._premium_vorlieben.update(neu)
                if self.wahl is not None:
                    self.wahl = self.wahl.mit(**neu)
        if daten.get("live_art") in ("schnell", "sparsam"):
            object.__setattr__(EINST, "live_art", daten["live_art"])  # gilt ab dem nächsten Meetingstart
        if "bild_minuten" in daten:
            object.__setattr__(EINST, "onepager_minuten", max(0.0, min(60.0, float(daten["bild_minuten"]))))
        if "aufnahme" in daten:
            object.__setattr__(EINST, "aufnahme_speichern", bool(daten["aufnahme"]))  # ab dem nächsten Start
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
        mess = self.assistent.messung
        if mess and nachricht.get("typ") == "stimme":  # erster Ton nach Knopf oder Ansprache
            self.assistent.messung = None
            _zeit_loggen({"ausloeser": mess["ausloeser"], "modus": mess["modus"], "verzug_text": mess["verzug_text"],
                          "bis_ton": round(time.monotonic() - mess["t0"], 2)})
        for b in list(self.direkt):
            await b(nachricht)

    # --- Takt: Countdown und Zeitwarnung (FR-04) ---------------------------
    def takt(self) -> None:
        m = self.meeting
        if not m.laeuft:
            return
        self._kosten_pruefen()
        self._hoechstdauer_pruefen()
        # Monolog live: der Hinweis kommt, sobald die hochgezählte Rede die Schwelle erreicht
        if analyse.monolog_live(m, self.monolog_sekunden)[0]:
            self._monolog_hinweis()
        # Ticket #27: kein Live-Bild und kein Überblick im Takt mehr – nur auf Anfrage und am Ende. Stattdessen die
        # stille Zusammenfassung je Abschnitt (Punktwechsel, 20 min) aus coach/artefakte.py.
        self.assistent.takt()
        self.artefakte.takt()  # Abschnitt nach 20 min, Fünf-Minuten-Band
        self._namen_zuordnen()
        self._abschnitt_takt()
        if "alle" in m.regel_ids:
            self._alle_pruefen()
        if not 0 <= m.aktiver_punkt < len(m.agenda):
            return
        if "zeit" not in m.regel_ids:
            return  # Ticket #27: nicht gewählte Regeln sind unsichtbar – kein Zeit-Hinweis (die Uhr links bleibt)
        i = m.aktiver_punkt
        p = m.agenda[i]
        farbe = p.ampel(m.genutzt(i), EINST.zeit_rot_prozent)
        if farbe in ("gelb", "rot"):
            self.entscheider.einmalig(
                m, f"zeit-{i}-gelb", "zeit", "hinweis", "gruppe",
                f"„{p.titel}“: Zeitfenster erreicht. Weiterarbeiten oder zum nächsten Punkt wechseln?"
                + regeln.vereinbart(m.regel_ids, "zeit"), punkt=i,
            )
        if farbe == "rot":
            ueber = m.genutzt(i) - p.minuten * 60
            self.entscheider.einmalig(
                m, f"zeit-{i}-rot", "zeit", "warnung", "gruppe",
                f"„{p.titel}“ ist {analyse.mmss(ueber)} Min. über dem Zeitfenster.", punkt=i,
            )

    # --- Kostenbremse (Ticket #64) ------------------------------------------
    def _kosten_pruefen(self) -> None:
        """Meeting-Kostendeckel (coach/kosten.py) erreicht? Zentrale Sperre über den Client: alle Aufrufstellen
        prüfen schon `self._client is None` und fallen dort auf ihre „kein Schlüssel“-Behandlung zurück – lokale
        Signale (Zeit, Monolog, Überlappung, Sprechererkennung) laufen unverändert weiter."""
        if self._kosten_gedeckelt or self.wahl is None or self._client is None:
            return
        deckel = kosten.DECKEL_USD.get(self.wahl.stufe)
        if deckel is None or self.kosten_stand()["meeting"] < deckel:
            return
        self._kosten_gedeckelt = True
        alt, self._client = self._client, None
        if hasattr(alt, "schliessen"):
            hintergrund_leise(alt.schliessen())
        # Die teuersten Ströme laufen über eigene WebSockets, nicht über self._client (Live-Text:
        # coach/livetext.py; Realtime-Gespräch/-Begrüßung: coach/gespraech.py, coach/begruessung.py) – sie
        # bleiben offen, bis sie selbst geschlossen werden. Laufende hier geordnet zu, neue verweigert
        # `ki_gesperrt` oben zentral in Gespraech.starten (Begruessung erbt davon).
        if self.hoerstrom is not None and self.hoerstrom.live is not None:
            hintergrund_leise(self.hoerstrom.live.schliessen())
        if self.assistent.gespraech is not None:
            hintergrund_leise(self.assistent.gespraech.schliessen())
        self.entscheider.einmalig(
            self.meeting, "kosten-deckel", "kosten", "warnung", "gruppe",
            f"Kostendeckel für dieses Meeting erreicht ({deckel:.0f} $) – die KI-Auswertung ist für den Rest "
            "des Meetings aus, Nestor hört weiter zu und zeigt die technischen Hinweise.",
        )
        if self.archiv is not None and not self.archiv.fertig:
            self.archiv.ereignis("kosten_deckel", stufe=self.wahl.stufe, deckel_usd=deckel)
        hintergrund(self._kosten_deckel_melden(deckel))

    async def _kosten_deckel_melden(self, deckel: float) -> None:
        """Telegram über den vorhandenen Worker-Rückkanal (api_abschluss.worker_melden), wie schon bei
        Meeting-Start/-Ende (coach/server.py, coach/api_abschluss.py). Lokal (kein Cloud-Meeting) ein No-Op."""
        if not self._cloud_meeting or self.wahl is None:
            return
        from .api_abschluss import worker_melden

        await asyncio.to_thread(
            worker_melden, "/intern/kosten-deckel", {**self._cloud_meeting, "stufe": self.wahl.stufe, "usd": deckel},
        )

    def _hoechstdauer_pruefen(self) -> None:
        """Höchstdauer je Meeting (coach/kosten.py): Warnung im Band HOECHSTDAUER_WARNUNG_SEKUNDEN vorher, bei
        Erreichen ein geordnetes Ende wie ein normales „Fertig“ (Ablage und Datenspende bleiben möglich)."""
        if self._hoechstdauer_beendet:
            return
        rest = kosten.HOECHSTDAUER_SEKUNDEN - self.meeting.jetzt()
        if rest <= 0:
            self._hoechstdauer_beendet = True
            self.entscheider.einmalig(
                self.meeting, "hoechstdauer-ende", "hoechstdauer", "warnung", "gruppe",
                "Höchstdauer von 3 Std. erreicht – Nestor beendet das Meeting geordnet.",
            )
            hintergrund(self.hoeren_beenden())
            return
        if rest <= kosten.HOECHSTDAUER_WARNUNG_SEKUNDEN:
            self.entscheider.einmalig(
                self.meeting, "hoechstdauer-warnung", "hoechstdauer", "hinweis", "gruppe",
                "Noch 10 Min. bis zur Höchstdauer von 3 Std. – Nestor beendet das Meeting dann von selbst.",
            )

    # --- Zuhören -----------------------------------------------------------
    def vokabel_prompt(self) -> str:
        """Kontext für die Transkription: Fachwörter und Namen aus der Einrichtung, dazu der letzte Satz."""
        m = self.meeting
        # Der Prompt muss in der Sprache des Meetings sein – sonst übersetzt die Transkription (AMI-Test 05.10.)
        deutsch = EINST.sprache == "de"
        teile = ["Besprechung auf Deutsch." if deutsch else "Meeting in English."]
        if self.assistent.aktiv:
            teile.append(f"Der Moderationsassistent heißt {EINST.assistent_name}." if deutsch
                         else f"The meeting assistant is called {EINST.assistent_name}.")
        if m.titel:
            teile.append((f"Thema: {m.titel}." if deutsch else f"Topic: {m.titel}."))
        if m.agenda:
            teile.append("Agenda: " + "; ".join(p.titel + (f" ({p.ziel})" if p.ziel else "") for p in m.agenda) + ".")
        if m.teilnehmende:
            teile.append(("Teilnehmende: " if deutsch else "Participants: ") + ", ".join(m.teilnehmende) + ".")
        if m.transkript:
            teile.append(m.transkript[-1].text)
        return " ".join(teile)[-800:]

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
        if "kurz" not in self.meeting.regel_ids:
            return  # Ticket #27: nicht gewählte Regeln sind unsichtbar
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
        jetzt = self.meeting.jetzt()
        if jetzt - self.meeting.sprache_bis > analyse.SPRACHE_AKTUELL_SEKUNDEN:
            self.meeting.sprache_seit = jetzt
        self.meeting.sprache_bis = jetzt

    def _ueberlappung_pruefen(self) -> None:
        """FR-06: technisches Signal, keine Bewertung von Unterbrechungen. Hinweis nur mit der Regel „Ausreden lassen“
        (Ticket #27: nicht gewählte Regeln sind unsichtbar); gezählt wird trotzdem (Gesprächsdynamik)."""
        m = self.meeting
        if "ausreden" not in m.regel_ids and not gleichzeitig_regel(m.regeln):
            return
        if EINST.segmentierung:
            # Mit Segmentierung: ein Hinweis an die Gruppe erst bei wiederholtem Durcheinander – mindestens zwei
            # Vorfälle in einer Minute. Einzelne kurze Überlappungen sind normal (synthetische Kontrollrunde 06.10.:
            # ein Hinweis bei null gezählten Vorfällen) und erscheinen nur im Zähler.
            if len(analyse.ueberlappungs_vorfaelle(m, m.jetzt() - 60)) >= 2:
                zusatz = regeln.vereinbart(m.regel_ids, "ausreden")
                self.entscheider.vorschlagen(m, "ueberlappung", "hinweis", "gruppe",
                                             "Mehrere Personen sprechen gleichzeitig." + zusatz)
            return
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

    async def _themen_pruefen(self, text: str, karenz: int | None = None, kontext: list[str] | None = None,
                              fenster_ab: float | None = None) -> dict | None:
        """FR-05: Abgleich Gespräch ↔ aktueller Agendapunkt per Sprachmodell. `fenster_ab`: Beginn des eingeordneten
        Fensters – fiel seitdem eine Rückkehr-Ansage, kommt kein Fokus-Hinweis mehr (Ticket #24)."""
        m = self.meeting
        if not m.agenda or self.knopfdruck:  # Knopfdruck: kein Themen-Abgleich und keine Ton-Prüfung im Lauf
            return None
        if self._client is None:
            self.entscheider.einmalig(
                m, "info-kein-schluessel", "info", "hinweis", "moderation",
                "Fokus-Erkennung ist aus: kein KI-Schlüssel bzw. Offline-Modus.",
            )
            return None
        punkt_vorher = m.aktiver_punkt
        try:
            modell = self.wahl.zuordnung_modell
            ergebnis, nutzung = await themen.zuordnen(
                self._client, modell, m, text, self.wahl.analyse_aufwand, ton="ton" in m.regel_ids, kontext=kontext
            )
        except Exception as e:  # noqa: BLE001
            ki_fehler.melden(self, "themen", e, "nächster Versuch mit dem nächsten Abschnitt.")  # Ticket #72
            return None
        ki_fehler.erholt(self, "themen")
        nutzung_loggen({"art": "themen", "modell": modell, **nutzung})
        # Erst jetzt prüfen: Die Rückkehr-Ansage kann auch während der Zuordnung gefallen sein
        zurueck = fenster_ab is not None and self._rueckkehr_ab is not None and self._rueckkehr_ab >= fenster_ab
        if m.aktiver_punkt == punkt_vorher:
            analyse.themen_auswerten(m, self.entscheider, ergebnis, karenz or self.karenz_bloecke, zurueck)
        # sonst: während der Zuordnung wurde der Punkt gewechselt – das Fenster bezog sich auf den alten Punkt
        # (Cloudlauf 08.10.: Band nannte Punkt 3, während nach der Rückwärts-Ansage Punkt 1 aktiv war)
        self._ton_melden(ergebnis.get("ton", []))
        return ergebnis

    def punkt_wechseln(self, i: int) -> None:
        """Agendapunkt wechseln (Moderation, Vorschlag, Abspielmodus); Regel 10 prüft den abgeschlossenen Punkt."""
        m = self.meeting
        alt = m.aktiver_punkt
        m.punkt_wechseln(i)
        if alt != m.aktiver_punkt:  # bisher Gesagtes gehört zum alten Punkt: nicht mehr ins Fenster der Zuordnung
            self._fenster_ab = max(self._fenster_ab, m.jetzt())
            for h in m.hinweise:
                if h.art == "fokus":
                    h.dauer = min(h.dauer, max(0, m.jetzt() - h.zeit))
        if alt != m.aktiver_punkt and not self.knopfdruck and self._client is not None and m.laeuft:
            # Ticket #27: still die Zusammenfassung des abgeschlossenen Punkts als Karte (Artefakte nur aus diesem
            # Abschnitt); mit der Regel „Ergebnisse festhalten“ Lücken markiert und ein Band-Hinweis
            hintergrund(self.artefakte.abschnitt_abschliessen(alt, m.jetzt(), "punkt"))

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
        if self.archiv_aktiv:
            from .archiv import Archiv

            if self.archiv is not None and self.archiv.beobachten in self.beobachter:
                self.beobachter.remove(self.archiv.beobachten)
            try:  # Audio nur live – eine abgespielte Aufnahme liegt schon als Datei vor
                self.archiv = Archiv(self, audio=EINST.aufnahme_speichern and not self.simulation_laeuft)
                self.beobachter.append(self.archiv.beobachten)
            except OSError as e:
                log.warning("Meeting-Ablage nicht möglich: %s", e)
                self.archiv = None
        KOSTEN.neues_meeting()
        if self.wahl is not None and self.wahl.basis and self._client is not None:
            # Basis: Kontextwörter der Batch-Transkription (Voxtral)
            m = self.meeting
            self._client.stichwoerter = ([EINST.assistent_name] if self.assistent.aktiv else []) + [
                p.titel for p in m.agenda] + m.teilnehmende
        self.hoerstrom = Hoerstrom(self, mit_text=self._client is not None)
        try:
            await self.hoerstrom.starten()
        except Exception as e:  # noqa: BLE001
            log.warning("Live-Text nicht verbunden: %s", fehlertext(e))
            self.fehler = f"Live-Text nicht verbunden: {fehlertext(e)}"
            self.hoerstrom.live = None
        if self.knopfdruck:
            # Statt der gesprochenen Begrüßung (ginge an die Sprachausgabe): Einverständnis als Hinweis im Dashboard
            self.entscheider.einmalig(self.meeting, "knopf-einverstaendnis", "info", "hinweis", "gruppe",
                                      einverstaendnis(self.meeting))
        await self.melden()
        if self.assistent.aktiv and self._client is not None and not self.knopfdruck:
            hintergrund(self.assistent.begruessen())

    async def hoeren_zufuehren(self, pcm24k: bytes) -> None:
        if self.hoerstrom and self.archiv and not self.archiv.fertig:
            stumm = self.stumm or self.assistent.pausiert  # was niemand hören soll, wird auch nicht aufgenommen
            self.archiv.audio(bytes(len(pcm24k)) if stumm else pcm24k)
        if self.hoerstrom:
            await self.hoerstrom.zufuehren(pcm24k)
            if self.hoerstrom.live and self.hoerstrom.live.fehler:
                self.fehler = f"Live-Text: {self.hoerstrom.live.fehler}"

    async def hoeren_beenden(self) -> None:
        if not self.hoerstrom:
            return
        hs, self.hoerstrom = self.hoerstrom, None
        await hs.beenden()
        # Kein letzter Themen-Abgleich mehr: nach dem Ende erzeugte er nur Hinweise, die niemand mehr sieht
        # (synthetische Kontrollrunde 06.10.: zwei Fokus-Hinweise in der letzten Sekunde)
        self._abschnitt_zuruecksetzen()
        self.meeting.teiltext = ""
        self.meeting.beenden()
        if self.assistent.gespraech:
            await self.assistent.gespraech.schliessen()
        # Knopfdruck: auch am Ende nichts ohne Knopf – Ergebnisse und Bild gibt es, wenn vorher gedrückt wurde
        basis = self.bild_als_text
        if basis and not self.knopfdruck and self._client is not None:
            # Basis hat kein Abschlussbild, dessen Analyse in Premium protokoll.md ist (coach/archiv.py) – deshalb
            # am Ende das Protokoll wie beim Knopf: die letzten Sätze auf Artefakte prüfen (Ticket #26), daraus
            # protokoll.md (Ticket #15).
            self._protokoll_laeuft = True
            hintergrund(self._protokoll_am_ende())
        elif not self.knopfdruck and self._client is not None:
            hintergrund(self.artefakte.erkennen())  # Ticket #26: die letzten Sätze noch auswerten, ohne Nachfrage
        if self.onepager_am_ende and not self.knopfdruck:
            if basis:  # Abschluss-Überblick; entsteht gerade einer (Zuruf, Takt), wird er danach nachgeholt
                frisch = (self.ueberblick is not None and not self._ueberblick_laeuft
                          and self.meeting.jetzt() - self.ueberblick["stand"] < 30)
                if not frisch:  # ein Überblick aus den letzten 30 s ist schon der Endstand
                    self.ueberblick_starten(nachholen=True)
            else:
                self.onepager_starten()  # Abschlussbild (FR-13); entsteht gerade eins, wird es danach nachgeholt
        if self.archiv and not self.archiv.fertig:
            self.archiv.ereignis("stopp")
            self.archiv.schreiben(endgueltig=False)
            hintergrund(self._archiv_abschliessen(self.archiv))
        await self.melden()

    async def _archiv_abschliessen(self, archiv) -> None:
        """Ablegen, sobald Abschlussbild, Folie und Ergebnisprüfung durch sind (höchstens ~4 min warten)."""
        for _ in range(240):
            if not (self._onepager_laeuft or self._folie_laeuft or self._ueberblick_laeuft or self._protokoll_laeuft
                    or self.artefakte.laeuft):
                break
            await asyncio.sleep(1)
        await asyncio.sleep(8)  # Ergebnisprüfung des letzten Punkts
        try:
            archiv.schreiben(endgueltig=True)
        except OSError as e:
            log.warning("Meeting-Ablage fehlgeschlagen: %s", e)
            archiv.fertig = True
        await self.melden()

    async def _protokoll_am_ende(self) -> None:
        from .knopfdruck import _protokoll

        try:
            async with self.knopf.sperre:  # nicht gleichzeitig mit einem gerade gedrückten Protokoll-Knopf
                await _protokoll(self, "", am_ende=True)
        except Exception as e:  # noqa: BLE001
            ki_fehler.melden(self, "protokoll", e)  # Ticket #72: im Technikbericht statt nur im Log
        finally:
            self._protokoll_laeuft = False
            await self.melden()

    async def teiltext(self, text: str) -> None:
        self.meeting.teiltext = text
        self.assistent.teiltext(text)
        await self.melden()

    async def sprecher_abschnitt(self, abschnitte: list[Segment], ende: float, mischung: list[float],
                                 ueber: list[tuple[float, float]] | None = None) -> None:
        """Strom 2: Personen einer Äußerung bekannt (kommt vor dem Text); mehrere bei Sprecherwechsel ohne Pause."""
        m = self.meeting
        m.letztes_block_ende = max(m.letztes_block_ende, ende)
        abschnitte = [a for a in abschnitte if not self.assistent.eigene_sprache(a.start, a.ende)]
        for a in abschnitte:
            a.sprecher = self.namen.get(a.sprecher, a.sprecher)
        if abschnitte:
            m.segmente.extend(abschnitte)
            m.segmente.sort(key=lambda s: s.start)
        # Nestors Lautsprecher kann im Raummikro als zweite Stimme erscheinen.
        # Nur den betroffenen Zeitbereich herausnehmen, nicht den ganzen Block.
        mischung = [t for t in mischung if not self.assistent.spricht_um(t)]
        echte_ueber = []
        for a, b in ueber or []:
            reste = [(a, b)]
            for x, y in self.assistent.sprechzeiten:
                reste = [(u, v) for l, r in reste for u, v in ((l, min(r, x)), (max(l, y), r)) if v > u]
            echte_ueber.extend(reste)
        if mischung:
            m.mischungen.extend(mischung)
            self.protokoll.append({"zeit": mischung[0], "art": "ueberlappung"})
        if ueber is not None:
            m.ueberlappungen_gezaehlt = True
        for a, b in echte_ueber:
            # Vorfälle zählen: weniger als 1 s auseinander gehört zusammen
            if m.ueberlappungen and a - m.ueberlappungen[-1][1] < 1.0:
                m.ueberlappungen[-1][1] = max(m.ueberlappungen[-1][1], b)
            else:
                m.ueberlappungen.append([a, b])
        self._ueberlappung_pruefen()
        self._monolog_pruefen()
        await self.melden()

    def name_lernen(self, sprecher: str, text: str, start: float = 0.0, ende: float = 0.0) -> None:
        """Vorstellungsrunde: „Ich bin Lea“ -> die Stimme, die das gesagt hat, heißt ab jetzt Lea, auch rückwirkend.

        Ticket #27 (in den Demos wurde nur eine von mehreren Personen erkannt): Eine kurze Vorstellung (~1–1,5 s) ist
        zu kurz für eine neue Person im Stimmregister (coach/stimmen.py braucht drei ähnliche Fenster, ~3 s) – der
        Satz kam als „Person ?“ an oder bei der ähnlichsten schon bekannten Person, die oft schon einen Namen hatte; in
        beiden Fällen ging der Name verloren. Jetzt wird der Name mit dem Stimm-Fingerabdruck genau dieser Äußerung
        gemerkt und still der passenden Person zugeordnet, sobald es sie gibt (`_namen_zuordnen`)."""
        from .assistent import name_aus
        from .hoeren import UNSICHER

        name = name_aus(text, self.meeting.teilnehmende)
        if not name or name in self.namen.values() or any(o["name"] == name for o in self.namen_offen):
            return
        vektor = self.hoerstrom.vektor_an(start, ende) if self.hoerstrom is not None else None
        sicher = sprecher.startswith("Person ") and sprecher != UNSICHER and sprecher not in self.namen
        self.namen_offen.append({"name": name, "vektor": vektor, "sprecher": sprecher if sicher else None,
                                 "zeit": self.meeting.jetzt(), "start": start, "ende": ende})
        self.protokoll.append({"zeit": self.meeting.jetzt(), "art": "name_gehoert", "person": sprecher, "name": name})
        self._namen_zuordnen()

    def _namen_zuordnen(self) -> None:
        """Offene Namen den Personen im Stimmregister zuordnen: beste Ähnlichkeit zuerst, je Person ein Name.
        Ohne Fingerabdruck (Tests, Abspielmodus ohne Stimmen) gilt der Sprecher des Satzes, wenn er eindeutig war."""
        if not self.namen_offen:
            return
        from .hoeren import person_name

        reg = self.hoerstrom.stimmen.register if self.hoerstrom is not None else None
        vergeben = set(self.namen)
        paare = []
        schwerpunkte = reg.schwerpunkte() if reg is not None else []
        for o in self.namen_offen:
            if o["vektor"] is not None and schwerpunkte:
                for i, sp in enumerate(schwerpunkte):
                    p = person_name(i)
                    if p not in vergeben and reg.sekunden[i] >= NAME_MIN_SEKUNDEN:
                        paare.append((float(o["vektor"] @ sp), o["name"], p))
            elif o["vektor"] is None and o["sprecher"] and o["sprecher"] not in vergeben:
                paare.append((1.0, o["name"], o["sprecher"]))
        paare.sort(reverse=True)
        neu = []
        for aehnlich, name, person in paare:
            if aehnlich < NAME_SCHWELLE or person in self.namen or name in self.namen.values():
                continue
            # eindeutig: die zweitbeste Person darf nicht fast genauso gut passen
            zweite = max((a for a, n, p in paare if n == name and p != person and p not in self.namen), default=0.0)
            if aehnlich - zweite < NAME_ABSTAND and aehnlich < 0.99:
                continue
            self._name_setzen(person, name)
            neu.append(name)
        self.namen_offen = [o for o in self.namen_offen if o["name"] not in self.namen.values()
                            and self.meeting.jetzt() - o["zeit"] < NAME_WARTEN_SEKUNDEN]
        if neu:
            erkannt = ", ".join(self.namen.values())
            self.entscheider.vorschlagen(self.meeting, "namen", "hinweis", "gruppe", f"Erkannt: {erkannt}",
                                         schluessel=f"namen-{len(self.namen)}", dauer=20.0)

    def _name_setzen(self, person: str, name: str) -> None:
        self.namen[person] = name
        for s in self.meeting.segmente + self.meeting.transkript:
            if s.sprecher == person:
                s.sprecher = name
        self.protokoll.append({"zeit": self.meeting.jetzt(), "art": "name", "person": person, "name": name})

    def taste_hinweis(self) -> None:
        """Basis hört nicht auf „Nestor“ (Funkgerät, Ticket #27 Nachtrag D). Ticket #72: beim ersten ignorierten
        Ansprechen einmal verständlich ins Band, danach nicht mehr – die Funkgerät-Logik selbst bleibt."""
        self.entscheider.einmalig(self.meeting, "taste", "taste", "hinweis", "gruppe",
                                  f"In Basis: Sprechtaste halten, dann fragen – auf „{EINST.assistent_name}, …“ hört "
                                  f"{EINST.assistent_name} hier nicht.", dauer=20.0)

    async def satz(self, seg: Segment, zeilen: list[Segment] | None = None) -> None:
        """Strom 1: fertiger Satz mit Sprecher. Sammelt Text für die Themen-Zuordnung (Strom 4).

        `zeilen`: dieselbe Äußerung nach Sprechern geteilt (Wechsel mitten in der Äußerung) – so landet sie im
        Transkript; Ansagen und Nestor sehen weiter den ganzen Text, damit „Nestor, …“ nicht zerrissen wird.
        """
        m = self.meeting
        if self.assistent.eigene_sprache(seg.start, seg.ende, seg.text):
            return  # der Coach hört sich selbst über den Lautsprecher – nicht ins Transkript
        if self.knopfdruck:
            # Sätze kommen erst beim Knopf, gesammelt: nur ins Transkript. Keine Ansage-Erkennung (der Wechsel käme
            # Minuten zu spät), keine Namen aus Text, keine Themen-Zuordnung, kein Nestor. Gemeldet wird danach.
            for z in zeilen or [seg]:
                z.sprecher = self.namen.get(z.sprecher, z.sprecher)
                m.transkript.append(z)
            m.transkript.sort(key=lambda s: s.start)
            return
        if self.assistent.vorstellung_bis is not None:
            self.name_lernen(seg.sprecher, seg.text, seg.start, seg.ende)
        for z in zeilen or [seg]:
            z.sprecher = self.namen.get(z.sprecher, z.sprecher)
            m.transkript.append(z)
            self._abschnitt.append(z)
        m.transkript.sort(key=lambda s: s.start)
        m.teiltext = ""
        self.artefakte.satz(zeilen or [seg])  # Ticket #72: Schnell-Erkennung bei klaren Signalen
        ziel = analyse.angekuendigter_punkt(seg.text, [p.titel for p in m.agenda], m.aktiver_punkt) if m.laeuft else None
        if ziel is not None:
            # Ausdrückliche Ansage mit Ziel: sofort wechseln, ohne auf die Themen-Zuordnung zu warten
            self.protokoll.append({"zeit": seg.ende, "art": "wechsel", "von": m.aktiver_punkt, "nach": ziel,
                                   "durch": "ansage"})
            self.punkt_wechseln(ziel)
            m.vorschlag = None
            # Was davor gesagt wurde, gehört zum alten Punkt – nicht gegen den neuen prüfen (sonst „zurück zu …“)
            self._abschnitt = list(zeilen or [seg])
            self._fenster_ab = min(z.start for z in self._abschnitt)  # ab der Ansage gehört alles zum neuen Punkt
        else:
            if m.laeuft and analyse.rueckkehr(seg.text, [p.titel for p in m.agenda], m.aktiver_punkt):
                self._rueckkehr(seg)
            if (analyse.ankuendigung(seg.text)
                    or sum(s.dauer for s in self._abschnitt) >= EINST.abschnitt_schritt_sekunden):
                self._abschnitt_schliessen()
        await self.melden()
        await self.assistent.satz(seg.text, seg.ende, self.namen.get(seg.sprecher, seg.sprecher), seg.start)

    # --- Themen-Zuordnung in gleitenden Fenstern (Strom 4, Ticket #24) ------------------------------------------
    def _abschnitt_zuruecksetzen(self) -> None:
        self._abschnitt, self._vorlauf = [], []
        self._fenster_ab, self._rueckkehr_ab = 0.0, None

    def _rueckkehr(self, seg: Segment) -> None:
        """„Gut, zurück zur Datenbank“: Die Runde ist wieder beim Thema. Ein Fokus-Hinweis aus einem Fenster, das bis
        hierher reicht, wäre veraltet; die Fokus-Ampel wird sofort grün."""
        m = self.meeting
        self._rueckkehr_ab = seg.start
        self._fenster_ab = max(self._fenster_ab, seg.start)
        if analyse.fokus_status(m.themen_verlauf, self.karenz_bloecke)[0] == "gelb":
            analyse.rueckkehr_merken(m)
        for h in m.hinweise:
            if h.art == "fokus":
                h.dauer = min(h.dauer, max(0, m.jetzt() - h.zeit))
        self.protokoll.append({"zeit": seg.ende, "art": "rueckkehr"})

    def _abschnitt_takt(self) -> None:
        """Ein Abschnitt schließt auch nach Zeit, nicht nur nach Sprechmenge: nach `abschnitt_ruhe_sekunden` Stille
        oder `abschnitt_max_sekunden` nach dem ersten offenen Satz. Sonst wartet das Ende einer Abschweifung vor einer
        Pause auf den nächsten Satz (Cloud-Lauf 08.10.: 30 s Pause, Hinweis 76 s nach Beginn). Ist zu wenig neu
        Gesprochenes da (ein „Gut.“), wandert es nur in den Vorlauf – kein Hinweis aus einem einzelnen kurzen Satz."""
        if not self._abschnitt or self.knopfdruck:
            return
        m = self.meeting
        jetzt = m.jetzt()
        # Stille: kein Satz zu Ende und keine Sprache am Mikrofon (VAD) – ein langer Satz, dessen Text noch nicht
        # da ist, zählt nicht als Pause
        still = jetzt - max(m.sprache_bis, *(s.ende for s in self._abschnitt)) >= EINST.abschnitt_ruhe_sekunden
        lang = jetzt - self._abschnitt[0].start >= EINST.abschnitt_max_sekunden
        if sum(s.dauer for s in self._abschnitt) >= EINST.abschnitt_min_sekunden:
            if still or lang:
                self._abschnitt_schliessen()
        elif still:
            self._vorlauf = (self._vorlauf + self._abschnitt)[-VORLAUF_MAX:]
            self._abschnitt = []

    def _fenster_nehmen(self) -> tuple[list[Segment], list[Segment], list[str]] | None:
        """Offene Sätze (neu) als Fenster: davor so viel schon Eingeordnetes, dass das Fenster etwa
        `abschnitt_sekunden` Sprache umfasst (überlappende Fenster), davor der ältere Verlauf als Kontext."""
        neu, self._abschnitt = self._abschnitt, []
        if not neu:
            return None
        rest = EINST.abschnitt_sekunden - sum(s.dauer for s in neu)
        grenze = neu[0].start - FENSTER_LUECKE
        i = len(self._vorlauf)
        while (i > 0 and rest > 0 and self._vorlauf[i - 1].ende >= grenze
               and self._vorlauf[i - 1].start >= self._fenster_ab):
            i -= 1
            rest -= self._vorlauf[i].dauer
        davor = self._vorlauf[i:]
        kontext: list[str] = []
        dauer = 0.0
        for s in reversed(self._vorlauf[:i]):
            if dauer >= KONTEXT_SEKUNDEN:
                break
            kontext.insert(0, f"{s.sprecher}: {s.text}")
            dauer += s.dauer
        self._vorlauf = (self._vorlauf + neu)[-VORLAUF_MAX:]
        return neu, davor, kontext

    def _abschnitt_schliessen(self) -> None:
        """Fenster sofort bilden (Reihenfolge bleibt), die Zuordnung läuft im Hintergrund."""
        fenster = self._fenster_nehmen()
        if fenster:
            hintergrund(self._abschnitt_auswerten(*fenster))

    async def _abschnitt_auswerten(self, neu: list[Segment] | None = None, davor: list[Segment] | None = None,
                                   kontext: list[str] | None = None) -> None:
        """Ein Fenster einordnen: `davor` (schon eingeordnet) + `neu`. Ohne Angabe die offenen Sätze (Skripte)."""
        if neu is None:
            fenster = self._fenster_nehmen()
            if not fenster:
                return
            neu, davor, kontext = fenster
        saetze = (davor or []) + neu
        text = "\n".join(f"{s.sprecher}: {s.text}" for s in saetze)
        ueberleitung = any(analyse.ankuendigung(s.text) for s in saetze)
        if ueberleitung:
            text += "\n[Im Abschnitt wird ausdrücklich ein Punkt angekündigt – ordne nach dem angekündigten Inhalt.]"
        async with self._themen_sperre:  # Reihenfolge der Fenster einhalten
            v = await self._themen_pruefen(text, karenz=1 if ueberleitung else None, kontext=kontext,
                                           fenster_ab=saetze[0].start)
            m = self.meeting
            m.block_texte.append("\n".join(f"{s.sprecher}: {s.text}" for s in neu))  # ohne Überschneidung
            if v:
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
        if aktion["typ"] == "weiter":
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
        elif aktion["typ"] == "pause":
            self.assistent.zustand = "pausiert"
        elif aktion["typ"] == "eintragen":  # Basis: „Nestor, Sofie übernimmt die Statusseite bis Freitag“ (#26)
            a, _ = self.artefakte.eintragen(aktion.get("daten") or {})
            if a is not None:
                self.protokoll.append({"zeit": m.jetzt(), "art": "artefakt_eingetragen", "id": a.id, "durch": "stimme"})
        await self.melden()

    async def einwand_umsetzen(self) -> None:
        """Jemand hat der Begrüßung widersprochen: nichts behalten, nicht weiter zuhören."""
        m = self.meeting
        if self.archiv:
            self.archiv.audio_verwerfen()
        m.transkript.clear()
        m.segmente.clear()
        m.block_texte.clear()
        m.mischungen.clear()
        m.ueberlappungen.clear()
        m.teiltext = ""
        self._abschnitt_zuruecksetzen()
        self.artefakte = Artefakte(self)
        m.ergebnisse = {}
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
        nutzung_loggen({"art": "live-text", "modell": self.wahl.live_modell if self.wahl else None,
                        "sekunden_audio": round(sekunden, 1)})

    def _karte_ablegen(self, karte: dict) -> dict:
        """Neue Karte in den Verlauf. `still`: kam ohne Bogen (Bild, Recherche, Abschnitts-Zusammenfassung,
        unterbrochener Bogen) – springt im Dashboard nur nach vorn, wenn die vordere Karte älter als ~60 s ist."""
        k = {"id": len(self.karten) + 1, "zeit": self.meeting.jetzt(), "quellen": [], "still": False, **karte}
        self.karten.append(k)
        return k

    def antwort_karte(self, frage: str, antwort: str, aktion: dict | None, quellen: list[dict],
                      still: bool = False) -> None:
        """Nestors gesprochene Antwort zusätzlich als Karte (Antwort in einem Satz, Einzelheiten auf der Karte).
        Bei Aktionen (Bild, Wechsel, Pause, Folie, Karte, Eintragen) zeigt der Verlauf das Ergebnis selbst."""
        if aktion and aktion.get("typ") in ("bild", "weiter", "pause", "folie", "eintragen", "karte", "recherche"):
            return
        hintergrund(self._karte_bauen(frage, antwort, quellen, still=still))

    async def _karte_bauen(self, frage: str, antwort: str, quellen: list[dict], still: bool = False) -> None:
        from . import karten
        from .folie import quelle_kurz

        recherche = bool(quellen)
        kontext = None if recherche else self.assistent.kontext(frage).rsplit("\n\nFrage an dich:", 1)[0]
        karte, nutzung = await karten.verdichten(self._client, frage, antwort, kontext=kontext, wahl=self.wahl)
        if nutzung:
            nutzung_loggen({"art": "karte", "modell": self.wahl.assistent_modell, **nutzung})
        if karte is None and recherche:
            karte = {"titel": frage, "punkte": karten.saetze(antwort)}
        if karte is None:
            return
        self._karte_ablegen({"art": "recherche" if recherche else "antwort", "frage": frage, **karte,
                             "quellen": [quelle_kurz(q) for q in quellen][:5], "still": still})
        await self.melden()

    def recherche_merken(self, frage: str, erg: dict) -> None:
        """Grundlage für die Folie – nur Frage, vorlesbarer Text und Quellen."""
        self.letzte_recherche = {"frage": frage, "text": erg["text"], "quellen": erg["quellen"],
                                 "zeit": self.meeting.jetzt()}

    def folie_starten(self) -> bool:
        """Letzte Recherche mit Quellen als Folie (Knopf ohne Bogen, z. B. aus Skripten)."""
        if self.letzte_recherche is None or self._client is None or self._folie_laeuft:
            return False
        self._folie_laeuft = True
        hintergrund(self.folie_bauen())
        return True

    async def folie_bauen(self, karte: bool = True) -> dict | None:
        """Folie aus der letzten Recherche (Bogen „Folie“, Ticket #27: „Hier ist die Folie“, keine „fertig“-Ansage)."""
        from . import folie

        self._folie_laeuft = True
        await self.melden()
        try:
            self.folie, nutzung = await folie.erstellen(self._client, self.letzte_recherche, wahl=self.wahl)
            self.folie_version += 1
            ki_fehler.erholt(self, "folie")
            nutzung_loggen({"art": "folie", "modell": self.wahl.assistent_modell, **nutzung})
            self.protokoll.append({"zeit": self.meeting.jetzt(), "art": "folie", "titel": self.folie["titel"]})
            if karte:
                self._karte_ablegen({"art": "folie", "titel": self.folie["titel"], "frage": self.folie["frage"],
                                     "punkte": self.folie["punkte"], "quellen": self.folie["quellen"],
                                     "folie": self.folie})
            return self.folie
        except Exception as e:  # noqa: BLE001
            ki_fehler.melden(self, "folie", e)  # Ticket #72
            return None
        finally:
            self._folie_laeuft = False
            await self.melden()

    def ueberblick_starten(self, fokus: str | None = None, nachholen: bool = False) -> bool:
        """Überblick als Text neu erstellen (Meetingende in Basis; auf Anfrage läuft er als Bogen).
        `nachholen`: entsteht gerade einer, danach noch einmal (Meetingende – der Stand soll vollständig sein)."""
        if not self.meeting.transkript or self._client is None:
            return False
        if self._ueberblick_laeuft:
            self._ueberblick_nachholen = self._ueberblick_nachholen or nachholen
            return False
        if self.bild_als_text:
            self._onepager_letzter_start = self.meeting.jetzt()  # Takt: der nächste automatische erst N min danach
        self._ueberblick_laeuft = True
        hintergrund(self.ueberblick_bauen(fokus))
        return True

    async def ueberblick_bauen(self, fokus: str | None = None, karte: bool = True) -> dict | None:
        from . import ueberblick

        self._ueberblick_laeuft = True
        await self.melden()
        try:
            u, nutzung = await ueberblick.erstellen(self._client, self.meeting, self.ueberblick, fokus, wahl=self.wahl)
            nutzung_loggen({"art": "ueberblick", "modell": self.wahl.analyse_modell, **nutzung})
            self.ueberblick = u
            self.ueberblick_version += 1
            ki_fehler.erholt(self, "ueberblick")
            self.protokoll.append({"zeit": self.meeting.jetzt(), "art": "ueberblick", "version": self.ueberblick_version,
                                   "fokus": fokus})
            if karte:
                self._karte_ablegen({"art": "ueberblick", "frage": "Überblick", "titel": "Überblick · Stand "
                                     + u["laufzeit"], "punkte": ueberblick.punkte(u), "ueberblick": u, "still": True})
            return u
        except Exception as e:  # noqa: BLE001
            self.onepager_fehler = f"Überblick fehlgeschlagen: {fehlertext(e)}"
            ki_fehler.melden(self, "ueberblick", e)  # Ticket #72
            return None
        finally:
            self._ueberblick_laeuft = False
            if self._ueberblick_nachholen:
                self._ueberblick_nachholen = False
                self.ueberblick_starten()
            await self.melden()

    async def bild_erstellen(self, fokus: str | None = None) -> None:
        """Langer Auftrag „Bild“ (Ticket #27): wartet auf ein laufendes Bild, zeichnet dann und kehrt zurück, wenn es
        fertig ist. Das Bild kommt still als Karte in den Verlauf (`_onepager_zeichnen`)."""
        while self._onepager_laeuft:
            await asyncio.sleep(0.5)
        if not self.onepager_starten(fokus):
            return
        try:
            while self._onepager_laeuft:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            for t in asyncio.all_tasks():
                if getattr(getattr(t.get_coro(), "cr_code", None), "co_name", "") == "_onepager_zeichnen":
                    t.cancel()
            self._onepager_laeuft = False
            raise

    def onepager_starten(self, fokus: str | None = None) -> bool:
        """Live-Bild neu zeichnen lassen (Bogen „Bild“, Meetingende, Knopfdruck).
        In Basis (bild_anbieter „text“) entsteht stattdessen der Überblick als Text – kein Bildmodell.

        False, wenn schon eins entsteht – dann wird es danach nachgeholt.
        """
        if not self.meeting.transkript:
            return False
        if self.bild_als_text:
            self._onepager_letzter_start = self.meeting.jetzt()  # Takt: alle N Minuten ab hier (auch wenn gerade einer entsteht)
            return self.ueberblick_starten(fokus)
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
        m = self.meeting
        stand = m.jetzt()
        t0 = time.monotonic()
        await self.melden()
        try:
            # Fortschreibung immer vom letzten Gesamtbild; ein Bild mit Fokus steht für sich
            vorher = None if fokus else self._onepager_voll
            if self.wahl is not None and self.wahl.bild_anbieter == "openai" and self._client is not None:
                from . import bild_gpt
                erg = await bild_gpt.erzeugen(self._client, m, vorher, fokus, wahl=self.wahl)
                self.onepager_png, self.onepager_svg = erg["png"], None
            else:
                raise RuntimeError("OpenAI-Bildweg nicht verfügbar; kein Anbieter-Fallback.")
            self.onepager_analyse = erg["analyse"]
            self.onepager_fokus = fokus
            if not fokus:
                self._onepager_voll = {k: erg.get(k) for k in ("analyse", "svg", "png")}
            self.onepager_version += 1
            self.onepager_stand = stand
            self.onepager_fehler = None
            ki_fehler.erholt(self, "bild")
            self.bilder[self.onepager_version] = self.onepager_png or self.onepager_svg
            for v in sorted(self.bilder)[:-6]:  # die letzten sechs Bilder bleiben für die Karten im Verlauf
                self.bilder.pop(v, None)
            self._karte_ablegen({"art": "bild", "frage": f"Bild{' · ' + fokus if fokus else ''}",
                                 "titel": f"Live-Bild · Stand {analyse.mmss(stand)}" + (f" · {fokus}" if fokus else ""),
                                 "version": self.onepager_version, "format": "png" if self.onepager_png else "svg",
                                 "still": True})
            nutzung_loggen({"art": "onepager", "anbieter": "openai",
                            "fortschreibung": vorher is not None,
                            "sekunden": round(time.monotonic() - t0), "schritte": erg.get("messung")})
            self.protokoll.append({"zeit": stand, "art": "onepager", "version": self.onepager_version, "fokus": fokus})
        except Exception as e:  # noqa: BLE001
            self.onepager_fehler = f"Live-Bild fehlgeschlagen: {str(e)[:160] or fehlertext(e)}"
            ki_fehler.melden(self, "bild", e)  # Ticket #72
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
