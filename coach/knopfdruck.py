"""Die Knöpfe (Lastenheft 4.2, Ticket #6, seit #13 in beiden Stufen gleich): die fünf Kernaktionen plus Bild,
Regelprüfung und freie Frage – unabhängig davon, ob sie über die Knopfleiste, einen Zuruf oder die Sprechtaste
ausgelöst werden (coach/assistent.py, coach/bogen.py). Ein Knopf führt die gewählte Analyse aus – aus vorhandenen
Bausteinen:

   stand     Wo stehen wir? Kontext wie bei Nestors Antworten (Assistent.kontext), Antwort als Karte
   regeln    die Regel-Ampeln zusammengefasst, ohne eigenen KI-Aufruf
   protokoll Meeting-Artefakte erkennen (coach/artefakte.py, Ticket #26), daraus protokoll.md und eine Karte
   bild      das vorhandene Live-Bild (onepager_starten)
   frage     freie Frage, Antwort als Text-Karte über den vorhandenen Karten-Weg

Fortschritt geht als {"typ": "knopf", "art", "schritt": "denke"|"fertig", "anteil": 0..1} an alle Dashboards; die
Sekunden je Schritt landen ohne Inhalte in logs/nestor_zeiten.jsonl (Latenzmessung 4.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

from .analyse import mmss
from .config import EINST

log = logging.getLogger("coach.knopfdruck")

ARTEN = ("stand", "regeln", "ueberblick", "protokoll", "bild", "frage", "zusammenfassen", "fehlt")
NAMEN = {"stand": "Wo stehen wir?", "regeln": "Regeln eingehalten?", "ueberblick": "Überblick", "protokoll": "Protokoll",
         "bild": "Bild", "frage": "Nestor fragen", "zusammenfassen": "Zusammenfassen", "fehlt": "Was fehlt?"}


class KnopfFehler(RuntimeError):
    """Knopf geht gerade nicht (kein Meeting, kein Schlüssel, läuft schon) – Text für die Oberfläche."""


class Knopfstand:
    """Zustand der Knopf-Analysen eines Meetings (am Coach: `coach.knopf`)."""

    def __init__(self) -> None:
        self.sperre = asyncio.Lock()  # ein Knopf zur Zeit
        self.laeuft: str | None = None  # Art des laufenden Knopfs
        self.schritt: str | None = None
        self.anteil = 0.0
        self.fehler: str | None = None
        self.protokoll: str | None = None  # Markdown vom Protokoll-Knopf (geht als protokoll.md in die Ablage)
        self.protokoll_zeit: float | None = None

    def schnappschuss(self) -> dict:
        return {"laeuft": self.laeuft, "schritt": self.schritt, "anteil": round(self.anteil, 2),
                "fehler": self.fehler, "protokoll": self.protokoll is not None}


# --- Ablauf -----------------------------------------------------------------
def reservieren(coach, art: str) -> None:
    """Vor dem Start prüfen und belegen (synchron, damit ein Doppelklick nicht zwei Läufe startet)."""
    k = coach.knopf
    if art not in ARTEN:
        raise KnopfFehler("Unbekannter Knopf.")
    if coach.hoerstrom is None:
        raise KnopfFehler("Es läuft kein Meeting.")
    if coach._client is None:
        raise KnopfFehler("Kein KI-Schlüssel – ohne ihn kann Nestor nichts auswerten.")
    if k.laeuft:
        raise KnopfFehler(f"Nestor ist noch bei „{NAMEN[k.laeuft]}“ – bitte kurz warten.")
    k.laeuft, k.schritt, k.anteil, k.fehler = art, "denke", 0.0, None


async def ausfuehren(coach, art: str, frage: str = "", senden=None) -> dict | None:
    """Ein Knopf: die Analyse ausführen. `senden(nachricht)` verteilt den Fortschritt.
    Ruft vorher `reservieren()` auf, falls das nicht schon geschehen ist. Liefert das Ergebnis oder None."""
    k = coach.knopf
    if k.laeuft != art:
        reservieren(coach, art)
    from .pipeline import _zeit_loggen, fehlertext

    zeiten = {"ausloeser": "knopf", "art": art, "meeting_s": round(coach.meeting.jetzt(), 1)}
    t0 = time.monotonic()

    async def melden(schritt: str, anteil: float, **extra) -> None:
        k.schritt, k.anteil = schritt, anteil
        if senden is not None:
            try:
                await senden({"typ": "knopf", "art": art, "schritt": schritt, "anteil": round(anteil, 2), **extra})
            except Exception:  # noqa: BLE001 – ein weggebrochenes Dashboard hält den Knopf nicht auf
                log.debug("Fortschritt nicht gesendet", exc_info=True)

    erg = None
    async with k.sperre:
        try:
            await melden("denke", 0.0)
            t1 = time.monotonic()
            erg = await ANALYSEN[art](coach, frage)
            zeiten["analyse_s"] = round(time.monotonic() - t1, 2)
            await melden("fertig", 1.0)
        except Exception as e:  # noqa: BLE001 – Fehler zeigen, Meeting läuft weiter
            log.warning("Knopf „%s“ fehlgeschlagen: %s", art, fehlertext(e))
            k.fehler = str(e) if isinstance(e, KnopfFehler) else f"„{NAMEN[art]}“ hat nicht geklappt ({fehlertext(e)})."
            zeiten["fehler"] = type(e).__name__
            await melden("fertig", 1.0, fehler=k.fehler)
        finally:
            zeiten["gesamt_s"] = round(time.monotonic() - t0, 2)
            _zeit_loggen(zeiten)
            k.laeuft = None
            await coach.melden()
    return erg


# --- Analysen -----------------------------------------------------------------
KARTE_FORMAT = ('Antworte ausschließlich mit JSON: {"titel": "höchstens 6 Wörter", '
                '"punkte": ["2 bis 5 Stichpunkte, je höchstens 16 Wörter"]')
GRUNDSATZ = ("Neutral: keine Bewertung von Personen, keine Partei, nichts erfinden – was nicht im Kontext steht, "
             "weißt du nicht, dann sag das. Personen heißen im Transkript „Person N“; nenne sie nicht so, sprich von "
             "„jemandem“ oder der Gruppe. „Entschieden“ nur, wenn ausdrücklich beschlossen. Deutsch, per „ihr“.")

STAND = (f"Du bist {{name}}, der Moderationsassistent eines Präsenzmeetings. Die Runde hat gefragt „Wo stehen "
         f"wir?“. {KARTE_FORMAT}, \"naechster_punkt\": Nummer oder null, \"sagen\": \"ein bis zwei kurze gesprochene "
         f"Sätze, zusammen höchstens 30 Wörter\"}}.\n"
         "Stichpunkte: wo die Runde in der Agenda steht und wie es mit der Zeit aussieht, was festgehalten ist, was "
         "offen ist; der letzte Stichpunkt ist ein Vorschlag für den nächsten Schritt und beginnt mit „Vorschlag:“.\n"
         "Agenda-Titel und Ziele ausschließlich aus den gespeicherten Agendadaten wörtlich übernehmen. "
         "Keine erfundenen Erläuterungen eines Punktes als bestehende Agenda ausgeben. Zusätzliche Ideen immer "
         "ausdrücklich als Vorschlag markieren.\n"
         "naechster_punkt: Nummer des Agendapunkts, zu dem die Runde jetzt wechseln sollte – nur wenn der aktuelle "
         "erledigt ist oder das Gespräch schon beim nächsten ist, sonst null.\n"
         "sagen: was auffällt oder was die Runde jetzt tun sollte – NICHT vorlesen, was auf der Karte steht; beginnt "
         f"mit „Hier ist sie.“\n{GRUNDSATZ}")

FRAGE = (f"Du bist {{name}}, der Moderationsassistent eines Präsenzmeetings. Die Runde hat dir eine Frage getippt; "
         f"die Antwort erscheint als Karte auf dem Bildschirm. {KARTE_FORMAT}}}.\n"
         "Der Titel nennt das Thema der Frage, die Stichpunkte beantworten sie – das Wichtigste zuerst, kurz.\n"
         f"{GRUNDSATZ}")


async def _karte_vom_modell(coach, system: str, nutzer: str, knopf: str, nutzung_art: str = "assistent") -> dict:
    """Ein Aufruf mit JSON-Antwort; Kosten unter der vorhandenen Art im Nutzungsprotokoll (ohne Inhalte)."""
    from .pipeline import nutzung_loggen

    t0 = time.monotonic()
    r = await coach._client.chat.completions.create(
        model=coach.wahl.assistent_modell, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": nutzer}],
        **({"reasoning_effort": coach.wahl.assistent_aufwand} if coach.wahl.assistent_aufwand else {}))
    try:
        roh = json.loads(r.choices[0].message.content or "{}")
    except ValueError:
        roh = {}
    u = getattr(r, "usage", None)
    nutzung_loggen({"art": nutzung_art, "modell": coach.wahl.assistent_modell, "knopf": knopf,
                    "tokens_rein": getattr(u, "prompt_tokens", None), "tokens_raus": getattr(u, "completion_tokens", None),
                    "sekunden": round(time.monotonic() - t0, 1)})
    return roh if isinstance(roh, dict) else {}


def _punkte(roh: dict, n: int = 5) -> list[str]:
    return [str(p)[:200] for p in (roh.get("punkte") or []) if str(p).strip()][:n]


async def _stand(coach, frage: str) -> dict:
    m = coach.meeting
    roh = await _karte_vom_modell(coach, STAND.replace("{name}", EINST.assistent_name),
                                  coach.assistent.kontext("Wo stehen wir, und was ist der nächste Schritt?"), "stand")
    karte = {"art": "stand", "frage": NAMEN["stand"], "titel": str(roh.get("titel") or "Stand")[:80],
             "punkte": _punkte(roh) or ["Dazu konnte Nestor gerade nichts sagen."]}
    try:
        ziel = int(roh.get("naechster_punkt")) - 1
    except (TypeError, ValueError):
        ziel = None
    if ziel is not None and 0 <= ziel < len(m.agenda) and ziel != m.aktiver_punkt:
        # derselbe Vorschlag wie bei der Themen-Zuordnung live: „Weiter zu …?“ – die Runde entscheidet
        m.vorschlag = {"punkt": ziel, "titel": m.agenda[ziel].titel, "begruendung": "Vorschlag auf Knopfdruck"}
    coach._karte_ablegen(karte)
    return karte


async def _frage(coach, frage: str) -> dict:
    roh = await _karte_vom_modell(coach, FRAGE.replace("{name}", EINST.assistent_name),  # JSON-Klammern: kein format
                                  coach.assistent.kontext(frage), "frage")
    punkte = _punkte(roh) or ["Dazu konnte Nestor gerade nichts sagen."]
    karte = {"art": "antwort", "frage": frage, "titel": str(roh.get("titel") or frage)[:80], "punkte": punkte}
    coach.assistent.verlauf.append((frage, " ".join(punkte)))  # Rückfragen beziehen sich darauf (kontext)
    coach._karte_ablegen(karte)
    return karte


async def _regeln(coach, frage: str, ablegen: bool = True) -> dict:
    """Fokus, Ton und Ergebnisse prüft Nestor laufend – die Karte fasst die Ampeln zusammen, ohne eigenen
    KI-Aufruf."""
    m = coach.meeting
    punkte = [f"{r['titel']}: " + ("eingehalten" if r["farbe"] in ("gruen", "grau") else "Achtung")
              + (f" – {r['detail']}" if r["detail"] else "") for r in coach.schnappschuss()["regel_status"]]
    karte = {"art": "regeln", "frage": NAMEN["regeln"], "titel": f"Regeln · Stand {mmss(m.jetzt())}",
             "punkte": punkte or ["Für dieses Meeting sind keine Gesprächsregeln gewählt."]}
    if ablegen:
        coach._karte_ablegen(karte)
    return karte


def _protokoll_md(coach, am_ende: bool = False) -> str:
    """Protokoll aus den Meeting-Artefakten (Ticket #26): je Agendapunkt Entscheidungen, Aufgaben, offene Punkte und
    Risiken, danach was außerhalb der Agenda festgehalten wurde. Lücken stehen als „fehlt“ dabei."""
    from .artefakte import FELD_NAME

    m, art = coach.meeting, coach.artefakte
    wie = "am Meetingende" if am_ende else "auf Knopfdruck"
    z = [f"# Protokoll: {m.titel or 'Meeting'}", "",
         f"{datetime.now():%d.%m.%Y} · Laufzeit {mmss(m.jetzt())} min · erstellt von Nestor {wie}"]
    if m.ziel:
        z.append(f"Ziel: {m.ziel}")

    def zeile(a) -> str:
        teile = [a.was]
        if a.typ == "entscheidung":
            teile.append({"endgueltig": "beschlossen", "vorlaeufig": "vorläufig"}.get(a.status, "nur Vorschlag"))
        if a.typ != "entscheidung" or a.wer:
            teile.append(f"wer: {a.wer or 'offen'}")
        if a.typ in ("aufgabe", "offen") or a.bis:
            teile.append(f"bis: {a.bis or 'offen'}")
        if a.typ == "risiko":
            teile.append(f"Reaktion: {a.reaktion or 'offen'}")
        luecken = a.luecken()
        return "- " + " · ".join(teile) + (f" – **fehlt: {', '.join(FELD_NAME[x] for x in luecken)}**" if luecken else "")

    def block(liste) -> list[str]:
        if not liste:
            return ["_Nichts festgehalten._"]
        aus = []
        for typ, titel in (("entscheidung", "Entscheidungen"), ("aufgabe", "Aufgaben"), ("offen", "Offene Punkte"),
                           ("risiko", "Risiken")):
            teil = [a for a in liste if a.typ == typ]
            if teil:
                aus += (["", f"**{titel}**"] if aus else [f"**{titel}**"]) + [zeile(a) for a in teil]
        return aus

    if m.agenda:
        for i, p in enumerate(m.agenda):
            z += ["", f"## {i + 1}. {p.titel}",
                  f"_{m.status(i)} · {mmss(m.genutzt(i))} von {p.minuten:.0f} min_" + (f" · Ziel: {p.ziel}" if p.ziel else ""),
                  ""] + block([a for a in art.liste if a.punkt == i and not a.ausserhalb])
        rest = [a for a in art.liste if a.punkt is None or a.ausserhalb]
        if rest:
            z += ["", "## Außerhalb der Agenda (Parkplatz)", ""] + block(rest)
    else:
        z += ["", "## Ergebnisse", ""] + block(art.liste)
    return "\n".join(z) + "\n"


async def _protokoll(coach, frage: str, am_ende: bool = False) -> dict | None:
    """Protokoll-Knopf; `am_ende`: dasselbe automatisch am Meetingende in Basis (Paket mit protokoll.md, Ticket #15),
    dann ohne Karte. Erkennt die Artefakte aus allem, was noch nicht ausgewertet ist (Ticket #26)."""
    m, k, art = coach.meeting, coach.knopf, coach.artefakte
    await art.erkennen()
    k.protokoll = _protokoll_md(coach, am_ende)
    k.protokoll_zeit = m.jetzt()
    if am_ende:
        return None
    if m.agenda:
        punkte = [f"{i + 1}. {p.titel}: " + ((m.ergebnisse[i]["ergebnis"] or "kein Beschluss")
                                              if i in m.ergebnisse else "nichts festgehalten")
                  for i, p in enumerate(m.agenda)]
    else:
        punkte = [a.kurz().split(". ", 1)[-1] for a in art.liste[-6:]] or ["Noch nichts festgehalten."]
    luecken = sum(1 for a in art.liste if a.luecken() and not a.abgelehnt)
    if luecken:
        punkte.append(f"{luecken} Lücke{'n' if luecken > 1 else ''} – im Dashboard rot markiert")
    karte = {"art": "protokoll", "frage": NAMEN["protokoll"], "titel": "Protokoll", "punkte": punkte[:8]}
    coach._karte_ablegen(karte)
    return karte


async def _ueberblick(coach, frage: str) -> dict:
    """Überblick als Text (coach/ueberblick.py) – in beiden Stufen; legt zugleich eine Karte für den Verlauf ab."""
    if not coach.meeting.transkript:
        raise KnopfFehler("Noch nichts gesagt – für einen Überblick fehlt der Stoff.")
    while coach._ueberblick_laeuft:  # läuft schon einer (Takt, Zuruf): abwarten, dann frisch
        await asyncio.sleep(0.3)
    u = await coach.ueberblick_bauen()
    if u is None:
        raise KnopfFehler(coach.onepager_fehler or "Der Überblick hat nicht geklappt.")
    return {"version": coach.ueberblick_version}


async def _bild(coach, frage: str) -> dict:
    if not coach.meeting.transkript:
        raise KnopfFehler("Noch nichts gesagt – für ein Bild fehlt der Stoff.")
    coach.onepager_starten()  # läuft schon eins, wird danach nachgeholt
    await coach.melden()
    while coach._onepager_laeuft:
        await asyncio.sleep(0.5)
    if coach.onepager_fehler:
        raise KnopfFehler(coach.onepager_fehler)
    return {"version": coach.onepager_version}


ANALYSEN = {"stand": _stand, "regeln": _regeln, "ueberblick": _ueberblick, "protokoll": _protokoll, "bild": _bild,
            "frage": _frage, "zusammenfassen": _protokoll, "fehlt": _protokoll}
# Ticket #27: jeder Knopf läuft als Antwortbogen (coach/assistent.py) – welcher Bogen?
BOGEN = {"stand": "stand", "regeln": "regeln", "ueberblick": "ueberblick", "protokoll": "festgehalten", "bild": "bild",
         "zusammenfassen": "zusammenfassen", "fehlt": "fehlt", "folie": "folie"}
