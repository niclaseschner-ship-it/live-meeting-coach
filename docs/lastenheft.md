# Nestor – Lastenheft

**Stand:** 08.10.2026 (Ticket #13: zwei Stufen; Ticket #26: Meeting-Artefakte; Ticket #27: Bedienlogik) · **Gilt für:** Nestor als Angebot über einen Link (SaaS) ·
**Vorgänger:** [archiv/spezifikation_v2.md](archiv/spezifikation_v2.md) (Laptop-Fassung, Messungen bis 05.10.)

Diese Datei beschreibt verbindlich, was Nestor tut. Wer etwas Nennenswertes ändert, trägt es hier im selben
Commit nach. Messberichte und Begründungen stehen in den verlinkten Dokumenten, hier stehen nur Ergebnisse.

## 1. Produkt

Nestor begleitet Präsenzmeetings (3–8 Personen, Deutsch). Er behält Agenda, Zeit und Gesprächsfluss im Blick,
antwortet auf Ansprache und hält fest, was besprochen und entschieden wurde. **Die Gruppe entscheidet,
Nestor zeigt nur an.**

**Grundregel (Ticket #27): Nestor spricht nur in einem Antwortbogen, den die Runde ausgelöst hat.** Ein Bogen
ist ein Auftrag und eine Antwort: sofort eine kurze Bestätigung, dann eine Karte im Verlauf, dann ein bis zwei Sätze
zu dem, was auffällt – nie das, was auf der Karte steht (Abschnitt 4.10). Was Nestor von sich aus merkt (Zeit, Thema,
Lücken, fünf Minuten vor Schluss, ein abgeschlossener Agendapunkt), kommt **still**: als Zeile im Band oben oder als
Karte im Verlauf – nie mit Stimme, nie als Pop-up. Einzige Ausnahme ist die Begrüßung mit der Einwilligung (Niclas,
08.10.2026). Neue Funktionen halten sich daran; wer gegen die Regel verstößt, ist ein Fehler.

Es gibt drei Orte und sonst nichts: **oben das Band** (Regel-Hinweise und Nestors stille Angebote, verschwindet von
selbst, höchstens ein Knopf), **in der Mitte der Verlauf** (alles Inhaltliche als Karte, neueste vorn, zurückblättern
wie durch Bilder in einer Chatgruppe) und **die Stimme** (nur im Bogen).

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
   Satz, wie man mit Nestor spricht (Premium wie ein Telefon, Basis wie ein Funkgerät), zur Verarbeitung und den
   erwarteten Kosten je Stunde, und der Hinweis, dass Niclas die Kosten vorstreckt. Dazu Links auf Impressum und
   Datenschutz. Der Schalter „Nur auf Knopfdruck“ ist vorerst aus dem Angebot (Ticket #27; der Code bleibt).
3. **Meeting einrichten:** Titel, Ziel und Agenda entstehen zusammen aus einer freien Eingabe – meist der
   eingefügten Einladungsmail (Abschnitt 4.1). Dann werden die Gesprächsregeln gewählt: verlässliche und Beta
   getrennt, dazu optional freie „weitere Regeln“ als Erinnerung, die Nestor nur vorliest, nicht prüft.
   **Handykopplung (Ticket #50):** Genau ein Handy je Meeting, anonym per QR-Code ohne Registrierung.
   Ein zweites Handy wird mit verständlicher Meldung abgewiesen und übernimmt weder Mikrofon noch Ton.
   Neuladen desselben Handys übernimmt dessen Verbindung, ohne zwei aktive Tabs zuzulassen. Nach Verbindung
   verschwindet der große erste Schritt und eine kompakte Rückmeldung zeigt, ob Mikrofon und Ton bereit sind.
   Nach Trennung erscheint der erste Schritt erneut. Der Start bleibt bis zu frischem Handy-Audio und
   angeschaltetem Handylautsprecher gesperrt.
4. **Meeting:** Dashboard mit denselben Knöpfen an denselben Stellen in beiden Stufen: links Zeit, Agenda und die
   gewählten Regeln, in der Mitte Nestor und der Verlauf, rechts Redeanteile und Gesprächsdynamik, oben das Band
   (Abschnitt 4.10). Premium kann zusätzlich ein Live-Bild zeichnen und spricht im Realtime-Gespräch.
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
| Nestor ansprechen | **wie ein Telefon:** „Nestor, …“; direkt nach dem Bogen eine Nachfrage ohne Namen; am Handy auch die Sprechtaste; die Knöpfe | **wie ein Funkgerät:** Sprechtaste halten, sprechen, loslassen (Laptop: Knopf oder Leertaste, Handy: großer Knopf); auf „Nestor“ reagiert Basis nicht; die Knöpfe |
| Nestors Antwort | Antwortbogen im Realtime-Gespräch; Reinreden macht ihn still | Antwortbogen mit der Stimme **Thorsten** (Thorsten-Voice, CC0); er redet aus, die Sprechtaste unterbricht |
| Bild / Überblick | Live-Bild auf Zuruf und per Knopf (langer Auftrag, kommt still) und am Ende; Überblick als Text per Knopf | **Überblick als Text** (Abschnitt 4.7) auf Zuruf und per Knopf und am Ende; kein Bildmodell |
| Knöpfe | Wo stehen wir? · Zusammenfassen · Was fehlt? · Protokoll · Überblick · Bild · Regeln eingehalten? (nur mit Regeln) · Nestor fragen | dieselben ohne Bild, dazu die Sprechtaste |
| Löschen | „Nein“ in der Begrüßung oder später „Nestor, nein“ löscht alles | dasselbe – Einwilligung und Nein bleiben per Stimme |
| Kosten (Richtwert) | ~2 € je Stunde | ~0,7 € je Stunde |

**Schalter „Nur auf Knopfdruck“ (nur Basis):** vorerst aus dem Angebot (Ticket #27) – auf der Startseite
ausgeblendet, der Code bleibt. Ohne Knopf geht dann nichts an Mistral: Der Ton bleibt auf dem Server, Transkript,
Fokus, Ton-Prüfung, Ergebnisse und Überblick gibt es nur auf Knopfdruck (Abschnitt 4.2), Nestor spricht nicht und
antwortet als Karte. Zeit, Redeanteile, Überlappung und Monolog laufen lokal weiter. Zusätzlich „letzte 5 Minuten
verwerfen“ und „alles verwerfen“. Kosten ~0,1–0,2 € je Stunde.

Die Startseite zeigt je Stufe einen Satz, wie man mit Nestor spricht, und zwei Plus- und zwei Minus-Stichpunkte
(Ticket #18/#27). **Premium**: „Wie ein Telefon: Ihr sagt „Nestor, …“, fragt direkt danach ohne Namen nach und könnt
ihm jederzeit ins Wort fallen.“, „+ Natürliches Gespräch: Nachfrage ohne Namen, ihr könnt reinreden“, „+ Live-Bild
auf Zuruf“, „− US-Anbieter (OpenAI)“, „− etwa 2 € je Meetingstunde“ (Richtwert). **Basis**: „Wie ein Funkgerät: Ihr
haltet die Sprechtaste, sprecht und lasst los – Nestor redet dann aus.“, „+ KI nur bei Mistral (Frankreich),
Verarbeitung in der EU“, „+ etwa 0,7 € je Meetingstunde“ (Richtwert), „− Fragen per Sprechtaste statt mit Namen,
kein Reinreden“, „− Überblick als Text statt Live-Bild“.

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

**Pilotfeedback (Ticket #49):** Auch eine freie Beschreibung eines Vorhabens ohne fertige Tagesordnung
ergibt einen strukturierten Agendaentwurf, nicht bloß ein befülltes Ziel. Fehlende Minuten werden geschätzt
und als Schätzung kenntlich gemacht. Fehlen Thema oder beabsichtigtes Ergebnis, erscheinen konkrete Rückfragen;
eine Folgeantwort verwendet den bisherigen Dialog. Während einer Rückfrage bleiben bestehende Felder und
Agendapunkte unverändert. Der kurze Vorbereitungsdialog bleibt nur im offenen Browser-Tab und wird nicht
dauerhaft gespeichert. Text und Sprache verwenden denselben Ablauf.

Daneben gibt es „Weitere Regeln“: ein Freitext in einer eigenen, neutral gestalteten Gruppe unterhalb der
Gesprächsregeln – deutlich von den prüfbaren Regeln abgehoben (anderes Symbol, gestrichelter Rahmen, eigener
Untertitel „Nestor liest sie zu Beginn vor – prüfen kann er sie nicht“), damit auf einen Blick klar ist, dass
Nestor das nur einmal am Anfang vorliest – höchstens drei Punkte wörtlich, sonst zusammengefasst mit „und N
weitere, die ihr auf dem Bildschirm seht“ – aber nicht prüft. Reine Erinnerung für die Runde, kein Signal.

### 4.2 Die Knöpfe – jeder Knopf ein Antwortbogen

Dieselben Knöpfe stehen in beiden Stufen an derselben Stelle im Dashboard (Leiste unter der Kopfleiste) und am Handy.
Jeder Knopf löst einen Antwortbogen aus wie ein Zuruf (Abschnitt 4.10): Bestätigung, Karte im Verlauf, ein bis zwei
Sätze. Während ein Bogen läuft, sind die Knöpfe gesperrt (sichtbar: „Nestor ist bei „Wo stehen wir?“ …“).

- **Wo stehen wir?** Stand der Agenda, Zeit, Festgehaltenes, Offenes und ein Vorschlag für den nächsten Schritt
  (Karte); ein Aufruf liefert Karte und Satz. Schlägt er einen Punktwechsel vor, steht „Weiter zu …?“ im Band.
- **Zusammenfassen:** holt den laufenden Abschnitt nach (Abschnitt 4.9) und zeigt Entscheidungen, Aufgaben und
  Offenes als Karte; ein kleiner Modellaufruf formuliert den Satz („Hier ist sie. Zwei Aufgaben haben noch niemanden,
  der sich kümmert.“).
- **Was fehlt?** die Lücken als Karte, Satz wie oben.
- **Protokoll:** die Karte „Festgehalten“ (alle Artefakte, Lücken rot und antippbar, „+ Eintragen“, Link auf das
  ganze Protokoll); die Liste steht nicht mehr dauerhaft in der linken Spalte.
- **Überblick:** Überblick als Text (Abschnitt 4.7) als Karte, „Hier ist der Überblick.“
- **Bild** (nur Premium): langer Auftrag (Abschnitt 4.10) – „Nehme ich mit …“, das Bild kommt still in den Verlauf.
- **Regeln eingehalten?** nur, wenn Regeln gewählt sind; fasst die Ampeln zusammen, ohne KI-Aufruf.
- **Nestor fragen:** getippt im Dashboard; gesprochen per Sprechtaste (Basis am Laptop und Handy, Premium am Handy) –
  halten, fragen, loslassen; der Ton der Frage wird transkribiert und wie „Nestor, …“ beantwortet. Was während des
  Haltens gesagt wird, löst nicht zusätzlich eine Antwort über den Live-Text aus.

Mit **„Nur auf Knopfdruck“** (Basis, vorerst aus dem Angebot) transkribiert ein Knopfdruck zuerst den bisher noch
nicht transkribierten Ton und führt dann die Analyse aus; die Antwort kommt als Karte ohne Stimme, Zusammenfassen und
Was fehlt sind dort das Protokoll. Gemessen (3-Minuten-Demo, [messung_basis.md](messung_basis.md)): 1,8–3,9 s je
Knopf. Weitere Regeln dieses Modus: Agendawechsel nur per Klick; am Meetingende keine automatische Auswertung;
**Verwerfen** entfernt Ton, Transkript und alles daraus Abgeleitete aus dem Zeitraum (die Aufnahme wird dort zu
Stille), Redeanteile bleiben. Ältere Messung mit OpenAI-Transkription und Codex: [messung_knopfdruck.md](messung_knopfdruck.md).

### 4.3 Signale und ihre Verlässlichkeit

**Nur gewählte Regeln sind sichtbar (Ticket #27).** Eine Regel, die die Runde nicht gewählt hat, hat kein Band,
keine Ampel und keine Prüfung – das gilt für Fokus, Zeit, Monolog und Überlappung genauso wie für die anderen (bis
#27 kamen diese vier immer). Was keine Regel ist, bleibt: die Uhr und der Countdown links, die Redeanteile, die
Gesprächsdynamik und der Agenda-Vorschlag „Weiter zu …?“ (ein Band-Hinweis mit Knopf).

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
| Nachfrage ohne Namen (Premium) | verlässlich | `scripts/einordnen_messen.py`, 14 Sätze direkt nach einer Antwort: 14/14 mit Denkaufwand „low“ (Median 1,04 s), 13/14 mit „none“ (Median 0,70 s; der eine Fehler war eine Zeitüberschreitung → still) – eingestellt ist „none“ | – |
| Namen aus der Vorstellungsrunde | verlässlich bei klaren Stimmen | `scripts/namensrunde_messen.py`, vier Azure-Stimmen, drei Reihenfolgen: vorher 0/12 Namen richtig (jede kurze Vorstellung landete als „Person ?“), jetzt 12/12, 0 falsch | – |

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

Pilotfeedback 09.10.2026 (#37, #43): Datenspende steht vor Unterstützung und Download. Während eines Uploads
ist Abschließen gesperrt; Fehler bleiben sichtbar und erlauben einen neuen Versuch. Abschließen startet eine
sichtbare, nicht verlängerbare Rückkehrfrist von fünf Minuten für Paket und Spende. Danach löscht die Cloud
automatisch und beendet den Container; lokal bleibt die explizite Einstellung `ablage_behalten` maßgeblich.

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

Pilotfeedback (#34, #44): Der Knopf bietet „Aktueller Punkt“ (Vorauswahl) und „Ganzes Meeting“. Aktueller Punkt
filtert Transkript und festgestellte Ergebnisse vor dem Modellaufruf. Ergebnisaktionen warten auf die laufende
Transkription; ein Timeout meldet den fehlenden letzten Beitrag statt unbemerkt alten Stand auszugeben.
Agenda-Titel und -Ziele stammen ausschließlich aus den gespeicherten Daten; neue Ideen heißen Vorschlag.

Weitere Pilotkorrekturen (#31–36, #45–48): Leertaste unterdrückt auch bei Wiederholung Seitensprünge,
Texteingaben bleiben normal bedienbar. Neue Ergebnisse erhalten einen deutlich beschrifteten Merker;
ein optionaler 0,12-Sekunden-Signalton ist standardmäßig aus und kostet keine KI-Aufrufe. Recherche behält
die vollständige Antwort und klickbare Quellen statt sie nochmals zu wenigen Stichworten zu verdichten;
fehlende Quellen werden ausdrücklich markiert. Monolog zeigt laufende Dauer und Schwelle, Dynamik ist
eingeklappt und zusätzlich im Abschluss verfügbar. Assistenten-Sprechfenster werden aus Überlappungszahlen
herausgenommen. Namen werden nur aus einer tatsächlichen Vorstellung gelernt, nicht aus Erwähnungen.
Eindeutige kleine ASR-Schreibvarianten können einem bereits eingetragenen Namen zugeordnet werden;
mehrdeutige Kandidaten werden nicht geraten (#35).
Ausdrückliche Korrekturen können bestehende Artefakte berichtigen, gemeinsame Verantwortlichkeit erfordert
eine belegte Vereinbarung. Relative Fristen erhalten das Meetingdatum als Bezug; pauschale Fristen ergänzen
alle betroffenen Aufgaben, spätere Ausnahmen nur die betreffende Aufgabe. Premium verwendet den
serverseitigen OpenAI-Projektschlüssel; Basis/Mistral bleibt die Vorauswahl.

Abnahme-Nachtrag (#40, #41): Telegram prüft zusätzlich zur HTTP-Antwort die positive Bot-API-Bestätigung
und protokolliert ausschließlich deren Erfolg, ohne Nachricht, Chat-ID oder Token. Die feste Begrüßung
verzichtet auf redundante Agenda-Kommentare und lange Bedienerklärungen; Einwilligung, Nein/Löschen,
Produktrolle, Agendawechsel, Sprechtaste und Namen bleiben enthalten.
Ein zwischenzeitlich gestartetes neues Meeting verlängert die alte Löschfrist nicht: ausschließlich dessen
alter Archivordner und die Fristreferenz werden entfernt, ohne das neue Meeting zurückzusetzen (#37).

Der Stand des Meetings als strukturierte Dashboard-Ansicht ohne Bildmodell (`coach/ueberblick.py`), in beiden Stufen:
Kopf (Titel, Laufzeit, aktueller Punkt, Agenda mit Status), ✅ Entschieden (grün), 🟡 Offen (bernstein),
📌 Aufgaben (wer, bis wann), ↪ Außerhalb der Agenda (grau) und „Neu seit dem letzten Stand“. Inhalte aus einem
Textaufruf über Agenda, die festgestellten Ergebnisse je Punkt (Regel 10) und das Transkript. Nichts wird gemalt:
Jede Zahl muss im Material vorkommen, sonst entfällt der Eintrag; „Person N“ erscheint nicht. In Basis ersetzt der
Überblick das Live-Bild (auf Zuruf, per Knopf und am Ende – seit Ticket #27 nicht mehr im 10-Minuten-Takt), in Premium
gibt es ihn per Knopf; beides als Karte im Verlauf. Er liegt als `ueberblick.md` in der Meeting-Ablage. Die Bildprobe mit Mistral (FLUX) war unbrauchbar
(55.000 € statt 25.000 €, Wortsalat, Bilddatei bei Microsoft Azure) – deshalb in Basis kein Bildmodell.

### 4.9 Meeting-Artefakte (Ticket #26, Ablauf seit Ticket #27)

Nestor erkennt **unabhängig von der Agenda** vier Artefakte und führt sie über das ganze Meeting
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
- **Erkennung bei Bedarf, nicht ständig:** Erkannt wird still je **Abschnitt** – wenn ein Agendapunkt endet, nach
  20 Minuten am selben Punkt und ohne Agenda alle 20 Minuten (`LMC_ABSCHNITT_MINUTEN`) – und nur über diesen
  Abschnitt. Auf Anfrage (Zusammenfassen, Was fehlt, Protokoll) wird nur der laufende Abschnitt nachgeholt, in
  parallelen Stücken (höchstens 6 000 Zeichen je Aufruf), damit der Bogen unter 15 s bleibt. Das Modell sieht die
  schon festgehaltenen Artefakte mit Nummer und ergänzt, statt doppelt anzulegen. Premium `gpt-5.4-mini`, Basis
  `mistral-medium-latest` (`mistral-small` war deutlich schlechter). Unter Konfidenz 0,4 wird nichts festgehalten,
  unter 0,5 nichts markiert. Gemessen nach 60 Minuten Meeting: Bogen „Zusammenfassen“ Premium 10,2 s, Basis 12,2 s (Abschnitt 4.10).
- **Zusammenfassung je Abschnitt (still):** eine Karte „Punkt 2 · Budget“ bzw. „Zwischenstand“ im Verlauf –
  entschieden, Aufgaben, offen, Risiken. Keine Stimme, keine Nachfrage.
- **Regel „Ergebnisse festhalten“** heißt nur noch: Lücken in diesen Karten rot markieren plus ein Band-Hinweis
  („2 Aufgaben ohne Verantwortliche in „Budget“ · Zur Karte ›“, der Knopf springt zur Karte). Ohne Regel keine
  Markierung und kein Band – die Karte kommt trotzdem. Die Ampel der Regel wird gelb, solange markierte Lücken offen
  sind.
- **Anzeige und Bearbeiten:** in den Karten des Verlaufs (Zusammenfassung, Was fehlt, Festgehalten, Punkt-Karte) je
  Eintrag Typ-Zeichen, Inhalt, wer · bis; was fehlt, steht als rotes Etikett dabei. Antippen öffnet die Bearbeitung
  an Ort und Stelle (Typ, Was, Wer, Bis wann, Status, Reaktion; „Nicht nötig“, „Löschen“). Die Karten zeigen immer den
  aktuellen Stand: Eine Lücke, die die Runde schließt, wird in derselben Karte grün – es entsteht keine neue Karte.
  Was die Runde setzt, gilt als bestätigt und wird von der Erkennung nicht überschrieben.
- **Lücke korrigieren per Stimme** ist ein normaler kurzer Bogen: Premium „Nestor, Anna macht das bis Freitag“
  (Realtime-Werkzeug `artefakt_eintragen`), Basis dasselbe per Sprechtaste (`AKTION: eintragen`) – Nestor sagt nur
  „Notiert.“
- **Fünf Minuten vor dem geplanten Ende** (immer, auch ohne Regel; geplantes Ende = Summe der Agendaminuten, bei
  kurzen Meetings zur Hälfte): still ins Band, als Angebot ohne Frage: „Noch 5 Minuten · Zusammenfassen ›“. Der Knopf
  löst den Bogen „Zusammenfassen“ aus (Zusammenfassung aus den Artefakten plus höchstens drei Lücken – zuerst
  Aufgaben ohne Wer, dann ohne Termin, dann unklare Entscheidungen bzw. hohe Risiken). Ein bloßes „Ja“ in den Raum
  wirkt nicht; in Premium geht „Nestor, gib mir die Zusammenfassung“, in Basis die Sprechtaste.
- **Nur auf Knopfdruck:** keine automatische Erkennung; Artefakte entstehen nur über den Protokoll-Knopf; der
  Band-Knopf „Zusammenfassen ›“ wirkt dort wie der Protokoll-Knopf.
- **Standardgliederung** (`meeting.json`, für Abschluss und Export #22): Kopf (Titel, Datum, Dauer, Ziel, „Ziel
  erreicht?“ – offen, bis die Korrekturansicht aus #22 es abfragt), Entscheidungen, Aufgaben (Was/Wer/Bis wann, Lücken),
  offene Punkte, Risiken, Parkplatz, Agenda Soll/Ist. Das Dokument selbst (Grafik, Regelanalyse, Anhang) kommt mit #22.
- **Kosten:** deutlich weniger Aufrufe als die frühere Erkennung je Minute Sprache (Premium etwa +0,2 $/h, Basis
  +0,15 $/h): je Abschnitt ein bis drei Aufrufe, dazu die Aufrufe auf Anfrage – im 60-Minuten-Messlauf zwei Abschnitte mit je zwei bis vier Aufrufen plus ein Zusammenfassen mit sechs parallelen Stücken.

### 4.10 Bedienlogik: Antwortbogen, Verlauf, Band (Ticket #27)

**Der Antwortbogen.** Ein Auftrag, ein Bogen, höchstens ~15 s (`coach/assistent.py`, `coach/bogen.py`):
1. sofort eine kurze Bestätigung aus dem Floskel-Vorrat – zwei bis drei Varianten je Art, für Zuruf, Sprechtaste und
   Knopf gleich („Bin dran.“, „Moment, kommt gleich.“, „Schau ich mir an, komme gleich zurück.“), je Stimme einmal
   erzeugt und zwischengespeichert;
2. dann erscheint die Karte im Verlauf;
3. dann ein bis zwei Sätze zu dem, was auffällt („Hier ist sie. Zwei Aufgaben haben noch niemanden, der sich
   kümmert. Schaut kurz drauf.“) – **nie vorlesen, was auf der Karte steht**. Für Zusammenfassen und Was fehlt
   formuliert ein kleiner Modellaufruf den Satz, bei Wo stehen wir liefert ihn derselbe Aufruf wie die Karte. Kurze
   Fragen („Wie viel Zeit noch?“): Antwort in einem Satz, die Karte trägt die Einzelheiten aus dem Meeting-Stand.
   Seh-Inhalte (Folie, Überblick, Liste): Bestätigung plus „Hier ist die Folie.“ – kein Inhalt gesprochen.

**Nur ein Bogen zur Zeit.** Knöpfe sind währenddessen gesperrt (sichtbar). Ein Zuruf bzw. die Sprechtaste unterbricht
den laufenden Bogen (Premium: Reinreden oder „Nestor, …“, Basis: die Sprechtaste) und startet den neuen – nie zwei
parallel. **Unterbrechen stoppt nur die Stimme, nicht die Arbeit:** Die Karte des ersten Auftrags kommt trotzdem
still in den Verlauf (im Realtime-Gespräch wird die Antwort fertig erzeugt, das Modell erfährt per
`conversation.item.truncate`, wie weit sie zu hören war). Gemessen: `scripts/bogen_messen.py` nach 60 Minuten: Bestätigung immer sofort (Floskel), Karte nach 0–11 s, Ende eines Karten-Bogens nach 1–12 s; Einzelwerte in [sprachassistent.md](sprachassistent.md).

**Lange Aufträge sind kein Bogen:** Bild (~60 s) und Recherche (20–60 s). Nestor sagt nur „Nehme ich mit, dauert ein
bisschen. Macht ruhig weiter.“; das Ergebnis kommt später **still** in den Verlauf (Bild-Karte, Recherche-Karte mit
Quellen), ohne „ist fertig“. Erklären lassen geht über einen neuen Auftrag („Nestor, erklär das Bild“). **Stau:**
höchstens zwei – einer läuft, einer wartet („Ich bin noch am Bild, die Recherche mache ich danach.“), ein dritter wird
abgewehrt („Ich hab gerade zwei Sachen auf dem Zettel. Fragt mich gleich nochmal.“). Oben rechts der Arbeitsring
„1 läuft · 1 wartet“; antippen zeigt beide, ✕ bricht ab. Kurze Fragen laufen neben langen Aufträgen sofort.

**Verlauf (Mitte):** Alles, was Inhalt ist, ist eine Karte – Antwort, Zusammenfassung, Was fehlt, Festgehalten,
Recherche mit Quellen, Folie, Bild, Überblick, Punkt-Zusammenfassung. Neueste vorn; mit ‹ › (am Handy wischen, am
Laptop auch die Pfeiltasten) blättert man zurück. Nichts muss man wegklicken. Ein Ergebnis eines Bogens springt nach
vorn und leuchtet kurz. Still Geliefertes (Bild, Recherche, Abschnitts-Zusammenfassung, unterbrochener Bogen) springt
nur nach vorn, wenn die vordere Karte älter als ~60 s ist – sonst reiht es sich dahinter ein, mit dem Merker
„1 neu ›“. Im leeren Verlauf steht eine Karte mit vier Beispielen, wie man Nestor nutzt (je Stufe passend). Über dem
Verlauf Nestors Zeile mit dem N: dreht sich, solange er arbeitet; darunter läuft mit, was er gerade sagt.

**Band (oben):** Regel-Hinweise (nur gewählte Regeln), Agenda-Vorschlag „Weiter zu …? · Weiter ›“, „Noch 5 Minuten ·
Zusammenfassen ›“, der Lücken-Hinweis mit Sprung zur Karte, „Erkannt: Anna, David …“ nach der Namensrunde und in
Basis „Sprechtaste halten, dann fragen“ (wenn jemand „Nestor“ sagt, höchstens einmal je Minute). Höchstens drei
Zeilen; jede verschwindet von selbst; ein Hinweis zu einem Agendapunkt verschwindet, sobald ein anderer Punkt aktiv
ist.

**Premium = Telefon.** Anfangen mit „Nestor, …“ (am Handy alternativ die Sprechtaste). Nach dem Bogen ist 15 s lang
eine Nachfrage ohne Namen möglich, sichtbar als Ring „Ich höre zu“, der abläuft (Follow-up-Modus wie bei
Sprachassistenten): **nur der erste Satz** danach kann eine Nachfrage sein; ist er nicht an Nestor gerichtet, schließt
das Fenster sofort. Entschieden wird in drei Stufen, im Zweifel schweigt Nestor: (1) spricht der Satz eine Person der
Runde an („Anna, …“, „…, oder Tarek?“) → nicht an Nestor; (2) eine klare Anschlussfrage oder ein Auftrag („Und bis
wann?“, „Zeig …“, „Kannst du …“) → an Nestor; (3) sonst ein schneller Text-Klassifikator (gpt-5.4-mini) mit Nestors
letzter Antwort: Frage an Nestor / an Nestor ohne Antwort („Passt“) / nicht an Nestor. Dieselbe Person wie die
Fragende ist nur ein Plus-Signal. Unterbrechen durch Reinreden.

**Basis = Funkgerät.** Anfangen nur mit der Sprechtaste: halten, sprechen, loslassen (Laptop: Knopf oder Leertaste,
Handy: großer Knopf). Basis hört nicht auf „Nestor“ – keine Ansprache per Name, kein Rückfrage-Fenster, keine
Echo-Probleme. Nestor redet aus; die Taste unterbricht ihn. Einwilligung und „Nein“ bleiben per Stimme („Nestor,
nein“ löscht auch in Basis alles).

**Begrüßung und Namen.** Nestor sagt in der Begrüßung alles (Einwilligung, Regeln, wie man ihn anspricht –
Telefon bzw. Funkgerät –, Agenda-Bitte, Start mit Punkt eins) und endet mit „Wenn ihr mögt, sagt kurz eure Namen,
dann schreibe ich das Protokoll mit Namen.“ Danach spricht er nicht mehr von sich aus; er ordnet die Namen still zu
(Name mit dem Stimm-Fingerabdruck der Vorstellung, zugeordnet, sobald die Stimme im Register sicher bekannt ist) und
zeigt oben „Erkannt: Anna, David …“. Gemessen: `scripts/namensrunde_messen.py`, vier Azure-Stimmen, drei Reihenfolgen: vorher 0/12 Namen richtig (jede kurze Vorstellung landete als „Person ?“), jetzt 12/12, 0 falsch.

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
