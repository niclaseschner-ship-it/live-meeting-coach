"""Wer spricht (lokal): Stimm-Fingerabdruck in kurzen Fenstern, Live-Zuordnung zu Personen, Überlappung.

Zuordnung je 1,5-s-Fenster (Schritt 0,75 s) statt je Äußerung: In lebhaften Gesprächen gibt es zwischen
Sprechern oft keine Pause, eine Äußerung enthält dann mehrere Personen (Talkshow: 3 von 23 Äußerungen
stammten von nur einer Person). Eine neue Person entsteht erst nach mehreren untereinander ähnlichen
Fenstern, die zu niemandem passen; danach Mehrheitsglättung über 3 Fenster.

Benchmark 05.10.2026 auf der Testbibliothek (scripts/bench_sprecher.py), Modell CAM++ (3D-Speaker, zh/en),
Schwelle 0,50: Stadtrat über Saalanlage 95 %, Talkshow 96 %, Zoom-Meeting 96 % der Sprechzeit richtig,
jeweils die richtige Personenzahl (3/4/6). Bei 0,45 fielen im Zoom-Meeting zwei Personen zusammen.
Das vorherige Modell (WeSpeaker ResNet34) lag im Stadtrat bei 62 % und fasste dort alle zu einer Person
zusammen. Schwelle an denselben Aufnahmen ermittelt – im Raumtest bestätigen.
"""

from __future__ import annotations

import numpy as np

from .config import EINST, WURZEL

RATE = 16000
MIN_SEKUNDEN = 1.0  # kürzere Äußerungen sind zu unsicher für einen eigenen Fingerabdruck
FENSTER_SEKUNDEN = 1.5
SCHRITT_SEKUNDEN = 0.75
MIN_PERSON_SEKUNDEN = 10.0  # nur gut bekannte Personen zählen für die Überlappungsprüfung
NEU_FENSTER = 3  # so viele zusammenhängende, unbekannte, untereinander ähnliche Fenster ergeben eine neue Person


def normiert(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


class Personenregister:
    """Reine Zuordnungslogik ohne Modell – testbar mit beliebigen Vektoren."""

    def __init__(self, schwelle: float, unsicher: float = 0.0, max_personen: int | None = None) -> None:
        self.schwelle = schwelle
        self.unsicher = unsicher  # darunter passt das Fenster zu niemandem sicher genug -> „Person ?“ statt raten
        self.max_personen = max_personen  # bekannte Teilnehmerzahl: keine weiteren Personen anlegen
        self.summen: list[np.ndarray] = []  # zeitgewichtete Summe der Fingerabdrücke je Person
        self.sekunden: list[float] = []
        self._kandidat: list[np.ndarray] = []  # Fenster, die zu niemandem passen (mögliche neue Person)

    def schwerpunkte(self) -> list[np.ndarray]:
        return [normiert(s) for s in self.summen]

    def aehnlichkeiten(self, v: np.ndarray) -> list[float]:
        return [float(v @ s) for s in self.schwerpunkte()]

    def zuordnen(self, v: np.ndarray, dauer: float) -> tuple[int, float]:
        """Ähnlichste bekannte Person über der Schwelle, sonst neue Person. Liefert (index, ähnlichkeit)."""
        sims = self.aehnlichkeiten(v)
        if sims:
            k = int(np.argmax(sims))
            if sims[k] >= self.schwelle:
                self.summen[k] = self.summen[k] + v * dauer
                self.sekunden[k] += dauer
                return k, sims[k]
        self.summen.append(v * dauer)
        self.sekunden.append(dauer)
        return len(self.summen) - 1, 1.0

    def fenster_zuordnen(self, vektoren: list[np.ndarray], schritt: float) -> list[int | None]:
        """Fenster einer Äußerung nacheinander zuordnen (online). Liefert je Fenster eine Person (oder None).

        Passt ein Fenster zu niemandem, wird es Kandidat; NEU_FENSTER aufeinanderfolgende Kandidaten, die sich
        untereinander ähneln, werden zu einer neuen Person – rückwirkend auch für ihre Fenster in dieser
        Äußerung. Bis dahin gilt die ähnlichste bekannte Person. Danach Glättung über 3 Fenster.
        """
        roh: list[int | None] = []
        kand_idx: list[int] = []
        for i, v in enumerate(vektoren):
            sims = self.aehnlichkeiten(v)
            k = int(np.argmax(sims)) if sims else None
            if k is not None and sims[k] >= self.schwelle:
                self.summen[k] = self.summen[k] + v * schritt
                self.sekunden[k] += schritt
                self._kandidat, kand_idx = [], []
                roh.append(k)
                continue
            voll = self.max_personen is not None and len(self.summen) >= self.max_personen
            if voll:  # alle Teilnehmenden sind bekannt: zur ähnlichsten, wenn halbwegs sicher, sonst „?“
                roh.append(k if k is not None and sims[k] >= max(self.unsicher, 0.25) else None)
                continue
            self._kandidat.append(v)
            kand_idx.append(i)
            letzte = self._kandidat[-NEU_FENSTER:]
            if len(letzte) == NEU_FENSTER and min(float(a @ b) for a in letzte for b in letzte) >= self.schwelle:
                self.summen.append(sum(letzte) * schritt)
                self.sekunden.append(NEU_FENSTER * schritt)
                neu = len(self.summen) - 1
                for j in kand_idx[-NEU_FENSTER:-1]:  # frühere Kandidaten dieser Äußerung (das aktuelle folgt unten)
                    roh[j] = neu
                self._kandidat, kand_idx = [], []
                roh.append(neu)
            else:
                roh.append(k if k is not None and sims[k] >= self.unsicher else None)
        glatt: list[int | None] = []
        for i in range(len(roh)):
            w = [x for x in roh[max(0, i - 1):i + 2] if x is not None]  # Nachbarn innerhalb der Äußerung
            glatt.append(max(set(w), key=w.count) if w else None)
        return glatt

    def stueck_zuordnen(self, v: np.ndarray, dauer: float, min_neu: float = 1.5) -> int | None:
        """Ein Segment (eine Stimme, allein gesprochen): ähnlichste Person über der Schwelle; sonst eine neue Person,
        wenn das Stück lang genug für einen sicheren Fingerabdruck ist; sonst None („Person ?“)."""
        sims = self.aehnlichkeiten(v)
        if sims:
            k = int(np.argmax(sims))
            if sims[k] >= self.schwelle:
                self.summen[k] = self.summen[k] + v * dauer
                self.sekunden[k] += dauer
                return k
        if dauer >= min_neu:
            self.summen.append(v * dauer)
            self.sekunden.append(dauer)
            return len(self.summen) - 1
        return None

    def mischung(self, fenster_vektoren: list[np.ndarray], max_sicher: float, zweit_min: float) -> list[int]:
        """Indizes der Fenster, die wie eine Mischung zweier bekannter Stimmen aussehen.

        Merkmal: Das Fenster passt zu keiner Person sicher (beste Ähnlichkeit < max_sicher), aber zu zwei
        verschiedenen gut bekannten Personen zugleich mittelmäßig (zweitbeste ≥ zweit_min).
        """
        bekannt = [i for i, s in enumerate(self.sekunden) if s >= MIN_PERSON_SEKUNDEN]
        if len(bekannt) < 2:
            return []
        sp = self.schwerpunkte()
        treffer = []
        for j, v in enumerate(fenster_vektoren):
            sims = sorted((float(v @ sp[i]) for i in bekannt), reverse=True)
            if sims[0] < max_sicher and sims[1] >= zweit_min:
                treffer.append(j)
        return treffer


class Stimmen:
    """Fingerabdruck-Modell (WeSpeaker über sherpa-onnx) plus Personenregister."""

    def __init__(self) -> None:
        import sherpa_onnx

        self._ext = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(WURZEL / "modelle" / EINST.stimm_modell), num_threads=2))
        self.register = Personenregister(EINST.stimm_schwelle, EINST.stimm_unsicher)
        self._seg = None
        if EINST.segmentierung and (WURZEL / "modelle" / "pyannote_segmentation_3_0.onnx").exists():
            from .segmentierung import Segmentierer

            self._seg = Segmentierer()

    def vektor(self, proben: np.ndarray) -> np.ndarray:
        st = self._ext.create_stream()
        st.accept_waveform(RATE, proben)
        st.input_finished()
        return normiert(np.array(self._ext.compute(st)))

    def analysieren(self, proben: np.ndarray) -> dict:
        """Eine Äußerung: Personen je Fenster, Abschnitte, Überlappung. Läuft im Hintergrund-Thread.

        Liefert {person (überwiegend), abschnitte [(von, bis, person)] relativ zum Äußerungsbeginn, mischung}.
        """
        dauer = len(proben) / RATE
        if self._seg is not None and EINST.segmentierung_art == "segmente":
            return self._analysieren_segmente(proben, dauer)
        erg = self._analysieren_fenster(proben, dauer)
        if self._seg is not None:  # Mischform: Personen aus den Fenstern, Überlappung aus der Segmentierung
            ueber = self._seg.analysieren(proben)["ueberlappung"]
            erg["ueberlappung"] = ueber
            erg["mischung"] = [round(t, 2) for a, b in ueber for t in np.arange(a, b, 0.5)]
            erg["abschnitte"] = ausschneiden(erg["abschnitte"], ueber)
        return erg

    def _analysieren_fenster(self, proben: np.ndarray, dauer: float) -> dict:
        if dauer < MIN_SEKUNDEN:
            return {"person": None, "abschnitte": [], "mischung": []}
        f, s = int(FENSTER_SEKUNDEN * RATE), int(SCHRITT_SEKUNDEN * RATE)
        if len(proben) < f:
            fenster, starts = [self.vektor(proben)], [0.0]
        else:
            starts = [i / RATE for i in range(0, len(proben) - f + 1, s)]
            fenster = [self.vektor(proben[int(t * RATE):int(t * RATE) + f]) for t in starts]
        # Überlappung zuerst prüfen (gegen die bisher bekannten Personen), dann zuordnen
        idx = self.register.mischung(fenster, EINST.mischung_max, EINST.mischung_zweit_min)
        # nur zusammenhängende Treffer (≥ 2 Fenster in Folge) zählen – einzelne sind Rauschen
        mischung = [starts[i] for i in idx if i + 1 in idx]
        personen = self.register.fenster_zuordnen(fenster, SCHRITT_SEKUNDEN)
        # Abschnitte: jedes Fenster steht für seine Mitte (± halber Schritt); Ränder bis Äußerungsgrenze
        abschnitte: list[list] = []
        for i, (t, p) in enumerate(zip(starts, personen)):
            von = 0.0 if i == 0 else t + (FENSTER_SEKUNDEN - SCHRITT_SEKUNDEN) / 2
            bis = dauer if i == len(starts) - 1 else t + (FENSTER_SEKUNDEN + SCHRITT_SEKUNDEN) / 2
            if abschnitte and abschnitte[-1][2] == p:
                abschnitte[-1][1] = bis
            else:
                abschnitte.append([von, bis, p])
        abschnitte = [(a, b, p) for a, b, p in abschnitte if p is not None]
        anteil: dict[int, float] = {}
        for a, b, p in abschnitte:
            anteil[p] = anteil.get(p, 0) + b - a
        person = max(anteil, key=anteil.get) if anteil else None
        return {"person": person, "abschnitte": abschnitte, "mischung": mischung}

    def _analysieren_segmente(self, proben: np.ndarray, dauer: float) -> dict:
        """Segmentierung (coach/segmentierung.py): Stücke je lokaler Stimme -> Fingerabdruck -> Person oder None
        („Person ?“, wenn zu kurz und keinem sicher zuzuordnen). Überlappung direkt aus dem Signal.
        Sprecher-Labor AMI (4 Sitzungen): 78 % richtig, 4–5 % falsch (vorher 6,5 %), Überlappung erstmals erkannt."""
        erg = self._seg.analysieren(proben)
        roh = []
        for stuecke in erg["stimmen"].values():
            teile = [proben[int(a * RATE):int(b * RATE)] for a, b in stuecke]
            laenge = sum(len(t) for t in teile) / RATE
            p = self.register.stueck_zuordnen(self.vektor(np.concatenate(teile)), laenge) if laenge >= 0.5 else None
            roh += [(a, b, p) for a, b in stuecke]
        roh.sort(key=lambda x: x[0])
        # kurze Lücken (Atempausen) schließen; Ränder bis zur Äußerungsgrenze
        abschnitte = []
        for i, (a, b, p) in enumerate(roh):
            nb = roh[i + 1][0] if i + 1 < len(roh) else dauer
            a = 0.0 if i == 0 and a < 0.6 else a
            b = nb if nb - b < 0.6 else b
            if abschnitte and abschnitte[-1][2] == p and a - abschnitte[-1][1] < 0.01:
                abschnitte[-1] = (abschnitte[-1][0], b, p)
            else:
                abschnitte.append((a, b, p))
        anteil: dict = {}
        for a, b, p in abschnitte:
            anteil[p] = anteil.get(p, 0) + b - a
        bekannt = {k: v for k, v in anteil.items() if k is not None}
        person = max(bekannt, key=bekannt.get) if bekannt else None
        # Überlappung als Zeitpunkte im Halbsekundentakt (wie bisher die Mischungs-Fenster)
        mischung = [round(t, 2) for a, b in erg["ueberlappung"] for t in np.arange(a, b, 0.5)]
        return {"person": person, "abschnitte": abschnitte, "mischung": mischung,
                "ueberlappung": erg["ueberlappung"]}


def ausschneiden(abschnitte: list[tuple[float, float, int | None]], ueber: list[tuple[float, float]]
                 ) -> list[tuple[float, float, int | None]]:
    """Überlappungsstellen aus den Abschnitten herausnehmen und als „Person ?“ (None) einsetzen."""
    aus = []
    for a, b, p in abschnitte:
        teile = [(a, b)]
        for x, y in ueber:
            neu = []
            for c, d in teile:
                if y <= c or x >= d:
                    neu.append((c, d))
                    continue
                if c < x:
                    neu.append((c, x))
                if y < d:
                    neu.append((y, d))
            teile = neu
        aus += [(c, d, p) for c, d in teile if d - c > 0.05]
    aus += [(x, y, None) for x, y in ueber]
    return sorted(aus)
