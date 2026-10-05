r"""Sprecher-Labor, Teil 2: Segmentierung (pyannote 3.0) statt fester Fenster – mit „Person ?“ und Überlappung.

    .venv\Scripts\python scripts\sprecher_labor_segment.py ami_ES2002a ami_ES2002b ami_ES2002c ami_ES2002d

Je Äußerung (Pausenerkennung wie live, höchstens 10 s) schneidet coach/segmentierung.py nach lokalen Stimmen und
Überlappung; jede lokale Stimme bekommt einen Fingerabdruck (CAM++) aus ihren allein gesprochenen Stellen.
Zwischenergebnisse in logs/sprecherlabor/<probe>.segm.json. Bewertet in 0,25-s-Schritten:
- Einzelsprecher-Momente laut Referenz: richtig / falsch / unsicher („Person ?“ oder nicht erfasst)
- Überlappung: Anteil der Referenz-Überlappung, die erkannt wird (Trefferquote), und Anteil der erkannten
  Überlappung, die wirklich eine ist (Genauigkeit)
Zum Vergleich dieselben Maße für die heutigen festen Fenster (Fingerabdrücke aus scripts/sprecher_labor.py).
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from coach.config import EINST  # noqa: E402
from coach.hoeren import nach_16k  # noqa: E402
from coach.stimmen import normiert  # noqa: E402
from coach.vad import Pausenerkennung  # noqa: E402

WURZEL = Path(__file__).resolve().parent.parent
PROBEN = WURZEL / "testbibliothek" / "proben"
AUDIO = WURZEL / "testbibliothek" / "audio"
LABOR = WURZEL / "logs" / "sprecherlabor"
RATE, R = 16000, 0.25


def vorbereiten(name: str) -> list[dict]:
    ziel = LABOR / f"{name}.segm.json"
    if ziel.exists():
        return json.loads(ziel.read_text(encoding="utf-8"))
    import sherpa_onnx

    from coach.segmentierung import Segmentierer

    with wave.open(str(AUDIO / f"{name}.wav")) as w:
        a = nach_16k(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768)
    vad, seg = Pausenerkennung(), Segmentierer()
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(WURZEL / "modelle" / EINST.stimm_modell), num_threads=4))
    aus = []
    for u, (start, _, proben) in enumerate(vad.zufuehren(a) + vad.ende()):
        erg = seg.analysieren(proben)
        for k, stuecke in erg["stimmen"].items():
            teile = [proben[int(x * RATE):int(y * RATE)] for x, y in stuecke]
            dauer = sum(len(t) for t in teile) / RATE
            vek = None
            if dauer >= 0.5:
                st = ext.create_stream()
                st.accept_waveform(RATE, np.concatenate(teile))
                st.input_finished()
                vek = normiert(np.array(ext.compute(st))).tolist()
            aus.append({"u": u, "k": k, "dauer": round(dauer, 2), "vek": vek,
                        "stuecke": [[round(start + x, 2), round(start + y, 2)] for x, y in stuecke]})
        for x, y in erg["ueberlappung"]:
            aus.append({"u": u, "k": -1, "ueberlappung": [round(start + x, 2), round(start + y, 2)]})
    LABOR.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(aus), encoding="utf-8")
    return aus


def zuordnen(items: list[dict], schwelle: float, min_neu: float, vorgabe: list[np.ndarray] | None = None,
             unsicher: float = 0.0) -> list[int | None]:
    """Online in Zeitreihenfolge. Mit vorgabe (Vorstellungsrunde): geschlossene Menge, unter `unsicher` -> None."""
    summen = [v.copy() for v in vorgabe] if vorgabe else []
    aus = []
    for it in items:
        if it.get("vek") is None:
            aus.append(None)
            continue
        v = np.array(it["vek"])
        sims = [float(v @ normiert(s)) for s in summen]
        k = int(np.argmax(sims)) if sims else None
        if k is not None and (sims[k] >= schwelle or (vorgabe is not None and sims[k] >= unsicher)):
            summen[k] = summen[k] + v * it["dauer"] * (0.2 if vorgabe else 1)
            aus.append(k)
        elif vorgabe is None and it["dauer"] >= min_neu:
            summen.append(v * it["dauer"])
            aus.append(len(summen) - 1)
        else:
            aus.append(None)
    return aus


def bewerten(abschnitte: list[tuple[float, float, int | None]], ueber: list[tuple[float, float]], ref: list[dict]) -> dict:
    personen = sorted({r["person"] for r in ref})
    T = np.arange(0, max(r["bis"] for r in ref), R)
    aktiv = np.zeros((len(personen), len(T)), bool)
    for r in ref:
        aktiv[personen.index(r["person"]), (T >= r["von"]) & (T < r["bis"])] = True
    lab = np.full(len(T), -2)  # -2 nichts erfasst, -1 „Person ?“
    for a, b, p in abschnitte:
        lab[(T >= a) & (T < b)] = -1 if p is None else p
    ue = np.zeros(len(T), bool)
    for a, b in ueber:
        ue[(T >= a) & (T < b)] = True
    lab[ue] = -1  # Überlappung wird als „?“ angezeigt
    einer = aktiv.sum(0) == 1
    wer = aktiv.argmax(0)
    paare: dict = {}
    for t in np.where(einer & (lab >= 0))[0]:
        paare[(lab[t], wer[t])] = paare.get((lab[t], wer[t]), 0) + 1
    zu, fp, fr = {}, set(), set()
    for (a, b), n in sorted(paare.items(), key=lambda x: -x[1]):
        if a not in fp and b not in fr:
            zu[a] = b
            fp.add(a)
            fr.add(b)
    m = np.where(einer)[0]
    richtig = np.mean([lab[t] >= 0 and zu.get(lab[t]) == wer[t] for t in m])
    unsicher = np.mean([lab[t] < 0 for t in m])
    ref_ue = aktiv.sum(0) >= 2
    treffer = (ue & ref_ue).sum() / max(1, ref_ue.sum())
    genau = (ue & ref_ue).sum() / max(1, ue.sum())
    return {"richtig": richtig, "falsch": 1 - richtig - unsicher, "unsicher": unsicher,
            "ueberlappung_treffer": treffer, "ueberlappung_genau": genau}


def vorstellung_vektoren(items: list[dict], ref: list[dict], probe_sek: float = 8.0) -> list[np.ndarray]:
    """Stimmprobe je Person: Segmente, die in deren ersten probe_sek Sekunden Referenz-Sprechzeit liegen."""
    aus = []
    for p in sorted({r["person"] for r in ref}):
        segs, gesammelt = [], 0.0
        for r in [r for r in ref if r["person"] == p]:
            gesammelt += r["bis"] - r["von"]
            segs.append((r["von"], r["bis"]))
            if gesammelt >= probe_sek:
                break
        vs = [np.array(it["vek"]) * it["dauer"] for it in items if it.get("vek") is not None and any(
            a - 0.2 <= it["stuecke"][0][0] and it["stuecke"][-1][1] <= b + 0.2 for a, b in segs)]
        aus.append(normiert(np.sum(vs, axis=0)) if vs else np.zeros(192))
    return aus


def main() -> None:
    import sprecher_labor as L

    gesamt: dict[str, list[dict]] = {}
    for name in sys.argv[1:]:
        ref = json.loads((PROBEN / name / "probe.json").read_text(encoding="utf-8"))["referenz"]["sprecher"]
        alle = vorbereiten(name)
        items = sorted([i for i in alle if i["k"] >= 0], key=lambda i: i["stuecke"][0][0])
        ueber = [tuple(i["ueberlappung"]) for i in alle if i["k"] == -1]

        def abschn(personen, luecke: float = 0.6):
            roh = sorted((a, b, p) for it, p in zip(items, personen) for a, b in it["stuecke"])
            # kurze Lücken schließen (Atempausen): Abschnitt bis zum nächsten verlängern, wenn < luecke
            return [(a, nb if 0 < nb - b < luecke else b, p)
                    for (a, b, p), (nb, _, _) in zip(roh, roh[1:] + [(1e9, 0, None)])]

        ergebnisse = {}
        # heute: feste Fenster, keine Überlappung im Signal, kein „?“
        d = dict(np.load(LABOR / f"{name}.campplus.npz"))
        ergebnisse["heute (Fenster)"] = bewerten(L.fenster_zu_abschnitten(d["von"], d["bis"], L.online(d, 0.5)), [], ref)
        for s in (0.45, 0.5, 0.55):
            ergebnisse[f"Segment online {s}"] = bewerten(abschn(zuordnen(items, s, 1.5)), ueber, ref)
        vorg = vorstellung_vektoren(items, ref)
        for u in (0.0, 0.3):
            ergebnisse[f"Segment + Vorstellung, ? unter {u}"] = bewerten(
                abschn(zuordnen(items, 1.0, 99, vorgabe=vorg, unsicher=u)), ueber, ref)
        for k, e in ergebnisse.items():
            gesamt.setdefault(k, []).append(e)
            print(f"{name:13} {k:32} richtig {e['richtig']:5.1%}  falsch {e['falsch']:5.1%}  ? {e['unsicher']:5.1%}  "
                  f"Überlappung erkannt {e['ueberlappung_treffer']:5.1%} (davon echt {e['ueberlappung_genau']:5.1%})", flush=True)
    print("\nMittel")
    for k, es in gesamt.items():
        print(f"{k:32} " + "  ".join(f"{m} {np.mean([e[m] for e in es]):5.1%}" for m in es[0]))


if __name__ == "__main__":
    main()
