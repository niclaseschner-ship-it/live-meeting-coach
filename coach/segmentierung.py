"""Sprecherwechsel und gleichzeitiges Sprechen innerhalb einer Äußerung erkennen (pyannote segmentation 3.0).

Das Modell (MIT, 6 MB, über sherpa-onnx) bekommt bis zu 10 s Audio und sagt je ~17 ms, welche von bis zu drei
lokalen Stimmen spricht – auch zwei gleichzeitig („Powerset“: still, A, B, C, A+B, A+C, B+C). Damit schneiden wir
eine Äußerung an echten Sprecherwechseln statt in feste 1,5-s-Fenster und sehen Überlappungen direkt im Signal.
Wer die lokalen Stimmen A/B/C sind, entscheidet danach der Stimm-Fingerabdruck (coach/stimmen.py).

Sprecher-Labor 05.10.2026 (AMI, Tischmikrofon): mit festen Fenstern höchstens 64–75 % der Sprechzeit zuordenbar,
weil Überlappungen (15–17 % der Zeit) und kurze Beiträge verloren gingen – deshalb dieser Schritt.
"""

from __future__ import annotations

import numpy as np

from .config import EINST, WURZEL

RATE = 16000
FENSTER = 160000  # 10 s
# Powerset-Klassen -> aktive lokale Stimmen
KLASSEN = [(), (0,), (1,), (2,), (0, 1), (0, 2), (1, 2)]
GLAETTUNG = 15  # Frames (~0,25 s): häufigste Klasse im Fenster – sonst flackert die Zuordnung Frame für Frame


class Segmentierer:
    def __init__(self, modell: str = "pyannote_segmentation_3_0.onnx") -> None:
        import onnxruntime as ort

        opt = ort.SessionOptions()
        opt.intra_op_num_threads = 2
        self._s = ort.InferenceSession(str(WURZEL / "modelle" / modell), opt, providers=["CPUExecutionProvider"])
        meta = self._s.get_modelmeta().custom_metadata_map
        self.schritt = int(meta.get("receptive_field_shift", 270)) / RATE  # Sekunden je Ausgabe-Frame
        self.versatz = int(meta.get("receptive_field_size", 991)) / RATE / 2

    def frames(self, proben: np.ndarray) -> np.ndarray:
        """Aktive lokale Stimmen je Frame als bool-Matrix (frames × 3) für bis zu 10 s Audio."""
        return self._frames(proben)[0]

    def _frames(self, proben: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(aktiv frames × 3, Wahrscheinlichkeit „zwei gleichzeitig“ je Frame, geglättet)."""
        x = np.zeros(FENSTER, dtype=np.float32)
        x[:min(len(proben), FENSTER)] = proben[:FENSTER]
        y = self._s.run(None, {"x": x[None, None, :]})[0][0]  # (frames, 7) Log-Wahrscheinlichkeiten
        klasse = glaetten(y.argmax(axis=1), GLAETTUNG)
        aktiv = np.zeros((len(klasse), 3), dtype=bool)
        for i, k in enumerate(klasse):
            for s in KLASSEN[k]:
                aktiv[i, s] = True
        zwei = np.convolve(np.exp(y[:, 4:7]).sum(axis=1), np.ones(9) / 9, "same")
        n = int(min(len(proben), FENSTER) / RATE / self.schritt)  # Frames hinter dem Audioende abschneiden
        return aktiv[:n], zwei[:n]

    def zeit(self, frame: int) -> float:
        return frame * self.schritt + self.versatz * 0  # Frame-Mitte; Versatz ist im Modell bereits zentriert

    def analysieren(self, proben: np.ndarray, min_sek: float = 0.25) -> dict:
        """Liefert {stimmen: {k: [(von, bis)]} je lokaler Stimme (nur allein gesprochen),
        ueberlappung: [(von, bis)]} relativ zum Äußerungsbeginn, Abschnitte kürzer als min_sek fallen weg.
        Längere Äußerungen werden in 10-s-Stücke geteilt; lokale Stimmen heißen dann (stück, k) – welche Person
        dahintersteckt, entscheidet erst der Fingerabdruck."""
        if len(proben) > FENSTER:
            stimmen, ueber = {}, []
            for i, c in enumerate(range(0, len(proben), FENSTER)):
                teil = self._analysieren(proben[c:c + FENSTER], min_sek)
                off = c / RATE
                for k, st in teil["stimmen"].items():
                    stimmen[i * 3 + k] = [(a + off, b + off) for a, b in st]
                ueber += [(a + off, b + off) for a, b in teil["ueberlappung"]]
            return {"stimmen": stimmen, "ueberlappung": ueber}
        return self._analysieren(proben, min_sek)

    def _analysieren(self, proben: np.ndarray, min_sek: float) -> dict:
        aktiv, p_zwei = self._frames(proben)
        allein = aktiv.sum(axis=1) == 1
        # Überlappung: Wahrscheinlichkeit „zwei gleichzeitig“ über der Schwelle (AMI: 0,3 -> knapp die Hälfte
        # der Überlappungszeit gefunden, 70 % der Meldungen echt; nur die wahrscheinlichste Klasse: 36 % / 79 %)
        zwei = p_zwei >= EINST.ueberlappung_schwelle
        stimmen: dict[int, list[tuple[float, float]]] = {}
        for k in range(3):
            for a, b in _laeufe(allein & aktiv[:, k]):
                if (b - a) * self.schritt >= min_sek:
                    stimmen.setdefault(k, []).append((a * self.schritt, b * self.schritt))
        ueber = [(a * self.schritt, b * self.schritt) for a, b in _laeufe(zwei) if (b - a) * self.schritt >= min_sek]
        return {"stimmen": stimmen, "ueberlappung": ueber}


def glaetten(klasse: np.ndarray, breite: int) -> np.ndarray:
    """Modus-Filter über die Klassenfolge (gleitendes Fenster, ungerade Breite)."""
    if breite <= 1 or len(klasse) < breite:
        return klasse
    h = breite // 2
    gepolstert = np.concatenate([np.full(h, klasse[0]), klasse, np.full(h, klasse[-1])])
    zaehler = np.stack([np.convolve((gepolstert == k).astype(np.int16), np.ones(breite, np.int16), "valid")
                        for k in range(len(KLASSEN))])
    return zaehler.argmax(axis=0)


def _laeufe(maske: np.ndarray) -> list[tuple[int, int]]:
    """Zusammenhängende True-Bereiche als (start, ende) in Frames."""
    if not len(maske):
        return []
    d = np.diff(np.concatenate([[0], maske.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))
