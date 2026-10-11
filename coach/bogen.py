"""Antwortbogen (Ticket #27): was Nestor auf einen Auftrag hin zeigt und sagt.

Ein Bogen ist die einzige Gelegenheit, bei der Nestor spricht (außer der Begrüßung): sofort eine kurze Bestätigung
aus dem Floskel-Vorrat, dann erscheint die Karte im Verlauf, dann ein bis zwei Sätze zu dem, was auffällt – nie das
vorlesen, was auf der Karte steht. Ausgelöst wird er durch einen Zuruf („Nestor, …“, Premium), die Sprechtaste
(Basis, am Handy auch Premium), eine getippte Frage oder einen Knopf; alle Wege laufen hier zusammen.

Dieses Modul baut den Inhalt der Karten-Bögen (Wo stehen wir, Zusammenfassen, Was fehlt, Festgehalten, Regeln,
Überblick, Folie) und formuliert den Moderationssatz. Den Ablauf (Bestätigung, Sperre, Unterbrechen, Stimme) führt
der Assistent (coach/assistent.py).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from .analyse import mmss
from .config import EINST

log = logging.getLogger("coach.bogen")

KARTEN_ARTEN = ("stand", "zusammenfassen", "fehlt", "festgehalten", "regeln", "ueberblick", "folie",
                "neu_aufbereiten")
LANG_ARTEN = ("bild", "recherche")
NAMEN = {"stand": "Wo stehen wir?", "zusammenfassen": "Ergebnisse bündeln", "fehlt": "Lücken klären",
         "festgehalten": "Gesamtprotokoll", "regeln": "Regeln prüfen", "ueberblick": "Überblick", "folie": "Folie",
         "frage": "Frage", "bild": "Bild", "recherche": "Recherche", "neu_aufbereiten": "Karte neu aufbereiten"}

# --- Text-Weg (Basis, Premium-Kurzantwort): eindeutige Moderations-Aufträge direkt erkennen ----------------------
# Nur kurze, eindeutige Sätze – „fass zusammen, was Anna zum Budget gesagt hat“ ist eine Frage an das Modell. Im
# Gespräch (Premium) entscheidet das Modell selbst über seine Werkzeuge; dort wird nichts vorsortiert.
FUELL = {"bitte", "mal", "kurz", "doch", "uns", "mir", "nochmal", "jetzt", "gerade", "einmal", "eben", "okay", "ok",
         "hey", "noch", "schnell", "gerne", "gern", "denn", "eigentlich", "kannst", "könntest", "du", "würdest",
         "magst", "vielleicht", "bis", "hier", "dann", "also", "und", "ja"}
MUSTER = [
    ("zusammenfassen", r"(?:fass|fasse|fasst)(?: mir)?(?: das| alles| es| den punkt| den aktuellen punkt| bisher| soweit| die ergebnisse| ergebnisse)?"
                       r" zusammen|(?:gib|gibst|mach|machst|zeig|zeigst|hätte gern|hätten gern|ich hätte gern"
                       r"|wir hätten gern|wir brauchen|ich brauche)? ?(?:die |eine )?zusammenfassung(?: geben| machen)?"
                       r"|zusammenfassen|ergebnisse bündeln|bündel(?:e)?(?: mir)? die ergebnisse|"
                       r"bündle(?: mir)? die ergebnisse|bündeln wir die ergebnisse|lass(?: uns)? die ergebnisse bündeln"),
    ("fehlt", r"was fehlt|welche lücken(?: gibt es| haben wir)?|wo fehlt was|was ist offen|was haben wir offen"
              r"|wo sind lücken|was fehlt uns|lücken klären"),
    ("stand", r"wo stehen wir|wie weit sind wir|wo sind wir|wie ist der stand|was ist der stand"),
    ("festgehalten", r"(?:zeig|zeigst|gib|gibst)(?: das protokoll| die liste| was wir festgehalten haben"
                     r"| was festgehalten ist)|was haben wir festgehalten|was ist festgehalten|protokoll"
                     r"|was haben wir notiert|gesamtprotokoll"),
]


def karten_art(frage: str) -> str | None:
    """Ist das ein eindeutiger Moderations-Auftrag (Zusammenfassen, Was fehlt, Wo stehen wir, Festgehalten)?"""
    t = re.sub(r"[^\wäöüß ]", " ", (frage or "").lower())
    s = " ".join(w for w in t.split() if w not in FUELL)
    for art, muster in MUSTER:
        if re.fullmatch(muster, s):
            return art
    return None


# --- Moderationssatz ------------------------------------------------------------------------------------------
SATZ = """\
Du bist {name}, Moderationsassistent eines Präsenzmeetings. Auf dem Bildschirm erscheint gerade diese Karte:

{karte}

Sag der Runde dazu ein bis zwei kurze, gesprochene Sätze (zusammen höchstens 30 Wörter): Was fällt auf, was sollte
die Runde jetzt tun? Lies NICHT vor, was auf der Karte steht, keine Aufzählung. Fang mit „Hier ist sie.“ an. Per
„ihr“, nie „Sie“. Personen heißen „Person N“ – nenne sie nicht so. Erfinde nichts. Nur die Sätze."""
SATZ_FRIST = 5.0


def karte_als_text(karte: dict) -> str:
    z = [f"Titel: {karte.get('titel', '')}"] + [f"- {p}" for p in karte.get("punkte") or []]
    return "\n".join(z)


async def moderationssatz(coach, karte: dict, ersatz: str) -> str:
    """Kleiner Modellaufruf (Ticket #27): ein bis zwei Sätze zu dem, was auffällt. Ersatz bei Fehler oder Frist."""
    from .pipeline import nutzung_loggen

    if coach._client is None:
        return ersatz
    t0 = time.monotonic()
    # Basis bleibt bei mistral-medium: small war schneller (−2,5 s), sprach aber falsches Deutsch („sollten ihr“)
    modell = coach.wahl.assistent_modell
    try:
        r = await asyncio.wait_for(coach._client.chat.completions.create(
            model=modell,
            messages=[{"role": "user", "content": SATZ.format(name=EINST.assistent_name, karte=karte_als_text(karte))}],
            **({"reasoning_effort": coach.wahl.assistent_aufwand} if coach.wahl.assistent_aufwand else {})),
            SATZ_FRIST)
    except Exception as e:  # noqa: BLE001
        log.info("Moderationssatz nicht formuliert (%s) – Ersatz", type(e).__name__)
        return ersatz
    u = getattr(r, "usage", None)
    nutzung_loggen({"art": "assistent", "zweck": "bogen_satz", "modell": modell,
                    "tokens_rein": getattr(u, "prompt_tokens", None), "tokens_raus": getattr(u, "completion_tokens", None),
                    "sekunden": round(time.monotonic() - t0, 1)})
    text = re.sub(r"\s+", " ", (r.choices[0].message.content or "").replace("*", "")).strip().strip('"„“')
    if len(text) < 8 or text.startswith(("{", "[")):
        return ersatz  # kein brauchbarer Satz (leer, JSON) – lieber der Ersatz
    return text[:300]


# --- Karten aus den Meeting-Artefakten (live verknüpft: die Karte zeigt immer den aktuellen Stand) ----------------
def artefakt_karte(coach, art: str, titel: str, liste: list, luecken_zeigen: bool, **extra) -> dict:
    """Karte mit Artefakt-Nummern: Das Dashboard zeichnet die Einträge aus dem aktuellen Stand – eine Lücke, die die
    Runde schließt, wird in derselben Karte grün (Nachtrag A), statt eine neue Karte anzulegen."""
    from .artefakte import FELD_NAME

    punkte = []
    for a in liste[:12]:
        zeile = a.kurz().split(". ", 1)[-1]
        l = a.luecken()
        if luecken_zeigen and l and not a.abgelehnt:
            zeile += " – fehlt: " + ", ".join(FELD_NAME[x] for x in l)
        punkte.append(zeile)
    return {"art": art, "titel": titel, "ids": [a.id for a in liste], "luecken_zeigen": luecken_zeigen,
            "luecken_vorher": {str(a.id): a.luecken() for a in liste}, "punkte": punkte, **extra}


def luecken_text(liste: list) -> str:
    """„2 Aufgaben ohne Verantwortliche · 1 ohne Termin“ (Band, Ersatzsatz)."""
    ohne_wer = sum(1 for a in liste if a.typ == "aufgabe" and "wer" in a.luecken())
    ohne_bis = sum(1 for a in liste if a.typ == "aufgabe" and "bis" in a.luecken() and "wer" not in a.luecken())
    rest = sum(1 for a in liste if a.luecken() and a.typ != "aufgabe")
    teile = []
    if ohne_wer:
        teile.append(f"{ohne_wer} Aufgabe{'n' if ohne_wer > 1 else ''} ohne Verantwortliche")
    if ohne_bis:
        teile.append(f"{ohne_bis} ohne Termin")
    if rest:
        teile.append(f"{rest} {'weitere ' if teile else ''}Lücke{'n' if rest > 1 else ''}")
    return " · ".join(teile)


def _zahlwort(n: int) -> str:
    return {1: "Eine", 2: "Zwei", 3: "Drei", 4: "Vier", 5: "Fünf"}.get(n, str(n))


def ersatz_luecken(liste: list) -> str:
    luecken = [a for a in liste if a.luecken() and not a.abgelehnt]
    if not luecken:
        return "Hier ist sie. Alles Festgehaltene ist vollständig."
    ohne_wer = sum(1 for a in luecken if a.typ == "aufgabe" and "wer" in a.luecken())
    if ohne_wer:
        return (f"Hier ist sie. {_zahlwort(ohne_wer)} Aufgabe{'n haben' if ohne_wer > 1 else ' hat'} noch niemanden, "
                "der sich kümmert. Schaut kurz drauf.")
    return f"Hier ist sie. Bei {len(luecken)} Einträgen fehlt noch etwas. Schaut kurz drauf."


def bereich_waehlen(meeting, artefakte: list, bereich: str, punkt: int | None = None,
                    seit: float | None = None) -> tuple[str, list, list]:
    """(Titel, Ergebnisse, Transkript) eines Bereichs: Agendapunkt `punkt` (1-basiert), die Zeit `seit` Sekunden
    oder das ganze Meeting. Ergebnisse gehören zu dem Punkt, der aktiv war, als ihr Satz fiel."""
    if bereich == "punkt" and punkt is not None and 1 <= punkt <= len(meeting.agenda):
        i = punkt - 1
        return (f"Zusammenfassung · Punkt {punkt} · {meeting.agenda[i].titel}",
                [a for a in artefakte if a.punkt == i], meeting.punkt_transkript(i))
    if bereich == "seit" and seit is not None:
        return (f"Zusammenfassung · seit {mmss(seit)}", [a for a in artefakte if a.zeit >= seit],
                [s for s in meeting.transkript if s.ende >= seit])
    return f"Zusammenfassung · Stand {mmss(meeting.jetzt())}", list(artefakte), list(meeting.transkript)


def zusammenfassung_auswahl(artefakte: list) -> list:
    """Was auf die Karte passt: Beschlossenes zuerst, dann Aufgaben, dann Offenes (je die jüngsten)."""
    from .artefakte import beschlossen

    beschl = [a for a in artefakte if beschlossen(a)]
    aufgaben = [a for a in artefakte if a.typ == "aufgabe"]
    offen = [a for a in artefakte if a.typ != "aufgabe" and not beschlossen(a)]
    return beschl[-5:] + aufgaben[-8:] + offen[-4:]


NACHHOLEN_FRIST = 4.0  # so lange darf das Nachholen der Ergebnisse eine Zusammenfassung aufhalten


async def bereich_karte(coach, bereich: str = "gesamt", punkt: int | None = None,
                        seit: float | None = None) -> tuple[dict, list, str]:
    """Zusammenfassungs-Karte eines Bereichs aus den Ergebnissen (live verknüpft), dazu die Liste und ein
    Transkript-Auszug des Bereichs (für das, was besprochen, aber nicht festgehalten wurde)."""
    art = coach.artefakte
    try:
        await asyncio.wait_for(art.nachholen(), NACHHOLEN_FRIST)
    except asyncio.TimeoutError:
        log.info("Zusammenfassen: Nachholen dauert – mit dem bisherigen Stand")
    m = coach.meeting
    titel, artefakte, saetze = bereich_waehlen(m, art.liste, bereich, punkt, seit)
    liste = zusammenfassung_auswahl(artefakte)
    karte = artefakt_karte(coach, "zusammenfassung", titel, liste, True)
    if not liste:
        karte["punkte"] = ["Hier ist noch keine Entscheidung und keine Aufgabe festgehalten."]
    luecken = [a for a in art.luecken_liste(12) if a in artefakte][:3]
    for a in luecken:
        a.nachgefragt = True
    art.verlauf.append({"zeit": round(m.jetzt(), 1), "art": "zusammenfassung", "ids": [a.id for a in luecken]})
    coach.protokoll.append({"zeit": m.jetzt(), "art": "zusammenfassung", "bereich": bereich,
                            "luecken": [a.id for a in luecken]})
    auszug = "\n".join(f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in saetze if s.text)[-3000:]
    return karte, liste, auszug


async def zusammenfassen(coach, b) -> tuple[dict, str]:
    karte, liste, _ = await bereich_karte(coach, "gesamt")
    if not liste:
        karte["punkte"] = ["Bisher ist keine Entscheidung und keine Aufgabe festgehalten."]
    ersatz = ersatz_luecken(liste) if liste else "Hier ist sie. Bisher habe ich noch nichts Festes notiert."
    return karte, await moderationssatz(coach, karte, ersatz)


async def fehlt(coach, b) -> tuple[dict, str]:
    art = coach.artefakte
    await art.nachholen()
    liste = art.luecken_liste(12)
    karte = artefakt_karte(coach, "fehlt", "Was noch fehlt", liste, True)
    if not liste:
        karte["punkte"] = ["Keine Lücken: Alles Festgehaltene hat Wer und Termin."]
        return karte, "Hier ist sie. Gerade fehlt nichts – alles hat jemanden und einen Termin."
    return karte, await moderationssatz(coach, karte, ersatz_luecken(liste))


async def festgehalten(coach, b) -> tuple[dict, str]:
    art = coach.artefakte
    await art.nachholen()
    from .knopfdruck import _protokoll_md

    coach.knopf.protokoll = _protokoll_md(coach)
    coach.knopf.protokoll_zeit = coach.meeting.jetzt()
    karte = artefakt_karte(coach, "festgehalten", "Festgehalten", list(art.liste), True, protokoll=True)
    if not art.liste:
        karte["punkte"] = ["Noch nichts festgehalten."]
    n = sum(1 for a in art.liste if a.luecken() and not a.abgelehnt)
    satz = B_HIER["festgehalten"] + (f" Bei {n} Einträgen fehlt noch etwas." if n else "")
    return karte, satz


async def stand(coach, b) -> tuple[dict, str]:
    """Ein Aufruf liefert Karte und Satz (schneller als zwei)."""
    from . import knopfdruck

    m = coach.meeting
    roh = await knopfdruck._karte_vom_modell(coach, knopfdruck.STAND.replace("{name}", EINST.assistent_name),
                                             coach.assistent.kontext("Wo stehen wir, und was ist der nächste Schritt?"),
                                             "stand")
    karte = {"art": "stand", "frage": NAMEN["stand"], "titel": str(roh.get("titel") or "Stand")[:80],
             "punkte": knopfdruck._punkte(roh) or ["Dazu konnte Nestor gerade nichts sagen."]}
    try:
        ziel = int(roh.get("naechster_punkt")) - 1
    except (TypeError, ValueError):
        ziel = None
    if ziel is not None and 0 <= ziel < len(m.agenda) and ziel != m.aktiver_punkt:
        m.vorschlag = {"punkt": ziel, "titel": m.agenda[ziel].titel, "begruendung": "Vorschlag auf Knopfdruck"}
    satz = re.sub(r"\s+", " ", str(roh.get("sagen") or "")).strip() or "Hier ist sie."
    return karte, satz[:300]


async def regeln(coach, b) -> tuple[dict, str]:
    from . import knopfdruck

    karte = await knopfdruck._regeln(coach, "", ablegen=False)
    rot = [r for r in coach.schnappschuss()["regel_status"] if r["farbe"] in ("gelb", "rot")]
    if not coach.meeting.regel_ids:
        satz = "Für dieses Meeting habt ihr keine Regeln gewählt."
    elif not rot:
        satz = "Hier ist sie. Sieht gut aus, alles im grünen Bereich."
    else:
        satz = f"Hier ist sie. Bei „{rot[0]['titel']}“ hakt es gerade."
    return karte, satz


async def ueberblick(coach, b) -> tuple[dict | None, str]:
    if not coach.meeting.transkript:
        return ({"art": "antwort", "titel": "Überblick", "punkte": ["Noch nichts gesagt – für einen Überblick fehlt "
                                                                    "der Stoff."]}, "Dafür habt ihr noch zu wenig gesagt.")
    while coach._ueberblick_laeuft:
        await asyncio.sleep(0.3)
    u = await coach.ueberblick_bauen(karte=False, fokus=b.fokus or None)
    if u is None:
        return None, "Der Überblick hat gerade nicht geklappt."
    from . import ueberblick as U

    karte = {"art": "ueberblick", "frage": "Überblick", "titel": "Überblick · Stand " + u["laufzeit"],
             "punkte": U.punkte(u), "ueberblick": u}
    return karte, B_HIER["ueberblick"]


async def folie(coach, b) -> tuple[dict | None, str]:
    if coach.letzte_recherche is None:
        return None, "Dafür brauche ich erst eine Recherche."
    f = await coach.folie_bauen(karte=False)
    if f is None:
        return None, "Die Folie hat gerade nicht geklappt."
    karte = {"art": "folie", "titel": f["titel"], "frage": f["frage"], "punkte": f["punkte"], "quellen": f["quellen"],
             "folie": f}
    return karte, B_HIER["folie"]


async def neu_aufbereiten(coach, b) -> tuple[dict | None, str]:
    """Die zuletzt gezeigte Karte per LLM-Aufruf neu aufbereiten (Ticket #84): „Nestor, bereite das kürzer auf“.
    `b.fokus` trägt das „wie“ (kürzer, ausführlicher, als_liste, einfacher); `coach.karten[-1]` ist zu diesem
    Zeitpunkt noch die vorherige Karte – diese Karte selbst kommt erst danach über `_karte_ablegen` dazu."""
    from . import neu_aufbereiten as N

    vorherige = coach.karten[-1] if coach.karten else None
    if coach._client is None or not N.moeglich(vorherige):
        return None, "Dafür habe ich gerade keine passende Karte."
    karte, nutzung = await N.erstellen(coach._client, vorherige, b.fokus, wahl=coach.wahl)
    if karte is None:
        return None, "Das hat gerade nicht geklappt."
    if nutzung:
        from .pipeline import nutzung_loggen

        nutzung_loggen({"art": "neu_aufbereiten", "modell": coach.wahl.analyse_modell, **nutzung})
    return karte, B_HIER["karte"]


from .bestaetigung import HIER as B_HIER  # noqa: E402

BAUER = {"stand": stand, "zusammenfassen": zusammenfassen, "fehlt": fehlt, "festgehalten": festgehalten,
         "regeln": regeln, "ueberblick": ueberblick, "folie": folie, "neu_aufbereiten": neu_aufbereiten}
