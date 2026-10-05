r"""Sprecher-Labor: Strategien für „Wer spricht“ schnell gegeneinander messen – lokal, ohne API-Kosten.

    .venv\Scripts\python scripts\sprecher_labor.py vorbereiten ami_ES2002a ami_ES2002b …   # einmalig je Modell
    .venv\Scripts\python scripts\sprecher_labor.py messen ami_ES2002a ami_ES2002b …

Vorbereiten: Pausenerkennung wie live, dann Fingerabdrücke je 1,5-s-Fenster (Schritt 0,75 s) für jedes Modell in
modelle/; gespeichert in logs/sprecherlabor/<probe>.<modell>.npz. Messen: Strategien auf diesen Fenstern, bewertet
wie scripts/bench_sprecher.py (Anteil der Referenz-Sprechzeit mit richtiger Person, beste 1:1-Zuordnung).

Strategien
- online      heute live: Personenregister.fenster_zuordnen (Schwelle aus der Konfiguration bzw. Liste)
- vorstellung Vorstellungsrunde: je Person die ersten 8 s ihrer Sprechzeit laut Referenz als Stimmprobe, danach
              jedes Fenster zur ähnlichsten bekannten Person (geschlossene Menge), Schwerpunkte lernen mit
- anzahl      Personenzahl bekannt, Fenster nachträglich geclustert (agglomerativ, Kosinus) – obere Schranke
              für eine Korrektur im Hintergrund
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.config import EINST  # noqa: E402
from coach.hoeren import nach_16k  # noqa: E402
from coach.stimmen import FENSTER_SEKUNDEN, SCHRITT_SEKUNDEN, Personenregister, normiert  # noqa: E402
from coach.vad import Pausenerkennung  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
PROBEN = WURZEL / "testbibliothek" / "proben"
AUDIO = WURZEL / "testbibliothek" / "audio"
LABOR = WURZEL / "logs" / "sprecherlabor"
MODELLE = ["3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
           "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
           "wespeaker_en_voxceleb_resnet34_LM.onnx", "nemo_en_titanet_small.onnx"]
RASTER = 0.25
RATE = 16000


def kurz(modell: str) -> str:
    return modell.split("_")[2] if modell.startswith("3dspeaker") else modell.split("_")[0] + "_" + modell.split("_")[2]


def vorbereiten(name: str) -> None:
    import sherpa_onnx

    with wave.open(str(AUDIO / f"{name}.wav")) as w:
        a = nach_16k(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768)
    vad = Pausenerkennung()
    aeusserungen = vad.zufuehren(a) + vad.ende()
    f, s = int(FENSTER_SEKUNDEN * RATE), int(SCHRITT_SEKUNDEN * RATE)
    fenster = []  # (aeusserung, von, bis, proben)
    for k, (start, _, proben) in enumerate(aeusserungen):
        if len(proben) < RATE:  # wie live: kürzer als 1 s bekommt keinen Fingerabdruck
            continue
        anfaenge = list(range(0, max(1, len(proben) - f + 1), s)) if len(proben) >= f else [0]
        for i in anfaenge:
            fenster.append((k, start + i / RATE, start + min(len(proben), i + f) / RATE, proben[i:i + f]))
    LABOR.mkdir(parents=True, exist_ok=True)
    for modell in MODELLE:
        ziel = LABOR / f"{name}.{kurz(modell)}.npz"
        if ziel.exists():
            continue
        ext = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(WURZEL / "modelle" / modell), num_threads=4))
        vek = []
        for _, _, _, p in fenster:
            st = ext.create_stream()
            st.accept_waveform(RATE, p)
            st.input_finished()
            vek.append(normiert(np.array(ext.compute(st))))
        np.savez(ziel, vek=np.array(vek), aeusserung=np.array([x[0] for x in fenster]),
                 von=np.array([x[1] for x in fenster]), bis=np.array([x[2] for x in fenster]))
        print(f"  {name} {kurz(modell)}: {len(vek)} Fenster", flush=True)


def bewerten(abschnitte: list[tuple[float, float, int]], ref: list[dict]) -> float:
    """Anteil Referenz-Sprechzeit mit richtiger Person (beste 1:1-Zuordnung), Raster 0,25 s."""
    abschnitte = sorted(abschnitte)
    starts = np.array([a[0] for a in abschnitte])
    paare: dict[tuple, int] = {}
    for r in ref:
        for t in np.arange(r["von"], r["bis"], RASTER):
            i = int(np.searchsorted(starts, t, side="right")) - 1
            p = abschnitte[i][2] if i >= 0 and abschnitte[i][0] <= t < abschnitte[i][1] else None
            paare[(p, r["person"])] = paare.get((p, r["person"]), 0) + 1
    gesamt = sum(paare.values())
    richtig, frei_p, frei_r = 0, set(), set()
    for (p, r), n in sorted(paare.items(), key=lambda x: -x[1]):
        if p is not None and p not in frei_p and r not in frei_r:
            richtig += n
            frei_p.add(p)
            frei_r.add(r)
    return richtig / gesamt


def fenster_zu_abschnitten(von, bis, personen) -> list[tuple[float, float, int]]:
    """Überlappende Fenster -> lückenlose Abschnitte: jedes Fenster gilt ab seiner Mitte minus halber Schritt."""
    aus = []
    for v, b, p in zip(von, bis, personen):
        if p is None:
            continue
        mitte = (v + b) / 2
        aus.append((mitte - SCHRITT_SEKUNDEN / 2 - (0.375 if b - v >= FENSTER_SEKUNDEN else 0), b, int(p)))
    # Anfang des ersten Fensters einer Äußerung bis zur ersten Mitte mit abdecken
    return [(max(a, 0.0), b, p) for a, b, p in aus]


def online(d, schwelle: float) -> list[int | None]:
    reg = Personenregister(schwelle)
    aus: list[int | None] = []
    for k in np.unique(d["aeusserung"]):
        idx = np.where(d["aeusserung"] == k)[0]
        aus += reg.fenster_zuordnen([d["vek"][i] for i in idx], SCHRITT_SEKUNDEN)
    return aus


def vorstellung(d, ref: list[dict], probe_sek: float = 8.0, lernen: bool = True) -> list[int]:
    """Stimmprobe je Person: deren erste probe_sek Sekunden laut Referenz (simuliert die Vorstellungsrunde)."""
    personen = sorted({r["person"] for r in ref})
    schwer = []
    for p in personen:
        gesammelt, idx = 0.0, []
        for r in [r for r in ref if r["person"] == p]:
            treffer = np.where((d["von"] >= r["von"]) & (d["bis"] <= r["bis"] + 0.2))[0]
            idx += list(treffer)
            gesammelt += r["bis"] - r["von"]
            if gesammelt >= probe_sek and len(idx) >= 3:
                break
        schwer.append(normiert(np.sum(d["vek"][idx], axis=0)) if idx else np.zeros(d["vek"].shape[1]))
    summen = [s.copy() for s in schwer]
    aus = []
    for k in np.unique(d["aeusserung"]):
        idx = np.where(d["aeusserung"] == k)[0]
        roh = []
        for i in idx:
            sims = [float(d["vek"][i] @ normiert(s)) for s in summen]
            j = int(np.argmax(sims))
            roh.append(j)
            if lernen and sims[j] >= 0.6:  # nur sichere Fenster lernen mit
                summen[j] = summen[j] + d["vek"][i] * 0.2
        glatt = [max(set(roh[max(0, i - 1):i + 2]), key=roh[max(0, i - 1):i + 2].count) for i in range(len(roh))]
        aus += glatt
    return aus


def anzahl(d, k: int) -> list[int]:
    from sklearn.cluster import AgglomerativeClustering

    return list(AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(d["vek"]))


def messen(namen: list[str]) -> None:
    zeilen = []
    for modell in MODELLE:
        m = kurz(modell)
        for name in namen:
            pfad = LABOR / f"{name}.{m}.npz"
            if not pfad.exists():
                continue
            d = dict(np.load(pfad))
            ref = json.loads((PROBEN / name / "probe.json").read_text(encoding="utf-8"))["referenz"]["sprecher"]
            n_ref = len({r["person"] for r in ref})
            erg = {}
            for s in (0.4, 0.5, 0.6):
                p = online(d, s)
                erg[f"online {s}"] = bewerten(fenster_zu_abschnitten(d["von"], d["bis"], p), ref)
            erg["vorstellung"] = bewerten(fenster_zu_abschnitten(d["von"], d["bis"], vorstellung(d, ref)), ref)
            erg["vorstellung fest"] = bewerten(fenster_zu_abschnitten(d["von"], d["bis"], vorstellung(d, ref, lernen=False)), ref)
            try:
                erg["anzahl bekannt"] = bewerten(fenster_zu_abschnitten(d["von"], d["bis"], anzahl(d, n_ref)), ref)
            except ImportError:
                pass
            zeilen.append((m, name, erg))
            print(f"{m:16} {name:14} " + "  ".join(f"{k} {v:5.1%}" for k, v in erg.items()), flush=True)
    # Mittel je Modell und Strategie
    print()
    for modell in MODELLE:
        m = kurz(modell)
        z = [e for mm, _, e in zeilen if mm == m]
        if z:
            print(f"{m:16} Mittel " + "  ".join(f"{k} {np.mean([e[k] for e in z]):5.1%}" for k in z[0]))


if __name__ == "__main__":
    if sys.argv[1] == "vorbereiten":
        for n in sys.argv[2:]:
            vorbereiten(n)
    else:
        messen(sys.argv[2:])
