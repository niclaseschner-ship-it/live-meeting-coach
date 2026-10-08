r"""Baut das Testmaterial für Ticket #11 (Qualitätsrubrik, Grenzfälle der Ansprache): ein neues, technischeres
synthetisches Meeting plus zwölf eingeschnittene Grenzfälle der Ansprache-Erkennung, mit erwartetem Verhalten
in referenz.json. Getrennt von testbibliothek/cloudtest/bauen.py (#9, Vereinsrunde) – andere Quelle, andere
Zielsekunden, nicht überschreiben.

    LMC_CODEX_BEFEHL=codex ~/.venvs/lmc/bin/python testbibliothek/cloudtest/bauen_grenzfaelle.py

Schritt 1 (drehbuch): Codex über das ChatGPT-Abo (keine API-Kosten) schreibt ein Drehbuch „Incident-Review:
Ausfall des Kundenportals am Montag“ – IT-Team, 4 Personen, mit Fachsprache (Kubernetes, Rollback, Postgres,
Monitoring, SLA, Postmortem) und den sechs Ereignissen aus #9 (Monolog, Ansage, Abschweifung, Kraftausdruck,
Beschluss, Aufgabe ohne Zuständig). Eine Äußerung ist ausdrücklich als durchgehender Redebeitrag über 90 s
angefordert – in #9 blieben einzelne „monolog“-Äußerungen oft unter der 60-s-Schwelle der lokalen Erkennung
und wurden darum nicht erkannt (kein Fehler in Nestor, nur zu kurzes Material; siehe #9-Bericht).
Schritt 2 (vertonen): wie #9, Azure über Teachbuddy auf diesem Rechner, 0 $.
Schritt 3 (grenzfaelle_einfuegen): die zwölf Fälle aus dem Ticket, jeder mit erwartetem Verhalten in
referenz.json["grenzfaelle"]. Fall 9 (leise, schnell) bekommt eine eigene Nachbearbeitung (ffmpeg: Tempo
1,2×, −12 dB).

Ergebnis in testbibliothek/cloudtest/: drehbuch_grenzfaelle.json, referenz_grenzfaelle.json,
agenda_prompt_grenzfaelle.txt (im Git) und meeting_grenzfaelle.wav (per .gitignore ausgenommen).

Ticket #25 (abwechselnd reden): jeder Grenzfall trägt `warten` (true / "bestaetigung" / false, siehe
scripts/cloudtest_takt.py), und zwei Rückfragen im Redefluss kommen dazu – je direkt nach einer beantworteten
Frage eine Nachfrage ohne Namen (`RUECKFRAGEN`, Feld `nach`). Für vorhandenes Material ohne Neuvertonung:

    ~/.venvs/lmc/bin/python testbibliothek/cloudtest/bauen_grenzfaelle.py --rueckfragen-nachtragen

schneidet nur die beiden Rückfragen (Azure, Stimme „alloy“ wie alle Grenzfälle, 0 $) in die vorhandene
meeting_grenzfaelle.wav und verschiebt alle Zeiten danach in referenz_grenzfaelle.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent.parent
ZIEL = WURZEL / "testbibliothek" / "cloudtest"
sys.path.insert(0, str(WURZEL))
from coach.ki_abo import codex  # noqa: E402

RATE = 24000
VORLAUF = 25.0  # Lastenheft: Begrüßung + Zeitfenster für ein "Nein"
GAP = 0.6
ZIEL_WOERTER = 850  # ~6 min Basis-Dialog; mit zwölf Grenzfällen obendrauf insgesamt ~12 min
PERSON_STIMMEN = ["onyx", "nova", "echo", "shimmer"]  # vier Personen
GRENZFALL_STIMME = "alloy"  # für alle gesprochenen Grenzfall-Zeilen, im Material sonst ungenutzt

THEMA = "Incident-Review: Ausfall des Kundenportals am Montag"
AGENDA = [
    {"titel": "Ablauf des Ausfalls", "ziel": "Zeitlinie rekonstruieren, wer was wann bemerkt hat"},
    {"titel": "Ursache", "ziel": "Datenbank-Migration und fehlenden Rollback klären"},
    {"titel": "Maßnahmen", "ziel": "Sofort- und Folgemaßnahmen festlegen"},
    {"titel": "Kommunikation an Kunden", "ziel": "Was und wann an die Kundschaft geht"},
]
PERSONEN = ["Mara", "Jonas", "Sofie", "Tarek"]

AUFTRAG = f"""\
Schreibe das Drehbuch einer realistischen deutschen Teambesprechung: {THEMA}
Vier Personen: {", ".join(PERSONEN)} (IT-Team, Incident Commander, Backend/Datenbank, SRE/Monitoring,
Support/Kommunikation). Rund 6 Minuten gesprochener Text (rund 840 Wörter), natürliche gesprochene Sprache mit
Füllwörtern, Rückfragen und halben Sätzen – kein Theaterdialog. Viel Fachsprache: Kubernetes, Rollback,
Postgres, Monitoring, SLA, Postmortem, Migration, Downtime. Keine Unterbrechungen (jede Person redet aus).
Genau vier Agendapunkte in dieser Reihenfolge, jeweils besprochen:
1. {AGENDA[0]["titel"]} – {AGENDA[0]["ziel"]}
2. {AGENDA[1]["titel"]} – {AGENDA[1]["ziel"]}
3. {AGENDA[2]["titel"]} – {AGENDA[2]["ziel"]}
4. {AGENDA[3]["titel"]} – {AGENDA[3]["ziel"]}
Baue diese Ereignisse ein und markiere jede betroffene Äußerung (Feld "ereignisse"):
- am Anfang von Punkt 1 EIN zusammenhängender, nicht unterbrochener Redebeitrag einer Person über die
  Zeitlinie des Ausfalls, der FÜR SICH ALLEIN länger als 90 Sekunden gesprochener Zeit ist (ca. 230+ Wörter
  in genau dieser einen Äußerung, nicht auf mehrere verteilt): monolog
- beim Wechsel zu Punkt 2 eine ausdrückliche Ansage, z. B. "Kommen wir zur Ursache": wechsel_ansage
- mitten in Punkt 2 eine Abschweifung von rund 40 Sekunden über ein offensichtliches Nebenthema (z. B. die
  anstehende Team-Weihnachtsfeier oder einen Kaffeemaschinen-Defekt), darin ein deutscher Kraftausdruck:
  abschweifung, kraftausdruck
- gegen Ende von Punkt 3 ein klarer Beschluss mit einer konkreten Zahl (z. B. zusätzliche Monitoring-Alerts,
  ein Zeitfenster für die nächste Migration, eine Frist in Stunden): beschluss
- beim Wechsel zu Punkt 4 eine Ansage: wechsel_ansage
- gegen Ende eine Aufgabe, die klar benannt, aber niemandem ausdrücklich zugewiesen wird: aufgabe_ohne_zustaendig
Keine Fragen an einen Assistenten, keine Marke "nestor_frage" - die Grenzfälle der Ansprache kommen in einem
späteren Schritt separat dazu.
Antworte nur mit JSON:
{{"titel": "...", "ziel": "...",
  "agenda": [{{"titel": "...", "ziel": "...", "minuten": 5}}],
  "personen": [{{"name": "Vorname", "rolle": "..."}}],
  "aeusserungen": [{{"person": 0, "text": "...", "punkt": 0, "ereignisse": ["monolog"]}}]}}
"punkt" ist der Agendapunkt (ab 0), zu dem die Äußerung inhaltlich gehört; bei der Abschweifung -1.
"""


def mp3_zu_pcm(daten: bytes) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                        "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
                       input=daten, capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype="<i2")


def tempo_lautstaerke(pcm: np.ndarray, tempo: float = 1.0, db: float = 0.0) -> np.ndarray:
    """Nachbearbeitung für Grenzfall 9 (leise, schnell gesprochen) – ffmpeg atempo/volume auf fertiges PCM,
    unabhängig von der Synthese selbst (die restliche Stimme bleibt unverändert)."""
    roh = pcm.astype("<i2").tobytes()
    filt = []
    if tempo != 1.0:
        filt.append(f"atempo={tempo}")
    if db != 0.0:
        filt.append(f"volume={db}dB")
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE), "-ac", "1",
           "-i", "pipe:0"]
    if filt:
        args += ["-af", ",".join(filt)]
    args += ["-f", "s16le", "-ar", str(RATE), "-ac", "1", "pipe:1"]
    p = subprocess.run(args, input=roh, capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype="<i2")


def azure_tts():
    teachbuddy = Path.home() / "repos" / "teachbuddy"
    sys.path.insert(0, str(teachbuddy))
    for ziel_var, name in (("HOERSPIEL_AZURE_OPENAI_ENDPOINT", "azure-openai-endpoint"),
                           ("HOERSPIEL_AZURE_OPENAI_KEY", "azure-openai-key"),
                           ("HOERSPIEL_AZURE_OPENAI_DEPLOYMENT", "azure-openai-deployment")):
        if not os.environ.get(ziel_var):
            wert = subprocess.run(["sudo", "-n", "zugang", "holen", name], capture_output=True, text=True)
            if wert.returncode == 0:
                os.environ[ziel_var] = wert.stdout.strip()
    from podcast import vertonung

    return vertonung.aus_umgebung()


def kuerzen(d: dict) -> None:
    aeusserungen = d["aeusserungen"]
    woerter = lambda a: len(a["text"].split())  # noqa: E731
    gesamt = sum(woerter(a) for a in aeusserungen)
    ohne_marke = sorted((a for a in aeusserungen if not a.get("ereignisse")), key=woerter, reverse=True)
    for a in ohne_marke:
        if gesamt <= ZIEL_WOERTER:
            break
        aeusserungen.remove(a)
        gesamt -= woerter(a)


async def drehbuch(neu: bool = False) -> dict:
    datei = ZIEL / "drehbuch_grenzfaelle.json"
    if datei.exists() and not neu:
        d = json.loads(datei.read_text(encoding="utf-8"))
        vorher = len(d["aeusserungen"])
        kuerzen(d)
        if len(d["aeusserungen"]) != vorher:
            datei.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        woerter = sum(len(a["text"].split()) for a in d["aeusserungen"])
        print(f"Drehbuch: vorhanden ({datei}), auf {woerter} Wörter gekürzt (--neu zum Neuerzeugen).")
        return d
    text = await codex(AUFTRAG, frist=600)
    d = json.loads(text)
    kuerzen(d)
    ZIEL.mkdir(parents=True, exist_ok=True)
    datei.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    woerter = sum(len(a["text"].split()) for a in d["aeusserungen"])
    laengste_monolog = max((len(a["text"].split()) for a in d["aeusserungen"] if "monolog" in a.get("ereignisse", [])),
                           default=0)
    print(f"Drehbuch: {len(d['aeusserungen'])} Äußerungen, {woerter} Wörter, längster Monolog "
          f"{laengste_monolog} Wörter (~{laengste_monolog / 140 * 60:.0f} s), "
          f"Ereignisse: {sorted({e for a in d['aeusserungen'] for e in a.get('ereignisse', [])})}")
    return d


def blocks_aus_drehbuch(d: dict) -> list[dict]:
    blocks = []
    for n, a in enumerate(d["aeusserungen"]):
        blocks.append({"kind": "utt", "person": a["person"], "punkt": a.get("punkt"),
                       "ereignisse": a.get("ereignisse", []), "text": a["text"]})  # audio kommt in vertonen()
        if n < len(d["aeusserungen"]) - 1:
            blocks.append({"kind": "gap"})
    return blocks


def vertonen(blocks: list[dict], tts) -> None:
    """Audio nachträglich an die utt-Blöcke hängen (erst Text/Struktur, dann Synthese – so bleibt die
    Zuordnung Äußerung->Index stabil, falls kuerzen() später noch greift)."""
    for b in blocks:
        if b["kind"] == "utt":
            b["audio"] = mp3_zu_pcm(tts.synthese(text=b["text"], voice=PERSON_STIMMEN[b["person"] % len(PERSON_STIMMEN)]))
        elif b["kind"] == "gap":
            b["audio"] = np.zeros(int(GAP * RATE), dtype="<i2")


def zeiten(blocks: list[dict]) -> list[float]:
    t, aus = 0.0, []
    for b in blocks:
        aus.append(t)
        t += len(b["audio"]) / RATE
    aus.append(t)
    return aus


def naechste_grenze(blocks: list[dict], ziel_s: float) -> int:
    ts = zeiten(blocks)
    return min(range(len(blocks) + 1), key=lambda i: abs(ts[i] - ziel_s))


def einfuegen(blocks: list[dict], index: int, neue: list[dict]) -> None:
    blocks[index:index] = neue


def stille(sek: float) -> dict:
    return {"kind": "silence", "audio": np.zeros(int(sek * RATE), dtype="<i2")}


def sprech_block(tts, id_: str, text: str, tempo: float = 1.0, db: float = 0.0) -> dict:
    audio = mp3_zu_pcm(tts.synthese(text=text, voice=GRENZFALL_STIMME))
    if tempo != 1.0 or db != 0.0:
        audio = tempo_lautstaerke(audio, tempo, db)
    return {"kind": "grenzfall", "audio": audio, "text": text, "id": id_}


# ---------- Ticket #25: warten und Rückfragen im Redefluss ----------
# Ob der Test nach dem Fall wartet, bis Nestor fertig ist (scripts/cloudtest_takt.py). "bestaetigung": nur bis
# die erste Rückmeldung gesprochen ist („macht ruhig weiter“, Bild/Folie); False: gar nicht – Hineinreden (#20)
# und Sätze, auf die Nestor nicht reagieren soll, laufen im Redefluss weiter.
WARTEN = {
    "antwort": True, "ja_dann_antwort": True, "antwort_mit_quellen": True,
    "antwort_erwuenscht_dokumentieren": True,
    "folie": "bestaetigung", "nachfrage_oder_bild_mit_fokus": "bestaetigung",
    "nestor_verstummt": False, "keine_antwort": False, "kein_fehlausloeser": False, "kein_abbruch": False,
    "agendawechsel": False,
}
# Teile, nach denen zusätzlich gewartet wird: „Nestor?“ – wer ihn so anspricht, wartet auf sein „Ja?“.
WARTEN_TEIL = {("2_name_dann_frage", 0): True}

# (id, nach Grenzfall, Text): eine Nachfrage ohne Namen direkt nach Nestors Antwort; danach geht das Meeting
# normal weiter. Im Material steht davor RUECKFRAGE_ABSTAND Stille (Platz für die Antwort im Modus am Stück);
# im abwechselnden Modus überspringt der Test sie bis auf 0,8 s.
RUECKFRAGEN = [
    ("1r_rueckfrage_reicht", "1_name_satzende", "Und reicht das noch für alle Punkte?"),
    ("2r_rueckfrage_wer", "2_name_dann_frage", "Und wer übernimmt das?"),
]
RUECKFRAGE_ABSTAND = 8.0


def warten_setzen(grenzfaelle: list[dict]) -> None:
    nach = {rid: basis for rid, basis, _ in RUECKFRAGEN}
    for g in grenzfaelle:
        g["warten"] = WARTEN.get(g["erwartet"], False)
        for i, t in enumerate(g.get("teile", [])):
            if (g["id"], i) in WARTEN_TEIL:
                t["warten"] = WARTEN_TEIL[(g["id"], i)]
        if g["id"] in nach:
            g["nach"] = nach[g["id"]]


def rueckfragen_nachtragen() -> None:
    """Die Rückfragen in vorhandenes Material schneiden (keine Neuvertonung des Rests): direkt nach dem Ende des
    Grundfalls Stille + Rückfrage einfügen, alle späteren Zeiten verschieben."""
    ref_datei, wav_datei = ZIEL / "referenz_grenzfaelle.json", ZIEL / "meeting_grenzfaelle.wav"
    referenz = json.loads(ref_datei.read_text(encoding="utf-8"))
    with wave.open(str(wav_datei), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    if abs(len(audio) / RATE - referenz["dauer_s"]) > 0.5:
        raise SystemExit("meeting_grenzfaelle.wav passt nicht zu referenz_grenzfaelle.json – erst neu bauen.")
    vorhanden = {g["id"] for g in referenz["grenzfaelle"]}
    tts = None
    for rid, basis_id, text in RUECKFRAGEN:
        if rid in vorhanden:
            print(f"{rid}: schon im Material.")
            continue
        tts = tts or azure_tts()
        basis = next(g for g in referenz["grenzfaelle"] if g["id"] == basis_id)
        clip = sprech_block(tts, rid, text)["audio"]
        einschub = np.concatenate([np.zeros(int(RUECKFRAGE_ABSTAND * RATE), dtype="<i2"), clip])
        bei = basis["ende"]
        a = int(round(bei * RATE))
        audio = np.concatenate([audio[:a], einschub, audio[a:]])
        dauer = len(einschub) / RATE

        def schieben(t: float) -> float:
            return round(t + dauer, 2) if t >= bei - 1e-6 else t

        for e in referenz["ereignisse"]:
            e["zeit_s"] = schieben(e["zeit_s"])
        for g in referenz["grenzfaelle"]:
            if g is basis:
                continue
            g["start"], g["ende"] = schieben(g["start"]), schieben(g["ende"])
            for t in g["teile"]:
                t["start"], t["ende"] = schieben(t["start"]), schieben(t["ende"])
        start = round(bei + RUECKFRAGE_ABSTAND, 2)
        ende = round(bei + dauer, 2)
        referenz["grenzfaelle"].append({"id": rid, "ziel_s": basis["ziel_s"], "erwartet": "antwort",
                                        "start": start, "ende": ende,
                                        "teile": [{"text": text, "start": start, "ende": ende}]})
        print(f"{rid}: „{text}“ nach {basis_id} bei {start:.2f}s eingefügt (+{dauer:.1f}s).")
    referenz["grenzfaelle"].sort(key=lambda g: g["start"])
    warten_setzen(referenz["grenzfaelle"])
    referenz["dauer_s"] = round(len(audio) / RATE, 1)
    with wave.open(str(wav_datei), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(audio.tobytes())
    ref_datei.write_text(json.dumps(referenz, ensure_ascii=False, indent=1), encoding="utf-8")
    if tts is not None:
        print(f"Azure (Teachbuddy, eigenes Kontingent): {tts.zeichen} Zeichen, 0 $.")
    print(f"meeting_grenzfaelle.wav: {len(audio) / RATE / 60:.2f} min, {len(referenz['grenzfaelle'])} Grenzfälle.")


# ---------- Die zwölf Grenzfälle (Ticket #11; Fall 6 laut Nachtrag des Koordinators 07.10. geändert) ----------
# ziel_s in aufsteigender Reihenfolge, damit jeder Fall an der zu diesem Zeitpunkt nächstgelegenen
# Äußerungsgrenze der bereits (durch frühere Fälle) verschobenen Aufnahme eingefügt wird. Bei eng benachbarten
# Zielzeiten über spärlichem Basismaterial (wenige, dafür lange Äußerungen – der 90-s-Monolog!) kann ein
# späterer Fall an derselben Grenze wie ein früherer landen und ihn im fertigen Material nach hinten schieben;
# die Zeitstempel in referenz.json werden deshalb NICHT hier, sondern erst ganz am Ende aus der fertigen
# Blockliste gelesen (siehe grenzfaelle_protokoll_aus_blocks) – nur das ist zuverlässig.
def grenzfaelle_einfuegen(blocks: list[dict], tts) -> list[dict]:
    reihenfolge: list[tuple[str, float, str]] = []  # (id, ziel_s, erwartet), Anzeige-/Soll-Reihenfolge

    def eintragen(id_: str, ziel_s: float, erwartet: str, segmente: list[dict], pause_danach: float = 0.0) -> None:
        i = naechste_grenze(blocks, ziel_s)
        neue = [stille(0.3)]
        for seg in segmente:
            if "stille_s" in seg:
                neue.append(stille(seg["stille_s"]))
                continue
            if seg.get("id"):  # eigener Fall im selben Einschub (Rückfrage, #25)
                reihenfolge.append((seg["id"], ziel_s, seg["erwartet"]))
            neue.append(sprech_block(tts, seg.get("id") or id_, seg["text"], seg.get("tempo", 1.0),
                                     seg.get("db", 0.0)))
            if seg.get("stille_nach_s"):
                neue.append(stille(seg["stille_nach_s"]))
        if pause_danach:
            neue.append(stille(pause_danach))
        einfuegen(blocks, i, neue)
        reihenfolge.append((id_, ziel_s, erwartet))

    rueckfrage = {basis: {"id": rid, "text": text, "erwartet": "antwort"} for rid, basis, text in RUECKFRAGEN}
    eintragen("1_name_satzende", 150, "antwort",
             [{"text": "Wie viel Zeit haben wir noch, Nestor?"},
              {"stille_s": RUECKFRAGE_ABSTAND}, rueckfrage["1_name_satzende"]], pause_danach=22.0)

    eintragen("2_name_dann_frage", 190, "ja_dann_antwort",
             [{"text": "Nestor?", "stille_nach_s": 2.0},
              {"text": "Was haben wir zu Punkt eins beschlossen?"},
              {"stille_s": RUECKFRAGE_ABSTAND}, rueckfrage["2_name_dann_frage"]], pause_danach=22.0)

    eintragen("3a_nuschel_nester", 230, "antwort_erwuenscht_dokumentieren",
             [{"text": "Nester, fass mal zusammen."}], pause_danach=22.0)
    eintragen("3b_nuschel_nestro", 260, "antwort_erwuenscht_dokumentieren",
             [{"text": "Nestro, wo stehen wir gerade?"}], pause_danach=22.0)

    eintragen("4_rueckfrage_direkt", 285, "antwort",
             [{"text": "Und wer kümmert sich darum?"}], pause_danach=22.0)

    # Fall 5 braucht echte Stille vor der Rückfrage (>30 s seit der letzten Nestor-Interaktion), damit das
    # Fenster für Rückfragen ohne Namen sicher zu ist.
    eintragen("5_rueckfrage_spaet", 330, "keine_antwort",
             [{"stille_s": 32.0}, {"text": "Und bis wann ungefähr?"}], pause_danach=8.0)

    eintragen("6a_viktor", 360, "kein_fehlausloeser", [{"text": "Viktor, kannst du das übernehmen?"}], pause_danach=1.5)
    eintragen("6b_next_week", 365, "kein_fehlausloeser", [{"text": "Das schieben wir auf next week."}], pause_danach=1.5)
    eintragen("6c_eigentor", 370, "kein_fehlausloeser", [{"text": "Das war ein echtes Eigentor von uns."}], pause_danach=1.5)
    eintragen("6d_nest", 375, "kein_fehlausloeser",
             [{"text": "Das ist ein Nest von Abhängigkeiten, da müssen wir vorsichtig sein."}], pause_danach=2.0)

    eintragen("7_unklare_anweisung", 400, "nachfrage_oder_bild_mit_fokus",
             [{"text": "Nestor, mach mal das mit dem Bild, aber nur für den Teil vorhin."}], pause_danach=18.0)

    # Fall 8: Auslöser, kurze Pause (angenommener Antwortbeginn ~2 s, Lastenheft-Messwert), dann 2 s in die
    # (angenommene) Antwort hineinreden - mangels echter Nestor-Stimme im Offline-Material nur als Zeitpunkt
    # in referenz.json markiert, nicht als echtes Hineinreden ins Audio (siehe Bericht).
    eintragen("8_hineinreden", 430, "nestor_verstummt",
             [{"text": "Nestor, kannst du uns das Postmortem-Template schicken?"},
              {"stille_s": 2.0},
              {"text": "Moment, warte, ich hab noch was."}], pause_danach=10.0)

    eintragen("9_leise_schnell", 460, "antwort",
             [{"text": "Nestor, notier kurz die SLA-Zahl von eben.", "tempo": 1.2, "db": -12.0}], pause_danach=22.0)

    eintragen("10_nein_normalsatz", 490, "kein_abbruch",
             [{"text": "Nein, das sehe ich anders."}], pause_danach=2.0)

    eintragen("11_agenda_rueckwaerts", 510, "agendawechsel",
             [{"text": "Lass uns nochmal kurz zu Punkt eins zurück."}], pause_danach=5.0)

    eintragen("12a_recherche", 540, "antwort_mit_quellen",
             [{"text": "Nestor, wie ist der aktuelle Stand bei der Umsetzung von NIS2 in Deutschland?"}],
             pause_danach=35.0)
    eintragen("12b_folie", 578, "folie", [{"text": "Ja, mach eine Folie."}], pause_danach=10.0)

    return reihenfolge


def grenzfaelle_protokoll_aus_blocks(blocks: list[dict], reihenfolge: list[tuple[str, float, str]]) -> list[dict]:
    """Einzige verlässliche Quelle für die Grenzfall-Zeitstempel: ein Durchlauf über die FERTIGE Blockliste
    (nach allen Einfügungen und dem Voranstellen des Vorlaufs) statt der Momentaufnahmen beim Einfügen selbst
    (siehe Kommentar an grenzfaelle_einfuegen)."""
    ts = zeiten(blocks)
    teile_je_id: dict[str, list[dict]] = {}
    for i, b in enumerate(blocks):
        if b["kind"] != "grenzfall":
            continue
        teile_je_id.setdefault(b["id"], []).append(
            {"text": b["text"], "start": round(ts[i], 2), "ende": round(ts[i + 1], 2)})
    aus = []
    for id_, ziel_s, erwartet in reihenfolge:
        teile = teile_je_id.get(id_, [])
        if not teile:
            continue
        aus.append({"id": id_, "ziel_s": ziel_s, "erwartet": erwartet,
                   "start": teile[0]["start"], "ende": teile[-1]["ende"], "teile": teile})
    # Nach tatsächlicher Zeit sortieren (nicht nach ziel_s): bei eng benachbarten Zielzeiten über spärlichem
    # Basismaterial kann ein später eingefügter Fall vor einen früheren rutschen (s. o.) - referenz.json soll
    # die wirkliche Reihenfolge im Material zeigen, nicht die beabsichtigte.
    aus.sort(key=lambda g: g["start"])
    warten_setzen(aus)
    return aus


def referenz_bauen(blocks: list[dict]) -> list[dict]:
    ts = zeiten(blocks)
    aus = []
    for i, b in enumerate(blocks):
        if b["kind"] != "utt" or not b.get("ereignisse"):
            continue
        for e in b["ereignisse"]:
            aus.append({"ereignis": e, "zeit_s": round(ts[i], 2), "person": b["person"], "punkt": b["punkt"],
                       "text": b["text"]})
    return aus


async def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--neu", action="store_true", help="Drehbuch neu über Codex erzeugen statt das vorhandene zu nutzen")
    ap.add_argument("--rueckfragen-nachtragen", action="store_true",
                    help="nur die Rückfragen (#25) in vorhandenes Material schneiden, nichts neu vertonen")
    args = ap.parse_args()
    if args.rueckfragen_nachtragen:
        rueckfragen_nachtragen()
        return

    d = await drehbuch(neu=args.neu)
    tts = azure_tts()
    blocks = blocks_aus_drehbuch(d)
    vertonen(blocks, tts)
    reihenfolge = grenzfaelle_einfuegen(blocks, tts)
    print(f"Azure (Teachbuddy, eigenes Kontingent): {tts.zeichen} Zeichen, 0 $.")

    blocks = [{"kind": "intro", "audio": np.zeros(int(VORLAUF * RATE), dtype="<i2")}] + blocks
    # Zeitstempel erst jetzt aus der fertigen Liste lesen (siehe grenzfaelle_protokoll_aus_blocks) - zuverlässig
    # auch wenn ein später eingefügter Fall einen früheren im Material nach hinten geschoben hat.
    grenzfaelle_protokoll = grenzfaelle_protokoll_aus_blocks(blocks, reihenfolge)

    ereignisse = referenz_bauen(blocks)
    audio = np.concatenate([b["audio"] for b in blocks])
    ZIEL.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ZIEL / "meeting_grenzfaelle.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(audio.tobytes())

    referenz = {
        "titel": d["titel"], "ziel": d["ziel"], "agenda": d.get("agenda", AGENDA),
        "dauer_s": round(len(audio) / RATE, 1), "vorlauf_s": VORLAUF,
        "ereignisse": ereignisse, "grenzfaelle": grenzfaelle_protokoll,
    }
    (ZIEL / "referenz_grenzfaelle.json").write_text(json.dumps(referenz, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")

    agenda_text = (
        f"Betreff: Incident-Review – Ausfall Kundenportal, heute 16 Uhr\n\n"
        "Hallo zusammen,\n\n"
        "wir gehen heute um 16 Uhr den Ausfall vom Montag durch. Teilnehmende: "
        + ", ".join(PERSONEN) + ".\n\n"
        "Agenda:\n"
        + "\n".join(f"{i + 1}. {p['titel']} (ca. {p['minuten']} Min.) - {p['ziel']}"
                    for i, p in enumerate(d.get("agenda", AGENDA)))
        + "\n\nBis später!\nMara\n"
    )
    (ZIEL / "agenda_prompt_grenzfaelle.txt").write_text(agenda_text, encoding="utf-8")

    print(f"meeting_grenzfaelle.wav: {len(audio) / RATE / 60:.2f} min, {len(ereignisse)} Ereignisse, "
          f"{len(grenzfaelle_protokoll)} Grenzfall-Einschübe.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
