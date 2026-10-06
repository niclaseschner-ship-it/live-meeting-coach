"""Meeting-Ablage: was nach dem Meeting bleibt – für die Runde und zum Nachvollziehen.

    meetings/2026-10-06_1015_teamrunde/
        zusammenfassung.png|svg   Abschlussbild
        protokoll.md              Analyse hinter dem Bild (Ergebnisse, Aufgaben, Verlauf)
        bericht.json              alles Messbare: Transkript, Hinweise, Agenda, Karten, Dynamik, Kosten,
                                  Zeitreihe – dasselbe Format wie die Testläufe (scripts/abspielen.py),
                                  damit die Auswertungsskripte auch auf echten Meetings laufen
        aufnahme.wav              Audio (24 kHz mono), mit scripts/abspielen.py erneut durchspielbar
        debug/coach.log           Warnungen und Fehler des Coachs während des Meetings
        debug/ereignisse.jsonl    Mikrofon- und Lautsprecherwechsel, Start/Stopp und woher
        debug/nestor_zeiten.jsonl Knopf/Ansprache bis zum ersten Ton
        debug/nutzung.jsonl       API-Aufrufe mit Kosten (ohne Inhalte)

Gilt nur für den Server (nicht für Testskripte). Sagt die Runde bei der Begrüßung „Nein“, wird die Aufnahme
gelöscht und nicht weiter aufgenommen.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import time
import wave
from datetime import datetime
from pathlib import Path

from .config import EINST, WURZEL

log = logging.getLogger("coach.archiv")


def bericht(coach, zeitreihe: list[dict] | None = None, **extra) -> dict:
    """Alles Messbare eines Meetings als JSON-taugliches dict (auch für die Testläufe)."""
    m = coach.meeting
    return {
        **extra,
        "personen": sorted({s.sprecher for s in m.segmente}),
        "redeanteile": {k: round(v, 1) for k, v in m.redeanteile().items()},
        "transkript": [{"start": round(s.start, 1), "ende": round(s.ende, 1), "sprecher": s.sprecher, "text": s.text}
                       for s in m.transkript],
        "hinweise": [{"zeit": round(h.zeit, 1), "art": h.art, "text": h.text} for h in m.hinweise],
        "protokoll": coach.protokoll,
        "mischungen": [round(t, 1) for t in m.mischungen],
        "zeitreihe": zeitreihe or [],
        "onepager_version": coach.onepager_version,
        "karten": coach.karten,
        "folie": coach.folie,
        "ergebnisse": {str(i): e for i, e in m.ergebnisse.items()},
        "agenda": [{"titel": p.titel, "minuten": p.minuten, "genutzt": round(m.genutzt(i), 1)}
                   for i, p in enumerate(m.agenda)],
        "kosten": coach.kosten_stand(),
        "dynamik": coach.dynamik(),
        "namen": coach.namen,
        "ueberlappungen": m.ueberlappungen,
        "einstellungen": coach.einstellungen(),
        "fehler": coach.fehler,
    }


def _kurz(titel: str) -> str:
    s = re.sub(r"[^\w]+", "_", titel.lower()).strip("_")
    return s[:40] or "meeting"


def _jsonl_seit(quelle: Path, ziel: Path, seit: str) -> None:
    """Zeilen eines Protokolls ab Meetingbeginn kopieren (ISO-Zeitstempel im Feld „zeit“)."""
    try:
        zeilen = [z for z in quelle.read_text(encoding="utf-8").splitlines()
                  if z.strip() and json.loads(z).get("zeit", "") >= seit]
    except (OSError, ValueError):
        return
    if zeilen:
        ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


class Archiv:
    def __init__(self, coach, audio: bool) -> None:
        self.coach = coach
        self.seit = time.strftime("%Y-%m-%dT%H:%M:%S")
        name = f"{datetime.now():%Y-%m-%d_%H%M}_{_kurz(coach.meeting.titel)}"
        basis = Path(EINST.archiv)
        self.ordner = basis / name
        n = 2
        while self.ordner.exists():
            self.ordner = basis / f"{name}_{n}"
            n += 1
        (self.ordner / "debug").mkdir(parents=True)
        self.fertig = False
        self.zeitreihe: list[dict] = []
        self.laufzeiten: list[float] = []
        self._wav: wave.Wave_write | None = None
        self.mit_audio = audio  # bleibt nach dem Schließen der Datei wahr – außer nach einem Einwand
        if audio:
            self._wav = wave.open(str(self.ordner / "aufnahme.wav"), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(24000)
        self._log = logging.FileHandler(self.ordner / "debug" / "coach.log", encoding="utf-8")
        self._log.setLevel(logging.INFO)
        self._log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(self._log)
        self.ereignis("start", titel=coach.meeting.titel, aufnahme=audio)

    @property
    def aufnahme(self) -> bool:
        return self.mit_audio

    def stand(self) -> dict:
        return {"ordner": self.ordner.name, "fertig": self.fertig, "aufnahme": self.aufnahme}

    # --- während des Meetings ----------------------------------------------
    def audio(self, pcm24k: bytes) -> None:
        if self._wav is not None:
            self._wav.writeframes(pcm24k)

    def audio_verwerfen(self) -> None:
        """Einwand der Runde: nichts behalten."""
        self.mit_audio = False
        if self._wav is not None:
            self._wav.close()
            self._wav = None
        (self.ordner / "aufnahme.wav").unlink(missing_ok=True)
        self.ereignis("einwand", aufnahme_geloescht=True)

    def ereignis(self, art: str, **daten) -> None:
        z = {"zeit": time.strftime("%Y-%m-%dT%H:%M:%S"), "meeting_s": round(self.coach.meeting.jetzt(), 1),
             "art": art, **daten}
        try:
            with (self.ordner / "debug" / "ereignisse.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(z, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def laufzeit(self, ms: float) -> None:
        self.laufzeiten.append(float(ms))

    async def beobachten(self) -> None:
        """Vom Coach bei jeder Änderung: Zeitreihe je Sekunde (Agendapunkt, Klima, Ampeln)."""
        if self.fertig:
            return
        m = self.coach.meeting
        t = round(m.jetzt())
        if not self.zeitreihe or self.zeitreihe[-1]["t"] != t:
            s = self.coach.schnappschuss()
            self.zeitreihe.append({"t": t, "punkt": m.aktiver_punkt, "klima": (s.get("dynamik") or {}).get("klima"),
                                   "ampeln": {a["name"]: a["farbe"] for a in s["ampeln"]}})

    # --- nach dem Meeting ----------------------------------------------------
    def schreiben(self, endgueltig: bool) -> None:
        """Bericht, Bild, Protokoll und Debug-Daten ablegen. Erst sofort beim Stopp (falls danach etwas abstürzt),
        dann endgültig, wenn Abschlussbild und Ergebnisprüfung fertig sind."""
        c = self.coach
        if self._wav is not None and endgueltig:
            self._wav.close()
            self._wav = None
        lz = sorted(self.laufzeiten)
        extra = {"archiv": self.ordner.name, "beginn": self.seit, "titel": c.meeting.titel,
                 "laufzeit_handy_ms": ({"anzahl": len(lz), "median": statistics.median(lz), "max": lz[-1],
                                        "p90": lz[int(0.9 * (len(lz) - 1))]} if lz else None)}
        (self.ordner / "bericht.json").write_text(
            json.dumps(bericht(c, self.zeitreihe, **extra), ensure_ascii=False, indent=1), encoding="utf-8")
        if c.onepager_png:
            (self.ordner / "zusammenfassung.png").write_bytes(c.onepager_png)
        elif c.onepager_svg:
            (self.ordner / "zusammenfassung.svg").write_text(c.onepager_svg, encoding="utf-8")
        if c.onepager_analyse:
            (self.ordner / "protokoll.md").write_text(c.onepager_analyse, encoding="utf-8")
        logs = WURZEL / "logs"
        _jsonl_seit(logs / "nestor_zeiten.jsonl", self.ordner / "debug" / "nestor_zeiten.jsonl", self.seit)
        _jsonl_seit(logs / "nutzung.jsonl", self.ordner / "debug" / "nutzung.jsonl", self.seit)
        if endgueltig:
            self.ereignis("abgelegt")
            logging.getLogger().removeHandler(self._log)
            self._log.close()
            self.fertig = True
            log.info("Meeting abgelegt: %s", self.ordner)
