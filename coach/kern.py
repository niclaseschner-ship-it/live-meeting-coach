"""Nestors Kern: eine Anfrage, ein Modell, ein Werkzeugkatalog – in Basis und Premium gleich.

Jede Anfrage an Nestor (Sprechtaste, Name, Knopf mit Freitext, getippt, Gesprächszug) geht als EIN Aufruf mit dem
aktuellen Stand des Meetings an das Sprachmodell der Stufe. Vorsortiert wird nichts: Das Modell versteht, was gemeint
ist, und wählt dazu Werkzeuge (coach/werkzeuge.py). Danach sagt es in ein, zwei Sätzen, was es getan hat und was dabei
herauskommt – Handeln ersetzt nie die Antwort. Einzige Ausnahme: `nicht_an_mich` (die Runde redete untereinander).

- **Premium** spricht über das Realtime-Modell (coach/gespraech.py): Anweisung und Werkzeuge kommen von hier, die
  Ausführung auch (`ausfuehren`).
- **Basis** (und Premium ohne Gespräch) über den Text-Weg (`text_antwort`): Chat-Aufruf mit Werkzeugen, gestreamt,
  Satz für Satz in die Sprachausgabe; nach einer Werkzeugrunde ein zweiter Aufruf für den Abschlusssatz.

Schranken im Code: höchstens eine Werkzeugrunde je Anfrage, geprüfte Argumente (Fehler gehen ans Modell zurück, damit
es sagt, was nicht geht), lange Aufträge (Recherche, Bild) laufen im Hintergrund und kommen still als Karte.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from types import SimpleNamespace

from . import werkzeuge as W
from .config import EINST

log = logging.getLogger("coach.kern")

ANWEISUNG = """\
Du bist {name}, Moderationsassistent und Teil dieser Runde in einem Präsenzmeeting. Du sprichst mit der Gruppe wie
ein erfahrener, freundlicher Kollege, der den Überblick behält: natürlich, locker, auf Deutsch, per „ihr“, nie „Sie“.

Verstehen:
- Jede Nachricht an dich ist eine Bitte oder Frage der Runde. Überleg, was die Runde gerade braucht – nicht, welches
  Wort gefallen ist. Grundlage ist der Stand unten: Agenda, Festgehaltenes, letzte Karten und Antworten, Recherche
  und das Transkript. Was dort steht, weißt du; was nicht dort steht, erfindest du nicht.
- Inhalte aus dem Gespräch (genannte Optionen, Argumente, Zahlen) holst du aus dem Transkript, auch wenn sie nicht
  festgehalten sind. „Die Optionen“, „das von vorhin“, „die Folie“, „die Karte“ meinen das, was im Stand schon steht.
- Fragen zu einer fertigen Recherche beantwortest du aus „Letzte Recherche“; „stell die Folie/Recherche vor“ heißt:
  sag in zwei Sätzen, was dabei herauskam. Neu recherchieren nur, wenn die Runde etwas Neues aus dem Internet wissen
  will.
- „Was fehlt uns noch?“ beantwortest du als Moderator: Was braucht die Runde, um ihr Ziel und den aktuellen
  Agendapunkt zu erreichen (etwa Kriterien, eine Bewertung, eine Entscheidung)? Lücken bei Wer und Termin nur, wo es
  um Aufgaben geht.
- Ist wirklich unklar, was gemeint ist, frag in einem kurzen Satz nach, statt zu raten.

Antworten:
- Du antwortest immer hörbar: ein, höchstens zwei Sätze, das Wichtigste zuerst. Eine kurze Aufzählung (bis fünf
  knappe Dinge) sagst du in einem Satz; Längeres gehört auf eine Karte, dann sagst du nur den Kern.
- Deine Antwort wird vorgelesen: kein Markdown, keine Sternchen, keine Aufzählungszeichen, keine Klammern.
- Nach einem Werkzeug sagst du in einem Satz, was du getan hast und was dabei herauskommt („Hab ich ergänzt, jetzt
  sind es vier: …“, „Ich recherchiere das, die Karte kommt gleich.“). Lies Karten nicht vor.
- Gespräche der Gruppe, die du nur mithörst, kommentierst du nie von dir aus.
- Personen heißen im Transkript „Person N“ – sprich dann von „jemandem“. Agendapunkte nennst du mit Nummer und Titel
  aus der Agenda, sprechbar: „Punkt zwei, Budget“.

Werkzeuge:
- Höchstens eine Werkzeugrunde je Anfrage: rufe alle nötigen Werkzeuge auf einmal auf, dann antworte.
- Eine Karte ergänzen oder ändern („nimm das noch auf die Folie“) heißt: mit `karte` eine neue, vollständige Karte
  zeigen. Festgehaltenes änderst du nur, wenn die Runde ausdrücklich den Eintrag meint.
- Festhalten (artefakt_eintragen) nur, wenn die Runde es will („fürs Protokoll“, „schreib auf“, „notier“). Optionen
  und Kriterien sind keine Entscheidungen. Eine Recherche, die du selbst machst, ist keine Aufgabe der Runde.
- „Beschlossen“ sagst du nur, wenn es als Entscheidung festgehalten oder ausdrücklich so gesagt ist.
- Sagt die Runde, dass sie zu einem anderen Agendapunkt geht („dann gehen wir zum nächsten Punkt“, „zurück zu
  Punkt eins“), wechselst du. Eine Frage zum Punkt oder nach dem nächsten Punkt ist kein Wechselwunsch.
{bestaetigung}
STAND DES MEETINGS (bei jeder Anfrage neu):
{lage}
"""
# Ist die Sofort-Bestätigung an (LMC_BESTAETIGUNG), hat das System schon „Bin dran“ o. ä. gesagt
BESTAETIGUNG = """
Oft hat das System schon kurz bestätigt („Bin dran“), bevor du drankommst. Fang deshalb nicht mit „Okay“,
„Moment“, „Klar“ oder „Gern“ an, sondern direkt mit dem Inhalt.
"""
UEBERLAST = "Ich komme gerade nicht durch, versucht es gleich nochmal."
FEHLER = "Entschuldigung, das hat gerade nicht geklappt."
SATZENDE_RE = re.compile(r"(?<=[.!?])\s+")
VERLAUF = 3  # so viele frühere Fragen und Antworten gehen im Text-Weg mit (das Gespräch hat sein eigenes Gedächtnis)
AUSFUEHREN_FRIST = 20.0  # länger darf ein Werkzeug (Karte bauen) die Antwort nicht aufhalten


def anweisung(assistent) -> str:
    return ANWEISUNG.format(name=EINST.assistent_name, lage=assistent.lage(),
                            bestaetigung=BESTAETIGUNG if EINST.bestaetigung else "")


# --- Werkzeuge ausführen (beide Stufen) ----------------------------------------------------------------------------
async def ausfuehren(a, b, name: str, arg, *, gerichtet: bool = True) -> dict:
    """Ein Werkzeugaufruf: prüfen, ausführen, Ergebnis für das Modell. Gesprochen wird hier nichts – das Modell sagt
    danach selbst, was es getan hat. `b`: der Bogen der Anfrage (Protokoll in nestor.jsonl, Karten, Abbruch)."""
    c, m = a.coach, a.coach.meeting
    if not isinstance(arg, dict):
        arg = {}
    aufruf = {"name": name, "argumente": arg}  # Nestors Seite: jeder Aufruf mit Argumenten in nestor.jsonl
    if b is not None:
        b.werkzeuge.append(aufruf)
    arg, fehler = W.pruefen(name, arg, nummern={x.id for x in c.artefakte.liste}, agenda=len(m.agenda),
                            aktiver_punkt=m.aktiver_punkt, jetzt=m.jetzt(), gerichtet=gerichtet)
    if fehler:
        aufruf["fehler"] = fehler
        c.protokoll.append({"zeit": m.jetzt(), "art": "werkzeug_abgelehnt", "werkzeug": name, "fehler": fehler})
        return {"ok": False, "fehler": fehler}
    try:
        return await asyncio.wait_for(_ausfuehren(a, b, name, arg), AUSFUEHREN_FRIST)
    except asyncio.TimeoutError:
        aufruf["fehler"] = "frist"
        return {"ok": False, "fehler": "Das dauert gerade zu lange."}
    except Exception as e:  # noqa: BLE001 – ehrlich sagen statt zu hängen
        log.warning("Werkzeug %s fehlgeschlagen: %s", name, type(e).__name__)
        aufruf["fehler"] = type(e).__name__
        return {"ok": False, "fehler": "Das hat gerade nicht geklappt."}


async def _ausfuehren(a, b, name: str, arg: dict) -> dict:
    from . import bogen as BG

    c, m = a.coach, a.coach.meeting
    if name == "nicht_an_mich":
        if b is not None:
            b.verworfen = True
        return {"ok": True, "schweigen": True}
    if name == "artefakt_eintragen":
        e, _ = c.artefakte.eintragen(arg)
        if e is None:
            return {"ok": False, "fehler": "Das konnte ich keinem Eintrag zuordnen."}
        c.protokoll.append({"zeit": m.jetzt(), "art": "artefakt_eingetragen", "id": e.id, "durch": "stimme"})
        await c.melden()
        return {"ok": True, "eingetragen": e.kurz(), "fehlt_noch": e.luecken()}
    if name in ("ergebnis_entfernen", "ergebnis_aendern"):
        nummer = arg["nummer"]
        e = (c.artefakte.entfernen(nummer) if name == "ergebnis_entfernen"
             else c.artefakte.aendern(nummer, str(arg.get("text") or "")))
        if e is None:
            return {"ok": False, "fehler": "Das finde ich in der Liste nicht."}
        c.protokoll.append({"zeit": m.jetzt(), "art": "artefakt_entfernt" if name == "ergebnis_entfernen"
                            else "artefakt_geaendert", "id": nummer, "durch": "stimme"})
        await c.melden()
        return {"ok": True, "eintrag": e.kurz(), "hinweis": "im Dashboard lässt es sich rückgängig machen"}
    if name == "auftrag_abbrechen":
        auftrag = a.auftraege.ziel_art(arg.get("art"))
        if auftrag is None:
            return {"ok": False, "fehler": "Gerade läuft nichts, was ich abbrechen könnte."}
        a.auftrag_abbrechen(auftrag.id)
        await c.melden()
        return {"ok": True, "abgebrochen": auftrag.titel}
    if name == "recherchieren":
        return a.lang_starten("recherche", str(arg.get("frage") or (b.frage if b else "")))
    if name == "bild_zeichnen":
        fokus = str(arg.get("fokus") or "")
        fokus = "" if fokus.lower() in ("gesamt", "alles") else fokus
        if c.bild_als_text:  # Basis: kein Bildmodell – der Überblick als Text steht nach wenigen Sekunden
            return await _karte_bauen(a, b, "ueberblick", fokus)
        return a.lang_starten("bild", b.frage if b else "", fokus)
    if name == "folie_erstellen":
        return await _karte_bauen(a, b, "folie")
    if name == "karte_zeigen":
        return await _karte_bauen(a, b, arg["art"])
    if name == "karte_neu_aufbereiten":
        return await _karte_bauen(a, b, "neu_aufbereiten", arg.get("wie", ""))
    if name == "zusammenfassen":
        karte, _, auszug = await BG.bereich_karte(c, arg["bereich"], arg.get("punkt"), arg.get("seit"))
        _ablegen(a, b, karte)
        a.letzte_aktion = {"typ": "karte", "art": "zusammenfassen"}
        await c.melden()
        return {"ok": True, "karte": {"titel": karte["titel"], "punkte": karte["punkte"]},
                "besprochen": auszug or "(in diesem Bereich noch nichts gesagt)",
                "hinweis": "Die Karte steht. Sag, was auffällt – auch Besprochenes, das nicht festgehalten ist."}
    if name == "karte":
        _ablegen(a, b, {"art": "antwort", "titel": arg["titel"], "punkte": arg["punkte"]})
        a.letzte_aktion = {"typ": "karte", "art": "frei"}
        await c.melden()
        return {"ok": True, "hinweis": "Die Karte steht."}
    if name == "agendapunkt_wechseln":
        await c.assistent_aktion({"typ": "weiter", "ziel": str(arg["nummer"])})
        a.letzte_aktion = {"typ": "weiter", "ziel": str(arg["nummer"])}
        p = m.agenda[m.aktiver_punkt]
        return {"ok": True, "jetzt": f"Punkt {m.aktiver_punkt + 1}: {p.titel}", "ziel": p.ziel or None}
    if name == "zuhoeren_pausieren":
        await c.assistent_aktion({"typ": "pause"})
        a.letzte_aktion = {"typ": "pause"}
        return {"ok": True, "hinweis": "Wieder an nur über den Knopf im Dashboard – sag das dazu."}
    if name == "gespraech_beenden":
        return {"ok": True}
    return {"ok": False, "fehler": f"Werkzeug {name} gibt es nicht."}


async def _karte_bauen(a, b, art: str, fokus: str = "") -> dict:
    """Eine feste Karte (Stand, Was fehlt, Festgehalten, Überblick, Folie, neu aufbereitet) bauen und ablegen; der
    Inhalt geht an das Modell, damit es sagen kann, was auffällt."""
    from . import bogen as BG

    teil = SimpleNamespace(fokus=fokus, frage=b.frage if b else "", id=b.id if b else None)
    karte, _ = await BG.BAUER[art](a.coach, teil, satz=False)
    if karte is None:
        return {"ok": False, "fehler": {"folie": "Für eine Folie brauche ich erst eine Recherche.",
                                        "neu_aufbereiten": "Dafür habe ich gerade keine passende Karte."}.get(
                                            art, "Die Karte hat gerade nicht geklappt.")}
    _ablegen(a, b, {**karte, "frage": karte.get("frage") or (b.frage if b else "") or BG.NAMEN.get(art)})
    a.letzte_aktion = {"typ": "karte", "art": art}
    await a.coach.melden()
    return {"ok": True, "karte": {"titel": karte.get("titel"), "punkte": (karte.get("punkte") or [])[:12]},
            "hinweis": "Die Karte steht. Sag, was auffällt, ohne sie vorzulesen."}


def _ablegen(a, b, karte: dict) -> dict:
    frage = (b.frage if b is not None else "") or ""
    k = a.coach._karte_ablegen({**karte, "frage": karte.get("frage") or frage[:200],
                                "still": bool(b is not None and b.abgeloest),
                                **({"bogen": b.id} if b is not None else {})})
    if b is not None:
        b.karte = True
    return k


# --- Text-Weg (Basis, Premium ohne Gespräch) -----------------------------------------------------------------------
def sprechbar(satz: str) -> str:
    """Was vorgelesen wird, ohne Markdown (Mistral hält sich nicht immer an die Anweisung)."""
    satz = re.sub(r"\*\*|__|\*|`|^#+\s*|^[-•]\s+", "", satz, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", satz).strip()


def saetze_teilen(puffer: str) -> tuple[list[str], str]:
    """Fertige Sätze aus dem Puffer lösen; der unfertige Rest bleibt stehen."""
    teile = SATZENDE_RE.split(puffer)
    return [t.strip() for t in teile[:-1] if t.strip()], teile[-1]


async def text_antwort(a, b, bestaetigt: bool = False) -> None:
    """Chat-Aufruf mit Werkzeugen, gestreamt in die Sprachausgabe. Ruft das Modell Werkzeuge auf, werden sie
    ausgeführt und ein zweiter Aufruf (ohne Werkzeuge) formuliert den Abschlusssatz. Wird der Bogen abgelöst, schweigt
    die Stimme – die Antwort wird trotzdem fertig und kommt als Karte."""
    c = a.coach
    frage = b.frage
    a.zustand = "denkt"
    await c.melden()
    t0 = time.monotonic()
    if not bestaetigt:
        a.text_neu(frage)
    saetze: asyncio.Queue = asyncio.Queue()
    floskel = None if bestaetigt else a.bestaetigung_fuer(frage)
    if floskel:  # sofort hörbar, während das Modell noch denkt
        saetze.put_nowait(("floskel", floskel))
    sprecher = asyncio.ensure_future(a._sprechen_warteschlange(saetze, b))
    gesprochen: list[str] = []
    nachrichten = [{"role": "system", "content": anweisung(a)}]
    for f, antwort in a.verlauf[-VERLAUF:]:
        nachrichten += [{"role": "user", "content": f}, {"role": "assistant", "content": antwort}]
    nachrichten.append({"role": "user", "content": frage})
    try:
        aufrufe = await _runde(c, nachrichten, saetze, gesprochen, werkzeuge=True)
        if aufrufe:
            ergebnisse = []
            for aufruf in aufrufe:
                try:
                    argumente = json.loads(aufruf["argumente"] or "{}")
                except json.JSONDecodeError:
                    argumente = {}
                ergebnisse.append(await ausfuehren(a, b, aufruf["name"], argumente))
            if not b.verworfen:
                nachrichten.append({"role": "assistant", "content": "".join(gesprochen) or None, "tool_calls": [
                    {"id": x["id"], "type": "function", "function": {"name": x["name"], "arguments": x["argumente"]}}
                    for x in aufrufe]})
                for x, erg in zip(aufrufe, ergebnisse):
                    nachrichten.append({"role": "tool", "tool_call_id": x["id"], "name": x["name"],
                                        "content": json.dumps(erg, ensure_ascii=False)})
                await _runde(c, nachrichten, saetze, gesprochen, werkzeuge=False)
    except asyncio.CancelledError:
        sprecher.cancel()
        raise
    except Exception as e:  # noqa: BLE001
        from .mistral import ist_ueberlast

        log.warning("Antwort fehlgeschlagen: %s", type(e).__name__)
        satz = UEBERLAST if ist_ueberlast(e) else FEHLER
        gesprochen.append(satz)
        b.fehler = type(e).__name__
        await saetze.put(satz)
    await saetze.put(None)
    await sprecher
    antwort = " ".join(gesprochen).strip()
    aktion = {"werkzeuge": [w["name"] for w in b.werkzeuge]} if b.werkzeuge else None
    a.letzte = {"frage": frage, "antwort": antwort, "zeit": c.meeting.jetzt(), "aktion": aktion}
    b.gesagt, b.aktion = antwort, aktion
    if antwort:
        a.verlauf.append((frage, antwort))
        if not b.werkzeuge:  # Bedienlogik: jede reine Antwort steht auch als Karte im Verlauf; nach einem Werkzeug
            c.antwort_karte(frage, antwort, None, [], still=b.abgeloest, pflicht=True)  # zeigt das Dashboard dessen
            # Ergebnis selbst (Karte, Eintrag, Wechsel, später die Recherche)
    c.protokoll.append({"zeit": c.meeting.jetzt(), "art": "assistent", "frage": frage, "antwort": antwort,
                        "aktion": aktion, "sekunden": round(time.monotonic() - t0, 1)})
    await c.melden()


async def _runde(c, nachrichten: list, saetze: asyncio.Queue, gesprochen: list, *, werkzeuge: bool) -> list[dict]:
    """Ein gestreamter Aufruf: Text Satz für Satz in die Sprachausgabe, Werkzeugaufrufe gesammelt zurück."""
    wahl = c.wahl
    t0 = time.monotonic()
    extra = {"tools": W.fuer_chat(), "tool_choice": "auto" if werkzeuge else "none"}
    if wahl.assistent_aufwand:
        extra["reasoning_effort"] = wahl.assistent_aufwand
    strom = await c._client.chat.completions.create(model=wahl.assistent_modell, messages=nachrichten, stream=True,
                                                    stream_options={"include_usage": True}, **extra)
    puffer, aufrufe, nutzung = "", {}, None
    async for teil in strom:
        if teil.usage:
            nutzung = teil.usage
        if not teil.choices:
            continue
        d = teil.choices[0].delta
        for tc in getattr(d, "tool_calls", None) or []:
            x = aufrufe.setdefault(tc.index if tc.index is not None else len(aufrufe),
                                   {"id": "", "name": "", "argumente": ""})
            x["id"] = tc.id or x["id"]
            if tc.function is not None:
                x["name"] = tc.function.name or x["name"]
                x["argumente"] += tc.function.arguments or ""
        if d.content:
            puffer += d.content
            fertig, puffer = saetze_teilen(puffer)
            for s in filter(None, map(sprechbar, fertig)):
                gesprochen.append(s)
                await saetze.put(s)
    if sprechbar(puffer):
        gesprochen.append(sprechbar(puffer))
        await saetze.put(sprechbar(puffer))
    if nutzung:
        from .pipeline import nutzung_loggen

        nutzung_loggen({"art": "assistent", "modell": wahl.assistent_modell, "tokens_rein": nutzung.prompt_tokens,
                        "tokens_raus": nutzung.completion_tokens, "sekunden": round(time.monotonic() - t0, 1)})
    liste = [aufrufe[i] for i in sorted(aufrufe)]
    for i, x in enumerate(liste):
        x["id"] = x["id"] or f"aufruf{i:03d}"  # Mistral verlangt eine ID, die Antwort zurückgibt
    return [x for x in liste if x["name"]]
