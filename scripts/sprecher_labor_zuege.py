r"""Sprecher-Labor, Auswertung nach Zuglänge: Wie gut sitzt die Zuordnung bei kurzen und langen Beiträgen, und wie
genau sind die Redeanteile? Läuft auf den Fingerabdrücken aus scripts/sprecher_labor.py (CAM++), nur AMI-Proben.

    .venvScriptspython scriptssprecher_labor_zuege.py
"""
import json, sys, numpy as np
sys.path.insert(0, 'scripts'); sys.argv = ['x']
import sprecher_labor as L
R = 0.25
def frames(abschnitte, T):
    lab = np.full(len(T), -1)
    for a, b, p in abschnitte:
        lab[(T >= a) & (T < b)] = p
    return lab
for name in ['ami_ES2002a', 'ami_ES2002b', 'ami_ES2002c', 'ami_ES2002d']:
    d = dict(np.load(f'logs/sprecherlabor/{name}.campplus.npz'))
    ref = json.loads(open(f'testbibliothek/proben/{name}/probe.json', encoding='utf-8').read())['referenz']['sprecher']
    pers = sorted({r['person'] for r in ref}); T = np.arange(0, max(r['bis'] for r in ref), R)
    aktiv = np.zeros((len(pers), len(T)), bool)
    for r in ref: aktiv[pers.index(r['person']), (T >= r['von']) & (T < r['bis'])] = True
    # Zuglänge: zusammenhängende Aktivität je Person mit Lücken < 1 s
    zug = np.zeros((len(pers), len(T)))
    for i in range(len(pers)):
        a = aktiv[i].copy(); idx = np.where(a)[0]
        if not len(idx): continue
        start = idx[0]; prev = idx[0]
        for j in list(idx[1:]) + [None]:
            if j is None or j - prev > 1 / R:
                zug[i, start:prev + 1] = (prev - start + 1) * R; start = j
            if j is not None: prev = j
    einer = aktiv.sum(0) == 1
    wer = np.argmax(aktiv, 0); laenge = zug[wer, np.arange(len(T))]
    for strat, p in [('heute', L.online(d, 0.5)), ('vorstellung', L.vorstellung(d, ref))]:
        lab = frames(L.fenster_zu_abschnitten(d['von'], d['bis'], p), T)
        # beste 1:1-Zuordnung auf Einzelsprecher-Frames
        paare = {}
        for t in np.where(einer & (lab >= 0))[0]:
            paare[(lab[t], wer[t])] = paare.get((lab[t], wer[t]), 0) + 1
        zu, fp, fr = {}, set(), set()
        for (a, b), n in sorted(paare.items(), key=lambda x: -x[1]):
            if a not in fp and b not in fr: zu[a] = b; fp.add(a); fr.add(b)
        ok = np.array([zu.get(lab[t], -9) == wer[t] for t in range(len(T))])
        txt = []
        for lo, hi in [(0, 3), (3, 10), (10, 30), (30, 1e9)]:
            m = einer & (laenge >= lo) & (laenge < hi)
            txt.append(f'Zug {lo}-{hi if hi < 1e9 else "∞"}s ({m.mean() / einer.mean():.0%}): {ok[m].mean():.0%}')
        # Redeanteile: Referenz vs erkannt (nach Zuordnung)
        ref_ant = aktiv.sum(1) / aktiv.sum()
        erk = np.array([sum(1 for t in range(len(T)) if lab[t] >= 0 and zu.get(lab[t]) == i) for i in range(len(pers))], float)
        erk_ant = erk / max(1, (lab >= 0).sum())
        fehler = np.abs(ref_ant - erk_ant).max()
        print(f'{name} {strat:11} ' + ' | '.join(txt) + f' | Redeanteil max. Abweichung {fehler * 100:.0f} Pkt')
