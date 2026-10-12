"""Prüfstand für Nestors Verstehen: echte Anfragen gegen das echte Modell der Stufe, ohne Mikrofon und ohne Ton.

Jeder Fall baut ein frisches Meeting auf (Agenda, Transkript bis zum Zeitpunkt der Anfrage, aktiver Punkt, schon
Festgehaltenes, letzte Recherche, frühere Antworten) und stellt EINE Anfrage über die Sprechtaste. Mitgeschnitten
wird, was Nestor sagt, welche Werkzeuge er aufruft und welche Karten entstehen. Bewertet wird regelbasiert:
Hat er etwas mit Inhalt gesagt? Kommen die erwarteten Begriffe vor? Hat er das richtige Werkzeug genommen und
keins der verbotenen?

Grundlage der Sofa-Fälle ist die Datenspende vom 12.10.2026 (Niclas allein, Basis): die Anfragen sind wörtlich,
das Transkript ist die Whisper-Fassung der Aufnahme. Dazu typische Moderationsbitten.

    ~/.venvs/lmc/bin/python scripts/nestor_pruefstand.py --stufe basis --bericht logs/pruefstand/basis_vorher
    ~/.venvs/lmc/bin/python scripts/nestor_pruefstand.py --stufe premium --nur S1,S2

Schlüssel aus der Umgebung (LMC_MISTRAL_SCHLUESSEL bzw. OPENAI_API_KEY). Kosten: wenige Cent je Durchlauf.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.config import EINST  # noqa: E402

AGENDA = [
    {"titel": "Optionen für die Sofa-Platzierung sammeln", "minuten": 10},
    {"titel": "Kriterien für die Entscheidung festlegen", "minuten": 10},
    {"titel": "Optionen bewerten und vergleichen", "minuten": 15},
    {"titel": "Endgültige Entscheidung treffen", "minuten": 10},
]

# Whisper-Fassung der Aufnahme (Sekunde, Text) – nur Niclas spricht
TRANSKRIPT = [
    (30, "Ich bin Niclas und lege mal los."),
    (57, "Wir können das Sofa vor das Fenster stellen."),
    (61, "Wir können es an die große Wand stellen."),
    (64, "Wir können es in die Nische stellen."),
    (66, "Und wir können es direkt hinter die Tür stellen."),
    (71, "Das sollten dann quasi so die ersten wesentlichen Optionen sein."),
    (77, "Wenn jetzt keiner was sagt, dann bin ich der Einzige, der dazu was zu sagen hat."),
    (83, "Ich spreche einfach mal noch weiter."),
    (152, "Kannst du mal jetzt die wesentlichen Optionen nochmal zusammenfassen, die wir haben für das Sofa stellen?"),
    (175, "Du solltest sagen, welche Optionen wir haben für das Sofa, wie wir es stellen."),
    (192, "Okay, und das Nächste wäre dann direkt vor das Fenster. Also haben wir eigentlich vier Optionen."),
    (254, "Gut, dann gehen wir zum nächsten Agenda-Punkt."),
    (263, "Okay, relevante Faktoren. Kommen wir mal wieder zum Thema."),
    (283, "Licht, Raumaufteilung, Nutzerkomfort."),
    (287, "Beim Fenster sitzt man natürlich mit dem Rücken zum Licht. Das ist gut zum Lesen. Aber man kann nicht "
          "rausschauen."),
    (296, "Wenn wir es in die Nische stellen, dann schauen wir nur an die Wand."),
    (300, "Dafür hat der Raum noch das größte Raumgefühl, wenn wir es an die lange Wand stellen."),
]

RECHERCHE_FENG_SHUI = {
    "frage": "Grundlagen Feng Shui für die Platzierung eines Sofas",
    "text": ("Feng Shui empfiehlt für das Sofa die sogenannte Kommandoposition: mit dem Rücken an eine feste Wand, "
             "mit Blick zur Tür, aber nicht direkt in einer Linie mit ihr. Ein Sofa frei im Raum oder mit dem Rücken "
             "zum Fenster gilt als unruhig, weil die Rückendeckung fehlt. Der Weg durch den Raum soll frei bleiben, "
             "das Sofa soll den Eingang nicht blockieren. Natürliches Licht von der Seite ist günstig."),
    "quellen": [{"titel": "Feng Shui im Wohnzimmer", "url": "https://example.org/feng-shui"}],
}

OPTIONEN = ("fenster", "wand", "nische", "tür")

# Fälle: t = Meetingzeit der Anfrage, punkt = aktiver Agendapunkt (0-basiert), frage = wörtlich
# erwartet: sprechen (Inhalt gesagt), woerter (mind. n der Begriffe in Gesagtem + Karten), werkzeug (eins davon),
# verboten (keins davon). Werkzeugnamen wie im Katalog coach/werkzeuge.py.
FAELLE = [
    {"id": "S1", "quelle": "Spende 01:52", "t": 152, "punkt": 0,
     "frage": "Kannst du mal jetzt die wesentlichen Optionen nochmal zusammenfassen, die wir haben für das Sofa stellen?",
     "sprechen": True, "woerter": (OPTIONEN, 3), "verboten": ["recherchieren", "agendapunkt_wechseln"]},
    {"id": "S2", "quelle": "Spende 02:41", "t": 161, "punkt": 0,
     "verlauf": [("Sag, welche Optionen wir haben für das Sofa.",
                  "Ihr habt bisher drei Optionen: an die große Wand, in die Nische oder direkt hinter die Tür.")],
     "karten": [{"art": "antwort", "titel": "Optionen fürs Sofa",
                 "punkte": ["An die große Wand", "In die Nische", "Direkt hinter die Tür"]}],
     "transkript_extra": [(158, "Okay, und das Nächste wäre dann direkt vor das Fenster. Also haben wir eigentlich "
                                "vier Optionen.")],
     "frage": "Kannst du die vierte Option noch ergänzen auf der Antwortfolie? Also welche Platzierung wir haben für "
              "das Sofa.",
     "sprechen": True, "woerter": (OPTIONEN, 4), "verboten": ["ergebnis_aendern", "ergebnis_entfernen",
                                                               "recherchieren"]},
    {"id": "S3", "quelle": "Spende 03:21", "t": 261, "punkt": 1,
     "frage": "Sag uns nochmal, was wir jetzt hier genau machen bei dem Agenda-Punkt.",
     "sprechen": True, "woerter": (("kriteri",), 1), "verboten": ["agendapunkt_wechseln", "recherchieren"]},
    {"id": "S4", "quelle": "Spende 04:56", "t": 302, "punkt": 2,
     "frage": "Kannst du uns nochmal aus Agendapunkt 1 die Optionen raussuchen, die wir hatten für das Sofa stellen?",
     "sprechen": True, "woerter": (OPTIONEN, 3), "verboten": ["recherchieren", "agendapunkt_wechseln"]},
    {"id": "S5", "quelle": "Spende 05:25", "t": 335, "punkt": 2,
     "frage": "Kannst du uns mal die Grundlagen von Feng Shui raussuchen, was wir da beachten müssten, wenn wir das "
              "Sofa jetzt stellen?",
     "sprechen": False, "werkzeug": ["recherchieren"], "verboten": ["artefakt_eintragen"]},
    {"id": "S6", "quelle": "Spende 05:55", "t": 360, "punkt": 2, "recherche": True,
     "frage": "Kannst du mir die Folie kurz vorstellen, die du recherchiert hast?",
     "sprechen": True, "woerter": (("rücken", "wand", "tür", "kommando", "blick"), 2), "verboten": ["recherchieren"]},
    {"id": "M1", "quelle": "Moderation", "t": 258, "punkt": 0,
     "frage": "Gut, dann gehen wir zum nächsten Agendapunkt.",
     "werkzeug": ["agendapunkt_wechseln"], "verboten": ["recherchieren"]},
    {"id": "M2", "quelle": "Moderation", "t": 330, "punkt": 2,
     "frage": "Lass uns nochmal kurz zu Punkt eins zurück.",
     "werkzeug": ["agendapunkt_wechseln"], "verboten": ["recherchieren"]},
    {"id": "M3", "quelle": "Moderation", "t": 330, "punkt": 3,
     "frage": "Fürs Protokoll: wir stellen das Sofa an die lange Wand.",
     "sprechen": True, "werkzeug": ["artefakt_eintragen"], "verboten": ["recherchieren", "ergebnis_entfernen"]},
    {"id": "M4", "quelle": "Moderation", "t": 330, "punkt": 2,
     "artefakte": [{"typ": "aufgabe", "was": "Maße der Nische ausmessen", "wer": "Niclas", "bis": "Freitag"}],
     "frage": "Streich die Aufgabe mit dem Ausmessen wieder, das brauchen wir nicht.",
     "sprechen": True, "werkzeug": ["ergebnis_entfernen"], "verboten": ["recherchieren"]},
    {"id": "M5", "quelle": "Moderation", "t": 330, "punkt": 2,
     "frage": "Wie viel Zeit haben wir noch für diesen Punkt?",
     "sprechen": True, "woerter": (("minute",), 1), "verboten": ["recherchieren", "agendapunkt_wechseln"]},
    {"id": "M6", "quelle": "#89 Voxtral", "t": 330, "punkt": 2,
     "frage": "findel mir mal die Ergebnisse",
     "sprechen": True, "woerter": (OPTIONEN, 2), "verboten": ["recherchieren"]},
    {"id": "M7", "quelle": "Moderation", "t": 330, "punkt": 2,
     "frage": "Mach uns eine Karte mit Vor- und Nachteilen je Option.",
     "sprechen": True, "werkzeug": ["karte"], "woerter": (OPTIONEN, 3), "verboten": ["recherchieren"]},
    {"id": "M8", "quelle": "Moderation", "t": 330, "punkt": 2,
     "frage": "Was fehlt uns noch, damit wir entscheiden können?",
     "sprechen": True, "verboten": ["recherchieren", "agendapunkt_wechseln"]},
]

# Alte Aktionen (Text-Weg mit „AKTION:“) auf die Werkzeugnamen abbilden, damit beide Wege gleich bewertet werden
ALT = {"recherche": "recherchieren", "weiter": "agendapunkt_wechseln", "eintragen": "artefakt_eintragen",
       "entfernen": "ergebnis_entfernen", "aendern": "ergebnis_aendern", "bild": "bild_zeichnen",
       "folie": "folie_erstellen", "pause": "zuhoeren_pausieren", "neu_aufbereiten": "karte_neu_aufbereiten"}


def werkzeuge_aus(eintrag: dict) -> list[str]:
    namen = [w["name"] for w in eintrag.get("werkzeuge") or [] if not w.get("fehler")]
    art = eintrag.get("art")  # alter Text-Weg: vorsortierte Bögen (Wortmuster) statt Werkzeug
    if art == "recherche" or art == "bild":
        namen.append(ALT[art])
    elif art == "zusammenfassen":
        namen.append("zusammenfassen")
    elif art in ("fehlt", "stand", "festgehalten", "ueberblick"):
        namen.append("karte_zeigen")
    a = eintrag.get("aktion")
    if a and a.get("typ") == "karte":
        namen.append("zusammenfassen" if a.get("art") == "zusammenfassen" else "karte_zeigen")
    elif a and a.get("typ") in ALT:
        namen.append(ALT[a["typ"]])
    return namen


async def fall_laufen(fall: dict, stufe: str) -> dict:
    from coach.pipeline import Coach
    from coach.zustand import Segment

    nestor: list[dict] = []
    import coach.pipeline as P

    P._zeit_loggen = nestor.append
    P.nutzung_loggen = lambda e: None
    c = Coach()
    c.stufe_setzen(stufe)
    c._einrichten({"titel": "Wohnzimmer: wohin mit dem Sofa?", "ziel": "Einen Platz für das neue Sofa festlegen",
                   "agenda": AGENDA, "teilnehmende": ["Niclas", "Sophia"]})
    m = c.meeting
    m.starten(virtuell=True)
    zeilen = [z for z in TRANSKRIPT if z[0] < fall["t"]] + list(fall.get("transkript_extra", []))
    segmente = [Segment("Niclas", text, float(t), float(t) + len(text) / 14) for t, text in sorted(zeilen)]
    m.segmente_hinzufuegen(segmente)
    m.virtuelle_zeit = float(fall["t"])
    m.aktiver_punkt = fall["punkt"]
    for daten in fall.get("artefakte", []):
        c.artefakte.eintragen(daten, herkunft="erkannt")
    for k in fall.get("karten", []):
        c._karte_ablegen({**k, "zeit": fall["t"] - 20})
    if fall.get("recherche"):
        c.letzte_recherche = dict(RECHERCHE_FENG_SHUI)
        c._karte_ablegen({"art": "recherche", "titel": RECHERCHE_FENG_SHUI["frage"],
                          "punkte": [RECHERCHE_FENG_SHUI["text"]], "zeit": fall["t"] - 15, "still": True})
    a = c.assistent
    a.verlauf.extend(fall.get("verlauf", []))
    karten_vorher = len(c.karten)
    gesagt: list[dict] = []
    sprechen_alt, floskel_alt = a._sprechen, a.floskel_sagen

    async def sprechen(text, *args, **kw):
        gesagt.append({"art": "satz", "text": text})
        return await sprechen_alt(text, *args, **kw)

    async def floskel(text, *args, **kw):
        gesagt.append({"art": "floskel", "text": text})
        return await floskel_alt(text, *args, **kw)

    a._sprechen, a.floskel_sagen = sprechen, floskel
    t0 = time.monotonic()
    b = a.annehmen(fall["frage"], "taste")
    while time.monotonic() - t0 < 60 and (a.bogen is not None or (b is not None and b.task and not b.task.done())):
        await asyncio.sleep(0.2)
    await asyncio.sleep(1.5)  # Antwortkarte (verdichten) läuft im Hintergrund nach
    for auftrag in list(a.auftraege.liste):  # Recherche/Bild nicht wirklich zu Ende laufen lassen
        a.auftrag_abbrechen(auftrag.id)
    if a.gespraech is not None:
        await a.gespraech.schliessen("pruefstand")
    sekunden = round(time.monotonic() - t0, 1)
    bogen = [e for e in nestor if e.get("ausloeser") == "bogen"]
    eintrag = bogen[-1] if bogen else {}
    neue_karten = [{"art": k.get("art"), "titel": k.get("titel"), "punkte": k.get("punkte")}
                   for k in c.karten[karten_vorher:]]
    artefakte = [{"nr": x.id, "typ": x.typ, "was": x.was} for x in c.artefakte.liste]
    return {"id": fall["id"], "frage": fall["frage"], "gesagt": gesagt, "antwort": eintrag.get("antwort"),
            "werkzeuge": werkzeuge_aus(eintrag), "roh": {k: eintrag.get(k) for k in ("aktion", "werkzeuge", "fehler")},
            "karten": neue_karten, "artefakte": artefakte, "aktiver_punkt": m.aktiver_punkt, "sekunden": sekunden}


def bewerten(fall: dict, erg: dict) -> dict:
    # Basis spricht über _sprechen, Premium über das Realtime-Modell selbst (dann steht es nur in „antwort“)
    saetze = " ".join(g["text"] for g in erg["gesagt"] if g["art"] == "satz") or (erg.get("antwort") or "")
    alles = (saetze + " " + (erg.get("antwort") or "") + " " + json.dumps(erg["karten"], ensure_ascii=False)).lower()
    pruefungen = []
    if fall.get("sprechen"):
        pruefungen.append(("spricht mit Inhalt", len(saetze.strip()) >= 15))
    if fall.get("woerter"):
        woerter, n = fall["woerter"]
        treffer = [w for w in woerter if w in alles]
        pruefungen.append((f"nennt ≥{n} von {'/'.join(woerter)}", len(treffer) >= n))
    if fall.get("werkzeug"):
        pruefungen.append((f"Werkzeug {' oder '.join(fall['werkzeug'])}",
                           any(w in erg["werkzeuge"] for w in fall["werkzeug"])))
    for w in fall.get("verboten", []):
        pruefungen.append((f"kein {w}", w not in erg["werkzeuge"]))
    if fall["id"] == "M1":
        pruefungen.append(("aktiver Punkt danach 2", erg["aktiver_punkt"] == 1))
    if fall["id"] == "M2":
        pruefungen.append(("aktiver Punkt danach 1", erg["aktiver_punkt"] == 0))
    ok = all(p[1] for p in pruefungen)
    return {"ok": ok, "pruefungen": [{"was": w, "ok": o} for w, o in pruefungen]}


async def protokoll_pruefen(stufe: str) -> dict:
    """Landen die besprochenen Optionen und Kriterien im Protokoll? Abschnitt Punkt 1 und Punkt 2/3 auswerten."""
    from coach.pipeline import Coach
    from coach.zustand import Segment
    import coach.pipeline as P

    P._zeit_loggen = lambda e: None
    P.nutzung_loggen = lambda e: None
    c = Coach()
    c.stufe_setzen(stufe)
    c._einrichten({"titel": "Wohnzimmer: wohin mit dem Sofa?", "agenda": AGENDA, "teilnehmende": ["Niclas", "Sophia"]})
    m = c.meeting
    m.starten(virtuell=True)
    m.segmente_hinzufuegen([Segment("Niclas", text, float(t), float(t) + len(text) / 14) for t, text in TRANSKRIPT])
    m.virtuelle_zeit = 320.0
    await c.artefakte.abschnitt_abschliessen(0, 250.0, "punkt")
    await c.artefakte.abschnitt_abschliessen(2, 320.0, "punkt")
    liste = [{"nr": a.id, "typ": a.typ, "was": a.was} for a in c.artefakte.liste]
    text = json.dumps(liste, ensure_ascii=False).lower()
    optionen = [o for o in OPTIONEN if o in text]
    kriterien = [k for k in ("licht", "raumgefühl", "komfort", "lesen", "rausschauen") if k in text]
    return {"liste": liste, "optionen": optionen, "kriterien": kriterien,
            "ok": len(optionen) >= 3 and len(kriterien) >= 2}


async def haupt(args) -> None:
    object.__setattr__(EINST, "stimme_aus", True)
    object.__setattr__(EINST, "bestaetigung", False)
    faelle = [f for f in FAELLE if not args.nur or f["id"] in args.nur.split(",")]
    ergebnisse = []
    for runde in range(args.runden):
        for fall in faelle:
            try:
                erg = await fall_laufen(fall, args.stufe)
            except Exception as e:  # noqa: BLE001
                erg = {"id": fall["id"], "frage": fall["frage"], "fehler": f"{type(e).__name__}: {e}", "gesagt": [],
                       "werkzeuge": [], "karten": [], "aktiver_punkt": None}
            erg["runde"] = runde + 1
            erg["bewertung"] = bewerten(fall, erg)
            ergebnisse.append(erg)
            zeichen = "✓" if erg["bewertung"]["ok"] else "✗"
            gesagt = " | ".join(g["text"] for g in erg["gesagt"])[:160]
            print(f"{zeichen} {fall['id']} r{runde + 1} [{', '.join(erg['werkzeuge']) or '-'}] {gesagt}", flush=True)
    protokoll = None if args.ohne_protokoll else await protokoll_pruefen(args.stufe)
    if protokoll:
        print(f"{'✓' if protokoll['ok'] else '✗'} Protokoll: Optionen {protokoll['optionen']}, "
              f"Kriterien {protokoll['kriterien']}", flush=True)
    bestanden = sum(e["bewertung"]["ok"] for e in ergebnisse)
    print(f"\n{args.stufe}: {bestanden}/{len(ergebnisse)} Anfragen bestanden", flush=True)
    if args.bericht:
        ziel = Path(args.bericht)
        ziel.mkdir(parents=True, exist_ok=True)
        (ziel / "ergebnisse.json").write_text(json.dumps(
            {"stufe": args.stufe, "bestanden": bestanden, "gesamt": len(ergebnisse), "faelle": ergebnisse,
             "protokoll": protokoll}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--stufe", choices=("basis", "premium"), required=True)
    p.add_argument("--nur", default="", help="Fall-IDs, kommagetrennt")
    p.add_argument("--runden", type=int, default=1)
    p.add_argument("--bericht", default="")
    p.add_argument("--ohne-protokoll", action="store_true")
    p.add_argument("--neu-bewerten", default="", help="ergebnisse.json eines Laufs neu bewerten (ohne Modell)")
    args = p.parse_args()
    if args.neu_bewerten:
        pfad = Path(args.neu_bewerten)
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        nach_id = {f["id"]: f for f in FAELLE}
        for e in daten["faelle"]:
            e["bewertung"] = bewerten(nach_id[e["id"]], e)
            print(f"{'✓' if e['bewertung']['ok'] else '✗'} {e['id']} r{e['runde']} "
                  + "; ".join(p["was"] for p in e["bewertung"]["pruefungen"] if not p["ok"]))
        daten["bestanden"] = sum(e["bewertung"]["ok"] for e in daten["faelle"])
        pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{daten['stufe']}: {daten['bestanden']}/{daten['gesamt']}")
    else:
        asyncio.run(haupt(args))
