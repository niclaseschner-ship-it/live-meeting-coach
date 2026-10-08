r"""Abwechselnd reden im Cloud-Testlauf (Ticket #25): die Teilnehmenden warten, bis Nestor fertig ist.

Bis #25 lief das Meeting-Audio am Stück durch (`--use-file-for-fake-audio-capture`). Seit Nestor unterbrechbar
ist (#23), hätte der Test ihn ständig unterbrochen. Jetzt ersetzt ein Init-Script `getUserMedia` durch eine
WebAudio-Quelle, die der Test abschnittsweise füttert und anhält:

- Die Audiodatei wird an den Satzgrenzen aus der Referenz in Abschnitte geschnitten: nach jedem Grenzfall bzw.
  Teil eines Grenzfalls, für den die Referenz `warten` setzt (Ansprache an Nestor mit erwarteter Antwort).
- Vor dem ersten Abschnitt wartet der Test die Begrüßung ab, nach jedem Schnitt Nestors Antwort: Zustand wieder
  `bereit`/`gespraech`, seit ≥ 1,5 s kein `stimme`-Paket, im Browser keine Wiedergabe mehr (`stimme.naechste`
  in static/basis.js), stabil über 2 s. Zeitlimit mit Befund statt Hängen (60 s, Begrüßung 120 s).
  `warten: "bestaetigung"` (Bild, Folie: „macht ruhig weiter“) wartet nur, bis die erste Rückmeldung zu Ende
  gesprochen ist, `warten: false` (Hineinreden, Fehlauslöser) gar nicht.
- Nach dem Warten wird die Stille übersprungen, die das Material für eine Antwort am Stück vorgesehen hatte
  (bis auf 0,8 s) – sonst säßen alle nach jeder Antwort noch 22 s stumm da.
- Ein Zeitplan (Quellzeit ↔ Laufachse) wird mitgeschrieben; damit rechnen Bewertung und HTML-Bericht die
  Referenzzeiten auf die tatsächliche Meetinguhr um, und die Tonspur im Bericht enthält die Pausen.

Reine Funktionen hier (Abschnitte, Zeitabbildung, Prüfungen), die Browser-Regie unten in `Regie`.
"""

from __future__ import annotations

import asyncio
import base64
import bisect
import json
import time
import wave
from pathlib import Path

import numpy as np

RATE = 24000
STILLE_SCHWELLE = 64  # int16-Betrag; das synthetische Material hat in den Lücken echte Nullen
STILLE_BEHALTEN_S = 0.8  # so viel Pause bleibt nach Nestors Antwort, bevor jemand weiterredet
REAKTION_FRIST_S = 10.0  # reagiert Nestor so lange gar nicht, geht das Meeting weiter (Befund „keine Reaktion“)
BEGRUESSUNG_REAKTION_S = 25.0
FERTIG_RUHE_S = 1.5  # kein stimme-Paket seit so vielen Sekunden
STABIL_S = 2.0  # „fertig“ muss so lange ununterbrochen gelten (Zustand springt zwischen Satz und Werkzeug)
ZEITLIMIT_S = 60.0
BEGRUESSUNG_LIMIT_S = 120.0
TAKT_S = 0.25

NESTOR_FERTIG = ("bereit", "gespraech")
NESTOR_ARBEITET = ("angesprochen", "denkt", "recherchiert", "spricht")
NESTOR_REAGIERT = ("denkt", "recherchiert", "spricht")  # „angesprochen“ setzt die Realtime-VAD bei jedem Sprecher

# Standard, wenn die Referenz für einen Grenzfall kein `warten` angibt (referenz_grenzfaelle.json setzt es seit
# #25 ausdrücklich für jeden Fall).
WARTEN_STANDARD = {
    "antwort": True, "ja_dann_antwort": True, "antwort_mit_quellen": True,
    "antwort_erwuenscht_dokumentieren": True,
    "folie": "bestaetigung", "nachfrage_oder_bild_mit_fokus": "bestaetigung",
}


def warten_von(g: dict):
    return g.get("warten", WARTEN_STANDARD.get(g.get("erwartet"), False))


# ---------- Material ----------
def wav_laden(pfad: Path) -> np.ndarray:
    with wave.open(str(pfad), "rb") as w:
        if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{pfad}: erwartet 24 kHz mono 16 bit")
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def material_pruefen(referenz: dict, pcm: np.ndarray) -> str | None:
    """Passt die Audiodatei zur Referenz? Sonst stimmen alle Schnitte nicht (z. B. neue Referenz mit Rückfragen
    aus #25, aber noch die alte meeting_grenzfaelle.wav im Hauptordner). Meldung oder None."""
    dauer = len(pcm) / RATE
    if abs(dauer - referenz["dauer_s"]) > 0.5:
        return (f"Audiodatei {dauer:.1f} s, Referenz {referenz['dauer_s']:.1f} s – passt nicht zusammen "
                "(Material neu bauen, siehe docs/cloudtest.md)")
    return None


def schnittpunkte(referenz: dict) -> list[dict]:
    """Wo das Meeting-Audio anhält: Ende jedes Teils mit eigenem `warten`, sonst Ende des letzten Teils eines
    Grenzfalls mit `warten`; im älteren #9-Schema (`nestor`, Vereinsrunde) nach jeder Anweisung – bei Bild/Folie
    nur bis zur Bestätigung. Aufsteigend nach Quellzeit."""
    aus = []
    for i, n in enumerate(referenz.get("nestor", [])):
        modus = n.get("warten", "bestaetigung" if n.get("bild") else True)
        if modus:
            aus.append({"quelle_s": n["ende"], "modus": modus, "id": f"anweisung_{i + 1}", "teil": 0,
                        "erwartet": "antwort", "text": n["text"]})
    for g in referenz.get("grenzfaelle", []):
        teile = g.get("teile") or [{"start": g["start"], "ende": g["ende"], "text": ""}]
        for i, t in enumerate(teile):
            letzter = i == len(teile) - 1
            modus = t.get("warten", warten_von(g) if letzter else False)
            if modus:
                aus.append({"quelle_s": t["ende"], "modus": modus, "id": g["id"], "teil": i,
                            "erwartet": g.get("erwartet"), "text": t.get("text", "")})
    aus.sort(key=lambda s: s["quelle_s"])
    return aus


def stille_ueberspringen(pcm: np.ndarray, von_s: float, bis_s: float, behalten_s: float = STILLE_BEHALTEN_S) -> float:
    """Neuer Abschnittsbeginn: führende Stille ab `von_s` bis auf `behalten_s` weglassen."""
    a, b = int(von_s * RATE), int(bis_s * RATE)
    laut = np.flatnonzero(np.abs(pcm[a:b].astype(np.int32)) > STILLE_SCHWELLE)
    if not len(laut):
        return von_s
    erster = (a + int(laut[0])) / RATE
    return max(von_s, round(erster - behalten_s, 3))


def abschnitte_bauen(referenz: dict, pcm: np.ndarray, bis_s: float | None = None,
                     ohne_warten: bool = False) -> list[dict]:
    """[{nr, von, bis, warten: None | Schnittpunkt}] in Quellzeit. Der erste Abschnitt beginnt nach dem Vorlauf
    (Stille für die Begrüßung, die der Test jetzt abwartet), jeder Abschnitt nach einem Warten nach der für die
    Antwort am Stück vorgesehenen Stille. `bis_s` kürzt das Material (kurze Probeläufe)."""
    ende = min(len(pcm) / RATE, bis_s) if bis_s else len(pcm) / RATE
    schnitte = [] if ohne_warten else [s for s in schnittpunkte(referenz) if s["quelle_s"] < ende - 0.5]
    aus, von = [], stille_ueberspringen(pcm, 0.0, ende)
    for s in schnitte:
        if s["quelle_s"] <= von:
            continue
        aus.append({"nr": len(aus), "von": round(von, 3), "bis": s["quelle_s"], "warten": s})
        von = stille_ueberspringen(pcm, s["quelle_s"], ende)
    aus.append({"nr": len(aus), "von": round(von, 3), "bis": round(ende, 3), "warten": None})
    return aus


def referenz_kuerzen(referenz: dict, bis_s: float | None) -> dict:
    """Für Probeläufe mit `--bis`: nur, was in der gekürzten Quelle vorkommt."""
    if not bis_s:
        return referenz
    r = json.loads(json.dumps(referenz))
    r["ereignisse"] = [e for e in r.get("ereignisse", []) if e["zeit_s"] < bis_s]
    r["nestor"] = [n for n in r.get("nestor", []) if n["ende"] < bis_s]
    r["grenzfaelle"] = [g for g in r.get("grenzfaelle", []) if g["ende"] < bis_s]
    r["dauer_s"] = min(r["dauer_s"], bis_s)
    return r


# ---------- Zeitabbildung Quellzeit -> Meetinguhr ----------
def uhr_versatz(zustaende: list[dict]) -> float | None:
    """Meetinguhr − Laufachse: Median aus (zustand.zeit − Empfangszeit) über alle Zustände während des
    Hörens. Laufachse = ws.jsonl-Zeit `t` = Zeitplan-Zeiten der Regie (beide relativ zum Laufstart). Nur
    Meldungen, deren Uhr seit der vorigen weitergelaufen ist: steht der Server (Cloudlauf 08.10.: Meetinguhr
    blieb ab 217,6 s stehen, die Seite bekam weiter denselben Stand), würden die alten Stände den Median
    verziehen."""
    d, vorige = [], None
    for z in zustaende:
        if z.get("hoeren") and z.get("zeit", 0) > 0 and z["zeit"] != vorige:
            d.append(z["zeit"] - z["_t"])
        vorige = z.get("zeit")
    d.sort()
    return d[len(d) // 2] if d else None


def zeitplan_auf_meetinguhr(zeitplan: list[dict], versatz: float) -> list[dict]:
    return [{**a, "meeting_von": round(a["t_start"] + versatz, 3)} for a in zeitplan]


def quelle_zu_meeting(r: float, plan: list[dict]) -> float:
    """Quellzeit `r` → Meetinguhr über den (auf die Meetinguhr gebrachten) Zeitplan. Liegt `r` in übersprungener
    Stille, zählt der Beginn des nächsten Abschnitts (bzw. das Ende des letzten)."""
    if not plan:
        return r
    for a in plan:
        if a["von"] - 1e-6 <= r <= a["bis"] + 1e-6:
            return a["meeting_von"] + (r - a["von"])
    for a in plan:
        if r < a["von"]:
            return a["meeting_von"]
    letzter = plan[-1]
    return letzter["meeting_von"] + (letzter["bis"] - letzter["von"]) + (r - letzter["bis"])


def referenz_auf_meetinguhr(referenz: dict, plan: list[dict]) -> dict:
    """Kopie der Referenz mit allen Zeiten auf der Meetinguhr (Pausen verschieben alles danach)."""
    r = json.loads(json.dumps(referenz))
    f = lambda x: round(quelle_zu_meeting(x, plan), 2)  # noqa: E731
    for e in r.get("ereignisse", []):
        e["zeit_s"] = f(e["zeit_s"])
    for n in r.get("nestor", []):
        n["start"], n["ende"] = f(n["start"]), f(n["ende"])
    for g in r.get("grenzfaelle", []):
        g["start"], g["ende"] = f(g["start"]), f(g["ende"])
        for t in g.get("teile", []):
            t["start"], t["ende"] = f(t["start"]), f(t["ende"])
    if plan:
        r["dauer_s"] = round(plan[-1]["meeting_von"] + plan[-1]["bis"] - plan[-1]["von"], 1)
    return r


def meeting_spur(pcm: np.ndarray, plan: list[dict], dauer_s: float) -> np.ndarray:
    """Meeting-Ton so, wie er im Browser lief: jeder Abschnitt an seiner Stelle auf der Meetinguhr, dazwischen
    die Pausen (Ticket #25: „die Tonspur im Bericht enthält die Pausen“)."""
    aus = np.zeros(int(dauer_s * RATE) + 1, dtype=np.int16)
    for a in plan:
        stueck = pcm[int(a["von"] * RATE):int(a["bis"] * RATE)]
        ziel = int(round(a["meeting_von"] * RATE))
        if ziel < 0:
            stueck, ziel = stueck[-ziel:], 0
        n = max(0, min(len(stueck), len(aus) - ziel))
        aus[ziel:ziel + n] = stueck[:n]
    return aus


def wav_schreiben(pfad: Path, pcm: np.ndarray) -> None:
    with wave.open(str(pfad), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.astype("<i2").tobytes())


# ---------- Prüfungen aus #21 Punkt 5 ----------
def stimme_platzieren(frames: list[dict]) -> list[dict]:
    """Wo jedes stimme-Paket auf der Laufachse erklingt – wie static/basis.js abspielt: jedes Stück beginnt bei
    seiner Ankunft oder, wenn das vorige noch läuft, direkt danach (nicht Ankunft plus Stücklänge, sonst wächst
    bei schneller als Echtzeit geschickten Stücken ein Versatz auf). `stimme_stopp` beendet die Wiedergabe wie
    stimme.stopp(): laufende und eingereihte Stücke werden dort abgeschnitten, das nächste beginnt bei seiner
    Ankunft (Ticket #25/#21 Punkt 5: sonst rutscht nach einer Unterbrechung alles Weitere nach hinten).
    [{t, pos, dauer, pcm}] – `pcm` ist das Base64 der Nachricht."""
    import base64

    aus: list[dict] = []
    pos = 0.0
    for f in frames:
        d = f["daten"]
        if f["richtung"] != "empfangen" or not isinstance(d, dict):
            continue
        if d.get("typ") == "stimme":
            dauer = len(base64.b64decode(d["pcm"])) // 2 / RATE
            start = max(f["t"], pos)
            aus.append({"t": f["t"], "pos": start, "dauer": dauer, "pcm": d["pcm"]})
            pos = start + dauer
        elif d.get("typ") == "stimme_stopp":
            for p in reversed(aus):
                if p["pos"] + p["dauer"] <= f["t"]:
                    break
                p["dauer"] = max(0.0, f["t"] - p["pos"])
            pos = 0.0
    return aus


def stimme_bloecke(platzierung: list[dict], luecke_s: float = 1.0) -> list[dict]:
    """Zusammenhängende Wiedergaben aus der Platzierung der stimme-Pakete (cloudtest.stimme_platzieren):
    neuer Block, wenn ein Paket erst nach mehr als `luecke_s` Ruhe beginnt. [{start_t, ende_t, start_pos}]."""
    bloecke: list[dict] = []
    for p in platzierung:
        if bloecke and p["pos"] - bloecke[-1]["ende_pos"] <= luecke_s:
            bloecke[-1]["ende_pos"] = p["pos"] + p["dauer"]
            bloecke[-1]["ende_t"] = max(bloecke[-1]["ende_t"], p["t"])
            continue
        bloecke.append({"start_t": p["t"], "ende_t": p["t"], "start_pos": p["pos"], "ende_pos": p["pos"] + p["dauer"]})
    return bloecke


def antwort_texte(zustaende: list[dict]) -> list[dict]:
    """Jede neue gespeicherte Antwort (assistent.letzte – daraus zeigt das Dashboard Karte bzw. Untertitel):
    [{t, zeit, frage, antwort}] mit Laufachse `t` der ersten Meldung, in der sie auftaucht."""
    aus, gesehen = [], set()
    for z in zustaende:
        l = (z.get("assistent") or {}).get("letzte") or {}
        if not l.get("antwort"):
            continue
        schluessel = (l.get("zeit"), l.get("antwort"))
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        aus.append({"t": z["_t"], "zeit": l.get("zeit"), "frage": l.get("frage") or "", "antwort": l["antwort"]})
    return aus


def ton_text_paare(bloecke: list[dict], texte: list[dict], ab_t: float = 0.0,
                   vor_s: float = 30.0, nach_s: float = 20.0) -> tuple[list[dict], list[dict]]:
    """(Ton ohne Text, Text ohne Ton). Ein Ton-Block hat seinen Text, wenn eine Antwort zwischen Blockbeginn − 5 s
    und Blockende + `nach_s` gespeichert wurde (eine kurze Bestätigung vor der eigentlichen Antwort zählt mit);
    ein Text hat seinen Ton, wenn ein Block zwischen Text − `vor_s` und Text + 10 s spielte. Begrüßung (vor
    `ab_t`) ausgenommen – sie hat absichtlich keine Karte."""
    bloecke = [b for b in bloecke if b["start_t"] >= ab_t]
    texte = [x for x in texte if x["t"] >= ab_t]
    ton_ohne = [b for b in bloecke
                if not any(b["start_t"] - 5 <= x["t"] <= b["ende_t"] + nach_s for x in texte)]
    text_ohne = [x for x in texte
                 if not any(x["t"] - vor_s <= b["start_t"] <= x["t"] + 10 for b in bloecke)]
    return ton_ohne, text_ohne


def _mmss(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def zustand_bei(zustaende: list[dict], t: float) -> str | None:
    i = bisect.bisect_right([z["_t"] for z in zustaende], t) - 1
    return ((zustaende[i].get("assistent") or {}).get("zustand")) if i >= 0 else None


def bestaetigung_messen(zustaende: list[dict], stimme: list[dict], t_frage_ende: float,
                        bis_t: float) -> tuple[float | None, float | None]:
    """(sichtbar_s, ton_s) ab dem Ende der Frage (Laufachse): erstes sichtbares Zeichen, dass Nestor arbeitet
    (Zustand angesprochen/denkt/recherchiert/spricht – stand er schon beim Frage-Ende darauf, 0), und erster
    Ton. None, wenn bis `bis_t` nichts kam."""
    sichtbar = None
    if zustand_bei(zustaende, t_frage_ende) in NESTOR_ARBEITET:
        sichtbar = 0.0
    else:
        for z in zustaende:
            if t_frage_ende < z["_t"] <= bis_t and (z.get("assistent") or {}).get("zustand") in NESTOR_ARBEITET:
                sichtbar = round(z["_t"] - t_frage_ende, 2)
                break
    ton = next((round(s["_t"] - t_frage_ende, 2) for s in stimme if t_frage_ende - 0.5 <= s["_t"] <= bis_t), None)
    return sichtbar, ton


def tonspur_abweichungen(platzierung: list[dict], zustaende: list[dict], versatz_nestor: float,
                         luecke_s: float = 1.0) -> list[dict]:
    """#21 Punkt 5: liegt Nestors Stimme in der Tonspur des Berichts dort, wo sie ankam? Je Block das erste
    Paket: Lage in nestor_stimme.wav + Verschiebung im Bericht gegen die Ankunft auf der Meetinguhr (über die
    zeitlich nächste Zustandsmeldung). [{t, ankunft, im_bericht, abweichung}]"""
    if not zustaende:
        return []
    ts = [z["_t"] for z in zustaende]
    aus = []
    for b in stimme_bloecke(platzierung, luecke_s):
        i = bisect.bisect_left(ts, b["start_t"])
        nah = min((j for j in (i - 1, i) if 0 <= j < len(ts)), key=lambda j: abs(ts[j] - b["start_t"]))
        ankunft = zustaende[nah]["zeit"] + (b["start_t"] - ts[nah])
        im_bericht = b["start_pos"] + versatz_nestor
        aus.append({"t": round(b["start_t"], 2), "ankunft": round(ankunft, 2), "im_bericht": round(im_bericht, 2),
                    "abweichung": round(im_bericht - ankunft, 2)})
    return aus


def takt_pruefpunkte(takt: dict, zustaende: list[dict], stimme_platzierung: list[dict], stimme: list[dict],
                     versatz_nestor: float | None, offline: bool = False) -> tuple[list[dict], dict]:
    """Prüfpunkte und Kennzahlen zum abwechselnden Reden (#25) und aus #21 Punkt 5. Getrennt von der
    Referenz-Prüfliste, damit Treffer/Verpasst dort vergleichbar mit älteren Läufen bleiben."""
    aus: list[dict] = []
    k: dict = {}

    def pruefen(name: str, status: str, detail: str = "") -> None:
        aus.append({"name": name, "status": status, "detail": detail})

    pausen = takt.get("pausen", [])
    begr = next((p for p in pausen if p["art"] == "begruessung"), None)
    if begr is not None:
        ungestoert = begr["ergebnis"] == "fertig" and not begr.get("stopps")
        k["begruessung_s"] = begr.get("ton_dauer_s")
        k["begruessung_ungestoert"] = ungestoert
        if begr["ergebnis"] == "keine_reaktion":
            pruefen("Takt: Begrüßung ungestört durchgelaufen", "beobachtet",
                    f"keine Begrüßung binnen {BEGRUESSUNG_REAKTION_S:.0f} s (offline/Knopfdruck?)")
        else:
            pruefen("Takt: Begrüßung ungestört durchgelaufen", "ok" if ungestoert else "fehlt",
                    f"{begr['ergebnis']}, gesprochen {begr.get('ton_dauer_s') or 0:.0f} s, abgewartet "
                    f"{begr['dauer_s']:.0f} s, Abbrüche (stimme_stopp) {begr.get('stopps', 0)}")

    sichtbar, ton = [], []
    for p in pausen:
        if p["art"] != "grenzfall":
            continue
        name = f"Takt: Nestor abgewartet nach {p['id']}" + (f" (Teil {p['teil'] + 1})" if p.get("teil") else "")
        teile = [f"Warten {p['dauer_s']:.1f} s ({'bis zur Bestätigung' if p['modus'] == 'bestaetigung' else 'bis fertig'})"]
        if p.get("sichtbar_s") is not None:
            teile.append(f"sichtbar nach {p['sichtbar_s']:.1f} s")
            sichtbar.append(p["sichtbar_s"])
        if p.get("ton_s") is not None:
            teile.append(f"erster Ton nach {p['ton_s']:.1f} s")
            ton.append(p["ton_s"])
        if p.get("stopps"):
            teile.append(f"{p['stopps']}× stimme_stopp")
        if p["ergebnis"] == "zeitlimit":
            pruefen(name, "fehlt", "Zeitlimit erreicht, Nestor nicht fertig – " + ", ".join(teile))
        elif p["ergebnis"] in ("abgebrochen", "kein_hoeren"):
            pruefen(name, "fehlt", f"{p['ergebnis']} (Meetinguhr steht bzw. Hörstrom aus) – " + ", ".join(teile))
        elif p["ergebnis"] == "keine_reaktion":
            pruefen(name, "beobachtet", f"keine Reaktion binnen {REAKTION_FRIST_S:.0f} s – " + ", ".join(teile))
        else:
            pruefen(name, "ok", ", ".join(teile))

        if p.get("rueckfrage") and offline:
            pruefen(f"Takt: Rückfrage im Redefluss {p['id']}", "offline", "ohne Schlüssel keine Antwort möglich")
        elif p.get("rueckfrage"):
            weiter = p.get("weiter_segmente")
            ok = p["ergebnis"] == "fertig" and p.get("ton_s") is not None and (weiter is None or weiter > 0)
            pruefen(f"Takt: Rückfrage im Redefluss {p['id']}", "ok" if ok else "fehlt",
                    ("beantwortet" if p.get("ton_s") is not None else "nicht beantwortet")
                    + (f", danach {weiter} neue Segmente in 30 s" if weiter is not None else ""))

    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None
    k["bestaetigung_sichtbar_median_s"], k["bestaetigung_sichtbar_max_s"] = median(sichtbar), max(sichtbar, default=None)
    k["erster_ton_median_s"], k["erster_ton_max_s"] = median(ton), max(ton, default=None)
    k["zeitlimits"] = sum(1 for p in pausen if p["ergebnis"] == "zeitlimit")

    # Ton und Text je Antwort
    ab_t = begr["t_ende"] if begr else 0.0
    bloecke = stimme_bloecke(stimme_platzierung)
    texte = antwort_texte(zustaende)
    ton_ohne, text_ohne = ton_text_paare(bloecke, texte, ab_t)
    k["antworten_text"], k["ton_bloecke"] = len([x for x in texte if x["t"] >= ab_t]), len(
        [b for b in bloecke if b["start_t"] >= ab_t])
    k["ton_ohne_text"], k["text_ohne_ton"] = len(ton_ohne), len(text_ohne)
    detail = f"{k['ton_bloecke']} Ton-Blöcke, {k['antworten_text']} Antworttexte"
    if ton_ohne:
        uhr = versatz_nestor or 0.0  # Laufachse → Meetinguhr
        detail += "; Ton ohne Text bei " + ", ".join(
            f"{_mmss(b['start_t'] + uhr)} ({b['ende_pos'] - b['start_pos']:.1f} s)" for b in ton_ohne[:6]) + \
            (" Meetinguhr" if versatz_nestor is not None else " Laufachse")
    if text_ohne:
        detail += "; nur Text, nicht gesprochen: " + "; ".join(f"„{x['antwort'][:50]}“" for x in text_ohne[:3])
    pruefen("Takt: zu jeder Antwort Ton und Text", "ok" if not (ton_ohne or text_ohne) else "fehlt", detail)

    # Tonspur im Bericht gegen die Ankunft der Stimme
    if versatz_nestor is not None and stimme_platzierung:
        abw = tonspur_abweichungen(stimme_platzierung, zustaende, versatz_nestor)
        groesste = max(abw, key=lambda a: abs(a["abweichung"]), default=None)
        k["tonspur_abweichung_max_s"] = abs(groesste["abweichung"]) if groesste else None
        schlecht = [a for a in abw if abs(a["abweichung"]) > 1.0]
        pruefen("Takt: Tonspur im Bericht ≤ 1 s neben der Ankunft der Stimme", "fehlt" if schlecht else "ok",
                f"{len(abw)} Blöcke, größte Abweichung {groesste['abweichung']:+.2f} s" if groesste else "keine Blöcke"
                + (f"; > 1 s bei {', '.join(str(a['ankunft']) + 's' for a in schlecht[:5])}" if schlecht else ""))
    return aus, k


# ---------- Browser: steuerbares Mikrofon ----------
INIT_SCRIPT = r"""
(() => {
  const RATE = 24000;
  const md = navigator.mediaDevices;
  const original = md && md.getUserMedia ? md.getUserMedia.bind(md) : null;
  const m = window.__testMikro = {
    ctx: null, bus: null, quelle: null, puffer: {}, laeuft: false, nr: -1, stroeme: 0,
    _ctx() {
      if (!this.ctx) { this.ctx = new AudioContext({ sampleRate: RATE }); this.bus = this.ctx.createGain(); }
      this.ctx.resume();
      return this.ctx;
    },
    strom() {  // je getUserMedia ein eigener Strom: die Seite stoppt die Spuren beim Beenden
      const c = this._ctx(), ziel = c.createMediaStreamDestination();
      this.bus.connect(ziel); this.stroeme++;
      return ziel.stream;
    },
    laden(nr, b64) {
      const c = this._ctx(), roh = atob(b64), n = roh.length >> 1;
      const puffer = c.createBuffer(1, n, RATE), d = puffer.getChannelData(0);
      for (let i = 0; i < n; i++) {
        let v = roh.charCodeAt(2 * i) | (roh.charCodeAt(2 * i + 1) << 8);
        if (v >= 32768) v -= 65536;
        d[i] = v / 32768;
      }
      this.puffer[nr] = puffer;
      return puffer.duration;
    },
    starten(nr) {
      const c = this._ctx(), q = c.createBufferSource();
      if (this.quelle) { try { this.quelle.stop(); } catch (e) {} }
      q.buffer = this.puffer[nr]; delete this.puffer[nr];
      q.connect(this.bus);
      q.onended = () => { if (this.quelle === q) { this.quelle = null; this.laeuft = false; } };
      this.quelle = q; this.laeuft = true; this.nr = nr;
      q.start();
      return c.currentTime;
    },
    stand() {
      return { laeuft: this.laeuft, nr: this.nr, stroeme: this.stroeme,
               uhr: this.ctx ? this.ctx.currentTime : null };
    },
  };
  if (md) md.getUserMedia = async (c) => (c && c.audio ? m.strom() : original(c));
})();
"""

# Was die Seite gerade tut: Nestors Zustand und ob noch Ton im Browser ansteht (static/basis.js: stimme.naechste
# ist das geplante Ende der zuletzt eingereihten Wiedergabe, stopp() setzt es auf 0).
SEITE_STAND = """() => ({
  z: (typeof zustand !== 'undefined' && zustand && zustand.assistent) ? zustand.assistent.zustand : null,
  rest: (typeof stimme !== 'undefined' && stimme.ctx) ? Math.max(0, stimme.naechste - stimme.ctx.currentTime) : 0,
  hoeren: (typeof zustand !== 'undefined' && zustand) ? !!zustand.hoeren : false,
})"""


class Regie:
    """Spielt die Abschnitte über das steuerbare Mikrofon ab und wartet dazwischen auf Nestor. Alle Zeiten auf
    der Laufachse (Sekunden seit Laufstart, wie ws.jsonl)."""

    def __init__(self, seite, spur, pcm: np.ndarray, abschnitte: list[dict], lauf_start: float,
                 notieren, referenz: dict) -> None:
        self.seite, self.spur, self.pcm, self.abschnitte = seite, spur, pcm, abschnitte
        self.lauf_start, self.notieren, self.referenz = lauf_start, notieren, referenz
        self.zeitplan: list[dict] = []
        self.pausen: list[dict] = []
        self.fertig = False
        self.abbrechen = False  # aufzeichnen() setzt das, wenn die Meetinguhr steht
        self.screenshot_ziele: list[float] = []  # Laufachse; aufzeichnen() rechnet auf die Meetinguhr um
        self._aufgaben: list[asyncio.Future] = []
        self.rueckfragen = {g["id"] for g in referenz.get("grenzfaelle", []) if g.get("nach")}

    def jetzt(self) -> float:
        return time.monotonic() - self.lauf_start

    async def stand(self) -> dict:
        try:
            return await self.seite.evaluate(SEITE_STAND)
        except Exception:  # noqa: BLE001 – Seite navigiert/lädt gerade
            return {"z": None, "rest": 0, "hoeren": False}

    async def abwarten(self, art: str, modus, t_bezug: float, limit_s: float, reaktion_s: float,
                       info: dict) -> dict:
        """Wartet, bis Nestor fertig ist (siehe Moduldoku). t_bezug: Ende der Frage bzw. Meetingstart."""
        t0 = self.jetzt()
        stopps0 = self.spur.stopp_zahl
        reagiert = False
        stabil_seit = None
        ergebnis = "fertig"
        while True:
            jetzt = self.jetzt()
            s = await self.stand()
            letzte_stimme = self.spur.letzte_stimme_t
            stimme_seit = letzte_stimme is not None and letzte_stimme >= t_bezug - 0.5
            if stimme_seit or s["z"] in NESTOR_REAGIERT:
                reagiert = True
            ruhe = (letzte_stimme is None or jetzt - letzte_stimme >= FERTIG_RUHE_S) and s["rest"] <= 0.05
            if modus == "bestaetigung" and stimme_seit:
                fertig = ruhe  # nur die erste Rückmeldung abwarten („macht ruhig weiter“)
            else:
                fertig = reagiert and ruhe and s["z"] in NESTOR_FERTIG
            if not s["hoeren"] and jetzt - t0 > 3:
                ergebnis = "kein_hoeren"
                break
            if fertig:
                stabil_seit = stabil_seit if stabil_seit is not None else jetzt
                if jetzt - stabil_seit >= STABIL_S:
                    break
            else:
                stabil_seit = None
            if not reagiert and jetzt - t_bezug >= reaktion_s and s["z"] not in NESTOR_ARBEITET and ruhe:
                ergebnis = "keine_reaktion"
                break
            if jetzt - t0 >= limit_s:
                ergebnis = "zeitlimit"
                break
            if self.abbrechen:
                ergebnis = "abgebrochen"
                break
            await asyncio.sleep(TAKT_S)
        t_ende = self.jetzt()
        ton = self.spur.stimme_dauer_seit(t_bezug - 0.5)
        p = {"art": art, "modus": modus, **info, "t_bezug": round(t_bezug, 3), "t_ende": round(t_ende, 3),
             "dauer_s": round(t_ende - t0, 1), "ergebnis": ergebnis, "reagiert": reagiert,
             "stopps": self.spur.stopp_zahl - stopps0, "ton_dauer_s": round(ton, 1)}
        self.pausen.append(p)
        self.notieren(f"Takt: {art} {info.get('id', '')} – {ergebnis} nach {p['dauer_s']:.1f} s "
                      f"(Nestor sprach {ton:.1f} s, stimme_stopp {p['stopps']}×)")
        return p

    async def abspielen(self, a: dict) -> None:
        stueck = self.pcm[int(a["von"] * RATE):int(a["bis"] * RATE)]
        b64 = base64.b64encode(stueck.astype("<i2").tobytes()).decode("ascii")
        dauer = await self.seite.evaluate("([nr, b]) => window.__testMikro.laden(nr, b)", [a["nr"], b64])
        del b64
        vor = self.jetzt()
        await self.seite.evaluate("(nr) => window.__testMikro.starten(nr)", a["nr"])
        t_start = (vor + self.jetzt()) / 2
        self.zeitplan.append({"nr": a["nr"], "von": a["von"], "bis": a["bis"], "t_start": round(t_start, 3),
                              "t_ende": round(t_start + dauer, 3)})
        # Screenshot-Ziele: jedes Ereignis/jeder Grenzfall in diesem Abschnitt, auf der Laufachse
        for zeit in ([e["zeit_s"] for e in self.referenz.get("ereignisse", [])]
                     + [n["start"] for n in self.referenz.get("nestor", [])]
                     + [g["start"] for g in self.referenz.get("grenzfaelle", [])]):
            if a["von"] <= zeit < a["bis"]:
                self.screenshot_ziele.append(t_start + zeit - a["von"])
        self.screenshot_ziele.sort()
        await asyncio.sleep(max(0.0, dauer - 0.5))
        while (await self.seite.evaluate("() => window.__testMikro.stand().laeuft")):
            await asyncio.sleep(0.05)

    def segmente_seit(self, t: float) -> int:
        """Wie viele neue Segmente das Transkript seit Laufzeit t bekam (läuft das Meeting weiter?)."""
        mit = [f for f in self.spur.frames if isinstance(f["daten"], dict) and "segmente" in f["daten"]]
        vorher = [f for f in mit if f["t"] < t]
        nachher = [f for f in mit if f["t"] >= t]
        if not nachher:
            return 0
        schl = lambda f: {(s.get("start"), s.get("text")) for s in f["daten"]["segmente"] or []}  # noqa: E731
        return len(schl(nachher[-1]) - (schl(vorher[-1]) if vorher else set()))

    async def lauf(self, begruessung: bool = True) -> None:
        try:
            if begruessung:
                await self.abwarten("begruessung", True, self.jetzt(), BEGRUESSUNG_LIMIT_S, BEGRUESSUNG_REAKTION_S,
                                    {})
            for a in self.abschnitte:
                if self.abbrechen:
                    self.notieren("Takt: abgebrochen (Meetinguhr steht) – keine weiteren Abschnitte.")
                    break
                s = await self.stand()
                if not s["hoeren"]:
                    self.notieren("Takt: Hörstrom ist aus – Abspielen beendet.")
                    break
                await self.abspielen(a)
                w = a.get("warten")
                if not w:
                    continue
                t_frage = self.zeitplan[-1]["t_ende"]
                info = {"id": w["id"], "teil": w["teil"], "erwartet": w["erwartet"], "quelle_s": w["quelle_s"],
                        "rueckfrage": w["id"] in self.rueckfragen}
                limit = ZEITLIMIT_S
                p = await self.abwarten("grenzfall", w["modus"], t_frage, limit, REAKTION_FRIST_S, info)
                zust = self.spur.zustaende()
                stimme = self.spur.nachrichten("stimme")
                p["sichtbar_s"], p["ton_s"] = bestaetigung_messen(zust, stimme, t_frage, p["t_ende"])
                rest = sum(b["bis"] - b["von"] for b in self.abschnitte[a["nr"] + 1:])
                if p["rueckfrage"] and rest >= 5.0:  # läuft das Meeting nach der Rückfrage weiter?
                    self._aufgaben.append(asyncio.ensure_future(self._weiter_messen(p, p["t_ende"])))
        finally:
            self.fertig = True

    async def _weiter_messen(self, p: dict, t_weiter: float) -> None:
        await asyncio.sleep(30.0)
        p["weiter_segmente"] = self.segmente_seit(t_weiter)

    def ergebnis(self) -> dict:
        return {"zeitplan": self.zeitplan, "pausen": self.pausen,
                "abschnitte": [{k: v for k, v in a.items() if k != "warten"} | {"warten": bool(a.get("warten"))}
                               for a in self.abschnitte]}
