# Nestor – Lastenheft

**Stand:** 07.10.2026 · **Gilt für:** Nestor als Angebot über einen Link (SaaS) ·
**Vorgänger:** [archiv/spezifikation_v2.md](archiv/spezifikation_v2.md) (Laptop-Fassung, Messungen bis 05.10.)

Diese Datei beschreibt verbindlich, was Nestor tut. Wer etwas Nennenswertes ändert, trägt es hier im selben
Commit nach. Messberichte und Begründungen stehen in den verlinkten Dokumenten, hier stehen nur Ergebnisse.

## 1. Produkt

Nestor begleitet Präsenzmeetings (3–8 Personen, Deutsch). Er behält Agenda, Zeit und Gesprächsfluss im Blick,
antwortet auf Ansprache und hält fest, was besprochen und entschieden wurde. **Die Gruppe entscheidet,
Nestor zeigt nur an.**

Nestor ist ein privates Projekt von Niclas Eschner und kein Geschäft. Die API-Kosten trägt Niclas vor,
Nutzer gleichen sie am Ende freiwillig aus.

## 2. Ablauf für Nutzer

```
Link + Passwort ─► Startseite ─► Meeting einrichten ─► Meeting ─► Abschluss
                   Modus wählen   Agenda per Prompt              Paket · Unterstützung · Datenspende
```

1. **Zugang:** Jeder Kunde bekommt einen Link und ein eigenes Passwort. Ein Kunde kann mehrere Meetings
   gleichzeitig führen.
2. **Startseite:** Was Nestor kann, die Wahl zwischen den zwei Modi (Abschnitt 3), die erwarteten Kosten je
   Stunde und der Hinweis, dass Niclas die Kosten vorstreckt. Dazu Links auf Impressum und Datenschutz.
3. **Meeting einrichten:** Die Agenda entsteht aus freier Eingabe (Abschnitt 4.1). Dann werden die
   Gesprächsregeln gewählt.
4. **Meeting:** Dashboard wie bisher, je nach Modus mit oder ohne Live-Unterstützung.
5. **Abschluss:** Nach „Meeting beenden“ folgt eine Seite mit drei Angeboten:
   - **Eigenes Paket** herunterladen (Abschnitt 4.4).
   - **Unterstützung:** echte Kosten des Meetings, drei Vorschläge und ein PayPal-QR-Code.
   - **Datenspende** mit Feedback.

   Danach wird der Meetingzustand auf dem Server gelöscht.

## 3. Die zwei Modi

| | **Live** | **Auf Knopfdruck** |
|---|---|---|
| Ton | läuft zum Server und in Echtzeit zu OpenAI | läuft zum Server und bleibt dort |
| Live-Transkript, Fokus, Ton, Ergebnisse | live | nur auf Knopfdruck |
| Monolog, Redeanteile, Überlappung, Zeit | live | live (lokal auf dem Server, ohne KI-Dienst) |
| Nestor | hört auf seinen Namen und antwortet gesprochen | auf Knopfdruck, als Text (Abschnitt 4.2) |
| Live-Bild | alle 10 min und auf Zuruf | nur auf Knopfdruck |
| Löschen | „Nein“ in der Begrüßung löscht alles | zusätzlich „letzte 5 Minuten verwerfen“ und „alles verwerfen“ |
| Kosten (Richtwert) | ~2 $ je Stunde | ~0,4 $ je Stunde bei 4 Knopfdrücken (Stand, Regeln, Protokoll, Bild) |

Auf der Startseite steht zu **Live** wörtlich: „Alles Gesprochene wird in Echtzeit von OpenAI verarbeitet.“ Zu
**Auf Knopfdruck**: „Ohne Ihren Knopfdruck gibt Nestor nichts an KI-Dienste weiter. Ihr Ton liegt bis dahin
nur auf unserem Server in der EU und wird am Ende gelöscht.“

Die Kostenrichtwerte stammen aus dem Nutzungsprotokoll (`coach/kosten.py`). Der Wert für „Auf Knopfdruck“ ist
gemessen (Ticket #7, [docs/messung_knopfdruck.md](messung_knopfdruck.md)) an einer 60-Minuten-Probe mit vier
Knopfdrücken (Stand, Regeln, Protokoll, Bild): Transkription + Bild zusammen 0,25 $ bei ~49 % Sprechanteil in der
Probe, hochgerechnet bis ~0,32 $ bei durchgehender Rede; dazu kommen im echten Betrieb (API statt Codex) ein bis
zwei Cent für die Text-Analyse. Macht zusammen rund 0,3–0,4 $/h – daher der Richtwert 0,4.

## 4. Funktionen

### 4.1 Agenda per Prompt

Ein Eingabefeld nimmt Text, Eingefügtes (Tabelle aus Outlook, Mail, Liste) oder Sprache entgegen. Daraus
macht ein Sprachmodell eine Tabelle mit den Spalten Punkt, Minuten und Ziel (optional). Die Tabelle ist
direkt bearbeitbar. Über dasselbe Feld lässt sie sich im Dialog weiter ändern, etwa mit „Punkt 3 kürzer,
dafür Pause einbauen“. Titel und Gesamtdauer schlägt das Modell mit vor. Im Modus „Auf Knopfdruck“ gilt das
Absenden einer Spracheingabe als Knopfdruck.

### 4.2 Analysen auf Knopfdruck

Ein Knopfdruck transkribiert den bisher noch nicht transkribierten Ton (fertige Teile bleiben gespeichert)
und führt dann die gewählte Analyse aus:

- **Wo stehen wir?** Stand der Agenda und Vorschlag für den nächsten Schritt
- **Regeln eingehalten?** Prüfung der vereinbarten Gesprächsregeln
- **Protokoll**
- **Live-Bild**
- **Nestor fragen:** freie Frage als Text (Spracheingabe folgt)

Bis die Antwort kommt, sieht man den Fortschritt. Gemessene Wartezeit (Ticket #7, 60-Minuten-Probe, Einzelheiten
und Messverfahren in [docs/messung_knopfdruck.md](messung_knopfdruck.md)):

| Meetingzeit | Knopf | Transkription | Analyse (Codex) | Gesamt | Kosten |
|---|---|---|---|---|---|
| 15 min | Stand | 28,0 s | 10,4 s | 38,4 s | 0,044 $ |
| 30 min | Regeln | 26,2 s | 14,6 s | 40,8 s | 0,044 $ |
| 60 min | Protokoll | 52,2 s | 10,4 s | 62,6 s | 0,088 $ |
| einmalig | Bild | – | 50,1 s | 50,1 s | 0,074 $ |

Die Analysezeit ist hier die des ChatGPT-Abos (`LMC_KI=codex`, ~8–15 s je Aufruf); über die echte API maß der
Vergleichslauf 2,6 s für denselben Aufruf (Begründung und Zahlen im Messbericht) – kostet dafür ein bis zwei
Cent statt nichts. Die Transkriptionszeit wächst mit der Menge offener Sprache (seit dem letzten Knopf), nicht
mit der Meetingdauer selbst; bei „Protokoll“ war sie am größten, weil seit „Regeln“ 30 Minuten statt 15
aufgelaufen waren.

Weitere Regeln in diesem Modus:
- Agendawechsel nur per Klick (Ansagen kämen erst beim nächsten Knopf an).
- Am Meetingende keine automatische Auswertung; Protokoll und Bild gibt es, wenn vorher gedrückt wurde.
- **Verwerfen** entfernt Ton, Transkript und alles daraus Abgeleitete (Karten, Bild, Protokoll, Befunde) aus dem
  Zeitraum; die Aufnahme wird dort zu Stille. Redeanteile bleiben, sie enthalten keine Inhalte.
- Erster Probelauf (3 min, 4 Knöpfe): je Knopf 9–15 s, davon Transkription 1–6 s; 0,009 $ Transkription.
  Ausführliche Messung über 60 Minuten: siehe Tabelle oben.

### 4.3 Signale und ihre Verlässlichkeit

Jedes Signal ist im Dashboard als **verlässlich** oder **experimentell** gekennzeichnet. Bei experimentellen
Signalen steht in einem Satz dabei, wie oft sie danebenliegen. Verlässliche Signale stehen vorn.

| Signal | Einstufung | Grundlage | Kurzsatz im Dashboard |
|---|---|---|---|
| Zeit und Agenda-Ampel | verlässlich | Uhr | – |
| Monolog (≥ 60 s) | verlässlich | 9/9 erkannt, 0 Fehlalarme ([gespraechsregeln.md](gespraechsregeln.md) §6) | – |
| Redeanteile, stille Person | verlässlich | ≤ 1 Prozentpunkt Abweichung; stille Person 3/3 | – |
| Wer spricht (anonym) | verlässlich bei klaren Stimmen | 0,2–1,6 % falsch zugeordnete Sprechzeit; Tischmikrofon im Besprechungsraum 7,5–14 % ([testlauf_2026-10-06.md](testlauf_2026-10-06.md)) | – |
| Live-Transkript | verlässlich | Eigennamen teils falsch | – |
| Kraftausdrücke, Angriffe | verlässlich | 31/32 erkannt, 2/51 Fehlalarme; Ende zu Ende 8/8 | – |
| Agendawechsel mit Ansage | verlässlich | sofort, 5–13 s | – |
| Agendawechsel ohne Ansage | experimentell | 15–60 s Verzug, kurze Punkte werden verpasst | „Experimentell: meldet einen stillen Themenwechsel meist erst nach 15 bis 60 Sekunden, kurze Punkte werden dabei manchmal verpasst.“ |
| Fokus (klares Fremdthema) | verlässlich | 3/3 erkannt nach 26–28 s, 0 Fehlalarme; eigene Tests mit Urlaub und Fußball. Fließende Übergänge zwischen Punkten: siehe Agendawechsel ohne Ansage | |
| Ergebnisse festhalten | experimentell | 4/5 Beschlüsse richtig, in englischem Material kaum | „Experimentell: erkennt 4 von 5 Beschlüssen richtig, bei englischsprachigem Material kaum.“ |
| Gleichzeitiges Sprechen | experimentell | findet 41–68 % der echten, 84–86 % der Meldungen stimmen | „Experimentell: findet 41 bis 68 % der echten Stellen; was gemeldet wird, stimmt in 84 bis 86 % der Fälle.“ |
| Ausreden lassen | experimentell | in geordneten Runden kaum Fehlalarme, in Zwischenruf-Proben unbrauchbar | „Experimentell: In geordneten Runden kaum Fehlalarme, in Proben mit vielen Zwischenrufen unbrauchbar.“ |
| Klima | experimentell | nicht gegen eine Referenz gemessen | „Experimentell: noch nicht gegen eine Referenz gemessen.“ |
| Nestor beantwortet Fragen | verlässlich | 20/22 im Testlauf, Antwort nach 1,5–6 s | – |

### 4.4 Paket zum Herunterladen

Ein ZIP mit Protokoll (`protokoll.md`), Abschlussbild, Transkript, Agenda mit Zeitnutzung und Hinweisen.
Die Aufnahme ist nur auf ausdrücklichen Wunsch dabei.

### 4.5 Unterstützung

Die Abschlussseite zeigt die gemessenen Kosten des Meetings und drei Vorschläge. Jeder wird auf volle Euro
aufgerundet, mindestens 2 €:

| Stufe | Bedeutung | Faktor auf die API-Kosten |
|---|---|---|
| Deckung | Kosten sicher gedeckt | × 2 |
| Fair | plus Anteil an Entwicklung und Betrieb | × 4 |
| Förderer | ermöglicht neue Funktionen | × 8 |

Daneben stehen der PayPal-QR-Code und der Link auf PayPal.me. Der Betrag steht im Link, wenn PayPal das
zulässt. Es gibt keine Rechnung und keine Gegenleistung, und es heißt „Unterstützung“, nicht „Kauf“.

Wer auf der Startseite einen eigenen OpenAI-Schlüssel hinterlegt hat (Abschnitt 6), sieht hier keine Stufen:
Die KI-Kosten liefen über das eigene OpenAI-Konto, ein Kostenausgleich entfällt also. Stattdessen steht knapper
„Wer die Entwicklung trotzdem unterstützen möchte“ mit dem allgemeinen PayPal.me-Link, ohne vorgeschlagenen
Betrag.

### 4.6 Datenspende und Feedback

- Freitextfeld für Feedback, auch ohne Datenspende absendbar.
- Datenspende: Transkript, Hinweise, Agenda und optional die Aufnahme. Absenden geht nur mit dem Häkchen
  „Alle Teilnehmenden sind einverstanden, dass diese Daten gespendet werden“.
- Hinweistext: „Die Daten werden maschinell ausgewertet, um Nestor zu verbessern. Niemand hört sie sich
  einzeln an oder wertet Inhalte aus.“
- Die Spende landet in einem Speicher in der EU (R2), lokal unter `spenden/`.

## 5. Rahmenbedingungen

| | |
|---|---|
| Kosten | Live ≤ 2 $ je Stunde, Knopfdruck ≤ 0,7 $ je Stunde, gemessen über das Nutzungsprotokoll |
| Datenhaltung | Ton und Transkript nur bis zum Abschluss; danach bleibt nur, was heruntergeladen oder gespendet wurde. Nutzungsprotokoll ohne Inhalte. |
| Ort | Server in der EU (Cloudflare-Jurisdiktion `eu`); Deutschland lässt sich nicht erzwingen |
| Browser | aktueller Chrome, Edge, Safari; Handy als Mikrofon wie bisher |
| Robustheit | fällt ein KI-Dienst aus, laufen Zeit, Redeanteile und Monolog weiter |

## 6. Betrieb

- **Cloudflare Containers** (Workers-Paid-Plan, 5 $/Monat). Ein Worker prüft das Passwort und startet je
  Meeting einen eigenen Container. Der Zustand bleibt im Prozess, wie heute.
- **Ein Image** mit Code und Modellen. Lokal läuft dasselbe mit `python -m coach` oder `docker run`.
- **OpenAI-Schlüssel:** Niclas' Schlüssel als Secret, in einem eigenen OpenAI-Projekt mit Ausgabenlimit. Wer
  möchte, trägt auf der Startseite (aufklappbare Zeile unter den Modus-Karten, optional) seinen eigenen Schlüssel
  ein – ein Angebot, kein Pflichtschritt. Ein eingetragener Schlüssel hat Vorrang vor Niclas' Schlüssel; die
  Kopfleiste im Dashboard zeigt dann unauffällig „eigener Schlüssel“. Im Cloud-Betrieb wird ein so eingetragener
  Schlüssel beim Abschluss des Meetings („Fertig“) wieder gelöscht – er gilt nur für dieses eine Meeting; im
  lokalen Betrieb bleibt er wie bisher gespeichert.
- **Kunden** stehen in einer Liste: Name, Passwort-Hash, Höchstzahl gleichzeitiger Meetings.
- **Abo-Wege** (Codex, Claude über den Pi) sind nur für Tests und in der Cloud aus.
- **Rechtstexte:** Impressum und Datenschutzerklärung, knapp und pragmatisch. Die Datenschutzerklärung nennt
  OpenAI und Cloudflare als Empfänger.

## 7. Nicht enthalten

Online-Meetings (Teams, Zoom), Stimmprofile über mehrere Meetings, Bewertung von Personen, Bezahlpflicht,
Nutzerkonten mit Selbstregistrierung.

## 8. Arbeitsweise

- **Tickets** sind GitHub-Issues in diesem Repo, eins je Arbeitspaket. Sie enthalten: Ziel, Bezug ins
  Lastenheft, Dateien, die angefasst werden dürfen, Dateien, die tabu sind, Abnahme und Prüfbefehl.
- **Branch je Ticket**, Commit-Nachricht mit `#<nr>`. Ein Ticket ist fertig, wenn die Abnahme erfüllt ist,
  die Tests grün sind und das Lastenheft stimmt.
- **Testen ohne unnötige API-Kosten:** `LMC_KI=codex` (Codex auf dem Pi), `LMC_TEXT_CACHE`, `LMC_STIMME_AUS=1`.
  Echte API-Aufrufe nur für eine Abnahme, die sie wirklich braucht, und mit Kosten im Ticket vermerkt.
