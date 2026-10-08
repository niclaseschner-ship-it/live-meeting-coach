"""Gemeinsamer Meeting-Zustand: Agenda, Uhr, Segmente, Hinweise."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field


@dataclass
class Agendapunkt:
    titel: str
    ziel: str = ""
    minuten: float = 10.0
    sekunden_genutzt: float = 0.0  # gebuchte Zeit aus früheren Phasen

    def ampel(self, genutzt: float, rot_prozent: float = 0) -> str:
        """Grün im Zeitfenster, Gelb bei Ablauf, Rot optional ab `rot_prozent` Überziehung (FR-04)."""
        plan = self.minuten * 60
        if plan <= 0:
            return "gruen"
        if rot_prozent > 0 and genutzt > plan * (1 + rot_prozent / 100):
            return "rot"
        if genutzt >= plan:
            return "gelb"
        return "gruen"


@dataclass
class Segment:
    sprecher: str
    text: str
    start: float  # Sekunden seit Meetingbeginn
    ende: float

    @property
    def dauer(self) -> float:
        return max(0.0, self.ende - self.start)


@dataclass
class Hinweis:
    """Eine Zeile im Band oben (Ticket #27): Regel-Hinweise und Nestors stille Angebote an die Runde. Verschwindet von
    selbst (`dauer`), höchstens ein Knopf (`aktion`). `punkt`: gilt nur, solange dieser Agendapunkt aktiv ist."""
    art: str  # monolog | zeit | fokus | ton | ueberlappung | alle | ausreden | fuenf | luecken | namen | taste | info
    stufe: str  # hinweis | warnung | eskalation
    publikum: str  # moderation | gruppe | nachher
    text: str
    zeit: float
    id: int = 0
    aktion: dict | None = None  # Knopf: {"text": "Zusammenfassen", "bogen": "zusammenfassen"} | {"karte": id}
    punkt: int | None = None
    dauer: float = 45.0


@dataclass
class Meeting:
    titel: str = ""
    ziel: str = ""
    agenda: list[Agendapunkt] = field(default_factory=list)
    regeln: list[str] = field(default_factory=list)  # eigene Regeln: Erinnerung, wird nicht geprüft
    regel_ids: list[str] = field(default_factory=list)  # gewählte Regeln aus coach/regeln.py
    teilnehmende: list[str] = field(default_factory=list)
    aktiver_punkt: int = 0
    abgeschlossen: set[int] = field(default_factory=set)
    laeuft: bool = False
    segmente: list[Segment] = field(default_factory=list)  # Sprecherspur: wer spricht wann (Monolog, Überlappung, Redeanteile)
    transkript: list[Segment] = field(default_factory=list)  # Sätze mit Text und zugeordnetem Sprecher (Anzeige, Fokus)
    hinweise: list[Hinweis] = field(default_factory=list)
    mischungen: list[float] = field(default_factory=list)  # Zeitpunkte mit Stimmen-Mischung (Überlappung)
    ueberlappungen: list[list[float]] = field(default_factory=list)  # Vorfälle gleichzeitigen Sprechens [von, bis]
    ueberlappungen_gezaehlt: bool = False  # True, sobald die Segmentierung Vorfälle liefert (statt Mischungs-Schätzung)
    teiltext: str = ""  # laufender Live-Text der aktuellen Äußerung
    themen_verlauf: list[dict] = field(default_factory=list)
    block_texte: list[str] = field(default_factory=list)
    vorschlag: dict | None = None
    letztes_block_ende: float = 0.0  # Meetingzeit, bis zu der Audio verarbeitet ist
    sprache_bis: float = -1e9  # zuletzt vom Mikrofon gemeldete Sprachaktivität
    gestartet_um: float | None = None
    virtuelle_zeit: float | None = None  # gesetzt im Simulationsbetrieb
    _punkt_seit: float = 0.0
    punkt_beginne: list[tuple[int, float]] = field(default_factory=list)  # (Punkt, Meetingzeit) je Wechsel
    ergebnisse: dict[int, dict] = field(default_factory=dict)  # je Punkt, abgeleitet aus coach/artefakte.py (#26)

    # --- Uhr -------------------------------------------------------------
    def jetzt(self) -> float:
        if self.virtuelle_zeit is not None:
            return self.virtuelle_zeit
        if self.gestartet_um is None:
            return 0.0
        return time.time() - self.gestartet_um

    def starten(self, virtuell: bool = False) -> None:
        self.gestartet_um = time.time()
        self.virtuelle_zeit = 0.0 if virtuell else None
        self._punkt_seit = 0.0
        self.punkt_beginne = [(self.aktiver_punkt, 0.0)]
        self.laeuft = True

    def beenden(self) -> None:
        if not self.laeuft:
            return
        self._zeit_buchen()
        self.laeuft = False

    def _zeit_buchen(self) -> None:
        if 0 <= self.aktiver_punkt < len(self.agenda):
            jetzt = self.jetzt()
            self.agenda[self.aktiver_punkt].sekunden_genutzt += jetzt - self._punkt_seit
            self._punkt_seit = jetzt

    def genutzt(self, i: int) -> float:
        basis = self.agenda[i].sekunden_genutzt
        if self.laeuft and i == self.aktiver_punkt:
            basis += self.jetzt() - self._punkt_seit
        return basis

    def punkt_wechseln(self, i: int) -> None:
        if not 0 <= i < len(self.agenda) or i == self.aktiver_punkt:
            return
        if self.laeuft:
            self._zeit_buchen()
        self.abgeschlossen.add(self.aktiver_punkt)
        self.abgeschlossen.discard(i)
        self.aktiver_punkt = i
        self.punkt_beginne.append((i, self.jetzt()))
        self.vorschlag = None
        self.themen_verlauf = []  # Fokus bezieht sich ab jetzt auf den neuen Punkt

    def punkt_transkript(self, i: int) -> list[Segment]:
        """Sätze, die gesprochen wurden, während Punkt i aktiv war (auch bei mehrfachem Aufruf)."""
        grenzen = self.punkt_beginne + [(-1, float("inf"))]
        bereiche = [(a, b) for (p, a), (_, b) in zip(grenzen, grenzen[1:]) if p == i]
        return [s for s in self.transkript if any(a <= s.start < b for a, b in bereiche)]

    def status(self, i: int) -> str:
        """Agenda-Status laut Lastenheft 7.1 A: offen / aktuell / abgeschlossen."""
        if i == self.aktiver_punkt:
            return "aktuell" if self.laeuft or self.gestartet_um is None else "abgeschlossen"
        return "abgeschlossen" if i in self.abgeschlossen else "offen"

    # --- Daten -----------------------------------------------------------
    def segmente_hinzufuegen(self, spur: list[Segment], saetze: list[Segment] | None = None) -> None:
        self.segmente.extend(spur)
        self.segmente.sort(key=lambda s: s.start)
        self.transkript.extend(spur if saetze is None else saetze)
        self.transkript.sort(key=lambda s: s.start)

    def redeanteile(self, seit: float = 0.0) -> dict[str, float]:
        anteile: dict[str, float] = {}
        for s in self.segmente:
            dauer = s.ende - max(s.start, seit)
            if dauer > 0:
                anteile[s.sprecher] = anteile.get(s.sprecher, 0.0) + dauer
        return anteile

    def schnappschuss(self, rot_prozent: float = 0) -> dict:
        return {
            "titel": self.titel,
            "ziel": self.ziel,
            "laeuft": self.laeuft,
            "zeit": self.jetzt(),
            "aktiver_punkt": self.aktiver_punkt,
            "agenda": [
                {
                    "titel": p.titel,
                    "ziel": p.ziel,
                    "minuten": p.minuten,
                    "genutzt": self.genutzt(i),
                    "verbleibend": p.minuten * 60 - self.genutzt(i),
                    "ampel": p.ampel(self.genutzt(i), rot_prozent),
                    "status": self.status(i),
                    "ergebnis": self.ergebnisse.get(i),
                }
                for i, p in enumerate(self.agenda)
            ],
            "regeln": self.regeln,
            "regel_ids": self.regel_ids,
            "teilnehmende": self.teilnehmende,
            "redeanteile": self.redeanteile(),
            "segmente": [asdict(s) for s in self.transkript[-200:]],
            "teiltext": self.teiltext,
            "hinweise": [asdict(h) for h in self.hinweise[-40:]],
            "vorschlag": self.vorschlag,
            "thema": self.themen_verlauf[-1] if self.themen_verlauf else None,
        }
