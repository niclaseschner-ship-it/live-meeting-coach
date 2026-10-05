# Rollenspiele: deutsches Testmaterial mit bekannter Wahrheit

Echte Meetings warten noch. Bis dahin spielen 3–5 Personen kurze Besprechungen nach Drehbuch: echter Raum,
ein Laptop-Mikrofon auf dem Tisch, deutsche Sprache. Weil die Rollenkarten festlegen, was wann passiert,
steht die Referenz schon vor der Aufnahme fest. Vorbild ist das AMI-Korpus, das genau so entstanden ist.

## Ablauf

1. **Einverständnis:** Alle wissen, dass aufgenommen wird, und sind einverstanden. Die Aufnahme bleibt lokal
   in `testbibliothek/` und kommt nicht ins Repo.
2. **Aufbau:** Laptop mittig auf dem Tisch, Coach im Dashboard starten, Agenda aus dem Szenario eintragen,
   Nestor an. Lautsprecher an, damit Echo und Selbstunterbrechung mitgetestet werden.
3. **Rollenkarten:** Jede Person bekommt nur ihre eigene Karte. Die Ereignisse sind grob getaktet
   („nach etwa 5 Minuten“); Abweichungen sind erwünscht, solange das Ereignis passiert.
4. **Nach der Aufnahme:** Die Spielleitung trägt die tatsächlichen Zeitpunkte der Ereignisse ein (Uhr im
   Dashboard ablesen oder hinterher aus dem Transkript). Daraus wird `probe.json` mit Referenz.
5. **Auswerten:** Erst gegen die Referenz (`scripts/testlauf_auswerten.py`), dann reden: Welche Hinweise
   haben geholfen, welche gestört? Das ist die eigentliche Messgröße.

Vor dem ersten Rollenspiel noch zu bauen: Aufnahme des Mikrofon-Audios im Dashboard mitschreiben (WAV), damit
dieselbe Runde später beliebig oft und ohne API-Kosten (Testmodus) erneut durch den Coach laufen kann.

## Szenario 1: Team-Weekly einer kleinen Agentur (20 min, 4 Personen)

**Agenda:** 1. Projektstand Kunde Müller (6 min) · 2. Urlaubsplanung Dezember (5 min) · 3. Neues
Zeiterfassungstool (7 min) · 4. Verschiedenes (2 min)

| Rolle | Karte |
|---|---|
| Leitung (A) | Moderiert. Leitet Punkt 2 ausdrücklich ein („Dann kommen wir zu Punkt zwei …“), Punkt 3 dagegen ohne Ansage. Fragt bei Punkt 3: „Nestor, wo stehen wir gerade?“ und am Ende „Nestor, wo fehlen noch Entscheidungen?“ |
| Projektleiterin (B) | Berichtet bei Punkt 1 ausführlich, **mindestens 90 Sekunden am Stück** ohne Pause. |
| Entwickler (C) | Fällt bei Punkt 3 **zweimal B ins Wort**, bevor B fertig ist. Schweift bei Punkt 2 etwa 40 s zum Fußball vom Wochenende ab. |
| Werkstudentin (D) | Sagt bei Punkt 1 und 2 nichts. Erst bei Punkt 3 ein kurzer Beitrag. |

**Entscheidungen:** Punkt 2 endet mit einem klaren Beschluss („Wir machen es so: …“), Punkt 3 bleibt offen
(„schauen wir uns nächste Woche an“), ohne dass jemand die Aufgabe übernimmt.

**Referenz:** Wechsel 1→2 mit Ansage, Wechsel 2→3 ohne · Monolog B · 2× Unterbrechung · Abschweifung ·
D lange still · Beschluss bei 2, offene Aufgabe ohne Zuständigen bei 3 · 2 Fragen an Nestor.

## Szenario 2: Hitzige Budgetrunde im Verein (25 min, 5 Personen)

**Agenda:** 1. Kassenbericht (5 min) · 2. Budget Sommerfest (10 min) · 3. Anschaffung Vereinsbus (8 min) ·
4. Termine (2 min)

| Rolle | Karte |
|---|---|
| Vorsitz (A) | Moderiert, zieht die Zeit bei Punkt 2 bewusst um 3–4 Minuten über. Bittet bei Punkt 3: „Nestor, gib uns einen kurzen Überblick, was ein gebrauchter Neunsitzer kostet.“ und danach „Ja, mach eine Folie dazu.“ |
| Kassenwart (B) | Trägt den Kassenbericht vor, sachlich, etwa 2 Minuten. |
| Kritiker (C) | Wird bei Punkt 2 laut und sagt einmal einen Kraftausdruck („Das ist doch Mist!“) und einmal etwas Persönliches („Du rechnest ja immer schön.“). Redet zweimal gleichzeitig mit E. |
| Jugendwart (D) | Bringt bei Punkt 2 schon den Bus aus Punkt 3 ins Spiel (Vorgriff). |
| Beisitzerin (E) | Versucht zu vermitteln, fasst bei Punkt 2 den Beschluss zusammen. |

**Referenz:** Zeitüberzug Punkt 2 · Kraftausdruck und persönlicher Angriff · 2× Überlappung · Vorgriff auf
Punkt 3 · Beschluss mit Betrag · Recherche mit Folie.

## Szenario 3: Ruhige Entscheidungsrunde (15 min, 3 Personen) – Kontrollgruppe

**Agenda:** 1. Auswahl Bürostandort (8 min) · 2. Nächste Schritte (5 min)

Alle halten sich an die Regeln: kurze Beiträge, kein Ins-Wort-Fallen, klare Ansagen beim Wechsel, Beschluss
mit Zuständigem und Termin. Einmal „Nestor, fass den Punkt kurz zusammen.“

**Referenz:** Hier sollen **keine** Hinweise kommen außer vielleicht der Zeit. Jeder andere Hinweis ist ein
Fehlalarm – das ist die wichtigste Kontrolle gegen zu viele Hinweise.
