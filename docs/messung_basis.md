# Messung Nestor Basis (Mistral)

Ticket #13 · Stand 08.10.2026 · Skripte: [`scripts/basis_messen.py`](../scripts/basis_messen.py),
[`scripts/parallel_messen.py`](../scripts/parallel_messen.py) (Rohdaten unter `logs/basis/`, nicht im Git).
Gemessen auf dem Pi (BuddyBoard), der nebenher ausgelastet war (Lastmittel ~10 auf 4 Kernen).

## Ergebnis in Kürze

| | Nestor Basis (Mistral) | Nestor Premium (OpenAI) |
|---|---|---|
| Sprechende → erster Ton | **Median 2,02 s** (Schritt 0, 10 Läufe), **2,12 s** im ganzen Coach (11 Zurufe) | Realtime-Gespräch wie bisher; Text-Weg im Lasttest 2,0–2,6 s |
| Richtige Aktion (12 Zurufe der Probe) | **24/24** (2 Läufe), erster Satz Median 0,54 s | 12/12, erster Satz Median 1,18 s |
| „Person N“ in Antworten | 0 von 24 | 1 von 12 |
| „Nestor“ erkannt | 10/10 (Schritt 0), 11/12 im Coach – einmal „Westor“, jetzt mit erkannt | wie bisher |
| Kein Aufruf an OpenAI | nachgewiesen: Nutzungsprotokoll nur `mistral-*` und `voxtral-*` (Demo, Zurufe, Knopfdruck) | – |
| Kosten je Stunde | **~0,45–0,6 $** (gerechnet aus gemessenen Aufrufen, unten) | ~2 $ |
| Parallele Meetings | **24 gleichzeitig ohne 429**, Antwortzeiten fast unverändert | **8 gleichzeitig ohne 429** (mehr nicht getestet, Kostendeckel) |

## Schritt 0: Sprechende → Thorstens erster Ton (Stoppregel 2,5 s)

**Ergebnis: Median 2,02 s (10 Läufe, 1,75–2,18 s) – unter 2,5 s, weitergebaut.**

Aufbau: Die zwölf Zurufe der Machbarkeitsprobe sind als Audio erzeugt (gespeicherte Stimme „nic-de“, also eine
menschlich klingende Fragestimme, nicht Thorsten). Eine durchgehende Live-Text-Sitzung bekommt 23 s Gespräch aus der
Messe-Demo, dann je Zuruf: 1,2 s Pause, Frage, 3,5 s Stille, 8 s Demo-Gespräch. Das Audio läuft in Echtzeit in
100-ms-Stücken durch dieselben Bausteine wie im Coach: Pausenerkennung (Silero, 0,5 s), Live-Text (`LiveTextMistral`,
Voxtral Realtime, `target_streaming_delay_ms=240`), Ansprache-Erkennung (`assistent.angesprochen`), Antwort mit
`mistral-medium-latest` (Systemanweisung aus `assistent.py`, Kontext der Messe-Demo bei 2:45), erster Satz an Voxtral
TTS mit `voice_id` Thorsten. Gemessen bis das erste Tonstück auf dem Server ankommt – wie `logs/nestor_zeiten.jsonl` im
Betrieb; der Weg zum Browser (LAN) und dessen Abspielpuffer fehlen.

| ab Sprechende | Median | min | max |
|---|---|---|---|
| Satz als Text da (Pause erkannt + Live-Text) | 0,84 s | 0,78 s | 1,04 s |
| erstes Antwort-Token | 1,30 s | 1,16 s | 1,50 s |
| erster ganzer Satz | 1,43 s | 1,23 s | 1,60 s |
| **erster Ton (Thorsten)** | **2,02 s** | **1,75 s** | **2,18 s** |

- 10 von 10 Zurufen mit „Nestor“ richtig erkannt und beantwortet.
- Ein Zuruf („Nestor, gib uns einen kurzen Überblick, was ein Eckstand … kostet“) wurde von der Pausenerkennung nach
  „Überblick“ geteilt; Nestor antwortete schon auf den ersten Teil. Das ist das Verhalten des Coaches in beiden Stufen
  (Äußerungsgrenze nach 0,5 s Pause), nicht Mistral-spezifisch.
- Vorlauf mit je einer frischen Live-Text-Sitzung pro Zuruf (ohne Gespräch davor): „Nestor“ kam am Sitzungsanfang
  oft falsch an („Nächstes Tor“, „Nest door“, einmal japanische Schrift). Im laufenden Meeting tritt das nicht auf –
  die Sitzung läuft dort vom Start an durch. Voxtral Realtime unterstützt weder eine Sprachvorgabe noch Kontextwörter
  (`context_bias`, `language`: API-Fehler 3051 „not supported“, geprüft 08.10.).
- Sprachausgabe einzeln gemessen (8 Sätze): erster Ton meist 0,4–0,65 s, aber Ausreißer bis 10 s. Deshalb startet
  `coach/mistral.py` nach 1,6 s ohne Ton eine zweite, gleiche Anfrage; die schnellere gewinnt.

## Im ganzen Coach (Abspielmodus, `LMC_STUFE=basis`)

**Zurufe mitten im Meeting** (`basis_messen.py pipeline --n 12`): dieselben zwölf Zurufe, je 8 s Stille danach, durch
`Coach.abspielen` – also mit Sprechererkennung, Zuordnung, Karten, Überblick und Recherche nebenher. Nestors eigene
Zeitmessung (`nestor_zeiten.jsonl`, Ansprache):

| | Median | min | max |
|---|---|---|---|
| Satz als Text da, ab Sprechende | 0,96 s | 0,68 s | 1,87 s |
| danach bis zum ersten Ton | 1,18 s | 0,60 s | 1,93 s |
| **Sprechende → erster Ton** | **2,12 s** | **1,56 s** | **3,10 s** |

- Aktionen im Lauf: Übersicht (2×, beide Male `bild` → Überblick als Text), Agendawechsel (2×), zwei Recherchen
  (je ~5 s mit 2 Quellen, „Ich schau kurz nach“ vorab), Pause. Die Pause hat das Skript nach 2 s wieder aufgehoben.
- 11 von 12 Zurufen beantwortet. Der zwölfte kam als „Westor, haben wir schon entschieden …“ an; das Namensmuster
  (`LMC_ASSISTENT_MUSTER`) nimmt seitdem auch „W“ am Anfang.
- Zweimal griff die zweite TTS-Anfrage (erster Ton nach 1,65 s bzw. 2,05 s).
- Kosten des Laufs (4:20 min, 12 Fragen, 2 Recherchen, 2 Überblicke): 0,19 $.

**Messe-Demo** (`abspielen.py demo/messeplanung.wav --mit-bild`, 3:11 min): läuft durch. „Nestor, wo stehen wir
gerade?“ → „Ihr seid bei Punkt zwei, Budget. Festgehalten ist die Obergrenze von 25.000 Euro.“ (Thorsten); „Nestor,
zeig uns bitte die Übersicht“ → Überblick als Text nach wenigen Sekunden. Zuordnung meldet den Fußball-Einschub
(1:09) als Fremdthema, der Kraftausdruck kommt als Ton-Hinweis. Nutzungsprotokoll: nur `mistral-medium-latest`,
`voxtral-mini-transcribe-realtime-2602`, `voxtral-mini-tts-latest` – **kein Aufruf an OpenAI** (im Prozess gab es
auch keinen OpenAI-Schlüssel). Kosten der Demo 0,066 $ (Premium im Vergleichslauf: 0,30 $).

**Nur auf Knopfdruck** (`basis_messen.py knopfdruck`): Demo abspielen, bei 1:40 / 2:30 / 3:05 Knöpfe drücken.
Bis zum ersten Knopf **0 KI-Aufrufe**. Danach Voxtral-Batch (`voxtral-mini-latest`) + `mistral-medium-latest`:

| Knopf | Wartezeit | Ergebnis |
|---|---|---|
| Wo stehen wir? (bei 1:40, 55 s offene Sprache) | 3,9 s | Karte „Termin und Messestand abgeschlossen“, Vorschlag Budget |
| Regeln eingehalten? | 1,9 s | Abschweifung 0:56–1:17 und „So ein Scheiß“ gefunden |
| Überblick | 2,5 s | Entschieden: 40 m² Eckstand, höchstens 25.000 Euro; Offen: Hotels; 3 Aufgaben |
| Protokoll | 1,8 s | |
| Nestor fragen (getippt) | 0,6 s | |

Kosten 0,018 $ für 3 Minuten mit fünf Knöpfen.

**Halten zum Sprechen**: WAV einer Frage an `/api/frage/audio` am laufenden Basis-Server: Voxtral-Batch 0,9 s,
Antwort mit Thorsten und Karte. Die Oberfläche (Halten am Handy) ist nur im Browser-Bildschirmfoto geprüft, nicht auf
einem echten Handy.

## Aktionen: die 12 Zurufe der Probe

`basis_messen.py aktionen` – Systemanweisung aus `assistent.py` (in Basis heißt `AKTION: bild` „Übersicht ins
Dashboard stellen“), Kontext der Messe-Demo bei 2:45.

| Stufe | Modell | Aktion richtig | erster Satz (Median) | „Person N“ genannt |
|---|---|---|---|---|
| Basis | mistral-medium-latest | **24/24** (2 Läufe) | 0,54 s | 0 |
| Premium | gpt-5.4-mini | 12/12 | 1,18 s | 1 |

`mistral-medium-latest` zeigt inzwischen auf Medium 3.5 (Denkaufwand nur `none`/`high`; „low“ von OpenAI wird in
Basis weggelassen).

## Zuordnung: Medium oder Small?

Ticket: „Small darf getestet werden, aber nur übernehmen, wenn die Ergebnisse gleich gut sind.“ Die Zuordnung alle
~15 s Gesprochenes ist mit Medium der größte Textposten (~0,37 $/h), mit Small ein Zehntel.

- 7 Abschnitte aus der Messe-Demo und ergänzte Fälle, Ansagen entfernt (Wechsel muss aus dem Inhalt kommen), zwei
  Fremdthemen (Fußball, Urlaub), ein Kraftausdruck; je 3 Läufe (`basis_messen.py zuordnung`):
  **Medium 21/21 Zuordnung, 21/21 Ton – Small 21/21, 21/21** (0,59 s bzw. 0,66 s).
- Demo-Transkript neu durchgespielt (`themen_vergleich.py`, je 2×): identische Wechsel und Fokus-Hinweise.

**Entscheidung: Small für die Zuordnung in Basis** (`LMC_BASIS_ZUORDNUNG_MODELL`, Rückweg auf Medium ohne Codeänderung).
Die Grundlage ist schmal (eine Demo, synthetische Fälle) – der erste echte Raumtest in Basis sollte die Zuordnung
gezielt ansehen. Nestors Antworten, Überblick, Ergebnisse und Protokoll bleiben auf Medium.

## Kosten je Stunde

Listenpreise in `coach/kosten.py` (geprüft 08.10. gegen docs.mistral.ai: Medium 3.5 1,5/7,5 $ je Mio. Tokens, Small 4
0,15/0,60 $, Voxtral Realtime 0,006 $/min, Voxtral Transcribe 0,003 $/min, TTS 16 $ je Mio. Zeichen). Für die Websuche
nennt Mistral keinen Preis; gerechnet mit 30 $ je 1000 (Sekundärquellen). Suchergebnisse rechnet Mistral als
„connector_tokens“ ab (~5000 je Suche) – im Protokoll vorsichtshalber als Eingabe-Tokens gezählt.

Je Aufruf gemessen (Nutzungsprotokoll der Läufe oben):

| Posten | je Aufruf | Annahme je Stunde | $ je Stunde |
|---|---|---|---|
| Live-Text (Voxtral Realtime) | – | 60 min | 0,36 |
| Zuordnung (Small; Medium) | 900 + 60 Tokens | ~200 Abschnitte | 0,035 (Medium 0,37) |
| Nestor-Antwort + Karte + Sprachausgabe | ~0,006 $ | 10 Fragen | 0,06 |
| Recherche (inkl. Suche) | ~0,033 $ | 2 | 0,07 |
| Überblick (alle 10 min) | ~0,003 $ | 7 | 0,02 |
| Ergebnisse je Punkt, Begrüßung | | | ~0,02 |
| **Summe** | | | **~0,55 $** (ohne Fragen ~0,45 $; mit Medium-Zuordnung ~0,9 $) |

Richtwert auf der Startseite: **0,6 €** je Stunde. Mit „Nur auf Knopfdruck“: Voxtral-Batch 0,003 $/min Sprache
(~0,1–0,2 $ je Stunde) plus wenige Cent je Knopf – deutlich unter den bisherigen 0,4 $/h (dort Transkription bei
OpenAI und Bild). Beides ist gerechnet, kein 60-Minuten-Lauf.

## Parallele Meetings: wo liegt die Grenze?

**Recherche** (08.10.):
- Mistral: Grenzen je Organisation und Modell als Anfragen je Sekunde, Tokens je Minute und je Monat. Stufen steigen
  automatisch mit dem abgerechneten Betrag (Tier 2 ab 20, Tier 3 ab 100, Tier 4 ab 500; darüber auf Anfrage beim
  Support); Prepaid-Guthaben zählt nicht. Konkrete Zahlen je Stufe veröffentlicht Mistral nicht, sie stehen im Konto
  unter admin.mistral.ai → Limits. Für Voxtral Realtime/TTS sind keine eigenen Grenzen dokumentiert. Laut Ticket zeigt
  das Konto 100 Anfragen/min und 100.000 Tokens/min.
  Quellen: help.mistral.ai „Why am I hitting API rate limits“, docs.mistral.ai/resources/known-limitations.
- OpenAI: Stufen nach Guthabenkäufen (Build ab 5 $, Launch ab 100 $, Grow ab 500 $). Je Modell (Build / Launch):
  gpt-5.4-mini 5.000 / 10.000 Anfragen/min; gpt-realtime 400 / 10.000 Anfragen/min; gpt-live-transcribe 2.000 / 10.000;
  gpt-4o-mini-tts 2.000 / 10.000. Eine Grenze für gleichzeitige Realtime-Sitzungen ist für gpt-realtime nicht
  dokumentiert. Quelle: developers.openai.com/api/docs/guides/rate-limits und die Modellseiten.

**Messung** (`parallel_messen.py`): N Meetings gleichzeitig, je 1:30–2:00 min Demo-Audio in Echtzeit an den Live-Text,
alle ~15 s eine Zuordnung, eine Nestor-Frage pro Minute (Antwort + erster Ton). Premium über den Allgemeinschlüssel
`openai-api-key` (der Cloud-Schlüssel `openai-nestor` ist in der Hausablage leer) und in beiden Stufen über den
Text-Weg – das Realtime-Gespräch von Premium ist nicht mitgemessen.

| Stufe | Meetings | 429 | Zuordnung (Median / max) | Nestor erster Ton (Median / max) |
|---|---|---|---|---|
| Basis | 1 | 0 | 0,71 / 0,83 s | 1,47 / 1,85 s |
| Basis | 8 | 0 | 0,95 / 1,50 s | 1,21 / 1,67 s |
| Basis | 16 | 0 | 0,66 / 1,90 s | 1,28 / 3,33 s |
| Basis | 24 | 0 | 1,21 / 2,18 s | 1,38 / 3,11 s |
| Premium | 1 | 0 | 1,72 / 2,85 s | 2,63 / 3,05 s |
| Premium | 8 | 0 | 1,56 / 2,88 s | 2,23 / 2,99 s |

- Die Zeilen ab 8 Meetings sind „nur API“ (`--nur-api`: Äußerungsgrenze alle 4 s statt lokaler Pausenerkennung).
  Mit Pausenerkennung für alle Meetings in einem Prozess wurde der Pi selbst zum Engpass (16 Meetings: Zuordnung
  2,4 s, erster Ton 3,7 s; 24: 4,0 s / 7,3 s – ohne einen einzigen 429). In der Cloud hat jedes Meeting einen eigenen
  Container; geteilt wird dort nur der Schlüssel, deshalb zählt die Zeile „nur API“.
- **Basis: bis 24 gleichzeitige Meetings kein 429**, Zuordnung und Antworten nur wenig langsamer (Median +0,2–0,5 s,
  einzelne Spitzen ~3 s). Das sind ~120 Anfragen/min – mehr als die im Konto genannten 100/min; die Grenze liegt also
  darüber, gefunden haben wir sie nicht. Weiter getestet wurde wegen des Kostendeckels nicht.
- **Premium: bis 8 kein 429**, Antwortzeiten unverändert. Nach den dokumentierten Grenzen (Build-Stufe) ist bei
  ~5–6 Anfragen je Meeting und Minute die Realtime-Grenze von 400/min der engste Posten – grob 60 Meetings.
- Gegen 429 gebaut: jede Anfrage an Mistral wird bei 429 bis zu 4-mal mit wachsender Wartezeit (0,5–4 s) wiederholt,
  danach sagt Nestor „Ich komme gerade nicht durch, versucht es gleich nochmal.“ (Hörprobe `09_ueberlast.wav`).

## Hörproben

Thorstens Stimme (Voxtral TTS, `voice_id` „nestor-thorsten-de“), erzeugt mit `basis_messen.py hoerproben`:
Begrüßung, Startsatz (Basis-Fassung), sieben Antworten aus dem Aktionen-Lauf, Überlast-Satz. Liegen unter
`logs/basis/hoerproben/` und auf dem Pi unter `~/brainstorm/mistral-probe/hoerproben_basis/` (nicht im Git).

## Offen

- Kein Raumtest: Echo-Unterdrückung, echte Stimmen, Tischmikrofon – wie bei Premium nur Abspiel- und Synthesetests.
- Zuordnung mit Small nur an der Demo und synthetischen Fällen geprüft (siehe oben).
- Die Kosten je Stunde sind aus Einzelaufrufen hochgerechnet; ein 60-Minuten-Lauf in Basis steht aus.
- Die Grenze paralleler Meetings in Basis liegt über 24 – genauer nur mit mehr Budget oder Blick in die Kontolimits.
