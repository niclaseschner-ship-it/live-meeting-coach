# Nestor – Lastenheft

**Stand:** 08.10.2026 (Ticket #13: zwei Stufen; Ticket #26: Meeting-Artefakte) · **Gilt für:** Nestor als Angebot über einen Link (SaaS) ·
**Vorgänger:** [archiv/spezifikation_v2.md](archiv/spezifikation_v2.md) (Laptop-Fassung, Messungen bis 05.10.)

Diese Datei beschreibt verbindlich, was Nestor tut. Wer etwas Nennenswertes ändert, trägt es hier im selben
Commit nach. Messberichte und Begründungen stehen in den verlinkten Dokumenten, hier stehen nur Ergebnisse.

## 1. Produkt

Nestor begleitet Präsenzmeetings (3–8 Personen, Deutsch). Er behält Agenda, Zeit und Gesprächsfluss im Blick,
antwortet auf Ansprache und hält fest, was besprochen und entschieden wurde. **Die Gruppe entscheidet,
Nestor zeigt nur an.**

**Grundregel: Nestor spricht nur, wenn er gefragt wird.** Gesprochen wird auf Ansprache (Name, Rückfrage direkt
nach seiner Antwort) oder auf einen Knopf. Will Nestor von sich aus auf etwas aufmerksam machen (Zeit, Thema,
Lücken, fünf Minuten vor Schluss), tut er das **still**: Einblendung, Pop-up mit Knöpfen oder Ampel – nie mit
Stimme. Einzige Ausnahme ist die Begrüßung mit der Einwilligung zu Beginn (Niclas, 08.10.2026). Neue Funktionen
halten sich daran; wer gegen die Regel verstößt, ist ein Fehler.

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
5. **Abschluss:** Nach „Meeting beenden“ folgt eine Seite, eingeleitet mit einem Abschluss-Kopf – „Danke!
   11 Minuten · 4 Punkte · 2 Entscheidungen“, mit demselben Logo wie im Dashboard – und drei Angeboten:
   - **Eigenes Paket** herunterladen (Abschnitt 4.4).
   - **Unterstützung:** echte Kosten des Meetings, drei Vorschläge und ein PayPal-QR-Code.
   - **Datenspende** (Abschnitt 4.6).

   Danach wird der Meetingzustand auf dem Server gelöscht.

**Stil (Rückmeldung Niclas 08.10.2026):** Startseite, Rechtstexte, Abschluss, Feedback-Fenster und die
Anmeldeseite duzen – „du“/„dein“, wenn die eine Person angesprochen wird, die Nestor einrichtet oder die
Rechtstexte liest, „ihr“/„euer“, wo es ausdrücklich um die ganze Runde im Meeting geht (z. B. der aufgenommene
Ton). Genau wie Nestors gesprochene Begrüßung, die schon „du“ und „ihr“ je nach Adressat mischt. Vorher stand
hier Sie-Form.

## 3. Die zwei Stufen

Produktentscheidung (Niclas, 08.10.2026): genau zwei Stufen, keine dritte Variante. Gleiche Funktionen, gleiche
Knöpfe, gleiche Stellen im Dashboard – man kann jederzeit umsteigen, ohne überrascht zu werden. Premium legt nur das
Erlebnis darauf (Gespräch, Live-Bild). `LMC_KI=codex` und der Claude-Bildweg sind reine Testwege, keine Stufe.

**Wording (Niclas, 08.10.2026, Ticket #18):** **Nestor Premium** (OpenAI) ist der **Standard** – auf der
Startseite zuerst, größer, mit dem Zusatz „Standard“. **Nestor Basis** (Mistral) ist das **Downgrade** für alle,
denen DSGVO-Nähe (alles in der EU, europäischer Anbieter) und weniger Kosten wichtiger sind als Gespräch und
Live-Bild.

| | **Nestor Premium** (Standard) | **Nestor Basis** (Downgrade, EU) |
|---|---|---|
| KI-Anbieter | OpenAI | nur Mistral AI (Frankreich, Verarbeitung in der EU), ein Schlüssel |
| Ton | läuft zum Server und in Echtzeit zu OpenAI | läuft zum Server und in Echtzeit zu Mistral (Voxtral Realtime) |
| Live-Transkript, Fokus, Ton, Ergebnisse | live | live |
| Monolog, Redeanteile, Überlappung, Zeit | live, lokal auf dem Server | live, lokal auf dem Server |
| Nestor ansprechen | „Nestor, …“ wie im Gespräch, und die Knöpfe | „Nestor, …“ per Zuruf und die Knöpfe (auch am Handy) |
| Nestors Antwort | Realtime-Gespräch: Rückfragen ohne Namen, Reinreden macht ihn still | gesprochen mit der Stimme **Thorsten** (Thorsten-Voice, CC0) und als Karte; keine Rückfragen ohne Namen, kein Ins-Wort-Fallen |
| Überblick | Überblick als Text per Knopf **und** Live-Bild alle 10 min und auf Zuruf | **Überblick als Text** (Abschnitt 4.7) nach 5 min, dann alle 10 min, auf Zuruf („zeig uns die Übersicht“) und per Knopf; kein Bildmodell |
| Knöpfe | Wo stehen wir? · Regeln eingehalten? · Überblick · Protokoll · Nestor fragen (am Handy: halten) | dieselben |
| Löschen | „Nein“ in der Begrüßung löscht alles | „Nein“ in der Begrüßung löscht alles |
| Kosten (Richtwert) | ~2 € je Stunde | ~0,7 € je Stunde |

**Schalter „Nur auf Knopfdruck“ (nur Basis):** der frühere Modus „Auf Knopfdruck“. Ohne Knopf geht nichts an
Mistral: Der Ton bleibt auf dem Server, Transkript, Fokus, Ton-Prüfung, Ergebnisse und Überblick gibt es nur auf
Knopfdruck (Abschnitt 4.2), Nestor hört nicht auf Zuruf und antwortet als Karte. Zeit, Redeanteile, Überlappung und
Monolog laufen lokal weiter. Zusätzlich „letzte 5 Minuten verwerfen“ und „alles verwerfen“. Kosten ~0,1–0,2 € je
Stunde (Voxtral-Transkription der Sprache plus wenige Cent je Knopf, gerechnet).

Die Startseite zeigt je Stufe zwei Plus- und zwei Minus-Stichpunkte statt Fließtext (kein Ganzsatz, Ticket #18).
**Premium**: „+ Natürliches Gespräch: Rückfragen ohne Namen, ihr könnt reinreden“, „+ Live-Bild alle 10 Minuten und
auf Zuruf“, „− US-Anbieter (OpenAI)“, „− etwa 2 € je Meetingstunde“ (Richtwert). **Basis**: „+ KI nur bei Mistral
(Frankreich), Verarbeitung in der EU“, „+ etwa 0,7 € je Meetingstunde“ (Richtwert), „− Ansprache immer mit Namen,
kein Reinreden“, „− Überblick als Text statt Live-Bild“. Zum Schalter wörtlich: „Nur auf Knopfdruck – ohne Knopf
geht nichts an Mistral. Euer Ton liegt bis dahin nur auf unserem Server in der EU und wird am Ende gelöscht.“

Darüber, gut sichtbar statt im Kleingedruckten, das Datenversprechen: „Wir sehen nichts von deinen Meetingdaten und
nutzen nichts davon – außer du erlaubst es uns am Ende ausdrücklich (Datenspende). Nach dem Meeting wird alles
gelöscht.“ Unter den Karten ein knapper Satz zum Hosting (Cloudflare, Server in der EU; Einzelheiten in der
Datenschutzerklärung) und, unaufdringlich und nicht als Hauptbotschaft, der Hinweis: „Nestor ist Open Source
(AGPL-3.0) und lässt sich selbst hosten“, mit Link auf das (seit 08.10.2026 öffentliche, seit 0da0713 unter
AGPL-3.0 lizenzierte) GitHub-Repo – solange das Repo privat gewesen wäre, hätte dieser Hinweis entfallen.

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

Daneben gibt es „Weitere Regeln“: ein Freitext in einer eigenen, neutral gestalteten Gruppe unterhalb der
Gesprächsregeln – deutlich von den prüfbaren Regeln abgehoben (anderes Symbol, gestrichelter Rahmen, eigener
Untertitel „Nestor liest sie zu Beginn vor – prüfen kann er sie nicht“), damit auf einen Blick klar ist, dass
Nestor das nur einmal am Anfang vorliest – höchstens drei Punkte wörtlich, sonst zusammengefasst mit „und N
weitere, die ihr auf dem Bildschirm seht“ – aber nicht prüft. Reine Erinnerung für die Runde, kein Signal.

### 4.2 Die Knöpfe – Analysen auf Knopfdruck

Dieselben Knöpfe stehen in beiden Stufen an derselben Stelle im Dashboard (Leiste unter der Kopfzeile) und am Handy:

- **Wo stehen wir?** Stand der Agenda und Vorschlag für den nächsten Schritt (Karte)
- **Regeln eingehalten?** Prüfung der vereinbarten Gesprächsregeln (Karte)
- **Überblick:** Überblick als Text (Abschnitt 4.7)
- **Protokoll:** wertet aus, was noch nicht auf Meeting-Artefakte geprüft ist (Abschnitt 4.9), und zeigt das
  Protokoll je Agendapunkt mit Entscheidungen, Aufgaben, offenen Punkten und Risiken; Lücken stehen als „fehlt“ dabei.
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
| Ergebnisse festhalten (Meeting-Artefakte, 4.9) | verlässlich | 4/5 Beschlüsse richtig im deutschen Material ([gespraechsregeln.md](gespraechsregeln.md) §10); Artefakte auf zwei Cloudlauf-Transkripten 12/16 und 10/11 (Premium), 15/16 und 9/11 (Basis, mehr Fehlalarme), die erwartete Lücke jedes Mal gefunden ([gespraechsregeln.md](gespraechsregeln.md) §10); im englischsprachigen AMI-Material deutlich schwächer (0/8, 1/9, 3/8, [testlauf_2026-10-06.md](testlauf_2026-10-06.md)) | – |
| Gleichzeitiges Sprechen | experimentell | findet 41–68 % der echten, 84–86 % der Meldungen stimmen | „Experimentell: findet 41 bis 68 % der echten Stellen; was gemeldet wird, stimmt in 84 bis 86 % der Fälle.“ |
| Ausreden lassen | experimentell | in geordneten Runden kaum Fehlalarme, in Zwischenruf-Proben unbrauchbar | „Experimentell: In geordneten Runden kaum Fehlalarme, in Proben mit vielen Zwischenrufen unbrauchbar.“ |
| Klima | experimentell | nicht gegen eine Referenz gemessen | „Experimentell: noch nicht gegen eine Referenz gemessen.“ |
| Nestor beantwortet Fragen | verlässlich | 20/22 im Testlauf, Antwort nach 1,5–6 s | – |

### 4.4 Paket zum Herunterladen

Ein ZIP mit Protokoll (`protokoll.md`), Abschlussbild (Basis: `ueberblick.md`, der Überblick als Text),
Transkript, Agenda mit Zeitnutzung und Hinweisen, dazu `meeting.json` (Standardgliederung, Abschnitt 4.9) und
`tasks.json` (nur die Aufgaben: was, wer, bis wann, Lücken, bestätigt) als Grundlage für das Export-Dokument (#22). In Premium ist das Protokoll die Analyse hinter dem
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

### 4.6 Feedback, Datenspende

- **Feedback-Knopf (Ticket #18, Nachtrag):** auf jeder Seite erreichbar – Startseite, Dashboard, Abschluss –, im
  Dashboard gut sichtbar, aber nicht in der Kopfleiste und nicht störend. Öffnet ein kleines Fenster: Art wählen
  (Feedback · Funktionswunsch · Fehler), Textfeld, Senden, kurzer Dank. Jederzeit erlaubt, auch während eines
  laufenden Meetings – anders als die Datenspende unten kein beendetes Meeting nötig. `POST /api/feedback`
  (`coach/api_abschluss.py`), legt über dieselbe Ablage ab wie die Datenspende (lokal ein Ordner, im Cloud-Betrieb
  R2), ohne Meetinginhalte.
- **Datenspende:** Transkript, Hinweise, Agenda und optional die Aufnahme, mit einer eigenen Anmerkung dazu.
  Absenden geht nur mit dem Häkchen „Alle Teilnehmenden sind einverstanden, dass diese Daten gespendet werden“.
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

### 4.9 Meeting-Artefakte (Ticket #26)

Nestor erkennt **unabhängig von der Agenda** im Live-Text vier Artefakte und führt sie über das ganze Meeting
(`coach/artefakte.py`, Grundlage [meeting_artefakte_2026-10-08.md](meeting_artefakte_2026-10-08.md)).
Agendapunkte müssen keine Entscheidung haben.

| Artefakt | Pflichtfelder | Lücke, wenn |
|---|---|---|
| **Aufgabe** | Was (Handlung), Wer (genau eine Person), Bis wann | eins fehlt; nur „wir/alle/jemand“; „prüfen/anschauen“ ohne Ergebnis |
| **Entscheidung** | Was gilt, endgültig/vorläufig, wer hat entschieden | nur Vorschlag; vorläufig ohne Wiedervorlage |
| **Offener Punkt** | präzise Frage, wer klärt, bis wann/Termin | weder Zuständige noch Wiedervorlage (außerhalb der Agenda: Parkplatz) |
| **Risiko** | Ursache → Auswirkung, wer beobachtet, Reaktion | diffuse Sorge; niemand beobachtet; hohes Risiko ohne Maßnahme |

- **Datenmodell:** je Artefakt Typ, Felder, Lücken (daraus „vollständig“), Konfidenz, Quelle (Zeit, Satz, Sprecher),
  Agendapunkt zur Zeit der Quelle, bestätigt ja/nein (Stimme oder Klick), nachgefragt, abgelehnt. Daraus abgeleitet:
  die Ergebnisse je Agendapunkt (Nestors Kontext, Überblick, Protokoll, Abschluss-Kopf) und die Standardgliederung.
- **Erkennung live:** etwa je Minute Sprache (Basis je zwei Minuten) ein Aufruf mit den neuen Sätzen, etwas Kontext
  und den schon festgehaltenen Artefakten mit Nummer – das Modell ergänzt, statt doppelt anzulegen. Zusätzlich beim
  Punktwechsel, vor der Zusammenfassung, auf den Protokoll-Knopf und am Ende. Premium `gpt-5.4-mini`, Basis
  `mistral-medium-latest` (`mistral-small` war im Vergleich deutlich schlechter: Aufgaben für Nestor, falsche
  Zuständige). Unter Konfidenz 0,4 wird nichts festgehalten, unter 0,5 nicht nachgefragt.
- **Anzeige:** linke Spalte unter der Agenda, „Festgehalten“ – unauffällig, je Eintrag Typ-Zeichen, Inhalt, wer · bis;
  was fehlt, steht als kleines rotes Etikett dabei („wer?“, „bis wann?“). Klick öffnet die Bearbeitung (Typ, Was, Wer,
  Bis wann, bei Entscheidungen der Status, bei Risiken die Reaktion), „+“ trägt von Hand ein. Was die Runde setzt, gilt
  als bestätigt und wird von der Erkennung nicht überschrieben.
- **Prüfung beim Punktwechsel** (nur mit der Regel „Ergebnisse festhalten“): Nestor fragt kurz und gebündelt, eine
  Frage je unvollständigem Artefakt mit konkretem Vorschlag („Ich hab notiert: Statusseite-Zusammenfassung. Wer
  übernimmt das, bis wann?“), höchstens zwei gesprochen, der Rest steht im Dashboard. Ist alles vollständig, schweigt er.
  Nach jedem Artefakt fragt er nur einmal; eine abgelehnte Nachfrage („brauchen wir nicht“, Knopf „Nicht nötig“)
  kommt nie wieder, auch nicht am Ende.
- **Fünf Minuten vor dem geplanten Ende** (immer, auch ohne Regel; geplantes Ende = Summe der Agendaminuten, bei
  Meetings unter zehn Minuten zur Hälfte): Rückfrage im Nestor-Feld mit „Ja, zusammenfassen“ / „Nein, danke“ und
  gesprochen: „Noch fünf Minuten. Soll ich zusammenfassen und die letzten Aufgaben verteilen?“. Bei Ja (Stimme oder
  Knopf): Zusammenfassung aus den Artefakten (nichts frei Formuliertes) plus höchstens drei Lücken – zuerst Aufgaben
  ohne Wer, dann ohne Termin, dann unklare Entscheidungen bzw. hohe Risiken; dazu eine Karte im Nestor-Feld.
- **Lücken schließen:** Nach einer Nachfrage gilt ein Satz ohne Namen 30 s lang als Antwort („Sofie übernimmt die
  Statusseite bis Freitag“) – ein kleiner Aufruf trägt ein, Nestor bestätigt kurz („Eingetragen: Sofie, bis Freitag.“).
  Mit Namen geht es jederzeit: Premium über das Realtime-Werkzeug `artefakt_eintragen`, Basis über
  `AKTION: eintragen`. Dazu Klick und Bearbeiten im Dashboard.
- **Nur auf Knopfdruck:** keine automatische Erkennung; Artefakte entstehen nur über den Protokoll-Knopf. Die
  Fünf-Minuten-Rückfrage erscheint still im Nestor-Feld; ihr Ja wirkt wie der Protokoll-Knopf.
- **Standardgliederung** (`meeting.json`, für Abschluss und Export #22): Kopf (Titel, Datum, Dauer, Ziel, „Ziel
  erreicht?“ – offen, bis die Korrekturansicht aus #22 es abfragt), Entscheidungen, Aufgaben (Was/Wer/Bis wann, Lücken),
  offene Punkte, Risiken, Parkplatz, Agenda Soll/Ist. Das Dokument selbst (Grafik, Regelanalyse, Anhang) kommt mit #22.
- **Kosten:** Premium etwa +0,2 $ je Stunde (≈ 50 Aufrufe à ~1 600 Tokens rein, ~450 raus), Basis etwa +0,15 $ je
  Stunde (≈ 27 Aufrufe à ~1 800/350 mit mistral-medium); gemessen auf zwei dichten 10-Minuten-Transkripten 0,13–0,17 $/h
  (Premium) und 0,14–0,24 $/h (Basis). Die frühere Ergebnisprüfung je Punkt entfällt dafür.

## 5. Rahmenbedingungen

| | |
|---|---|
| Kosten | Premium ≤ 2 $ je Stunde, Basis ≤ 0,7 $ je Stunde, gemessen über das Nutzungsprotokoll. Mit den Meeting-Artefakten (4.9) Premium etwa 2,2 $, Basis etwa 0,85 $ je Stunde (Richtwert mit 10 Fragen und 2 Recherchen) – Basis liegt damit über dem Ziel; ob seltener erkannt oder das Ziel angehoben wird, ist offen (Entscheidung Niclas) |
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
