# Gesprächsregeln: was der Coach prüfen kann – und wie wir es testen

Stand 05.10.2026 · Entwurf zur Diskussion

## 1. Ausgangslage

Im Dashboard gibt es ein Freifeld „Gesprächsregeln“. Das suggeriert, der Coach könne jede eingetragene
Regel überwachen. Tatsächlich wertet er heute nur eine Regel aus, und auch die nur indirekt: Steht
„ausreden“ oder „unterbrechen“ im Text, wird der Hinweis bei Sprecherüberlappung um diese Regel ergänzt
(`gleichzeitig_regel` in `coach/pipeline.py`). Alles andere im Freifeld wird nur gespeichert.

Ziel dieses Papiers: die zehn typischen Meeting-Regeln festlegen und für jede einzeln klären, **was davon
beobachtbar ist, wie gut, mit welchem Verfahren und wie wir es nachweisen.**

Leitplanken:
- **Lastenheft:** „Keine vorschnelle Bewertung. Der MVP soll beobachtbare Phänomene erkennen, nicht Motive
  oder soziale Qualität bewerten.“ Ausdrücklich nicht: bewerten, ob jemand unhöflich unterbricht;
  Persönlichkeits- oder Kompetenzbewertung; automatische Bewertung unausgeglichener Redeanteile.
  Regeln wie „respektvoller Ton“ gehen über das MVP hinaus. Wir formulieren sie deshalb als
  beobachtbares Ereignis („ein Kraftausdruck ist gefallen“), nicht als Urteil („Person X ist respektlos“).
- **Nur vereinbarte Regeln:** Der Coach prüft nur, was die Gruppe zu Beginn ausgewählt hat. Der Mensch entscheidet.
- **Einsatz in einer Firma:** Ein System, das Verhalten einzelner Beschäftigter auswertet, ist
  mitbestimmungspflichtig (§ 87 Abs. 1 Nr. 6 BetrVG) und datenschutzrelevant. Personenbezogene
  Regelauswertungen – wer unterbricht wen, wer flucht – deshalb nur für die Moderation, nicht
  gespeichert und nicht in der Gruppenansicht. Vor dem Einsatz mit Betriebsrat und Datenschutz klären.

## 2. Die zehn Regeln im Überblick

Zusammengestellt aus drei fachlichen Quellen, ergänzt um gängige Praxis-Kataloge (Quellen am Ende):

- **TZI-Hilfsregeln (Ruth Cohn)**, der deutsche Moderationsklassiker: „Nur einer zur gleichen Zeit“,
  „Vertritt dich selbst – sprich per Ich“, „Seitengespräche haben Vorrang“. Achtung: TZI verbietet
  Seitengespräche nicht, sondern holt sie in die Runde, weil sie meist etwas Wichtiges anzeigen.
  Der Coach-Hinweis bei Regel 2 sollte deshalb einladen, nicht ermahnen.
- **Roger Schwarz, „The Skilled Facilitator“**: das Standardwerk zu Ground Rules für Gruppen. Schwerpunkt
  sind Begründen, Interessen statt Positionen und gemeinsame Entscheidungen, also eher Regel 8–10.
- **Meeting-Forschung, Kauffeld & Lehmann-Willenbrock (2012)**: 92 Teammeetings auf Video, kodiert mit
  dem Kategoriensystem **act4teams**. Funktionales Verhalten wie Lösungsorientierung und
  Maßnahmenplanung hängt mit Meeting-Zufriedenheit und Teamproduktivität zusammen, „Jammerspiralen“
  sogar mit schlechterem Unternehmenserfolg Jahre später. act4teams kodiert auch dysfunktionale
  Äußerungen wie Abwerten und Jammern. Ob Unterbrechen und Seitengespräche eigene Codes sind, ist noch
  im Original zu prüfen (Cambridge Handbook of Group Interaction Analysis). Für unsere Tests ist
  act4teams als fertiges, erprobtes Label-Schema für Text-Testsets interessant (Regel 7–10).
- Formale Sitzungsordnungen (Gemeindeordnung, Geschäftsordnung des Bundestages) regeln Worterteilung
  und Ordnungsrufe. Das ist die Grundlage für die Stadtrat- und Bundestags-Proben.

Signalquellen: **A** = Akustik/Stimmen (lokal: wer spricht, Überlappung, Pegel) · **T** = Live-Text ·
**K** = Sprachmodell (Bedeutung im Kontext) · **U** = Uhr und Agenda.

| # | Regel | Was ist beobachtbar | Quellen | Prüfbarkeit | Stand im Coach |
|---|---|---|---|---|---|
| 1 | Ausreden lassen | Übernahme des Worts, während jemand mitten im Satz ist | A + T | ●●○ mittel | nur Überlappung als technisches Signal |
| 2 | Eine Person spricht – keine Seitengespräche | Parallel laufende, meist leisere zweite Unterhaltung | A | ●○○ schwach | Überlappung (kurz) |
| 3 | Beim Thema bleiben | Inhalt passt nicht zum aktuellen Agendapunkt | T + K | ●●○ mittel bis gut | Fokus-Ampel |
| 4 | Zeit einhalten | Zeitbudget je Punkt, Beginn und Ende | U | ●●● gut | Countdown, Agenda-&-Zeit-Ampel |
| 5 | Sich kurz fassen – keine Monologe | Zusammenhängende Redezeit einer Person | A | ●●● gut | Monolog-Ampel (≥ 60 s) |
| 6 | Alle kommen zu Wort – niemand dominiert | Redeanteile, wer lange still ist | A (+ Teilnehmerzahl) | ●●○ mittel bis gut | Redeanteile ohne Bewertung |
| 7 | Respektvoller Ton – keine Beleidigungen, keine Kraftausdrücke | Kraftausdrücke, persönliche Angriffe | T + K | ●●○ Kraftausdrücke gut, Angriffe mittel | – |
| 8 | Sachlich bleiben – Ich-Botschaften, keine Killerphrasen | Killerphrasen, Pauschalisierungen, Du-Vorwürfe | T + K | ●○○ schwach (Auslegungssache) | – |
| 9 | Zuhören und aufeinander eingehen | Wiederholte Argumente, Beiträge ohne Bezug | T + K | ●○○ schwach | – |
| 10 | Ergebnisse festhalten – wer macht was bis wann | Entscheidungen und Aufgaben, fehlende Verantwortliche/Termine | T + K | ●●○ mittel bis gut | teilweise im Live-Bild |

**Nicht prüfbar** mit Mikrofon und Transkript, obwohl in vielen Katalogen enthalten: Handys und Laptops
weglegen, Vertraulichkeit, vorbereitet erscheinen, andere Meinungen respektieren (eine Haltung, kein
Ereignis), pünktliches Erscheinen einzelner Personen. Solche Regeln kann der Coach nur anzeigen
(„Erinnerung“), nicht prüfen.

## 3. Die Regeln im Einzelnen

### Regel 1 – Ausreden lassen

**Arbeitsdefinition „Unterbrechung“:** Person B beginnt zu sprechen, während A spricht (Überlappung oder
Wechsel ohne Pause), **und** A bricht mitten im Satz ab, **und** B behält danach das Wort (≥ 3 s).
Keine Unterbrechung sind:
- Rückmeldesignale wie „ja“, „genau“, „mhm“: kurz, und A redet weiter
- reguläre Übergaben: A hat den Satz beendet
- gemeinsames Lachen

**Verfahren:**
1. Aus der Sprecherspur (Fenster je 0,75 s) Wechsel A → B finden, mit Überlappung oder Pause < 0,3 s.
2. Prüfen, ob A innerhalb von 2 s verstummt und B danach mindestens 3 s spricht.
3. Klären, ob A mitten im Satz war. Erste Stufe: Satzzeichen im Live-Text an der Wechselstelle. Zweite
   Stufe: Sprachmodell („Ist dieser Satz abgebrochen?“).

**Knackpunkt:** Der Live-Text kommt je Äußerung, nicht je Sprecher. Bei einem Wechsel ohne Pause wissen
wir nicht, welche Wörter noch zu A gehören. Lösungen sind Wortzeitstempel (eine zweite Texterkennung
je Sprecherabschnitt kostet zusätzlich) oder eine reine Akustik-Variante ohne Satzprüfung, die dafür
mehr Fehlalarme hat.

**Hinweis:**
- An die Gruppe, gesammelt und ohne Namen: „In den letzten 5 Minuten wurde oft ins Wort gefallen.
  Vereinbart war: Ausreden lassen.“
- Wer wen unterbricht, sieht höchstens die Moderation.

**Test:**
- **Kontrastpaar:** Talkshow `untervier` (wild) gegen `stadtrat` und `zoom_inca4d` (geordnet).
  Erwartung: Talkshow deutlich über 5 Unterbrechungen je 10 min, geordnete Proben unter 1.
- **Wahrheit:** Die Unterbrechungen der Talkshow (12 min) muss eine Person beim Anhören markieren,
  etwa 20 Minuten Arbeit. Ein kleines Markier-Werkzeug im Abspielmodus baue ich dafür: Taste drücken,
  wenn jemand unterbrochen wird. Zusätzlich die Bundestags-Plenarprotokolle: Zwischenrufe sind dort
  mit Wortlaut protokolliert und als Open Data verfügbar.
- **Messgrößen:** Trefferquote, Fehlalarme je 10 min in geordneten Proben, Verzug.
- **Ziel:** ≥ 70 % der markierten Unterbrechungen erkannt, ≤ 1 Fehlalarm je 10 min geordnet.

### Regel 2 – Keine Seitengespräche

**Arbeitsdefinition:** Mindestens 5 s lang laufen zwei Stimmen parallel. Eine davon ist deutlich
leiser (über 10 dB unter der Hauptstimme) und gehört nicht zum Hauptstrang.

**Verfahren:** Lokal über die vorhandene Stimmen-Mischung, die über mehrere Sekunden anhalten muss, plus
Pegelunterschied. Der Live-Text hilft kaum, weil die Texterkennung leise Nebenstimmen meist weglässt.

**Grenzen:** Ein gutes Konferenzmikrofon blendet leise Nebengespräche bewusst aus. Was das Mikro nicht
hört, kann der Coach nicht melden. Die Erkennung bleibt deshalb unsicher und hängt vom Raum ab.

**Test:**
- **Synthetisch mit exakter Wahrheit:** In `zoom_inca4d` und `stadtrat` mischen wir Gesprächsstücke
  aus `untervier` an bekannten Stellen leise ein, bei −10, −15 und −20 dB. Gemessen wird die
  Erkennungsrate je Lautstärke und die Fehlalarme in den unveränderten Proben.
- Danach Raumtest mit gespieltem Nebengespräch.

### Regel 3 – Beim Thema bleiben

**Vorhanden:** Fokus-Ampel. Die Themen-Zuordnung (GPT-5.4-mini) erkennt einen Abschnitt, der zu keinem
Agendapunkt passt, nach ≥ 20 s.

**Bekannte Schwächen:**
- Ein kurzes Fremdthema, das ohne Pause zwischen Agenda-Rede liegt, wird unzuverlässig erkannt
  (in einem von drei Läufen).
- Ein Ortsname aus einem späteren TOP löste einen falschen Sprung aus.

**Test:**
- **Neue abgeleitete Proben:** 5 eingeschnittene Fremdthemen in `stadtrat`, unterschiedlich lang
  (20, 40 und 90 s) und unterschiedlich fremd (ganz fremd: Talkshow; nah: anderes kommunales Thema).
- **Messgrößen:** Trefferquote, Verzug, Fehlalarme in der unveränderten Probe, Agenda-Wechsel gegen die
  Kapitelmarken (Referenz liegt in `stadtrat/probe.json`).
- **Ziel:** ≥ 4 von 5 Fremdthemen ab 40 s erkannt, kein Fehlalarm in `stadtrat`.

### Regel 4 – Zeit einhalten

**Vorhanden:** Countdown je Punkt und die Ampel Agenda & Zeit.

**Neu und einfach:**
- Geplante Anfangszeit in der Einrichtung, damit der Coach sieht, wann das Meeting wirklich beginnt.
- Prognose für das Ende („bei diesem Tempo rund 15 min über der Zeit“).

**Test:**
- Deterministisch, als Unit-Tests.
- Zusätzlich gegen die Agenda-Referenz `stadtrat`: geplante Minuten gegenüber den tatsächlichen
  Zeiten aus den Kapitelmarken.

### Regel 5 – Sich kurz fassen, keine Monologe

**Vorhanden:** Monolog-Ampel ab 60 s zusammenhängender Rede. Sie ist erst verlässlich, seit die
Sprechertrennung funktioniert (CAM++, 05.10.).

**Test, vollautomatisch aus der Bibliothek:**
- Aus der Sprecher-Referenz alle zusammenhängenden Redeabschnitte ≥ 60 s bestimmen, z. B. im Stadtrat
  den Kandidaten ab 1:16 mit 124 s und in der Talkshow ab 1:02 mit rund 90 s.
- Mit den Hinweisen des Coaches vergleichen.
- **Messgrößen:** Treffer, Fehlalarme, Verzug.
- **Ziel:** alle Monologe ≥ 75 s erkannt, kein Fehlalarm unter 45 s.

### Regel 6 – Alle kommen zu Wort, niemand dominiert

**Beobachtbar:**
- Redeanteile (vorhanden).
- Wie lange jemand schon still ist.
- Wie viele angemeldete Personen noch keine erkannte Stimme haben. Dafür braucht der Coach die
  Teilnehmerzahl aus der Einrichtung: „5 angemeldet, 3 Stimmen erkannt“.

**Hinweis ohne Bewertung:**
- „2 von 5 Teilnehmenden haben noch nicht gesprochen.“
- „Eine Person hatte in den letzten 10 Minuten mehr als die Hälfte der Redezeit.“

Das Lastenheft schließt eine Bewertung aus. Deshalb nur als Beobachtung und nur, wenn die Gruppe die
Regel gewählt hat.

**Test:**
- Redeanteile gegen die Sprecher-Referenz, das geht schon heute mit `bench_sprecher.py`.
- „Stille Person“: eine 4-Personen-Probe mit 5 angemeldeten Teilnehmenden einrichten. Erwartung:
  Hinweis nach der eingestellten Zeit.
- Dominanz: Stadtrat (OB etwa 60 %) gegen Talkshow (verteilt).

### Regel 7 – Respektvoller Ton: keine Beleidigungen, keine Kraftausdrücke

Hier gibt es zwei Teile.

**Kraftausdrücke:** Ein deutsches Wortverzeichnis in Stufen (derb bis beleidigend) gleicht den Live-Text
ab. Danach prüft das Sprachmodell den Zusammenhang: Ist es ein Zitat („er sagte: …“), ein Fachbegriff
oder Teil eines Eigennamens?

**Persönliche Angriffe:** Das Sprachmodell beurteilt jeden Satz mit seinem Kontext. Ist das harte Kritik
an der Sache („Das ist Quatsch“) oder eine Herabsetzung der Person („Sie haben doch keine Ahnung“)?

**Knackpunkte:**
1. Ob die Texterkennung Schimpfwörter wörtlich schreibt oder glättet, ist ungeprüft.
2. Die Grenze zwischen deutlicher Sachkritik und Angriff ist unscharf. Die Talkshow (Beispiel:
   „ärgerlicher Quatsch“) ist der natürliche Grenzfall.

**Hinweis:** nur an die Moderation, ohne Wertung: „Eine Äußerung könnte als persönlicher Angriff
ankommen (2:14).“ In der Gruppenansicht höchstens ohne Namen.

**Test in vier Stufen:**
1. **Text-Testset** (ohne Audio, kostet fast nichts): 150–200 gelabelte Sätze mit Kraftausdrücken,
   Angriffen, harter Sachkritik, Zitaten und Ironie. Wir erzeugen sie und prüfen sie zu zweit.
   Messgrößen: Genauigkeit und Trefferquote des Klassifikators.
2. **Sprachausgabe → Texterkennung:** dieselben Sätze mit mehreren synthetischen Stimmen sprechen
   lassen und prüfen, ob die Schimpfwörter im Transkript ankommen. Das beantwortet Knackpunkt 1.
3. **Echte Fälle:** Bundestagsdebatten mit Ordnungsruf. Diese stehen im Plenarprotokoll (Open Data,
   XML), dazu der Videoausschnitt als neue Probe.
4. **Negativkontrolle:** `stadtrat` (kein Treffer erwartet), `untervier` (harte Sachkritik, möglichst
   kein Angriffs-Hinweis).

### Regel 8 – Sachlich bleiben: Ich-Botschaften, keine Killerphrasen

**Ehrliche Einschätzung:** Ob jemand Ich-Botschaften verwendet, ist eine Stilfrage mit viel
Auslegungsspielraum. Ein Hinweis darauf wirkt schnell belehrend.

**Konkret erkennbar sind nur:**
- **Killerphrasen:** „Das haben wir schon immer so gemacht“, „Das klappt eh nicht“, „Dafür ist kein Geld da“.
- **Pauschalisierungen:** „immer“, „nie“, „alle“ als Vorwurf.

Das ginge über ein Sprachmodell mit einer kurzen Liste von Mustern.

**Vorschlag:** nur experimentell und nur für die Moderation. Erst messen, dann entscheiden.

**Test:**
- Text-Testset wie bei Regel 7. Zwei Personen labeln es unabhängig. Das Modell muss mindestens so gut
  übereinstimmen wie die beiden untereinander, sonst taugt die Regel nicht.
- Kontrast: Talkshow gegen Stadtrat.

### Regel 9 – Zuhören und aufeinander eingehen

**Beobachtbar ist nur ein Ausschnitt:**
- Dasselbe Argument kommt zum dritten Mal.
- Mehrere Beiträge hintereinander nehmen keinen Bezug aufeinander.

Beides geht über das Sprachmodell im Kontext-Strom.

**Vorschlag:** keine Ampel. Besser im Live-Bild sichtbar machen („Argument X dreimal genannt“).

**Test:**
- Transkripte mit eingesetzten Wiederholungen. Wahrheit bekannt, ohne Audio.
- Talkshow als echter Fall.

### Regel 10 – Ergebnisse festhalten: wer macht was bis wann

**Verfahren:**
- Das Sprachmodell zieht je Agendapunkt Entscheidungen und Aufgaben aus dem Transkript. Die
  Strukturanalyse des Live-Bilds macht das schon in Teilen.
- Beim Wechsel zum nächsten Punkt prüft der Coach: Wurde ein Ergebnis festgehalten? Hat jede Aufgabe
  eine verantwortliche Person und einen Termin?
- Hinweis: „TOP 3 abgeschlossen – kein Ergebnis festgehalten“ oder „Aufgabe ohne Verantwortliche/n“.

**Test:**
- `stadtrat` enthält 6 Abstimmungen mit bekanntem Ergebnis (einstimmig, mehrheitlich mit 1 Enthaltung …).
  Gemessen wird, wie viele davon mit richtigem Ergebnis gefunden werden.
- Für Aufgaben fehlt noch eine Probe. Ein Rollenspiel mit Drehbuch liefert sie, siehe 5.

## 4. Konsequenz für das Dashboard

Das Freifeld wird zu einer **Auswahl der zehn Regeln**. Neben jeder Regel steht, was der Coach leisten kann:

| Stufe | Bedeutung | Regeln |
|---|---|---|
| **wird geprüft** | belastbar, Ampel oder Hinweis | 4 Zeit, 5 Monologe, 6 Redeanteile/Stille, 3 Thema |
| **Hinweis möglich, kann irren** | Hinweis mit Vorsicht formuliert | 1 Ausreden lassen, 7 Ton, 10 Ergebnisse |
| **experimentell** | nur Moderation, abschaltbar | 2 Seitengespräche, 8 Sachlichkeit, 9 Eingehen |
| **Erinnerung** | wird angezeigt, nicht geprüft | eigene Regeln, Handys, Vertraulichkeit … |

Eigene Regeln bleiben möglich, landen aber sichtbar unter „Erinnerung – wird nicht geprüft“.
Die Einstufung ändert sich nur durch Messung (Abschnitt 5), nicht nach Gefühl.

## 5. Testprogramm

Testarten nach Aufwand:

| Testart | Wahrheit | Kosten | für Regeln |
|---|---|---|---|
| Kontrastpaar natürlicher Aufnahmen (geordnet gegen wild) | grob (Richtung muss stimmen) | gering | 1, 6, 7, 8 |
| Synthetische Mischung (Einschnitt, Einmischen in bekannter Lautstärke) | exakt | gering | 2, 3 |
| Text-Testsets (gelabelte Sätze, ohne Audio) | exakt, aber Labels sind Auslegung | sehr gering | 7, 8, 9, 10 |
| Sprachausgabe → Texterkennung | exakt | gering (Cent-Bereich) | 7 (kommt das Wort an?) |
| Dokumentierte Quellen (Bundestag: Zwischenrufe, Ordnungsrufe; Stadtrat: Kapitel, Beschlüsse) | gut | mittel (Abgleich Protokoll ↔ Video) | 1, 7, 10 |
| Von Hand markieren (Markier-Werkzeug im Abspielmodus) | gut | ~20 min je 12 min Aufnahme | 1, 2 |
| **Rollenspiel mit Drehbuch** im echten Raum, 5 Personen, geplante Regelverstöße zu bekannten Zeiten | exakt und realistisch | 1 Termin, ~30 min | alle; zugleich Raumtest für die Sprechertrennung |

Das Rollenspiel ist der wichtigste Test: Er ist zugleich der ausstehende Raumtest. Das Drehbuch schreibe
ich, sobald wir die Regelauswahl festgelegt haben. Es enthält alle zehn Regeln mit je 1–3 Verstößen und
Kontrollphasen ohne Verstoß.

## 6. Messstand 05.10.2026

Umgesetzt: Regelkatalog (`coach/regeln.py`), Auswahl mit Prüfstufen statt Freifeld, Karte „Vereinbarte
Regeln“ im Dashboard. Hinweise nennen die gewählte Regel („Vereinbart war: …“). Umgesetzt sind die Regeln
1 (nur Überlappung), 3, 4, 5, 6, 7 und 10; 2, 8 und 9 sind sichtbar mit „folgt“ markiert.

| Regel | Messung | Ergebnis |
|---|---|---|
| 3 Thema | `scripts/bench_fokus.py`: 3 Talkshow-Einschübe (26 / 63 / 79 s) an Satzgrenzen im Stadtrat-Transkript, dazu ein Kontrolllauf | **3/3 erkannt nach 26–28 s, 0 Fehlalarme**; ~5 Cent |
| 3 Agenda-Wechsel | gleicher Lauf, gegen Kapitelmarken; ausdrückliche Überleitungen („Tagesordnungspunkt 6“, „kommen wir zu …“) lösen die Zuordnung sofort aus | alle Wechsel **21–51 s** nach dem echten Wechsel, keiner übersprungen; falscher Vorschlag TOP 8 bleibt (Wortmeldung in TOP 7 behandelt tatsächlich den Scheibe-See) |
| 5 Monologe | `scripts/bench_regeln.py`, Monologe ≥ 60 s aus der Sprecher-Referenz | nach Korrektur (siehe unten): Stadtrat 3/3, Talkshow 2/2, Zoom 4/4, **0 Fehlalarme**; Verzug meist 5–30 s, max. 64 s bei 55 s Rede ohne jede Pause |
| 6 Redeanteile | gleicher Lauf | größte Abweichung zur Referenz **≤ 1 Prozentpunkt** in allen drei Proben |
| 6 stille Person | gleicher Lauf, eine angemeldete Person spricht nie | in allen drei Proben nach 10 min gemeldet, Anzahl zum Zeitpunkt korrekt |
| 7 Ton, Text | `scripts/bench_ton.py`, 100 Sätze (`testbibliothek/texte/ton.json`), davon 17 Grenzfälle | eindeutige Sätze: **31/32 erkannt, 2/51 Fehlalarme**; neutral 0/26, Sachkritik 1/18, Zitate 1/7 (Mozart-Liedtitel); unter 1 Cent je Lauf |
| 7 Ton, Ende zu Ende | `scripts/tts_probe.py`: 14 Sätze mit 4 synthetischen Stimmen durch die komplette Live-Pipeline | Live-Texterkennung schreibt Kraftausdrücke **wörtlich** („Scheiße“, „Bullshit“, „im Arsch“; nur „Vollpfosten“ → „Pfeilpfosten“); **8/8 erkannt, Zitat und Kontrollsätze ohne Hinweis** |
| 10 Ergebnisse | `scripts/bench_ergebnisse.py`, Stadtrat je TOP | **4/5 Beschlüsse mit richtigem Ergebnis** (auch „mehrheitlich, 1 Enthaltung“); TOP 6 verpasst (Äußerung mischt Abstimmung TOP 6 und Einleitung TOP 7); TOP 1 und 7 richtig „kein Ergebnis“ |
| 1 Ausreden lassen (umgesetzt, `coach/unterbrechung.py`, Bericht `docs/messung_unterbrechung.md`) | Wechsel ohne Pause, neue Person behält das Wort ≥ 3 s, kein Pegel-Einbruch | Talkshow 13,3 je 10 min, geordnete Proben 0–0,8; Hinweis ab 3 Stellen in 5 min (Talkshow: 3 Hinweise in 12 min, Stadtrat: keiner) |
| 1 Ausreden lassen (Ausgangswert) | `bundestag_ordnungsrufe`: Stimmen-Mischung gegen 31 protokollierte Zwischenrufe | nur **12/31** Zwischenrufe mit Mischung, dazu 70 Mischungen ohne Zwischenruf – als Unterbrechungs-Erkennung so nicht brauchbar |

Korrekturen aus der Messung:
- **Monolog-Fehlalarme:** Ursache war die Hochrechnung über die letzte bekannte Äußerung hinaus. Wechselte
  währenddessen die Person, bekam die vorige Person deren Redezeit. Hochrechnung abgeschaltet,
  Äußerungen auf höchstens 10 s begrenzt (Sprecher dadurch früher bekannt; Sprechertrennung 94–95 %
  statt 95–96 %), Wartezeit zwischen Monolog-Hinweisen je Person statt für alle.
- **Ton-Hinweise:** gleiche Art höchstens alle 90 s, jede Stelle wird aber gezählt („3. Stelle in den
  letzten 5 Minuten“) und protokolliert.
- **Agenda-Wechsel:** nicht weiter optimiert. Ein Verzug von 20–60 s ist ausreichend, weil der
  ausdrückliche Wechsel später per Ansprache an den Coach kommt (Ausbaustufe 2).
- **Fokus live:** Ein Fremdthema ohne Pause landet im selben Textstück wie Agenda-Rede und wird dann
  seltener erkannt; auf Satzebene (Test) klappt es. Kürzere Stücke (10 s) helfen etwas. Nicht weiter
  verfolgt, solange 20–60 s Verzug genügen.

Neues Testmaterial (`testbibliothek/`): Bundestag-Zusammenschnitt mit protokollierten Zwischenrufen
(Wahrheit für Regel 1 und 7), Stadtrat Ahaus (anderer Ratssaal), Bürgerversammlung Freital (hitzig, im
Saal), synthetische Ton-Probe. Untertitel als kostenloses Grob-Transkript.

Kosten 05.10.2026 für alle Messungen zusammen: ~134 000 Eingabe- und ~26 000 Ausgabe-Tokens
GPT-5.4-mini, 2,6 min Live-Text, 1 min Sprachausgabe, 24 min Diarisierung (Referenz) – grob 0,40–0,60 $.

## 7. Vorschlag zur Reihenfolge

1. **Sofort, ohne neue Daten:** Tests für Regel 4, 5 und 6 automatisch über die Bibliothek; abgeleitete
   Proben für Regel 3; Dashboard-Auswahl mit Prüfstufen statt Freifeld.
2. **Danach:** Regel 7 mit Text-Testset und Sprachausgabe-Test, Regel 10 auf `stadtrat`.
3. **Mit Markier-Werkzeug und Bundestags-Probe:** Regel 1 (Unterbrechungen). Sie ist der größte
   Brocken und braucht die Satzprüfung an der Wechselstelle.
4. **Rollenspiel/Raumtest:** alle Regeln, besonders 2.
5. **Experimentell, je nach Messung:** Regel 8 und 9.

## Quellen

Fachlich:
- Ruth C. Cohn: Von der Psychoanalyse zur themenzentrierten Interaktion (Klett-Cotta), Hilfsregeln der TZI;
  Zusammenfassung z. B. [Gesprächshilfe nach der TZI (selbsthilfenetz.de, PDF)](https://www.selbsthilfenetz.de/fileadmin/EigeneDateien/Download/04-infos-fuer-selbsthilfeaktive/gespraechshilfe-nach-der-themenzentrierten-aktion.pdf)
- Roger Schwarz: The Skilled Facilitator (Jossey-Bass), Ground Rules for Effective Groups
- S. Kauffeld, N. Lehmann-Willenbrock (2012): Meetings matter: Effects of team meetings on team and
  organizational success. Small Group Research 43(2) – [Kurzbeschreibung](https://www.mangold-international.com/research/publications/human-behavior/meetings-matter-effects-of-work-group-communication-on-organizational-success)
- act4teams-Kodiersystem: [Cambridge Handbook of Group Interaction Analysis](https://resolve.cambridge.org/core/books/cambridge-handbook-of-group-interaction-analysis/advanced-interaction-analysis-for-teams-act4teams-coding-scheme/1930BA23CB78C1881DD6EAC30CC4FB5B);
  Hintergrund: [Interview Lehmann-Willenbrock, Uni Hamburg](https://www.psy.uni-hamburg.de/en/arbeitsbereiche/arbeits-und-organisationspsychologie/aktuelles/was-sagt-wissenschaft-zu-meetings.html)

Praxis-Kataloge:
- [karrierebibel.de – Gesprächsregeln](https://karrierebibel.de/gespraechsregeln/)
- [Michigan State University Extension – Meeting guidelines and ground rules](https://www.canr.msu.edu/news/meeting_guidelines_and_ground_rules_are_basic_tools_for_successful_meetings)
- [pmstudycircle.com – Meeting Ground Rules: 8 Examples](https://pmstudycircle.com/meeting-ground-rules/)
- [ClickUp – Top 13 Meeting-Regeln](https://clickup.com/de/blog/263468/top-13-meeting-regeln-fuer-eine-bessere-kommunikation-im-team)
- [Deutscher Bundestag – Open Data (Plenarprotokolle als XML)](https://www.bundestag.de/services/opendata)
- Lastenheft „KI-gestützter Meeting-Assistent (MVP)“, Abschnitte Grundsätze und Nicht-Ziele
