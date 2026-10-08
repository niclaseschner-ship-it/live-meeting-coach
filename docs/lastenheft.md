# Nestor – Lastenheft

**Stand:** 08.10.2026 (Ticket #13: zwei Stufen) · **Gilt für:** Nestor als Angebot über einen Link (SaaS) ·
**Vorgänger:** [archiv/spezifikation_v2.md](archiv/spezifikation_v2.md) (Laptop-Fassung, Messungen bis 05.10.)

Diese Datei beschreibt verbindlich, was Nestor tut. Wer etwas Nennenswertes ändert, trägt es hier im selben
Commit nach. Messberichte und Begründungen stehen in den verlinkten Dokumenten, hier stehen nur Ergebnisse.

## 1. Produkt

Nestor begleitet Präsenzmeetings (3–8 Personen, Deutsch). Er behält Agenda, Zeit und Gesprächsfluss im Blick,
antwortet auf Ansprache und hält fest, was besprochen und entschieden wurde. **Die Gruppe entscheidet,
Nestor zeigt nur an.**

Nestor gibt es in **zwei Stufen** (Abschnitt 3): **Nestor Basis** nutzt nur Mistral AI (Frankreich, Verarbeitung in
der EU) – für Runden, bei denen der Einsatz sonst am Datenschutz scheitert („kein OpenAI“). **Nestor Premium** nutzt
OpenAI und legt Gespräch und Live-Bild darauf. Der Name bleibt in beiden Stufen Nestor.

Nestor ist ein privates Projekt von Niclas Eschner und kein Geschäft. Die API-Kosten trägt Niclas vor,
Nutzer gleichen sie am Ende freiwillig aus.

## 2. Ablauf für Nutzer

```
Link + Passwort ─► Startseite ─► Meeting einrichten ─► Meeting ─► Abschluss
                   Stufe wählen   Agenda per Prompt              Paket · Unterstützung · Datenspende
```

1. **Zugang:** Jeder Kunde bekommt einen Link und ein eigenes Passwort. Ein Kunde kann mehrere Meetings
   gleichzeitig führen.
2. **Startseite:** Was Nestor kann, die Wahl zwischen den zwei Stufen Basis und Premium (Abschnitt 3) mit je einem
   Satz zur Verarbeitung und den erwarteten Kosten je Stunde, in Basis der Schalter „Nur auf Knopfdruck“, und der
   Hinweis, dass Niclas die Kosten vorstreckt. Dazu Links auf Impressum und Datenschutz.
3. **Meeting einrichten:** Titel, Ziel und Agenda entstehen zusammen aus einer freien Eingabe – meist der
   eingefügten Einladungsmail (Abschnitt 4.1). Dann werden die Gesprächsregeln gewählt: verlässliche und Beta
   getrennt, dazu optional freie „weitere Regeln“ als Erinnerung, die Nestor nur vorliest, nicht prüft.
4. **Meeting:** Dashboard mit denselben Knöpfen an denselben Stellen in beiden Stufen; Premium zeigt zusätzlich
   das Live-Bild und spricht im Gespräch.
5. **Abschluss:** Nach „Meeting beenden“ folgt eine Seite mit drei Angeboten:
   - **Eigenes Paket** herunterladen (Abschnitt 4.4).
   - **Unterstützung:** echte Kosten des Meetings, drei Vorschläge und ein PayPal-QR-Code.
   - **Datenspende** mit Feedback.

   Danach wird der Meetingzustand auf dem Server gelöscht.

## 3. Die zwei Stufen

Produktentscheidung (Niclas, 08.10.2026): genau zwei Stufen, keine dritte Variante. Gleiche Funktionen, gleiche
Knöpfe, gleiche Stellen im Dashboard – man kann jederzeit umsteigen, ohne überrascht zu werden. Premium legt nur das
Erlebnis darauf (Gespräch, Live-Bild). `LMC_KI=codex` und der Claude-Bildweg sind reine Testwege, keine Stufe.

| | **Nestor Basis** (Einstieg, EU) | **Nestor Premium** |
|---|---|---|
| KI-Anbieter | nur Mistral AI (Frankreich, Verarbeitung in der EU), ein Schlüssel | OpenAI |
| Ton | läuft zum Server und in Echtzeit zu Mistral (Voxtral Realtime) | läuft zum Server und in Echtzeit zu OpenAI |
| Live-Transkript, Fokus, Ton, Ergebnisse | live | live |
| Monolog, Redeanteile, Überlappung, Zeit | live, lokal auf dem Server | live, lokal auf dem Server |
| Nestor ansprechen | „Nestor, …“ per Zuruf und die Knöpfe (auch am Handy) | „Nestor, …“ wie im Gespräch, und die Knöpfe |
| Nestors Antwort | gesprochen mit der Stimme **Thorsten** (Thorsten-Voice, CC0) und als Karte; keine Rückfragen ohne Namen, kein Ins-Wort-Fallen | Realtime-Gespräch: Rückfragen ohne Namen, Reinreden macht ihn still |
| Überblick | **Überblick als Text** (Abschnitt 4.7) nach 5 min, dann alle 10 min, auf Zuruf („zeig uns die Übersicht“) und per Knopf; kein Bildmodell | Überblick als Text per Knopf **und** Live-Bild alle 10 min und auf Zuruf |
| Knöpfe | Wo stehen wir? · Regeln eingehalten? · Überblick · Protokoll · Nestor fragen (am Handy: halten) | dieselben |
| Löschen | „Nein“ in der Begrüßung löscht alles | „Nein“ in der Begrüßung löscht alles |
| Kosten (Richtwert) | ~0,7 € je Stunde | ~2 € je Stunde |

**Schalter „Nur auf Knopfdruck“ (nur Basis):** der frühere Modus „Auf Knopfdruck“. Ohne Knopf geht nichts an
Mistral: Der Ton bleibt auf dem Server, Transkript, Fokus, Ton-Prüfung, Ergebnisse und Überblick gibt es nur auf
Knopfdruck (Abschnitt 4.2), Nestor hört nicht auf Zuruf und antwortet als Karte. Zeit, Redeanteile, Überlappung und
Monolog laufen lokal weiter. Zusätzlich „letzte 5 Minuten verwerfen“ und „alles verwerfen“. Kosten ~0,1–0,2 € je
Stunde (Voxtral-Transkription der Sprache plus wenige Cent je Knopf, gerechnet).

Auf der Startseite steht zu **Basis** wörtlich: „Alle KI-Dienste von Mistral AI (Frankreich), Verarbeitung in der
EU.“ Zu **Premium**: „Alles Gesprochene wird in Echtzeit von OpenAI verarbeitet.“ Zum Schalter: „Nur auf
Knopfdruck – ohne Knopf geht nichts an Mistral. Ihr Ton liegt bis dahin nur auf unserem Server in der EU und wird am
Ende gelöscht.“

Modelle in Basis: Live-Text `voxtral-mini-transcribe-realtime-2602` (Verzug 240 ms), Transkription auf Knopfdruck
`voxtral-mini-latest`, Text `mistral-medium-latest` (Nestor, Karten, Agenda per Prompt, Ergebnisse, Regeln, Protokoll,
Überblick, Folie), Zuordnung alle ~15 s `mistral-small-latest` (im Vergleich gleich gut, ein Zehntel der Kosten),
Recherche über die Conversations-API mit `web_search`, Stimme `voxtral-mini-tts-latest` mit der gespeicherten Stimme
Thorsten. Nestors `AKTION:`-Zeile bleibt Text, kein Tool-Call (Mistral hat in xbuddy Tool-Calls halluziniert).

Gemessen ([messung_basis.md](messung_basis.md)): Sprechende → Thorstens erster Ton im Median 2,0–2,1 s, alle zwölf
Zurufe der Probe lösen die richtige Aktion aus (24/24). Die Kostenrichtwerte stammen aus dem Nutzungsprotokoll
(`coach/kosten.py`); Basis ist aus gemessenen Einzelaufrufen hochgerechnet: Grundlast ~0,5 $/h (Live-Text allein 0,36 $/h), dazu
~0,01 $ je Frage an Nestor und ~0,06 $ je Recherche – mit 10 Fragen und 2 Recherchen ~0,7 $/h (≈ 0,65 €). Der
Cloud-Lauf vom 08.10. kam auf ~1 $/h, weil das Testmaterial sechs Zurufe mit zwei Recherchen in zehn Minuten
enthält (Ticket #15, [messung_basis.md](messung_basis.md)). Premium wie bisher ~2 $/h. Der frühere Richtwert für „Auf Knopfdruck“ mit OpenAI (0,4 $/h, Ticket #7,
[messung_knopfdruck.md](messung_knopfdruck.md)) gilt nicht mehr, seit der Schalter zu Basis gehört.

## 4. Funktionen

### 4.1 Agenda per Prompt

Ein Eingabefeld – groß und zentral ganz oben im Einrichten-Bereich – nimmt Text, Eingefügtes (Tabelle aus
Outlook, Mail, Liste, eine ganze Einladungsmail) oder Sprache entgegen. Daraus macht ein Sprachmodell eine
Tabelle mit den Spalten Punkt, Minuten und Ziel (optional); dazu schlägt es Titel, Ziel des Meetings und,
wenn genannt, die Teilnehmenden vor. Aus einer Einladungsmail wird der Betreff zum Titel, der einleitende
Satz mit Zweck oder Anlass zum Ziel, eine Uhrzeit „von–bis“ zur Gesamtdauer, auf die Punkte ohne eigene
Minutenangabe gleichmäßig verteilt werden. Titel, Ziel und Teilnehmende überschreibt das Modell nur, wenn sie
leer sind oder die Eingabe eindeutig ein neues Meeting beschreibt; ein gezielter Änderungswunsch („Ziel ist
eigentlich …“) ändert nur das gemeinte Feld. Die Tabelle ist direkt bearbeitbar. Über dasselbe Feld lässt sie
sich im Dialog weiter ändern, etwa mit „Punkt 3 kürzer, dafür Pause einbauen“. Mit „Nur auf Knopfdruck“ gilt
das Absenden einer Spracheingabe als Knopfdruck.

Daneben gibt es „Weitere Regeln“: ein Freitext (Kachel im selben Raster wie die Gesprächsregeln), den Nestor
einmal am Anfang vorliest – höchstens drei Punkte wörtlich, sonst zusammengefasst mit „und N weitere, die ihr
auf dem Bildschirm seht“ – aber nicht prüft. Reine Erinnerung für die Runde, kein Signal.

### 4.2 Die Knöpfe – Analysen auf Knopfdruck

Dieselben Knöpfe stehen in beiden Stufen an derselben Stelle im Dashboard (Leiste unter der Kopfzeile) und am Handy:

- **Wo stehen wir?** Stand der Agenda und Vorschlag für den nächsten Schritt (Karte)
- **Regeln eingehalten?** Prüfung der vereinbarten Gesprächsregeln (Karte)
- **Überblick:** Überblick als Text (Abschnitt 4.7)
- **Protokoll**
- **Nestor fragen:** im Dashboard getippt, am Handy **gehalten**: halten, fragen, loslassen – der Ton der Frage wird
  transkribiert und wie „Nestor, …“ beantwortet, gesprochen und als Karte. Freie Fragen schließen Recherche („gib uns
  einen Überblick zu …“) und das Arbeiten mit dem Transkript ein („such mir raus, was zum Budget gesagt wurde“).
  Was während des Haltens gesagt wird, löst nicht zusätzlich eine Antwort über den Zuruf aus.

Ohne „Nur auf Knopfdruck“ liegt das Transkript schon vor, ein Knopf braucht dann nur die Analyse (gemessen 1–4 s);
„Regeln eingehalten?“ fasst dann die laufenden Ampeln zusammen, ohne KI-Aufruf.

Mit **„Nur auf Knopfdruck“** (Basis) transkribiert ein Knopfdruck zuerst den bisher noch nicht transkribierten Ton
(fertige Teile bleiben gespeichert) und führt dann die Analyse aus; „Nestor fragen“ antwortet als Karte. Bis die
Antwort kommt, sieht man den Fortschritt. In Basis gemessen (3-Minuten-Demo, [messung_basis.md](messung_basis.md)):
1,8–3,9 s je Knopf. Die folgende Messung stammt noch aus dem früheren Modus mit OpenAI-Transkription und Codex
(Ticket #7, 60-Minuten-Probe, [docs/messung_knopfdruck.md](messung_knopfdruck.md)):

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

Weitere Regeln mit „Nur auf Knopfdruck“:
- Agendawechsel nur per Klick (Ansagen kämen erst beim nächsten Knopf an).
- Am Meetingende keine automatische Auswertung; Protokoll und Überblick gibt es, wenn vorher gedrückt wurde.
- **Verwerfen** entfernt Ton, Transkript und alles daraus Abgeleitete (Karten, Überblick, Protokoll, Befunde) aus dem
  Zeitraum; die Aufnahme wird dort zu Stille. Redeanteile bleiben, sie enthalten keine Inhalte.
- Erster Probelauf (3 min, 4 Knöpfe): je Knopf 9–15 s, davon Transkription 1–6 s; 0,009 $ Transkription.
  Ausführliche Messung über 60 Minuten: siehe Tabelle oben.

### 4.3 Signale und ihre Verlässlichkeit

Jedes Signal ist im Dashboard als **verlässlich** oder **Beta** gekennzeichnet (Schlüssel im Katalog/Code
weiterhin „experimentell“, Ticket #10 ändert nur den Anzeige-Text). Bei Beta-Signalen steht in einem Satz
dabei, wie oft sie danebenliegen. Verlässliche Signale stehen vorn und sind von den Beta-Signalen farblich
und räumlich getrennt – bei den Gesprächsregeln in der Einrichtung (zwei Gruppen) genauso wie bei den
Regel-Ampeln im Dashboard.

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

Ein ZIP mit Protokoll (`protokoll.md`), Abschlussbild (Basis: `ueberblick.md`, der Überblick als Text),
Transkript, Agenda mit Zeitnutzung und Hinweisen. In Premium ist das Protokoll die Analyse hinter dem
Abschlussbild; Basis hat kein Bild und erstellt es am Meetingende wie der Knopf „Protokoll“ (Ergebnisse je
Agendapunkt). Mit „Nur auf Knopfdruck“ gibt es Protokoll und Überblick nur, wenn vorher gedrückt wurde.
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

### 4.7 Überblick als Text

Der Stand des Meetings als strukturierte Dashboard-Ansicht ohne Bildmodell (`coach/ueberblick.py`), in beiden Stufen:
Kopf (Titel, Laufzeit, aktueller Punkt, Agenda mit Status), ✅ Entschieden (grün), 🟡 Offen (bernstein),
📌 Aufgaben (wer, bis wann), ↪ Außerhalb der Agenda (grau) und „Neu seit dem letzten Stand“. Inhalte aus einem
Textaufruf über Agenda, die festgestellten Ergebnisse je Punkt (Regel 10) und das Transkript. Nichts wird gemalt:
Jede Zahl muss im Material vorkommen, sonst entfällt der Eintrag; „Person N“ erscheint nicht. In Basis ersetzt der
Überblick das Live-Bild (nach 5 min, dann alle 10 min, auf Zuruf, am Ende, per Knopf), in Premium ist er neben dem Live-Bild
umschaltbar. Er liegt als `ueberblick.md` in der Meeting-Ablage. Die Bildprobe mit Mistral (FLUX) war unbrauchbar
(55.000 € statt 25.000 €, Wortsalat, Bilddatei bei Microsoft Azure) – deshalb in Basis kein Bildmodell.

## 5. Rahmenbedingungen

| | |
|---|---|
| Kosten | Premium ≤ 2 $ je Stunde, Basis ≤ 0,7 $ je Stunde, gemessen über das Nutzungsprotokoll |
| Datenschutz Basis | In Basis geht kein einziger Aufruf an OpenAI (nachgewiesen über das Nutzungsprotokoll) |
| Parallele Meetings | gemessen ohne 429: Basis bis 24, Premium bis 8 gleichzeitig ([messung_basis.md](messung_basis.md)); bei Überlast wiederholt Nestor mit Wartezeit und sagt sonst „Ich komme gerade nicht durch, versucht es gleich nochmal.“ |
| Datenhaltung | Ton und Transkript nur bis zum Abschluss; danach bleibt nur, was heruntergeladen oder gespendet wurde. Nutzungsprotokoll ohne Inhalte. |
| Ort | Server in der EU (Cloudflare-Jurisdiktion `eu`); Deutschland lässt sich nicht erzwingen |
| Browser | aktueller Chrome, Edge, Safari; Handy als Mikrofon wie bisher |
| Robustheit | fällt ein KI-Dienst aus, laufen Zeit, Redeanteile und Monolog weiter |

## 6. Betrieb

- **Cloudflare Containers** (Workers-Paid-Plan, 5 $/Monat). Ein Worker prüft das Passwort und startet je
  Meeting einen eigenen Container. Der Zustand bleibt im Prozess, wie heute.
- **Ein Image** mit Code und Modellen. Lokal läuft dasselbe mit `python -m coach` oder `docker run`.
- **Mistral-Schlüssel (Basis):** Niclas' Schlüssel als Secret `MISTRAL_API_KEY`, im Container als
  `LMC_MISTRAL_SCHLUESSEL`. Fehlt er, ist Basis auf der Startseite nicht wählbar. Die Stimme Thorsten ist im
  Mistral-Konto gespeichert; die Referenz (CC0) liegt in `coach/stimmen/`, um sie neu anzulegen.
- **OpenAI-Schlüssel (Premium):** Niclas' Schlüssel als Secret, in einem eigenen OpenAI-Projekt mit Ausgabenlimit. Wer
  möchte, trägt auf der Startseite (aufklappbare Zeile unter den Stufen-Karten, optional) seinen eigenen Schlüssel
  ein – ein Angebot, kein Pflichtschritt. Ein eingetragener Schlüssel hat Vorrang vor Niclas' Schlüssel; die
  Kopfleiste im Dashboard zeigt dann unauffällig „eigener Schlüssel“. Im Cloud-Betrieb wird ein so eingetragener
  Schlüssel beim Abschluss des Meetings („Fertig“) wieder gelöscht – er gilt nur für dieses eine Meeting; im
  lokalen Betrieb bleibt er wie bisher gespeichert.
- **Kunden** stehen in einer Liste: Name, Passwort-Hash, Höchstzahl gleichzeitiger Meetings. Ein Meeting zählt
  dagegen erst ab dem echten Start (`/api/start`), nicht schon beim Ansehen der Startseite (Ticket #12). „Fertig“
  im Abschluss gibt seinen Platz sofort frei und schließt den Container, ohne „Fertig“ erst nach 30 Minuten ohne
  Anfrage.
- **Abo-Wege** (Codex, Claude über den Pi) sind nur für Tests und in der Cloud aus.
- **Rechtstexte:** Impressum und Datenschutzerklärung, knapp und pragmatisch. Die Datenschutzerklärung nennt die
  Empfänger je Stufe: in Basis Mistral AI (statt OpenAI), in Premium OpenAI, in beiden Cloudflare.

### 4.8 Qualität aus Nutzersicht

Der Cloud-Testlauf (Ticket #9) prüft, ob alles funktioniert; die Rubrik in [qualitaet.md](qualitaet.md)
(Ticket #11) hält zusätzlich fest, ob es sich auch gut anfühlt – Ansprache-Treffer/Fehlauslöser,
Antwortzeit, Antwortgüte, Verständlichkeit der Oberfläche auf einen Blick, Live-Bild/Überblick-Treue,
Abschlusspaket-Brauchbarkeit, Ruhe (Hinweise je 10 min) und ein Gesamteindruck. Bewertet mit
`scripts/cloudtest_bewerten.py`, Kennzahlen gerechnet, Urteile 1–5 von einem Sprachmodell mit Bild-Eingabe.

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
