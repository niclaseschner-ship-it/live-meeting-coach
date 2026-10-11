"""Werkzeuge von Nestor im Gespräch (Premium) und ihre Prüfung.

Das Modell wählt das Werkzeug selbst – nach dem, was gemeint ist, nicht nach einzelnen Wörtern. Der Code prüft nur,
ob die Argumente zum Meeting passen (Ergebnis-Nummer und Agendapunkt existieren, Zeitangabe lesbar, Karte nicht
leer) – Leitplanke „Werkzeug-Validierung“. Was nicht passt, geht als Fehler an das Modell zurück, damit es kurz
sagt, was nicht stimmt, statt etwas Falsches zu tun.
"""

from __future__ import annotations

import re

BEREICHE = ("punkt", "gesamt", "seit")
AUFTRAG_ARTEN = ("recherche", "bild", "folie", "ueberblick")
KARTE_HOECHSTENS = 12

WERKZEUGE = [
    {"type": "function", "name": "zusammenfassen",
     "description": "Eine Zusammenfassung als Karte zeigen: was beschlossen, übernommen und offen ist, und was "
                    "besprochen wurde – für einen Agendapunkt (bereich=punkt, ohne Nummer der aktuelle), das ganze "
                    "Meeting (gesamt) oder die Zeit seit mm:ss (seit). Du bekommst den Inhalt der Karte zurück und "
                    "sagst danach ein bis zwei Sätze dazu, ohne sie vorzulesen.",
     "parameters": {"type": "object", "properties": {
         "bereich": {"type": "string", "enum": list(BEREICHE)},
         "punkt": {"type": "integer", "description": "Agendapunkt-Nummer bei bereich=punkt; weglassen = aktueller"},
         "seit": {"type": "string", "description": "Meetingzeit mm:ss bei bereich=seit"}},
         "required": ["bereich"]}},
    {"type": "function", "name": "karte",
     "description": "Eine freie Karte zeigen, wenn deine Antwort Einzelheiten hat (Liste, Vergleich, Schritte, "
                    "Zahlen). Kurzer Titel, höchstens zwölf knappe Punkte. Danach sagst du ein bis zwei Sätze.",
     "parameters": {"type": "object", "properties": {
         "titel": {"type": "string"},
         "punkte": {"type": "array", "items": {"type": "string"}}},
         "required": ["titel", "punkte"]}},
    {"type": "function", "name": "nicht_an_mich",
     "description": "Die Nachricht war nicht an dich gerichtet (die Runde redet untereinander, jemand spricht eine "
                    "Person an, ein Kommentar zur Sache). Dann sag NICHTS und ruf nur dieses Werkzeug auf.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "auftrag_abbrechen",
     "description": "Einen laufenden Hintergrund-Auftrag abbrechen („lass die Recherche“, „das Bild brauchen wir "
                    "nicht mehr“). Ohne Art der jüngste. Das System bestätigt selbst – sag nichts dazu.",
     "parameters": {"type": "object", "properties": {"art": {"type": "string", "enum": list(AUFTRAG_ARTEN)}}}},
    {"type": "function", "name": "bild_zeichnen",
     "description": "Visuelle Übersicht (Live-Bild) neu zeichnen lassen, dauert etwa eine Minute; das Bild erscheint "
                    "später still im Verlauf. Nicht, wenn die Runde nur ein vorhandenes Bild erklärt haben möchte.",
     "parameters": {"type": "object", "properties": {"fokus": {
         "type": "string", "description": "gesamt, ein Agendapunkt, was noch ansteht, wo Entscheidungen fehlen …"}},
         "required": ["fokus"]}},
    {"type": "function", "name": "agendapunkt_wechseln",
     "description": "Zum genannten Agendapunkt wechseln – nur, wenn die Gruppe das ausdrücklich möchte. Eine Frage "
                    "nach dem nächsten Punkt ist kein Wechselwunsch.",
     "parameters": {"type": "object", "properties": {"nummer": {"type": "integer"}}, "required": ["nummer"]}},
    {"type": "function", "name": "recherchieren",
     "description": "Im Internet recherchieren, z. B. „gib uns einen Überblick zu …“ oder aktuelle Fakten. Läuft im "
                    "Hintergrund; das Ergebnis erscheint später still als Karte mit Quellen. Formuliere die Frage ohne "
                    "Namen und ohne Interna aus dem Meeting.",
     "parameters": {"type": "object", "properties": {"frage": {"type": "string"}}, "required": ["frage"]}},
    {"type": "function", "name": "folie_erstellen",
     "description": "Das letzte Rechercheergebnis mit Quellen als Folie im Dashboard zusammenstellen. Nur nach "
                    "einer Recherche und wenn die Gruppe das möchte (z. B. „ja, mach eine Folie“).",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "karte_zeigen",
     "description": "Eine feste Karte in den Verlauf stellen: fehlt (was noch fehlt, Lücken), stand (wo stehen wir), "
                    "festgehalten (Protokoll, Liste des Festgehaltenen), ueberblick (Überblick als Text). Das System "
                    "sagt selbst dazu, was auffällt – sag nichts.",
     "parameters": {"type": "object", "properties": {"art": {
         "type": "string", "enum": ["fehlt", "stand", "festgehalten", "ueberblick"]}},
         "required": ["art"]}},
    {"type": "function", "name": "karte_neu_aufbereiten",
     "description": "Die zuletzt gezeigte Karte anders aufbereiten, wenn die Runde das zu ihr sagt („bereite das "
                    "anders auf“, „mach es kürzer“, „als Liste bitte“). Erscheint als neue Karte, die alte bleibt "
                    "stehen. Das System sagt selbst dazu – sag nichts.",
     "parameters": {"type": "object", "properties": {"wie": {
         "type": "string", "enum": ["kürzer", "ausführlicher", "als_liste", "einfacher"]}},
         "required": ["wie"]}},
    {"type": "function", "name": "artefakt_eintragen",
     "description": "Eine Aufgabe, Entscheidung, einen offenen Punkt oder ein Risiko eintragen oder ergänzen, wenn die "
                    "Gruppe es dir sagt („Sofie übernimmt die Statusseite bis Freitag“, „fürs Protokoll: wir nehmen "
                    "Variante B“). Nummer aus „Festgehaltene Artefakte“, für Neues weglassen. Nur Felder, die gesagt "
                    "wurden. Das System bestätigt mit „Notiert“ – sag nichts dazu.",
     "parameters": {"type": "object", "properties": {
         "nummer": {"type": "integer", "description": "Nummer eines festgehaltenen Artefakts; weglassen für Neues"},
         "typ": {"type": "string", "enum": ["aufgabe", "entscheidung", "offen", "risiko"]},
         "was": {"type": "string"}, "wer": {"type": "string"}, "bis": {"type": "string"},
         "status": {"type": "string", "enum": ["endgueltig", "vorlaeufig"]},
         "reaktion": {"type": "string"}}}},
    {"type": "function", "name": "ergebnis_entfernen",
     "description": "Ein festgehaltenes Artefakt aus der Liste entfernen, wenn die Gruppe das ausdrücklich sagt "
                    "(„nimm das von der Liste“, „das brauchen wir nicht mehr“, „streich das wieder“). Sofort "
                    "ausgeführt, die Karte bietet Rückgängig. Nummer aus „Festgehaltene Artefakte“.",
     "parameters": {"type": "object", "properties": {
         "nummer": {"type": "integer", "description": "Nummer des Artefakts, das entfernt werden soll"}},
         "required": ["nummer"]}},
    {"type": "function", "name": "ergebnis_aendern",
     "description": "Den Wortlaut eines festgehaltenen Artefakts ändern, wenn die Gruppe das ausdrücklich so "
                    "möchte („nimm statt X Y“, „das ist falsch, richtig ist …“). Nur der Text ändert sich, nicht "
                    "wer/bis/Status. Sofort ausgeführt, die Karte bietet Rückgängig.",
     "parameters": {"type": "object", "properties": {
         "nummer": {"type": "integer", "description": "Nummer des Artefakts, dessen Wortlaut sich ändert"},
         "text": {"type": "string", "description": "der neue Wortlaut"}},
         "required": ["nummer", "text"]}},
    {"type": "function", "name": "zuhoeren_pausieren",
     "description": "Die Gruppe möchte, dass du nicht mehr zuhörst. Wieder an nur über den Knopf im Dashboard.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "gespraech_beenden",
     "description": "Die Gruppe braucht dich gerade nicht mehr („danke, das war's“). Du hörst dann wieder nur auf "
                    "deinen Namen.", "parameters": {"type": "object", "properties": {}}},
]
NAMEN = {w["name"] for w in WERKZEUGE}
# Nach diesen Werkzeugen spricht das System selbst (Floskel bzw. Karten-Satz) – keine Abschlussantwort des Modells
SYSTEM_SPRICHT = ("bild_zeichnen", "recherchieren", "folie_erstellen", "karte_zeigen", "karte_neu_aufbereiten",
                  "artefakt_eintragen", "ergebnis_entfernen", "ergebnis_aendern", "auftrag_abbrechen")
# Nach diesen sagt das Modell in einer Abschlussantwort ein bis zwei Sätze (mit dem Werkzeug-Ergebnis)
ABSCHLUSS = ("zusammenfassen", "karte", "agendapunkt_wechseln", "zuhoeren_pausieren")


def zeit_lesen(text: str) -> float | None:
    """„12:30“ oder „12“ (Minuten) → Sekunden; sonst None."""
    m = re.fullmatch(r"\s*(\d{1,3})(?::(\d{1,2}))?\s*(?:min\w*)?\s*", str(text or ""))
    if not m or (m[2] is not None and int(m[2]) >= 60):
        return None
    return int(m[1]) * 60 + int(m[2] or 0)


def pruefen(name: str, arg, *, nummern: set[int], agenda: int, aktiver_punkt: int, jetzt: float,
            gerichtet: bool = True) -> tuple[dict, str | None]:
    """(bereinigte Argumente, Fehler). Fehler = None heißt: ausführen. Der Fehlertext geht an das Modell."""
    arg = arg if isinstance(arg, dict) else {}
    if name not in NAMEN:
        return arg, f"Werkzeug {name} gibt es nicht."
    if name in ("ergebnis_entfernen", "ergebnis_aendern") or (name == "artefakt_eintragen" and "nummer" in arg):
        nr = arg.get("nummer")
        if not isinstance(nr, int) or isinstance(nr, bool) or nr not in nummern:
            vorhanden = ", ".join(str(n) for n in sorted(nummern)) or "keine"
            return arg, f"Ein Ergebnis mit Nummer {nr} gibt es nicht (vorhanden: {vorhanden})."
        if name == "ergebnis_aendern" and not str(arg.get("text") or "").strip():
            return arg, "Der neue Wortlaut fehlt."
    if name == "agendapunkt_wechseln":
        nr = arg.get("nummer")
        if not isinstance(nr, int) or isinstance(nr, bool) or not 1 <= nr <= agenda:
            return arg, (f"Agendapunkt {nr} gibt es nicht (1 bis {agenda})." if agenda else "Es gibt keine Agenda.")
    if name == "zusammenfassen":
        bereich = arg.get("bereich")
        if bereich not in BEREICHE:
            return arg, f"bereich muss {', '.join(BEREICHE)} sein."
        aus = {"bereich": bereich}
        if bereich == "punkt":
            nr = arg.get("punkt", aktiver_punkt + 1)
            if not agenda:
                aus["bereich"] = "gesamt"  # ohne Agenda ist „der Punkt“ das ganze Meeting
            elif not isinstance(nr, int) or isinstance(nr, bool) or not 1 <= nr <= agenda:
                return arg, f"Agendapunkt {nr} gibt es nicht (1 bis {agenda})."
            else:
                aus["punkt"] = nr
        if bereich == "seit":
            t = zeit_lesen(arg.get("seit"))
            if t is None or t > jetzt:
                return arg, f"Zeitangabe „{arg.get('seit')}“ verstehe ich nicht (mm:ss, höchstens jetzt)."
            aus["seit"] = t
        return aus, None
    if name == "karte":
        titel = str(arg.get("titel") or "").strip()[:80]
        punkte = [str(p).strip()[:240] for p in arg.get("punkte") or [] if str(p).strip()]
        if not titel or not punkte:
            return arg, "Eine Karte braucht einen Titel und mindestens einen Punkt."
        return {"titel": titel, "punkte": punkte[:KARTE_HOECHSTENS]}, None
    if name == "auftrag_abbrechen" and arg.get("art") not in (None, *AUFTRAG_ARTEN):
        return arg, f"art muss {', '.join(AUFTRAG_ARTEN)} sein."
    if name == "nicht_an_mich" and gerichtet:
        return arg, "Du wurdest direkt angesprochen – antworte kurz oder frag nach."
    return arg, None
