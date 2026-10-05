# Spezifikation – Live Meeting Coach, Version 2 (Einsatz in echten Meetings)

**Stand:** 04.10.2026 · **Status:** Entwurf zur Abstimmung · **Grundlage:** Lastenheft „KI-gestützter
Meeting-Assistent (MVP)“ (isb Open Innovation, 02.10.2026), MVP-Prototyp in diesem Repo, Messungen vom 02.10.2026

Diese Spezifikation hebt den Hackathon-Prototyp auf ein Niveau, mit dem er in echten Meetings eingesetzt
werden kann. Sie übernimmt alle Anforderungen des Lastenhefts (FR-01 bis FR-09) und erweitert sie.
Erweiterungen über das Lastenheft hinaus sind mit **[neu]** markiert.

---

## 1. Ziel und Einsatzrahmen

**Ziel:** Ein sichtbarer KI-Co-Pilot, der Zeit, Fokus und Gesprächsfluss eines Meetings beobachtet,
Abweichungen dosiert anzeigt und laufend festhält, was besprochen und entschieden wurde.
Der Mensch entscheidet; die Anwendung zeigt nur Hinweise.

| Rahmen | Festlegung |
|---|---|
| Typisches Meeting | **5 Personen, Präsenz**, ein Raum |
| Betrieb | zunächst **auf dem Laptop** (lokaler Server + Browser) |
| Audio an Cloud-Anbieter | **erlaubt, auch US-Anbieter** |
| Namen der Sprecher | **nicht live nötig** – mit Verzug oder nach dem Meeting genügt |
| Kosten | **1–2 $ pro Meeting-Stunde**; mehr nur bei deutlichem Mehrwert |
| Sprache | Deutsch, mit englischen Fachbegriffen |

## 2. Lehren aus dem MVP (gemessen 02.10.2026)

1. **Die Sprechertrennung war der Engpass.** Text, Sprecher und Analyse liefen nacheinander; der Text
   wartete auf die Sprecherspur. Ergebnis: 10–25 s Verzug.
2. **`gpt-4o-transcribe-diarize` übersetzt deutsches Raumaudio ins Englische** – ohne Sprachvorgabe schon
   bei leichtem Rauschen, mit `language="de"` noch bei echtem Raumaudio. Prompts nimmt das Modell nicht an.
3. **Gleichzeitiges Sprechen** liefert bei diesem Modell keine überlappenden Zeitstempel, sondern ein
   schnelles Zickzack zwischen Sprechern.
4. **Bester Text:** `gpt-4o-transcribe` mit `language="de"` und Agenda als Prompt.
5. **Ohne Stimmprobe** vergibt die blockweise Diarisierung Buchstaben in jedem Block neu – Personen sind
   über Blockgrenzen nicht stabil.
6. **GPT-5 mit minimalem Denkaufwand** ordnet Themen in ~2 s statt ~10 s zu, gleiches Ergebnis.

## 2a. Benchmark 04.10.2026 – reine OpenAI-Pipeline mit lokalem Stimmabgleich

**Testmaterial:** 12 Minuten aus einem öffentlichen Zoom-Meeting auf Deutsch („InCa4D Innovative
Pflege“, Minute 14–26), 6 Personen, viele Sprecherwechsel. Referenz: Personen inhaltlich ermittelt
(Namen fallen im Gespräch). Rechner: Laptop, Ryzen 5 8640HS, nur CPU.

**Live-Text**

| Verfahren | erster Text | fertiger Satz | Qualität | Kosten/h |
|---|---|---|---|---|
| `gpt-live-transcribe` (Streaming, `delay=low`, Deutsch, Stichwörter) | 0,6 s nach Äußerungsbeginn | 0,7 s nach Äußerungsende | sehr gut; Eigennamen teils falsch („Briller“ statt Prilla) | ~1,02 $ |
| `gpt-4o-transcribe` je Äußerung (REST) | erst nach Äußerungsende | Median 1,1 s, max 4,1 s nach Ende | sehr gut, Namen eher richtig | ~0,36 $ |

Äußerungsgrenzen kommen aus der lokalen Pausenerkennung (Silero VAD, +0,5 s bis „Ende erkannt“).

**Wer spricht** (Anteil richtig zugeordneter Sprechzeit, Kennungen für 6 Personen)

| Verfahren | richtig | Kennungen | vermischt | Rechenzeit für 12 min |
|---|---|---|---|---|
| OpenAI `gpt-4o-transcribe-diarize`, ganzer Block | 81 % | 6 | 2 Kennungen mischen Personen | 284 s (Cloud) |
| Lokal voll (pyannote-Segmentierung + WeSpeaker) | 72 % | 6 | 2 | 408 s (CPU) – zu langsam |
| **Lokal live: Fingerabdruck je Äußerung (WeSpeaker), Schwelle 0,84** | **99 %** | 11, davon 8 nennenswert | **keine** | **0,3 s je Äußerung** |

- Ähnlichkeit gleiche Person Median 0,88, verschiedene Personen Median 0,60 – der Fingerabdruck trennt.
- Schwäche: Zu viele Kennungen (Moderation und eine Telefon-Stimme je zweimal). Automatisches
  Zusammenführen über die Ähnlichkeit verschmolz falsche Personen → Zusammenlegen per Klick oder über
  den Namensvorschlag aus dem Inhalt.
- **Einschränkung:** Zoom-Aufnahme – jede Person mit eigenem Mikrofon, kaum Überlappung. Im Präsenzraum
  mit einem Mikrofon für alle ist die Trennung schwerer; Überlappung wurde hier nicht geprüft.
  Ein Raumtest bleibt Pflicht.

**Folgerung:** Variante C (nur OpenAI + lokaler Stimmabgleich) ist die Startvariante:
Live-Text über `gpt-live-transcribe`, Sprecher lokal über Fingerabdruck je Äußerung, keine
OpenAI-Diarisierung im Live-Pfad. Geschätzte Kosten ~1,3 $/h (Live-Text 1,02 + Kontext; Live-Bild über Abo);
mit `gpt-4o-transcribe` je Äußerung statt Streaming ~1,0 $/h bei 1–4 s mehr Verzug.

## 2b. Testläufe 04.10.2026 – Version 2 als Ganzes

Zwei öffentliche Aufnahmen, je ~12 min, in Echtzeit durch die komplette Pipeline (Abspielmodus):
Stadtratssitzung Hoyerswerda (8 TOPs, Zeitmarken aus der Videobeschreibung als Referenz; bei 4:10 sind
40 s einer Talkshow als Fremdthema eingeschnitten) und die Talkshow „Unter Vier" (4 Personen).

| Baustein | Ergebnis |
|---|---|
| Live-Text | gut, Deutsch, in Echtzeit |
| Agenda-Abgleich | Wechsel erkannt, Verzug 3–90 s bei sehr kurzen TOPs; 1 falscher Sprung (Ortsname aus späterem TOP) |
| Fokus | Fremdthema verpasst – Modell nannte es „unklar" statt „neu" → Anweisung geschärft |
| Live-Bild | brauchbar bis gut: Beschlüsse mit Ergebnis, Kernaussage, Beziehungen, Status je Thema |
| **Wer spricht** | **(behoben 05.10., siehe 2c)** **versagte bei gemeinsamem Mikrofon**: Stadtrat komplett als eine Person; Talkshow ohne Pausen → Äußerungen bis 70 s mit mehreren Sprechern. Folge: Monolog, Redeanteile, Überlappung dort nicht verlässlich. Im Zoom-Test (ein Mikro je Person) lief es. |

## 2c. Wer spricht – Modellvergleich 05.10.2026

Referenz: Stadtrat inhaltlich ermittelt (Oberbürgermeister, Kandidat Beirat, Stadtrat mit Wortmeldung);
Talkshow aus der OpenAI-Diarisierung, die dort inhaltlich stimmig ist (4 Personen).

**Trennschärfe** (1,5-s-Fenster; AUC 0,5 = Raten, 1,0 = perfekt; EER = Fehlerrate am Gleichgewichtspunkt)

| Modell (sherpa-onnx) | Größe | Stadtrat AUC / EER | Talkshow AUC / EER | Rechenzeit je Fenster |
|---|---|---|---|---|
| WeSpeaker ResNet34 (bisher) | 27 MB | 0,55 / 47 % | 0,79 / 29 % | 25–42 ms |
| **CAM++ 3D-Speaker zh/en (neu)** | 28 MB | 0,84 / 20 % | **0,997 / 2,5 %** | 21–29 ms |
| ERes2NetV2 3D-Speaker | 71 MB | 0,84 / 22 % | 0,991 / 4,8 % | 112 ms |
| TitaNet small (NVIDIA) | 40 MB | **0,88 / 16 %** | 0,996 / 2,6 % | 16–19 ms |

**Live-Zuordnung** (online, wie im Coach)

| Verfahren | Stadtrat richtig / Personen | Talkshow richtig / Personen |
|---|---|---|
| WeSpeaker je Äußerung, Schwelle 0,84 (bisher) | 62 % / 1 statt 3 | Äußerungen mit mehreren Sprechern, nicht bewertbar |
| WeSpeaker je Fenster | 62–63 % | 60–68 % |
| CAM++ je Fenster, Schwelle 0,45, neue Person nach 3 Fenstern (Simulation) | 99 % / 3 | 95 % / 4 |
| TitaNet small je Fenster, Schwelle 0,40–0,45 | 99,5 % / 3 | 94,5 % / 4 |
| OpenAI `gpt-4o-transcribe-diarize` (ganzer Block, Vergleich) | versagt: Kandidat und Stadtrat bei „A“ (OB) | stimmig, 4 Personen |

- **Mit dem Live-Code über die Testbibliothek** (`scripts/bench_sprecher.py`, Sprechzeit in 0,25-s-Schritten):
  Schwelle 0,45 → Stadtrat 95 % / 3, Talkshow 96 % / 4, **Zoom 89 % / 5 statt 6** (zwei Personen
  verschmolzen); **Schwelle 0,50 (gewählt) → 95 % / 3, 96 % / 4, 96 % / 6**; 0,60 → Talkshow bekommt
  eine Person zu viel.
- Gesamte Pipeline mit CAM++ (Abspielmodus, Schwelle 0,45): Redeanteile Talkshow 124 / 119 / 366 / 103 s gegenüber
  Referenz 121 / 118 / 360 / 98 s; Stadtrat 423 / 138 / 116 s gegenüber ~420 / 135 / 120 s.
- Gewählt: CAM++ mit Schwelle 0,50 – mehrsprachig trainiert, klein, schnell.
  TitaNet ist gleichwertig und bleibt Ausweichmodell.
- Überlappung (Mischung zweier Stimmen) auf CAM++-Skala neu eingestellt (0,45 / 0,25): in Passagen
  ohne Überlappung ~0,3 % Fehlalarme je Fenster; Trefferquote bei echter Überlappung noch ungeprüft.
- **Einschränkung:** Schwelle an denselben drei Aufnahmen ermittelt – neue Proben in die Testbibliothek
  (`testbibliothek/`) aufnehmen und nachmessen.

**Offen:** Raumtest mit eigenem Konferenzmikro (Pflicht); Überlappung mit echten Daten prüfen;
pyannoteAI nur noch, falls der Raumtest scheitert.

## 3. Funktionale Anforderungen

### 3.1 Aus dem Lastenheft (unverändert gültig)

| ID | Anforderung | Kurzfassung |
|---|---|---|
| FR-01 | Meeting initialisieren | Titel, Ziel, Agenda, Zeitbudget je Punkt; optional Teilnehmende, Rollen, Regeln, Lernziele |
| FR-02 | Aktuellen Agendapunkt führen | manuell, per bestätigtem Vorschlag oder simuliert; neuer Countdown nach Wechsel |
| FR-03 | Monolog erkennen | Gelb ab 60 s zusammenhängender Rede, Grün nach Sprecherwechsel |
| FR-04 | Agenda- und Zeitdisziplin | Gelb bei Ablauf des Zeitbudgets, Rot optional (konfigurierbar) |
| FR-05 | Fokusverlust erkennen | Gelb nach ~20 s themenfremd; passt es zu einem anderen Punkt, wird dieser genannt |
| FR-06 | Sprecherüberlappung | Gelb, wenn mehrere gleichzeitig sprechen – technisches Signal, keine Bewertung |
| FR-07 | Redeanteile | Anteil je erkannter Person, ohne Bewertung |
| FR-08 | Ampeln setzen sich zurück | sobald die Ursache endet |
| FR-09 | Konfigurierbare Schwellwerte | zentral, ohne Codeänderung |

### 3.2 Erweiterungen

**FR-10 Live-Bild als One-Pager [neu, überarbeitet 04.10.2026]**
Das System zeichnet während des Meetings ein **Bild, das den Stand auf einen Blick zeigt** – kein
Protokoll, sondern ein One-Pager wie aus dem Teachbuddy-Grafikvergleich: Kernaussage, Themen mit Status,
Beziehungen zwischen den Themen, Farben mit Bedeutung, Icons, kleine Grafiken (Zeitstrahl, Fortschritt).

- **Inhalt:** Kernaussage zum Stand; Themen mit Status (besprochen / entschieden / offen / strittig);
  Entscheidungen mit Ergebnis; offene Fragen und Aufgaben; Beziehungen; Abschweifungen als eigener,
  grau abgesetzter Bereich „außerhalb der Agenda".
- **Aktualisierung:** **auf Knopfdruck**, automatisch **alle 10 Minuten** (konfigurierbar) und am Ende.
- **Darstellung:** groß in der Mitte des Dashboards; auch in der Gruppenansicht für den Beamer.
- **Verfahren (aus Teachbuddy, E-19a):** erst **Strukturanalyse** (Kernaussage, Themen mit festen
  Kennungen, Entscheidungen, Offenes, Beziehungen, Abschweifungen), dann **Zeichnen** in einem festen
  **Grundraster** (Kopf, Agenda-Leiste, Themenkarte mit festen Plätzen, Entschieden/Offen, Fußleiste).
- **Fortschreibung [05.10.2026]:** Ab dem zweiten Bild bekommt Claude die letzte Analyse und das letzte
  SVG und schreibt sie fort: bestehende Themen bleiben an ihrem Platz, Neues kommt dazu und trägt ein
  Etikett „neu“, die Fußleiste nennt, was sich seit dem letzten Bild geändert hat. Vorher wurde jedes
  Bild neu entworfen und sah dadurch jedes Mal anders aus.
- **Technik:** Claude über das Abo (`claude -p`, Analyse Opus, Zeichnen Sonnet, Denkaufwand jeweils
  niedrig; ohne Einstellungen, Hooks, MCP und Werkzeuge des Zielrechners), Ergebnis ein
  geschlossenes SVG 1600 × 1000; der Server entschärft es (keine Skripte, nichts Externes) und liefert
  es als Bild aus. Läuft per SSH auf dem Pi, wo das Abo angemeldet ist (`LMC_CLAUDE_BEFEHL`).
- **Mensch entscheidet:** Inhalte sind „erkannt", nicht bestätigt. Korrigieren im Bild ist noch offen.
- **Export:** PNG und die Strukturanalyse als Markdown.
- **Gemessen 04.10.2026:** 4–5 min je Bild (Analyse + Zeichnen), keine API-Kosten, Abo-Kontingent.
- **Umstellung 05.10.2026 auf OpenAI (Standard):** GPT-5.4 liest Agenda und Transkript und ruft den
  Bildgenerator (gpt-image-2, 1536×1024, Qualität medium) selbst auf, wie ChatGPT. Ab dem zweiten Bild
  bekommt es das letzte Bild als Vorlage (Bearbeiten statt Neuzeichnen). Experiment
  `scripts/bild_gpt_experiment.py` und `scripts/bild_gpt_fortschreiben.py`: deutlich saubereres Layout als
  die SVGs (keine Pfeile im Text), korrektes Deutsch; die Fortschreibung behält Layout, Icons und
  Positionen und markiert Neues. ~55 s und ~7–8 Cent je Bild. Varianten über unsere Strukturanalyse:
  medium ~5 ct und 42 s, high ~17 ct und 91 s, beide mit Analyse-Artefakten im Bild. Claude-SVG bleibt als
  kostenlose Alternative.
- **Gemessen 05.10.2026 (Stadtrat, 10:00 und 12:40):** alt 214 s (Analyse 75 s, Zeichnen 135 s – davon
  ~75 % Nachdenken des Zeichenmodells); neu mit Grundraster und niedrigem Denkaufwand 86–106 s
  (Analyse 20–25 s, Zeichnen 60–75 s). Ohne die Hooks des Pi sinkt der Grundkontext je Aufruf von ~34 000
  auf ~3 000 Tokens.
- **Akzeptanz:** Nach einem 20-minütigen Testmeeting zeigt das Bild jeden besprochenen Punkt, jede
  getroffene Entscheidung mit Ergebnis und eine erkennbare Kernaussage; Abschweifungen sind sichtbar.

> Hinweis: Das Lastenheft nennt „Zusammenfassung kompletter Meetings als Kernfunktion“ ausdrücklich als
> *nicht* Teil des MVP. FR-10 geht daher bewusst über das Lastenheft hinaus.

**FR-11 Live-Transkript [neu]**
Gesagtes erscheint **≤ 2 s** nach dem Sprechen als Text im Dashboard (Moderationsansicht), zunächst
vorläufig, dann als fertiger Satz. Sprecherzuordnung darf nachträglich ergänzt werden.

**FR-12 Sprecher mit Namen über Stimmprofil [neu]**
- Jede Person kann **einmalig** eine Stimmprobe einsprechen (~10–30 s); daraus entsteht ein
  **wiederverwendbares Stimmprofil**, das in späteren Meetings ohne neue Probe erkannt wird.
- Ohne Profil erscheinen Personen anonym (Person A, B, …) – **stabil über das ganze Meeting**.
- Namen dürfen **mit Verzug** erscheinen (Ziel ≤ 2 Minuten) oder erst in der Auswertung.
- Anonyme Personen lassen sich im Dashboard nachträglich benennen.
- Voraussetzung: Einwilligung (siehe 6.).

**FR-13 Auswertung nach dem Meeting [neu]**
Nach dem Beenden: finales Live-Bild (FR-10), Transkript mit Namen, Redeanteile, Zeitnutzung je
Agendapunkt und die Liste der Hinweise – als Export. Keine Speicherung über das Meeting hinaus, außer
der Nutzer exportiert ausdrücklich.

## 4. Nicht-funktionale Anforderungen

| ID | Anforderung | Zielwert |
|---|---|---|
| NF-01 | Verzug Live-Transkript | ≤ 2 s |
| NF-02 | Verzug Fokus-Ampel | ≤ 25 s nach Beginn des Exkurses (inkl. 20 s Karenz) |
| NF-03 | Verzug Monolog-, Überlappungs-Ampel | ≤ 5 s nach Erreichen der Schwelle bzw. Beginn der Überlappung |
| NF-04 | Verzug Namen | ≤ 2 Minuten, oder in der Auswertung |
| NF-05 | Sprecherstabilität | dieselbe Person behält im ganzen Meeting dieselbe Kennung |
| NF-06 | Texterkennung Deutsch | im Raumtest verständlich; Zielwert Wortfehlerrate ≤ 10 % |
| NF-07 | Kosten | ≤ 2 $ pro Meeting-Stunde, gemessen über das Nutzungsprotokoll |
| NF-08 | Robustheit | Ausfall eines Dienstes legt nicht alles lahm: ohne Sprecherdienst laufen Text, Zeit, Fokus weiter |
| NF-09 | Betrieb | Laptop (Windows), Browser Edge/Chrome, ein Konferenzmikrofon |
| NF-10 | Datenhaltung | Audio, Transkript, Profile nur so lange wie nötig (siehe 6.) |

## 5. Architektur

### 5.1 Grundprinzip: getrennte Ströme statt einer Kette

Jeder Strom arbeitet unabhängig und mit dem Verzug, den seine Aufgabe verträgt. Alle schreiben in einen
gemeinsamen Meeting-Zustand; daraus entstehen Ampeln, Hinweise und das Live-Bild.

```
                 ┌─ Strom 1: Live-Text ───────── Streaming-STT ──────────► Sätze (≤ 2 s)
Mikrofon ──Audio─┤
 (Browser)       ├─ Strom 2: Wer spricht ─────── Streaming-Diarisierung ─► Sprecherwechsel live (anonym)
                 │                                                          → Monolog, Überlappung, Redeanteile
                 └─ Strom 3: Namen ───────────── Batch alle 1–2 min ─────► Person A = „Florian“ (mit Verzug)

Sätze ──► Strom 4: Kontext ── Sprachmodell je Satzgruppe ──► Fokus, Agenda-Vorschlag
Sätze ──► Strom 5: Live-Bild ─ Claude (Abo): Strukturanalyse → SVG, alle 10 min / Knopf / Ende

Uhr ────► Countdown, Zeit-Ampel (regelbasiert, jede Sekunde)
```

Zusammenführung: Jeder Satz aus Strom 1 bekommt über die Zeitstempel die Person aus Strom 2; Strom 3
ersetzt später anonyme Kennungen durch Namen.

### 5.2 Anbieter – Vorschlag und Entscheidung

Die Entscheidung fällt **nach einem Vergleichstest mit echter Aufnahme aus dem Raum** (siehe 7.),
nicht nach Datenblatt.

| Strom | Variante A (Favorit) | Variante B (ein Anbieter) | Rückfall (vorhanden) |
|---|---|---|---|
| 1 Live-Text | **ElevenLabs Scribe v2 Realtime** (~150 ms, Deutsch ≤ 5 % WER laut Anbieter, Fachbegriffe als Vokabelhilfe) | **Speechmatics** Realtime | OpenAI Realtime-Transkription (`gpt-4o-transcribe`) |
| 2 Wer spricht (live) | **pyannoteAI Live-1** (Streaming-Diarisierung) | Speechmatics Realtime-Diarisierung | MVP-Lösung (blockweise, OpenAI) |
| 3 Namen | **pyannoteAI Precision-2** mit Stimmprofilen (Voiceprints) | Speechmatics `known_speakers` | OpenAI mit Stimmproben (max. 4, nur je Meeting) |
| 4 Kontext | GPT-5, minimaler Denkaufwand | gleich | – |
| 5 Live-Bild | Claude über Abo: Opus analysiert, Sonnet zeichnet SVG | gleich | – |

Begründung Variante A: Jeder Strom wird vom jeweils stärksten Spezialisten bedient; ElevenLabs bietet
keine Stimmprofile und keine Live-Diarisierung, pyannoteAI genau das. Variante B ist einfacher (ein
Anbieter, ein Datenstrom), Qualität für Deutsch aber ungeprüft.

### 5.3 Kostenschätzung je Meeting-Stunde (Variante A)

| Posten | Annahme | Kosten |
|---|---|---|
| Live-Text | ElevenLabs Scribe v2 Realtime | ~0,39 $ |
| Wer spricht | pyannoteAI Live-1 | ~0,20 € |
| Namen | pyannoteAI Precision-2, Batch | ~0,11 € |
| Stimmprofile | einmalig 0,015 € je Person | vernachlässigbar |
| Kontext | GPT-5 minimal, ~1 Aufruf je 15 s | ~0,25 $ |
| Live-Bild | Claude über Abo, 6 Bilder | 0 $ (Abo-Kontingent) |
| **Summe** | | **~1,3 $** |

Grundlage: Preisangaben der Anbieter bzw. Vergleichsseiten, Stand Okt. 2026; pyannoteAI zzgl.
Grundgebühr (Developer-Plan 19 €/Monat inkl. 19 € Guthaben). Zu bestätigen über das Nutzungsprotokoll.

### 5.4 Was aus dem MVP bleibt

Dashboard, Meeting-Zustand, Ampellogik, Entscheider, Themen-Zuordnung, Konfiguration, Simulation,
Tests. Ersetzt wird der Block „Zuhören“ (`coach/transkription.py`) durch die Ströme 1–3. Die
Schnittstelle zum Rest bleibt: Sätze mit Sprecher und Zeit, Sprecherspur mit Zeit.

## 6. Datenschutz und Mitbestimmung

Einschätzung, keine Rechtsberatung – vor dem ersten Einsatz klären.

- **Einwilligung aller Teilnehmenden** zu Beginn jedes Meetings; das Dashboard zeigt sichtbar, dass
  aufgezeichnet und ausgewertet wird.
- **Stimmprofile sind biometrische Daten** (DSGVO Art. 9): nur mit ausdrücklicher, widerrufbarer
  Einwilligung; Löschung auf Wunsch; Profile getrennt von Meetingdaten.
- **Betriebsrat:** Redeanteile je Person können als Verhaltens- bzw. Leistungskontrolle gelten
  (§ 87 Abs. 1 Nr. 6 BetrVG). Falls vorhanden, früh einbinden. Gestaltungshilfe: Redeanteile nur
  anonym live, Namen nur in der Auswertung für die Gruppe selbst.
- **Auftragsverarbeitung:** mit jedem Cloud-Anbieter (OpenAI, ElevenLabs, pyannoteAI) prüfen bzw.
  abschließen; Option „keine Nutzung zu Trainingszwecken“ wählen.
- **Speicherung:** Audio nie dauerhaft; Transkript und Live-Bild nur bis Meetingende, außer ausdrücklich
  exportiert; Nutzungsprotokoll ohne Inhalte.

## 7. Vorgehen

1. **Vergleichstest (vor dem Bau):** Eine 10-minütige Aufnahme eines echten 5-Personen-Meetings im
   Zielraum mit Konferenzmikrofon, mit Einwilligung aller. Dieselbe Aufnahme durch Variante A, B und
   Rückfall. Bewertet: Wortfehler (Stichprobe), Sprecherstabilität, erkannte Überlappungen, Verzug, Kosten.
2. **Bau Strom 1 + 4** (Live-Text und Kontext) – größter spürbarer Gewinn.
3. **Bau Strom 2** (Wer spricht live) – Monolog, Überlappung, Redeanteile.
4. **Bau FR-10** (Live-Bild als One-Pager) – erledigt 04.10.2026.
5. **Bau Strom 3 + FR-12** (Namen über Stimmprofil) nach Klärung Einwilligung/Betriebsrat.
6. **Pilot** in drei echten Meetings, Auswertung entlang Lastenheft Kap. 16 (Erkennung, Verständlichkeit,
   Nutzen, Störung, Schwellen).

## 8. Offene Punkte

- Konten bei ElevenLabs und pyannoteAI (ggf. Speechmatics) – legt Niclas an, Schlüssel in `.env`.
- Konferenzmikrofon für den Zielraum.
- Gibt es in der neuen Firma einen Betriebsrat? Wer gibt den Einsatz frei?
- Wer sieht das Live-Bild – nur Moderation oder Beamer für alle?
- Sollen bestätigte Entscheidungen/Aufgaben in ein anderes System (Tickets, Mail, Wiki) übergeben werden?
- Hybride Meetings (Teams) als spätere Ausbaustufe: anderer Audioeingang nötig.

## 9. Nicht Teil dieser Version

Sprachliche Intervention durch die KI, autonome Steuerung, Bewertung von Personen, Aussagen oder
Hierarchie, Kulturdiagnostik, Lernhistorie über Meetings (außer Stimmprofilen), Teams-/Online-Meetings.
