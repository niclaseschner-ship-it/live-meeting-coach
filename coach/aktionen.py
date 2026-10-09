"""Sichtbare Aktionsbeschreibung und vorsichtige Textkosten-Richtwerte (#51)."""
from .kosten import TOKENPREISE

AKTIONEN = {
    "stand": ("Wo stehen wir?", "Agenda, Zeit und nächster Schritt", "Meetingstand · kurze Karte"),
    "zusammenfassen": ("Ergebnisse bündeln", "Entscheidungen, Aufgaben und offene Punkte", "Bisher Festgehaltenes · kompakte Karte"),
    "fehlt": ("Lücken klären", "Fehlende Verantwortliche, Termine und Angaben", "Festgehaltene Ergebnisse · Lückenkarte"),
    "protokoll": ("Gesamtprotokoll", "Alle festgehaltenen Ergebnisse nach Agendapunkt", "Ganzes Meeting · Liste und Download"),
    "ueberblick": ("Punktüberblick", "Inhalte, Ergebnisse und Offenes strukturiert", "Aktueller Punkt · strukturierte Ansicht"),
    "bild": ("Meetingbild", "Das Meeting als visuelle Übersicht", "Ganzes Meeting · Bild"),
    "regeln": ("Regeln prüfen", "Die vereinbarten Gesprächsregeln auswerten", "Bisheriges Gespräch · Auswertung"),
    "frage": ("Nestor fragen", "Deine Frage mit dem Meetingkontext beantworten", "Freie Frage · Antwortkarte"),
}

KOSTENHINWEIS = ("Text ~US-ct sind grobe Richtwerte für die Textauswertung, keine Gesamtpreise oder Obergrenzen. "
                 "Sprachausgabe, Nachholen offener Beiträge und Recherche kommen gegebenenfalls hinzu. "
                 "Der tatsächliche geschätzte Verbrauch steht im Kostenzähler. Mehr Kontext kann mehr kosten.")


def katalog(coach, einst):
    """Keine KI-Aufrufe; Tarife aus dem vorhandenen Kostenzähler, Kontext grob mit 3 Zeichen/Token."""
    meeting = coach.meeting
    preise = TOKENPREISE.get(einst.assistent_modell)
    gesamt = sum(len(s.text) for s in meeting.transkript)
    aktuell = sum(len(s.text) for s in meeting.punkt_transkript(meeting.aktiver_punkt)) if meeting.agenda else gesamt
    aus = {}
    for art, (name, beschreibung, umfang) in AKTIONEN.items():
        detail = {"name": name, "beschreibung": beschreibung, "umfang": umfang, "kosten": "Text: variabel"}
        if art == "bild":
            detail["kosten"] = "Bild: variabel"
        elif art == "protokoll":
            detail["kosten"] = "Liste: lokal · KI ggf. extra"
        elif preise:
            zeichen = aktuell if art == "ueberblick" else min(gesamt, 9000) if art in ("stand", "frage") else gesamt
            if art in ("zusammenfassen", "fehlt"):
                zeichen = sum(len(a.was) + len(a.wer or "") + 100 for a in coach.artefakte.liste)
            rein = 1200 + zeichen / 3
            raus = 1000 if art == "ueberblick" else 400
            usd = (rein * preise[0] + raus * preise[1]) / 1e6
            def ct(wert):
                return f"{max(0.1, wert * 100):.1f}".replace(".", ",")
            detail["kosten"] = f"Text ~{ct(usd)}–{ct(usd * 2)} US-ct"
            if art == "ueberblick":
                mehr = (1200 + gesamt / 3) * preise[0] / 1e6 + raus * preise[1] / 1e6
                detail["kosten_gesamt"] = f"Text ~{ct(mehr)}–{ct(mehr * 2)} US-ct"
        aus[art] = detail
    return {"aktionen": aus, "kostenhinweis": KOSTENHINWEIS}
