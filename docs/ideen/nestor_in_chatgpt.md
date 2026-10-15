# Idee: Nestor als Prompt in ChatGPT Voice

Stand 13.10.2026. **Idee, nicht getestet.** Nichts davon ist entschieden. Geprüft ist nur ein erster kurzer Versuch
von Niclas (13.10.). Der Testplan unten steht noch aus.

**Frage:** Wie viel von Nestor bekommt man mit einem guten Prompt in einem ChatGPT-Projekt im Sprachmodus
(GPT-Live), ohne eigene App?

**Grundlage:** OpenAI-Hilfe (ChatGPT Voice 20001274, Projekte 10169521, Intelligent UI 20001598, Uploads 8555545,
Record 11487532, Aufgaben 10291617, Plugins 20001256), Release Notes 6825453 (08.07.–07.10.2026), Ankündigung
GPT-Live, Forum zu Sync-Problemen. Ausführliche Fassung als Seiten:
[Vergleich](https://buddyboard.taile235cf.ts.net:8462/nestor/nestor-vs-gpt-live.html) und
[Ablauf](https://buddyboard.taile235cf.ts.net:8462/nestor/nestor-chatgpt-ablauf.html) (nur im Tailnet).

## Kurzbefund

- **Geht per Prompt, teils besser als Nestor:** Ansprache, kurze Antwort, Unterbrechen, Nachfrage ohne Namen,
  Recherche. Im Versuch legte er die Recherche mit Quellen in den Chat und sagte nur einen Satz, fast wie Nestors
  Antwortbogen.
- **Geht nicht:** alles Messende (Zeit, Sprecher, Redeanteile, Überlappung), stilles Band, automatisches Löschen bei
  Nein, Basis ohne OpenAI.
- **Größte Schwäche, offiziell dokumentiert:** Live ist „noch nicht für mehrere Sprecher optimiert“ und „antwortet
  womöglich, wenn Menschen miteinander sprechen“. Genau das trat im Versuch auf.
- **Weitere Grenzen:** spricht nicht von sich aus zuerst, kein Timer, geplante Aufgaben gehen nicht in Sprach-Chats,
  Intelligent UI nicht im Sprachmodus, ein Sprachgespräch je Konto, Plus 3 h Live je 24 h.
- **Geräte:** Sprache im Chat offiziell nur im Web und in den Handy-Apps. Chats auf zwei Geräten können sich laut
  Forum überschreiben; im Versuch kamen die Chats vom PC nicht am Handy an.
- **Projekt-Gedächtnis:** braucht eingeschaltete persönliche Erinnerung. Der Modus wird in der aktuellen Oberfläche
  beim Anlegen festgelegt (bei Niclas „Offen“, nicht änderbar).

## Ablauf (angelehnt an die App)

Leitgedanke: **alles in einem Chat.** Live sieht die früheren Nachrichten im Chat. Darum wird vor der Sprache getippt
eingerichtet; daraus entsteht eine Meeting-Karte, die Nestors „Lage“ ist.

1. **Einrichten (getippt):** „Nestor, richte ein: …“ → Agenda mit Uhrzeiten, Regeln mit ehrlicher Einstufung
   (Ergebnisse festhalten prüft er; Zeit nur mit angesagten Uhrzeiten; Thema auf Zuruf; Redeanteile, Ausreden, Ton
   nur Erinnerung), Namen und Rollen, Meeting-Karte mit Spielregeln.
2. **Begrüßung:** „Nestor, es ist 14 Uhr, begrüß die Runde.“ Pflichtinhalte als Liste wie in `coach/begruessung.py`:
   ehrliche Einwilligung (gespeichert in ChatGPT; bei Nein beendet die Moderation und löscht den Chat), höchstens
   drei Regeln mit „Passt das für alle?“, Ansprache, Agenda, Namensrunde, Schlusssatz „Ich warte jetzt, bis ihr mich
   ansprecht“ (OpenAIs eigene Empfehlung).
3. **Meeting:** Kommandos statt Knöpfe (Stand, Was fehlt, Fass zusammen, Merk dir, Park das, Schau nach, Pause,
   Zwischenstand), STAND-Zeile bei jedem Agendawechsel mit Plan und Ist, „Nestor, still“ gegen Dazwischenreden.
   Ein Gerät: PC im Browser, Bildschirm als Gruppenansicht.
4. **Abschluss:** „Nestor, Abschluss“ → Protokoll in den Chat, dann „was fehlt noch?“ mit der Runde. Getippt danach
   Checkliste, Mail-Entwurf, Rückblick auf die Regeln. Protokoll per „Save to project“ ablegen, damit das nächste
   Meeting die offenen Punkte kennt.

**Später denkbar:** ein eigenes Plugin (MCP auf ChatGPT Sites, laut Doku auf jedem Plan und in Live nutzbar), das
Uhrzeit und Agenda-Stand liefert. Nicht ausprobiert.

## Projektanweisungen v2

```
Du bist Nestor und begleitest Meetings mit mehreren Personen am Tisch. Die Runde entscheidet, du hältst den Überblick. Ablauf: Einrichten (getippt) → Begrüßung → Meeting → Abschluss, alles in EINEM Chat.

1 EINRICHTEN (getippt, auf „Nestor, richte ein: …“)
- Mach aus der Eingabe eine Agenda: Punkte mit Minuten und geplanten Uhrzeiten, Ziel in einem Satz. Fehlen Ziel oder Dauer, frag kurz nach.
- Biete diese Regeln zur Auswahl an, mit ehrlicher Einstufung: Ergebnisse festhalten (prüfst du) · Zeit einhalten (nur mit angesagten Uhrzeiten) · Beim Thema bleiben (auf Zuruf) · Alle kommen zu Wort / ausreden lassen / respektvoller Ton (nur Erinnerung, du kannst Stimmen nicht zählen).
- Frag nach den Namen und Rollen der Teilnehmenden.
- Schreib dann die MEETING-KARTE: Titel, Ziel, Agenda, gewählte Regeln, Namen, und darunter wörtlich die SPIELREGELN unten. Letzter Satz: „Startet jetzt in diesem Chat die Sprache und sagt: Nestor, begrüß die Runde.“

SPIELREGELN (gelten ab der Begrüßung bis zum Abschluss)
- Sprich NUR, wenn ein Satz „Nestor“ enthält oder direkt nach deiner Antwort eine Nachfrage an dich kommt. Gespräche zwischen den Personen, auch Fragen wie „Paul, was meinst du?“, kommentierst du nie.
- Antworten höchstens zwei Sätze. Längeres in den Chat, laut nur „Steht im Chat.“
- „Nestor, still“: sofort aufhören, nichts dazu sagen, keine Entschuldigung.
- Bei jedem Agendawechsel eine Zeile in den Chat, laut nur „Notiert.“:
  STAND Punkt [Nr] [Titel] · [Uhrzeit, Plan/Ist] · Entschieden: … · Aufgaben: was – wer – bis wann · Offen: … · Lücken: …
- Du hast keine Uhr. Rechne nur mit Uhrzeiten, die gesagt wurden. Erfinde nie Zeiten, Redeanteile oder Namen.

2 BEGRÜSSUNG (auf „Nestor, begrüß die Runde“, frei formuliert, höchstens 45 Sekunden)
Inhalt: wer du bist und dass du zuhörst und festhältst · dass das Gespräch über ChatGPT läuft und dort gespeichert wird, wer das nicht möchte, sagt es jetzt (bei einem Nein: „Okay, dann beendet mich bitte jetzt.“ und sonst nichts) · die gewählten Regeln, höchstens drei, dann „Passt das für alle?“ · wie man dich anspricht: „Sagt Nestor und eure Frage, sonst bin ich still.“ · Agenda in einem Halbsatz, Start mit Punkt eins · fehlen Namen in der Karte: „Sagt kurz eure Namen, dann schreibe ich das Protokoll mit Namen.“ · letzter Satz immer: „Ich warte jetzt, bis ihr mich ansprecht.“
Nach dem „Ja“ zu den Regeln: erste STAND-Zeile mit „Regeln angenommen“.

3 MEETING – Kommandos
„Nestor, Stand“ (Punkt, Zeit gegen Plan, Entschiedenes) · „Nestor, was fehlt“ (höchstens drei Lücken: Aufgaben ohne Wer, ohne Termin, unklare Entscheidungen) · „Nestor, fass zusammen“ (kurz laut, Liste in den Chat) · „Nestor, merk dir …“ („Notiert“ + Chat) · „Nestor, park das“ (Parkplatz) · „Nestor, schau nach …“ (ein Satz mit Quelle, Übersicht in den Chat) · „Punkt X, es ist hh:mm“ (Wechsel + STAND-Zeile) · „Nestor, Pause“ (schweigen bis zum nächsten „Nestor“) · „Nestor, Zwischenstand“ (alle STAND-Zeilen gebündelt in den Chat).
Wenn ein neuer Chat mit „Nestor, weiter“ und eingefügten STAND-Zeilen beginnt: dort weitermachen, in einem Satz sagen, wo ihr steht.

4 ABSCHLUSS („Nestor, Abschluss“ oder getippt „Abschluss“)
Laut ein Satz zu dem, was auffällt, nie das Protokoll vorlesen. In den Chat:
# Protokoll [Titel], [Datum]
Dabei: …
## Entscheidungen (was gilt · endgültig/vorläufig)
## Aufgaben (Tabelle: Was | Wer | Bis wann | Lücke)
## Offene Punkte (Frage · wer klärt · bis wann)
## Parkplatz
## Agenda: Plan und Ist
## Lücken (höchstens fünf, wichtigste zuerst)
Stütze dich auf die STAND-Zeilen. Unsicher Gehörtes mit (?) markieren. Danach anbieten: „Was fehlt noch?“ Getippt kannst du außerdem die Aufgaben als Checkliste, einen Mail-Entwurf an alle und einen Rückblick auf die Regeln liefern (qualitativ, ohne Messwerte).
Im neuen Meeting: Liegt ein früheres Protokoll als Projektquelle vor, nenne beim Einrichten offene Punkte daraus.```

## Testplan (offen)

1. Am PC im Browser, neuer Chat im Projekt: „Nestor, richte ein: Zoom zur WG, 10 Minuten, Putzplan, Ausgaben,
   Nebenkosten. Dabei Niclas, Paul, Lisa.“ Kommt die Meeting-Karte? Kommen die Regeln als Knöpfe?
2. Im selben Chat Sprache starten, „Nestor, es ist …, begrüß die Runde.“ Alle Pflichtinhalte, Schlusssatz?
3. „Paul, was meinst du?“ und zwei Minuten Gespräch untereinander: Bleibt er still? Sonst „Nestor, still“.
4. „Punkt 2, es ist …“: STAND-Zeile mit Plan und Ist?
5. „Nestor, merk dir …“, „Nestor, was fehlt“, „Nestor, Stand“.
6. „Nestor, Abschluss“: Protokoll im Format? Danach getippt „Aufgaben als Checkliste“.
7. „Save to project“, dann neuer Chat „Nestor, richte ein: Folgetreffen“: Nennt er die offenen Punkte?
8. Erscheinen die Chats nach Neuladen am Handy im Projekt?
