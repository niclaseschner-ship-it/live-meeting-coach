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
import json
import logging
import re
import time

from .analyse import mmss
from .config import EINST

log = logging.getLogger("coach.bogen")

KARTEN_ARTEN = ("stand", "zusammenfassen", "fehlt", "festgehalten", "regeln", "ueberblick", "folie")
LANG_ARTEN = ("bild", "recherche")
NAMEN = {"stand": "Wo stehen wir?", "zusammenfassen": "Ergebnisse bündeln", "fehlt": "Lücken klären",
         "festgehalten": "Gesamtprotokoll", "regeln": "Regeln prüfen", "ueberblick": "Überblick", "folie": "Folie",
         "frage": "Frage", "bild": "Bild", "recherche": "Recherche"}

# --- Was will die Runde? Eindeutige Moderations-Aufträge direkt erkennen ------------------------------------------
# Nur kurze, eindeutige Sätze – „fass zusammen, was Anna zum Budget gesagt hat“ ist eine Frage an das Modell.
FUELL = {"bitte", "mal", "kurz", "doch", "uns", "mir", "nochmal", "jetzt", "gerade", "einmal", "eben", "okay", "ok",
         "hey", "noch", "schnell", "gerne", "gern", "denn", "eigentlich", "kannst", "könntest", "du", "würdest",
         "magst", "vielleicht", "bis", "hier", "dann", "also", "und", "ja"}
MUSTER = [
    ("zusammenfassen", r"(?:fass|fasse|fasst)(?: das| alles| es| den punkt| den aktuellen punkt| bisher| soweit)?"
                       r" zusammen|(?:gib|gibst|mach|machst|zeig|zeigst|hätte gern|hätten gern|ich hätte gern"
                       r"|wir hätten gern|wir brauchen|ich brauche)? ?(?:die |eine )?zusammenfassung(?: geben| machen)?"
                       r"|zusammenfassen|ergebnisse bündeln"),
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


# --- Rückfrage-Fenster (Premium): ist der erste Satz nach dem Bogen an Nestor gerichtet? -----------------------
# Ticket #27, Nachtrag C („Follow-up-Modus“ wie bei Sprachassistenten): Nur der erste Satz nach dem Bogen kann eine
# Nachfrage sein; ist er es nicht, schließt das Fenster sofort. Regeln, dann ein Klassifikator, im Zweifel schweigen –
# ein falsches Antworten bricht die Grundregel, ein verpasstes kostet nur ein neues „Nestor, …“.
NICHT_NAMEN = {"und", "also", "okay", "gut", "ja", "nein", "danke", "super", "prima", "genau", "moment", "hm", "achso",
               "ach", "klar", "stimmt", "aber", "dann", "so", "nee", "naja", "na", "oder", "jetzt", "hier", "das", "die",
               "der", "wir", "ihr", "ich", "du", "sie", "es", "was", "wer", "wie", "wo", "wann", "warum", "bitte",
               "perfekt", "richtig", "eben", "tja", "ok", "sorry", "hallo", "hey", "kurz", "übrigens", "apropos"}
VOKATIV_RE = re.compile(r"^\W*([A-ZÄÖÜ][a-zäöüß]+)\s*,")
ODER_NAME_RE = re.compile(r",\s*(?:oder|gell|ne|nicht wahr)?\s*([A-ZÄÖÜ][a-zäöüß]+)\s*\?\s*$")
ANSCHLUSS_RE = re.compile(r"^\W*und\s+(?:bis\s+wann|wer|wann|wie\s+viel\w*|wie\s+lange|wo|was|warum|wieso|"
                          r"welche\w*|wofür|womit)\b[^.!]*\?\s*$", re.IGNORECASE)
AUFTRAG_RE = re.compile(r"^\W*(?:und\s+)?(?:bitte\s+)?(?:zeig|trag|ergänz|ergänze|schreib|fass|erklär|erkläre|such|"
                        r"recherchier|lies|nenn|wiederhol|notier|halt\s+fest|mach\s+(?:uns|mir|eine?n?|die|den|das\s+bitte)"
                        r"|gib\s+(?:uns|mir)|kannst\s+du|könntest\s+du|würdest\s+du|magst\s+du)\b", re.IGNORECASE)


def jemand_anderes(text: str, namen: list[str] | None = None) -> bool:
    """„Anna, das machst du doch, oder?“, „… oder Tarek?“ – die Runde spricht eine Person an, nicht Nestor."""
    bekannte = {n.split()[0].lower() for n in namen or [] if n}
    for m in (VOKATIV_RE.match(text), ODER_NAME_RE.search(text)):
        if m and m.group(1).lower() not in NICHT_NAMEN and m.group(1).lower() != EINST.assistent_name.lower():
            return True
    woerter = {w.lower() for w in re.findall(r"\w+", text)}
    return bool(bekannte & woerter) and not AUFTRAG_RE.match(text)


# Ticket #28: kurze „Und …?“-Frage ohne Wir-/Uns-Sicht – „Und reicht das noch für alle Punkte?“ (Grenzfall 1r) ordnete
# der strengere Klassifikator in 2 von 3 Messungen als Gespräch der Runde ein
UND_FRAGE_RE = re.compile(r"^\W*und\b[^.!]*\?\s*$", re.IGNORECASE)
WIR_RE = re.compile(r"\b(?:wir|uns|unser\w*)\b", re.IGNORECASE)


def klar_an_nestor(text: str, namen: list[str] | None = None) -> bool:
    """Eindeutige Anschlussfrage („Und bis wann?“, „Und reicht das noch für alle Punkte?“) oder ein Auftrag („Zeig …“,
    „Kannst du …“) ohne anderen Namen."""
    und_frage = bool(UND_FRAGE_RE.match(text)) and len(text.split()) <= 8 and not WIR_RE.search(text)
    return not jemand_anderes(text, namen) and bool(ANSCHLUSS_RE.match(text) or AUFTRAG_RE.match(text) or und_frage)


# Ticket #28, Premium-Abendlauf 08.10.: Nach „Und reicht das noch für alle Punkte?“ (Antwort: „noch knapp drei Minuten“)
# fragte jemand die Kollegen „Heißt das, selbst ein schneller Application Rollback hätte uns nicht gerettet“ – eine
# Frage zu dem, was die Runde vorher besprochen hatte (Jonas: „… weshalb kein vollständiger Rollback möglich war“).
# Der Klassifikator hielt sie in 6 von 6 Messungen für eine Nachfrage an Nestor. Deshalb eine dritte Regel vor dem
# Modell: Teilt der Satz ein Sachwort mit dem, was die Runde zuletzt gesagt hat, aber keins mit Nestors Frage und
# Antwort, und spricht er Nestor nicht an, knüpft er an die Runde an – schweigen.
DU_RE = re.compile(r"\b(?:du|dir|dich|dein\w*|euch)\b", re.IGNORECASE)
NICHT_SACHWORT = {"haben", "hatte", "hätte", "hätten", "hatten", "würde", "würden", "werden", "wurde", "wurden",
                  "können", "konnte", "könnte", "müssen", "musste", "müsste", "sollen", "sollte", "sollten", "wollen",
                  "nicht", "schon", "immer", "eigentlich", "selbst", "heißt", "einen", "einem", "einer", "eines",
                  "diese", "dieser", "dieses", "diesem", "diesen", "unser", "unsere", "unseren", "unserem", "unserer",
                  "ihnen", "denen", "deren", "dessen", "damit", "darum", "dafür", "davon", "dazu", "daran", "wieder",
                  "etwas", "nichts", "alles", "allen", "aller", "jetzt", "gerade", "vorhin", "danach", "dabei",
                  "nochmal", "ebenfalls", "wirklich", "genau", "vielleicht", "ungefähr", "eben", "sowie", "weil",
                  "obwohl", "warum", "wieso", "welche", "welcher", "welches", "machen", "macht", "gesagt", "sagen",
                  "meinst", "meint", "kommen", "kommt", "gehen", "geht", "lassen", "zwischen", "durch", "gegen",
                  "unter", "über", "ohne", "schnell", "schneller", "bitte", "kurze", "kurzer", "erste", "ersten",
                  "zweite", "zweiten", "dritte", "dritten", "meine", "meiner", "seine", "ihrer", "ihren", "nestor"}


def _sachworte(text: str) -> set[str]:
    """Sachwörter (ab fünf Buchstaben, ohne Füllwörter), auf die ersten fünf Buchstaben gekürzt – „Rollback“ und
    „Rollbacks“, „schneller“ und „schnell“ fallen zusammen."""
    return {w[:5] for w in re.findall(r"[a-zäöüß]+", (text or "").lower()) if len(w) >= 5 and w not in NICHT_SACHWORT}


def knuepft_an_runde(text: str, vorher: list[str] | None, frage: str, antwort: str) -> bool:
    """„Heißt das, selbst ein schneller Application Rollback hätte uns nicht gerettet“ nach einer Antwort zur Restzeit:
    gleiches Sachwort wie die Runde vorher („Rollback“), keins wie Nestors Frage und Antwort, keine Anrede."""
    if DU_RE.search(text) or AUFTRAG_RE.match(text):
        return False
    eigene = _sachworte(text)
    runde = set().union(*(_sachworte(v.split(":", 1)[-1]) for v in vorher or [])) if vorher else set()
    return bool(eigene & runde) and not eigene & _sachworte(f"{frage} {antwort}")


EINORDNEN = """\
Ein Moderationsassistent namens {name} hat einer Besprechungsrunde gerade geantwortet. Direkt danach sagt jemand im
Raum den Satz unten. Ordne ihn ein:
- "frage_an_nestor": nur eine eindeutige Anschlussfrage, Bitte oder ein Auftrag an den Assistenten, der eine Antwort
  braucht. Dafür spricht: „Und …?“ als Anschluss an seine Antwort, die du-Form an ihn, eine Aufforderung an ihn
  („zeig“, „trag ein“), ein Rückbezug auf seine Worte („was meinst du mit …“, „welche … ist da gemeint“).
- "an_nestor_ohne_antwort": an den Assistenten, braucht aber keine Antwort („Passt“, „Danke“, „Alles klar“)
- "nicht_an_nestor": die Leute reden untereinander (über die Karte, mit einer Person, Weiterarbeit, Diskussion).
  Dafür spricht: die Wir-/Uns-Sicht aufs eigene Thema („Heißt das, … hätte uns …“, „Sollten wir nicht …“), eine Frage
  an die Runde, eine angesprochene Person.
Im Zweifel "nicht_an_nestor". Antworte nur mit JSON: {{"einordnung": "…"}}

Zuletzt in der Runde gesagt:
{vorher}
Frage an den Assistenten: {frage}
Seine Antwort: {antwort}
Satz: {satz}"""
EINORDNEN_FRIST = 2.5
EINORDNUNGEN = ("frage_an_nestor", "an_nestor_ohne_antwort", "nicht_an_nestor")


async def einordnen(client, satz: str, antwort: str, frage: str = "", vorher: list[str] | None = None
                    ) -> tuple[str, dict]:
    """Schneller Text-Klassifikator (Premium): (Einordnung, Nutzung). Fehler oder Frist: nicht an Nestor.

    Ticket #28: Er sieht auch die Frage, auf die Nestor geantwortet hat, und die letzten Sätze der Runde davor (`vorher`).
    Nur mit der Antwort („Ihr habt noch knapp drei Minuten.“) hielt er eine Sachfrage der Runde („Heißt das, selbst ein
    schneller Application Rollback hätte uns nicht gerettet“ – sie knüpft an „… weshalb kein vollständiger Rollback
    möglich war“ an) in 6 von 6 Messungen für eine Nachfrage an Nestor; diesen Fall fängt jetzt schon die Regel
    knuepft_an_runde ab. Prompt-Fassungen mit Prüffragen („gleiches Thema?“) machten ihn zu streng (Messung:
    scripts/einordnen_messen.py)."""
    if client is None:
        return "nicht_an_nestor", {}
    extra = {}
    if EINST.einordnen_aufwand:
        extra["reasoning_effort"] = EINST.einordnen_aufwand
    try:
        r = await asyncio.wait_for(client.chat.completions.create(
            model=EINST.assistent_modell, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": EINORDNEN.format(name=EINST.assistent_name, frage=(frage or "-")[:300],
                                                                  vorher="\n".join(vorher or []) or "-",
                                                                  antwort=(antwort or "-")[:600], satz=satz)}],
            **extra), EINORDNEN_FRIST)
        roh = json.loads(r.choices[0].message.content or "{}")
    except Exception as e:  # noqa: BLE001 – im Zweifel still
        log.info("Einordnung nicht möglich (%s)", type(e).__name__)
        return "nicht_an_nestor", {}
    u = getattr(r, "usage", None)
    nutzung = {"tokens_rein": getattr(u, "prompt_tokens", None), "tokens_raus": getattr(u, "completion_tokens", None)}
    e = roh.get("einordnung")
    return (e if e in EINORDNUNGEN else "nicht_an_nestor"), nutzung


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
    modell = EINST.assistent_modell
    try:
        r = await asyncio.wait_for(coach._client.chat.completions.create(
            model=modell,
            messages=[{"role": "user", "content": SATZ.format(name=EINST.assistent_name, karte=karte_als_text(karte))}],
            **({"reasoning_effort": EINST.assistent_aufwand} if EINST.assistent_aufwand else {})),
            SATZ_FRIST if EINST.ki != "codex" else 40)
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


async def zusammenfassen(coach, b) -> tuple[dict, str]:
    art = coach.artefakte
    await art.nachholen()
    m = coach.meeting
    beschl = [a for a in art.liste if a.typ == "entscheidung" and a.status != "vorschlag"]
    aufgaben = [a for a in art.liste if a.typ == "aufgabe"]
    offen = [a for a in art.liste if a.typ in ("offen", "risiko") or (a.typ == "entscheidung" and a.status == "vorschlag")]
    liste = beschl[-5:] + aufgaben[-8:] + offen[-4:]
    karte = artefakt_karte(coach, "zusammenfassung", f"Zusammenfassung · Stand {mmss(m.jetzt())}", liste, True)
    if not liste:
        karte["punkte"] = ["Bisher ist keine Entscheidung und keine Aufgabe festgehalten."]
    luecken = art.luecken_liste(3)
    for a in luecken:
        a.nachgefragt = True
    art.verlauf.append({"zeit": round(m.jetzt(), 1), "art": "zusammenfassung", "ids": [a.id for a in luecken]})
    coach.protokoll.append({"zeit": m.jetzt(), "art": "zusammenfassung", "luecken": [a.id for a in luecken]})
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


from .bestaetigung import HIER as B_HIER  # noqa: E402

BAUER = {"stand": stand, "zusammenfassen": zusammenfassen, "fehlt": fehlt, "festgehalten": festgehalten,
         "regeln": regeln, "ueberblick": ueberblick, "folie": folie}
