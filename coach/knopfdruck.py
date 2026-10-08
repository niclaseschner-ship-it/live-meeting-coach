"""Modus „Auf Knopfdruck“ (Lastenheft 3 und 4.2, Ticket #6): KI nur, wenn die Runde einen Knopf drückt.

Ohne Knopf geht nichts an einen KI-Dienst; Zeit, Monolog, Redeanteile, Überlappung und Ausreden lassen laufen
lokal weiter (die Weichen dafür stehen in hoeren.py, pipeline.py und assistent.py). Ein Knopf

1. transkribiert, was seit dem letzten Knopf gesprochen wurde (`Hoerstrom.nachtranskribieren`: der Weg von
   „sparsam“, höchstens vier gleichzeitig, Sätze in der Reihenfolge des Sprechens ins Transkript),
2. führt dann die gewählte Analyse aus – aus vorhandenen Bausteinen:
   stand     Wo stehen wir? Kontext wie bei Nestors Antworten (Assistent.kontext), Antwort als Karte
   regeln    vereinbarte Regeln: lokale aus regel_status, Fokus/Ton/Ergebnisse in einem Aufruf (Ton-Definition aus
             themen.py), Ergebnis als Karte und in den Regel-Ampeln
   protokoll Meeting-Artefakte erkennen (coach/artefakte.py, Ticket #26), daraus protokoll.md und eine Karte
   bild      das vorhandene Live-Bild (onepager_starten)
   frage     freie Frage, Antwort als Text-Karte über den vorhandenen Karten-Weg

Fortschritt geht als {"typ": "knopf", "art", "schritt": "transkribiere"|"denke"|"fertig", "anteil": 0..1} an alle
Dashboards; die Sekunden je Schritt landen ohne Inhalte in logs/nestor_zeiten.jsonl (Latenzmessung 4.2).

`verwerfen()` nimmt die letzten Minuten bzw. alles aus Warteschlange, Transkript und Aufnahme – und dazu jedes
Knopf-Ergebnis, das in dieser Zeit entstand, weil es Inhalte daraus enthalten kann. Redeanteile, Sprecherspur und
Äußerungszeiten bleiben: sie enthalten keine Inhalte, und ohne sie wären Monolog, Redeanteile und Klima für den Rest
des Meetings falsch.
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
KNOPF_REGELN = ("thema", "ton", "ergebnisse")  # Regeln, die den Text brauchen – live nur über KI-Dienste
INHALT_ARTEN = ("ton", "ergebnis", "assistent", "recherche", "folie", "name", "artefakt_nachfrage",
                "zusammenfassung")  # Protokolleinträge mit Inhalt

EINVERSTAENDNIS = ("Ich bin Nestor und höre mit – der Ton bleibt auf diesem Server. Zeit, Redeanteile und Monolog "
                   "laufen ohne KI. An einen KI-Dienst geht erst etwas, wenn ihr einen Knopf drückt. Ist jemand nicht "
                   "einverstanden, löscht „Alles verwerfen“ das Bisherige.")
# Gegenstück zu assistent.agenda_bitte() der gesprochenen Begrüßung (main, 5da9939). Ansagen allein reicht hier
# nicht – ohne Knopf liest Nestor nicht mit –, deshalb nur Anklicken; das Zusammenfassen ist der Knopf.
AGENDA_BITTE = (" Ich kann euch besser begleiten, wenn ihr den nächsten Punkt anklickt, sobald ihr wechselt. Wenn "
                "ihr wollt, drückt vorher „Wo stehen wir?“, dann fasse ich kurz zusammen, was ihr besprochen habt.")


def _weitere_regeln_hinweis(meeting) -> str:
    """Freitext-Regeln (coach/zustand.py: Meeting.regeln, Kachel „Weitere Regeln“, Ticket #10) im geschriebenen
    Einverständnis-Hinweis – Gegenstück zu assistent._weitere_regeln_satz() für den Modus ohne gesprochene
    Begrüßung. Höchstens drei wörtlich, sonst zusammengefasst; Nestor prüft sie auch hier nicht."""
    weitere = [r.strip() for r in meeting.regeln if r.strip()]
    if not weitere:
        return ""
    if len(weitere) <= 3:
        liste = ", ".join(weitere[:-1]) + (" und " if len(weitere) > 1 else "") + weitere[-1]
    else:
        rest = len(weitere) - 3
        liste = f"{', '.join(weitere[:3])} und {rest} weitere, die ihr auf dem Bildschirm seht"
    return f" Außerdem habt ihr euch vorgenommen: {liste} – das prüfe ich nicht, nur zur Erinnerung."


def einverstaendnis(meeting) -> str:
    """Hinweis beim Start statt der gesprochenen Begrüßung; die Bitte um Agendawechsel erst ab zwei Punkten,
    danach die weiteren (freien) Regeln als Erinnerung."""
    return (EINVERSTAENDNIS + (AGENDA_BITTE if len(meeting.agenda) >= 2 else "")
            + _weitere_regeln_hinweis(meeting))


class KnopfFehler(RuntimeError):
    """Knopf geht gerade nicht (kein Meeting, kein Schlüssel, läuft schon) – Text für die Oberfläche."""


class Knopfstand:
    """Zustand der Knopf-Analysen eines Meetings (am Coach: `coach.knopf`)."""

    def __init__(self) -> None:
        self.sperre = asyncio.Lock()  # ein Knopf zur Zeit; Verwerfen wartet, bis er durch ist
        self.laeuft: str | None = None  # Art des laufenden Knopfs
        self.schritt: str | None = None
        self.anteil = 0.0
        self.fehler: str | None = None
        self.regeln: dict[str, dict] = {}  # Regel-ID -> {farbe, detail, zeit} vom letzten Regel-Knopf
        self.regeln_bis = 0.0  # Meetingzeit, bis zu der das Transkript auf Regeln geprüft ist
        self.protokoll: str | None = None  # Markdown vom Protokoll-Knopf (geht als protokoll.md in die Ablage)
        self.protokoll_zeit: float | None = None

    def schnappschuss(self, hoerstrom) -> dict:
        offen = hoerstrom.offen() if hoerstrom else {"aeusserungen": 0, "sprache_sekunden": 0.0, "seit_sekunden": 0.0}
        return {"laeuft": self.laeuft, "schritt": self.schritt, "anteil": round(self.anteil, 2),
                "fehler": self.fehler, "protokoll": self.protokoll is not None, **offen}


# --- Ablauf -----------------------------------------------------------------
def reservieren(coach, art: str) -> None:
    """Vor dem Start prüfen und belegen (synchron, damit ein Doppelklick nicht zwei Läufe startet)."""
    k = coach.knopf
    if art not in ARTEN:
        raise KnopfFehler("Unbekannter Knopf.")
    # Seit Ticket #13 gibt es die Knöpfe in beiden Stufen und mit und ohne „Nur auf Knopfdruck“ – gleiche Knöpfe an
    # gleicher Stelle. Ohne Knopfdruck-Schalter ist das Transkript schon da; der Schritt „transkribiere“ ist dann leer.
    if coach.hoerstrom is None:
        raise KnopfFehler("Es läuft kein Meeting.")
    if coach._client is None:
        raise KnopfFehler("Kein KI-Schlüssel – ohne ihn kann Nestor nichts auswerten.")
    if k.laeuft:
        raise KnopfFehler(f"Nestor ist noch bei „{NAMEN[k.laeuft]}“ – bitte kurz warten.")
    k.laeuft, k.schritt, k.anteil, k.fehler = art, "transkribiere", 0.0, None


async def ausfuehren(coach, art: str, frage: str = "", senden=None) -> dict | None:
    """Ein Knopf: offenen Ton transkribieren, dann die Analyse. `senden(nachricht)` verteilt den Fortschritt.
    Ruft vorher `reservieren()` auf, falls das nicht schon geschehen ist. Liefert das Ergebnis oder None."""
    k = coach.knopf
    if k.laeuft != art:
        reservieren(coach, art)
    from .pipeline import _zeit_loggen, fehlertext

    hs = coach.hoerstrom
    zeiten = {"ausloeser": "knopf", "art": art, "meeting_s": round(coach.meeting.jetzt(), 1), "ki": EINST.ki}
    t0 = time.monotonic()

    async def melden(schritt: str, anteil: float, **extra) -> None:
        k.schritt, k.anteil = schritt, anteil
        if senden is not None:
            try:
                await senden({"typ": "knopf", "art": art, "schritt": schritt, "anteil": round(anteil, 2), **extra})
            except Exception:  # noqa: BLE001 – ein weggebrochenes Dashboard hält den Knopf nicht auf
                log.debug("Fortschritt nicht gesendet", exc_info=True)

    async def fortschritt(fertig: int, gesamt: int) -> None:
        await melden("transkribiere", fertig / max(1, gesamt), fertig=fertig, gesamt=gesamt)

    erg = None
    async with k.sperre:
        try:
            await melden("transkribiere", 0.0)
            tr = await hs.nachtranskribieren(fortschritt)
            zeiten.update(aeusserungen=tr["aeusserungen"], sekunden_audio=tr["sprache_sekunden"],
                          transkription_s=round(time.monotonic() - t0, 2))
            await coach.melden()  # Transkript sofort zeigen, die Analyse kommt danach
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
         "naechster_punkt: Nummer des Agendapunkts, zu dem die Runde jetzt wechseln sollte – nur wenn der aktuelle "
         "erledigt ist oder das Gespräch schon beim nächsten ist, sonst null.\n"
         "sagen: was auffällt oder was die Runde jetzt tun sollte – NICHT vorlesen, was auf der Karte steht; beginnt "
         f"mit „Hier ist sie.“\n{GRUNDSATZ}")

FRAGE = (f"Du bist {{name}}, der Moderationsassistent eines Präsenzmeetings. Die Runde hat dir eine Frage getippt; "
         f"die Antwort erscheint als Karte auf dem Bildschirm. {KARTE_FORMAT}}}.\n"
         "Der Titel nennt das Thema der Frage, die Stichpunkte beantworten sie – das Wichtigste zuerst, kurz.\n"
         f"{GRUNDSATZ}")

REGELN = ("Du prüfst als neutraler Prozessbegleiter, ob eine Besprechungsrunde ihre vereinbarten Gesprächsregeln "
          "eingehalten hat. Du bekommst Agenda, Agendawechsel und das Transkript eines Zeitraums. Beurteile nur das "
          "Gesprächsverhalten der Gruppe, nicht ob Aussagen richtig sind, und keine einzelnen Personen.\n"
          "Antworte ausschließlich mit einem JSON-Objekt mit genau diesen Schlüsseln:")
REGEL_AUFTRAG = {
    "thema": '\n"thema": {"eingehalten": true oder false, "befund": ein Satz – blieb das Gespräch beim jeweils '
             'aktiven Agendapunkt, oder wo (Zeit) und wohin schweifte es ab?}',
    "ergebnisse": '\n"ergebnisse": {"eingehalten": true oder false, "befund": ein Satz – wurden Ergebnisse '
                  'ausgesprochen und Aufgaben mit wer und bis wann vereinbart, oder was fehlt?}',
}


async def _karte_vom_modell(coach, system: str, nutzer: str, knopf: str, nutzung_art: str = "assistent") -> dict:
    """Ein Aufruf mit JSON-Antwort; Kosten unter der vorhandenen Art im Nutzungsprotokoll (ohne Inhalte)."""
    from .pipeline import nutzung_loggen

    t0 = time.monotonic()
    r = await coach._client.chat.completions.create(
        model=EINST.assistent_modell, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": nutzer}],
        **({"reasoning_effort": EINST.assistent_aufwand} if EINST.assistent_aufwand else {}))
    try:
        roh = json.loads(r.choices[0].message.content or "{}")
    except ValueError:
        roh = {}
    u = getattr(r, "usage", None)
    nutzung_loggen({"art": nutzung_art, "modell": EINST.assistent_modell, "knopf": knopf,
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


def _transkript_text(coach, seit: float) -> str:
    m = coach.meeting
    zeilen = [f"Agendawechsel um {mmss(t)}: jetzt Punkt {p + 1}" for p, t in m.punkt_beginne if t >= seit]
    zeilen += [f"[{mmss(s.start)}] {s.sprecher}: {s.text}" for s in m.transkript if s.start >= seit and s.text]
    return "\n".join(zeilen)


async def _regeln(coach, frage: str, ablegen: bool = True) -> dict:
    from . import regeln, themen

    m, k = coach.meeting, coach.knopf
    if not coach.knopfdruck:
        # Live: Fokus, Ton und Ergebnisse prüft Nestor laufend – die Karte fasst die Ampeln zusammen, ohne KI-Aufruf
        punkte = [f"{r['titel']}: " + ("eingehalten" if r["farbe"] in ("gruen", "grau") else "Achtung")
                  + (f" – {r['detail']}" if r["detail"] else "") for r in coach.schnappschuss()["regel_status"]]
        karte = {"art": "regeln", "frage": NAMEN["regeln"], "titel": f"Regeln · Stand {mmss(m.jetzt())}",
                 "punkte": punkte or ["Für dieses Meeting sind keine Gesprächsregeln gewählt."]}
        if ablegen:
            coach._karte_ablegen(karte)
        return karte
    jetzt = m.jetzt()
    ki = [r for r in m.regel_ids if r in KNOPF_REGELN]
    seit = k.regeln_bis
    text = _transkript_text(coach, seit)
    if ki and any(s.start >= seit and s.text for s in m.transkript):
        auftrag = REGELN + "".join(REGEL_AUFTRAG[r] for r in ki if r in REGEL_AUFTRAG)
        if "ton" in ki:  # dieselbe Definition wie live (31/32 erkannt, Lastenheft 4.3)
            auftrag += themen.TON.replace("Zusätzlich Schlüssel", "Schlüssel").replace("im NEUEN Abschnitt",
                                                                                     "im Transkript")
        agenda = "\n".join(f"{i + 1}. {p.titel}" + (f" – {p.ziel}" if p.ziel else "") for i, p in enumerate(m.agenda))
        nutzer = (f"Ziel des Meetings: {m.ziel or '-'}\nAgenda:\n{agenda or '(keine)'}\n\n"
                  f"Zeitraum {mmss(seit)} bis {mmss(jetzt)}:\n{text[-12000:]}")
        roh = await _karte_vom_modell(coach, auftrag, nutzer, "regeln", nutzung_art="themen")
        stand = f"Stand {mmss(jetzt)}"
        for rid in ki:
            if rid == "ton":
                stellen = themen.normalisieren(roh, len(m.agenda))["ton"]
                coach._ton_melden(stellen)  # wie live: Hinweis an die Moderation, zählt im Klima
                angriff = any(t["art"] == "angriff" for t in stellen)
                k.regeln[rid] = {"farbe": "rot" if stellen else "gruen", "zeit": jetzt,
                                 "detail": (("persönlicher Angriff" if angriff else "Kraftausdruck")
                                            + (f" ({len(stellen)}×)" if len(stellen) > 1 else "")
                                            if stellen else "respektvoll") + f" · {stand}",
                                 "befund": ("; ".join(f"„{t['zitat']}“" for t in stellen[:3]) if stellen
                                            else "kein Kraftausdruck, kein persönlicher Angriff")}
            else:
                r = roh.get(rid) if isinstance(roh.get(rid), dict) else {}
                ok = r.get("eingehalten") is not False
                k.regeln[rid] = {"farbe": "gruen" if ok else "gelb", "zeit": jetzt,
                                 "detail": ("eingehalten" if ok else "nicht eingehalten") + f" · {stand}",
                                 "befund": str(r.get("befund") or "")[:240]}
        k.regeln_bis = jetzt
    # Karte: alle gewählten Regeln, verlässliche zuerst (Reihenfolge aus regel_status)
    punkte = []
    for r in coach.schnappschuss()["regel_status"]:
        if r["id"] in KNOPF_REGELN:
            e = k.regeln.get(r["id"])
            zeile = (("eingehalten" if e["farbe"] == "gruen" else "nicht eingehalten") + " – " + e["befund"]
                     if e else "seit dem letzten Prüfen nichts Neues gesagt")
        else:
            zeile = ("eingehalten" if r["farbe"] in ("gruen", "grau") else "Achtung") + f" – {r['detail']}"
        punkte.append(f"{r['titel']}: {zeile}")
    if not punkte:
        punkte = ["Für dieses Meeting sind keine Gesprächsregeln gewählt."]
    karte = {"art": "regeln", "frage": NAMEN["regeln"],
             "titel": f"Regeln {mmss(seit)}–{mmss(jetzt)}" if ki else "Regeln", "punkte": punkte}
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
    dann ohne Karte. Erkennt die Artefakte aus allem, was noch nicht ausgewertet ist (im Modus „Nur auf Knopfdruck“
    der einzige Weg dorthin, Ticket #26)."""
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
# Ticket #27: ohne „Nur auf Knopfdruck“ läuft jeder Knopf als Antwortbogen (coach/assistent.py) – welcher Bogen?
BOGEN = {"stand": "stand", "regeln": "regeln", "ueberblick": "ueberblick", "protokoll": "festgehalten", "bild": "bild",
         "zusammenfassen": "zusammenfassen", "fehlt": "fehlt", "folie": "folie"}


# --- Verwerfen ------------------------------------------------------------------
async def verwerfen(coach, minuten: float | None) -> dict:
    """Die letzten `minuten` (None: alles) aus Warteschlange, Transkript und Aufnahme entfernen."""
    async with coach.knopf.sperre:  # nicht mitten in eine Auswertung hinein: erst danach, dann auch deren Ergebnis
        m, k = coach.meeting, coach.knopf
        jetzt = m.jetzt()
        seit = max(0.0, jetzt - minuten * 60) if minuten else 0.0
        n_warte = coach.hoerstrom.verwerfen(seit) if coach.hoerstrom else 0
        vorher = len(m.transkript)
        # Ein Satz, der in den Zeitraum hineinreicht, gehört dazu
        m.transkript = [s for s in m.transkript if s.ende <= seit]
        coach._abschnitt = [s for s in coach._abschnitt if s.ende <= seit]
        coach._vorlauf = [s for s in coach._vorlauf if s.ende <= seit]  # Fensteranfang und Kontext der Zuordnung
        m.teiltext = ""
        if not seit:
            m.block_texte.clear()
        # Was in der Zeit entstand, kann Inhalte daraus enthalten
        coach.karten = [c for c in coach.karten if c["zeit"] < seit]
        if coach.ueberblick is not None and coach.ueberblick["stand"] >= seit:
            coach.ueberblick = None
            coach.ueberblick_version += 1  # das Dashboard nimmt den Überblick dann heraus
        if coach.onepager_stand is not None and coach.onepager_stand >= seit:
            coach.onepager_svg = coach.onepager_png = coach.onepager_analyse = coach.onepager_stand = None
            coach._onepager_voll = None
            coach.onepager_version = 0  # das Dashboard nimmt das Bild dann heraus
        coach.artefakte.verwerfen(seit)  # Artefakte aus dem Zeitraum; das Transkript davor bleibt ausgewertet
        coach.protokoll = [e for e in coach.protokoll if not (e["art"] in INHALT_ARTEN and e["zeit"] >= seit)]
        hinweise = [h for h in m.hinweise if not (h.art in ("ton", "ergebnisse") and h.zeit >= seit)]  # mit Zitaten
        for i, h in enumerate(hinweise, start=1):
            h.id = i
        m.hinweise = hinweise
        if k.protokoll_zeit is not None and k.protokoll_zeit >= seit:
            k.protokoll = k.protokoll_zeit = None
        k.regeln = {r: e for r, e in k.regeln.items() if e["zeit"] < seit}
        k.regeln_bis = min(k.regeln_bis, seit)
        coach.assistent.verlauf.clear()
        if coach.archiv and not coach.archiv.fertig:
            coach.archiv.ausschneiden(seit)
        coach.protokoll.append({"zeit": jetzt, "art": "verworfen", "ab": round(seit, 1)})
        erg = {"ok": True, "ab": round(seit, 1), "aeusserungen": n_warte, "saetze": vorher - len(m.transkript)}
    await coach.melden()
    return erg
