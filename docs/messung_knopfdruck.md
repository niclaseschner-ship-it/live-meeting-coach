# Messung: Wartezeit und Kosten im Modus „Auf Knopfdruck“

Stand 07.10.2026 · Ticket #7 · `scripts/knopfdruck_messen.py`, `coach/knopfdruck.py`, `coach/kosten.py`

## Kurzfassung

- **Wartezeit** je Knopf liegt bei 10–20 s für Stand/Regeln auf 15/30 Minuten Meetingzeit und bei ~63 s für
  das Protokoll auf 60 Minuten (mehr offene Sprache seit dem letzten Knopf). Die Transkription dominiert die
  Zeit (26–52 s), die Text-Analyse ist über Codex mit 10–15 s dazu vergleichsweise klein.
- **Kosten** für die drei Text-Knöpfe über die volle Stunde: 0,176 $ (praktisch nur Transkription; die
  Text-Analyse über Codex kostet nichts extra). Der Bild-Knopf kostet separat 0,074 $ je Aufruf.
- **Richtwert aktualisiert:** `coach/config.py` `richtwert_knopfdruck_eur` von 0,5 auf 0,4 gesenkt – die
  gemessenen und hochgerechneten Werte liegen bei 0,25–0,4 $/h.
- **Gesamtkosten dieser Messung:** 0,263 $ (Budget war 0,60 $) – siehe „Kosten dieser Messung“ unten.

## Testmaterial: warum eine Ersatzaufnahme

Für eine ≥60-minütige deutsche Besprechung gab es auf diesem Rechner nichts Passendes:
- `testbibliothek/` enthält laut ihrer eigenen README nur die Beschreibung im Git; Proben und Audio bleiben
  bewusst lokal/intern und lagen auf diesem Pi nicht vor (kein `testbibliothek/proben/*/probe.json`).
- `scripts/bibliothek_laden.py` könnte eine Probe herunterladen, bräuchte dafür aber `yt_dlp` (hier nicht
  installiert) und genau die fehlenden `probe.json`-Dateien.
- `logs/` auf diesem Rechner enthielt nur `nestor_zeiten.jsonl`, keine Audiodateien. Von
  `scripts/pi_vertonen.py` lag ebenfalls nichts vor.
- `demo/messeplanung.wav` (die einzige vorhandene deutsche TTS-Aufnahme, echte Sprachausgabe, ~3,2 min) ist
  die einzige Audioquelle im Repo.

Ersatz: `scripts/knopfdruck_messen.py` hängt `demo/messeplanung.wav` 20-mal hintereinander (`aufnahme_bauen()`),
macht daraus 63,7 Minuten und legt sie unter `testbibliothek/audio/messung_knopfdruck.wav` ab (gitignored, wie
`logs/`). Das ist vertretbar, weil laut Ticket nur die **Menge offener Äußerungen seit dem letzten Knopf** die
Transkriptions- und Analysezeit bestimmt, nicht der Inhalt – und die Wiederholung liefert trotzdem echte,
zu transkribierende deutsche Sprache (keine Stille, kein Fake-Transkript). Was sie **nicht** leistet: eine
realistische Sprechdichte. Die Probe hat (gemessen über die Amplitude) nur ~42 % tatsächliche Sprache, weil die
Demo bewusst Pausen für Nestors Begrüßung und Antworten einbaut; über den vollen Messlauf kamen sogar nur ~49 %
zusammen (1761,8 s transkribierte Sprache auf 3600 s Meetingzeit, siehe Tabelle unten). Eine echte Besprechung
mit mehreren durcheinander redenden Personen dürfte näher an durchgehender Rede liegen – die Hochrechnung dazu
steht unten bei den Kosten.

## Aufbau des Laufs

`scripts/knopfdruck_messen.py` baut direkt einen `Coach` (wie `scripts/abspielen.py`, ohne Dashboard/Server),
setzt `modus = "knopfdruck"`, richtet ein Meeting ohne Sprachassistent ein (`assistent: False`, damit nichts an
`Nestor, …`-Stellen in der Demo hängen bleibt – unnötig, weil Knopfdruck das Zuhören des Assistenten ohnehin
abschaltet, aber zur Sicherheit) und füttert die Ersatzaufnahme paketweise wie im echten Abspielbetrieb. Die
Meetinguhr folgt dabei der Audiolänge, nicht der Wanduhr; das Füttern lief mit `--tempo 20` (höchstens ~26,5×
Echtzeit laut Geschwindigkeitstest auf diesem Pi), damit 63,7 Minuten Audio in guten drei Minuten durchlaufen –
die Meetingzeit an den Marken 15/30/60 min bleibt davon unberührt, nur die Wartezeit *für diese Messung selbst*
wird kürzer.

An den Marken 15, 30 und 60 Minuten Meetingzeit wird je ein Knopf gedrückt (`coach.knopfdruck.ausfuehren`), die
Zeiten kommen aus `logs/nestor_zeiten.jsonl` (dieselben Felder, die der Coach im echten Betrieb schreibt: je
Knopf `transkription_s`, `analyse_s`, `gesamt_s`, `aeusserungen`), die Kosten aus der Differenz von
`coach.kosten_stand()["meeting"]` vorher/nachher (`coach/kosten.py`, ab `hoeren_starten()` bei null). Vor jedem
Knopf schätzt das Skript aus der noch offenen Sprachzeit die zu erwartenden Transkriptionskosten und bricht ab,
wenn das zusammen mit dem bisherigen Stand das Budget sprengen würde.

**Kosten-Kontrolle:** Die Transkription lief echt gegen die API (`gpt-4o-transcribe`, ~0,006 $/min Sprache,
`OPENAI_API_KEY` nur für die Dauer des Laufs in die Umgebung geholt, nie in eine Datei oder ein Log geschrieben).
Die Text-Analyse (Stand, Regeln, Protokoll) lief über das Codex-Abo (`LMC_KI=codex LMC_CODEX_BEFEHL=codex`,
keine API-Kosten), `LMC_STIMME_AUS=1` verhindert Sprachausgabe.

## Ergebnis: Meetinglänge × Knopf → Sekunden und Kosten

| Meetingzeit | Knopf | Transkription | Analyse (Codex) | Gesamt | Äußerungen | Sprache seit letztem Knopf | Kosten |
|---|---|---|---|---|---|---|---|
| 15 min | Wo stehen wir? (`stand`) | 28,0 s | 10,4 s | 38,4 s | 129 | 442,5 s | 0,0443 $ |
| 30 min | Regeln eingehalten? (`regeln`) | 26,2 s | 14,6 s | 40,8 s | 128 | 439,7 s | 0,0439 $ |
| 60 min | Protokoll (`protokoll`) | 52,2 s | 10,4 s | 62,6 s | 260 | 879,6 s | 0,0880 $ |
| einmalig, separat (s. u.) | Bild (`bild`) | 0,0 s | 50,1 s | 50,1 s | 0 | 0 s | 0,0743 $ |

**Summe der drei Text-Knöpfe über die volle Stunde: 0,1762 $.** Das deckt zusammen praktisch die ganze seit
Meetingbeginn gesprochene Zeit ab (442,5 + 439,7 + 879,6 = 1761,8 s ≈ 29,4 min Sprache auf 3600 s Meetingzeit,
~49 % Sprechanteil in dieser Probe) – die Kosten liegen fast exakt bei `Sprache_s / 60 × 0,006 $`, die
Text-Analyse über Codex schlägt mit 0 $ zu Buche (siehe Nutzungsprotokoll: `tokens_rein`/`tokens_raus` sind bei
Codex-Aufrufen 0, weil das Abo keine Tokenzahlen liefert).

**Bild lief in einem separaten Kurzlauf, nicht am Ende der 60-Minuten-Probe:** Das Skript hatte ursprünglich
einen Fehler – es rief `coach.hoeren_beenden()` auf, bevor es den optionalen Bild-Knopf drückte, wodurch
`knopfdruck.reservieren()` mit „Es läuft kein Meeting“ abbrach (siehe `full_run.log`-Traceback dieser Messung).
Der Fehler ist in `scripts/knopfdruck_messen.py` behoben (Bild-Knopf jetzt vor `hoeren_beenden()`). Weil das
Ticket **höchstens einen vollen Lauf über 60 Minuten** erlaubt, wurde die teure 60-Minuten-Transkription nicht
wiederholt, um den Fix zu prüfen; der Bild-Knopf lief statt dessen separat auf einem 100-Sekunden-Ausschnitt
(real transkribiert, real analysiert) direkt nach einem „Stand“-Knopf (der Bild-Knopf braucht ein
nicht-leeres Transkript). 0,074 $ für 3818 Eingabe- und 986 Ausgabetokens (`gpt-5.4 + gpt-image-2` über die
Responses-API, medium-Qualität) passt zum Richtwert aus dem Ticket (~0,08 $) und zu `coach/kosten.py`
(`BILD = 0,05` + Text-Tokens). Der Bild-Knopf läuft unabhängig vom Modell für die Text-Analyse immer über die
echte API – `LMC_KI=codex` betrifft nur `chat.completions`, nicht `responses.create` (siehe `coach/ki_abo.py`,
`AboClient.__getattr__`).

## Codex- vs. API-Zeiten und -Kosten für Stand/Regeln/Protokoll

Das Ticket verlangt, Codex-Zeiten getrennt von einer API-Schätzung auszuweisen, weil Niclas zum Testen Codex
nutzt (`LMC_KI=codex`, kein API-Kostenrisiko beim Entwickeln), Kundinnen und Kunden im echten Betrieb aber immer
die API bekommen (Codex ist laut Lastenheft Abschnitt 6 „nur für Tests und in der Cloud aus“).

Statt das nur zu schätzen, lief ein zusätzlicher kleiner Vergleichslauf: derselbe „Stand“-Knopf auf demselben
100-Sekunden-Ausschnitt, einmal mit `LMC_KI=codex`, einmal mit `LMC_KI=openai` (echte API):

| Weg | Analysezeit | Kosten der Analyse | Tokens |
|---|---|---|---|
| Codex (`LMC_KI=codex`) | 9,1–10,6 s | 0 $ | keine (Abo liefert keine Tokenzahlen) |
| API (`LMC_KI=openai`, `gpt-5.4-mini`, `low`) | 2,6 s | 0,00165 $ | 785 rein, 236 raus |

Die API ist hier **~4× schneller** (2,6 s statt 9,1–10,6 s) und kostet **0,17 Cent** – das deckt sich mit der
Beobachtung aus `coach/ki_abo.py` („~5 s über Codex, 1–3 s über die API“, dort 05.10. gemessen; unsere Aufrufe
sind mit Agenda- und Kontexttext etwas größer, deshalb beide Seiten etwas länger). Für „Regeln“ und
„Protokoll“ auf 30/60 Minuten Transkript ist der Prompt deutlich größer (Regeln: Transkript seit dem letzten
Regel-Knopf plus Ton-Definition; Protokoll: ganzer bisheriger Text). Hochgerechnet von 785 auf das ~17-fache
Textvolumen bei „Protokoll“ (260 statt 15 Äußerungen) ergäben sich überschlägig ~13 000 Eingabe- und weiterhin
wenige hundert Ausgabe-Tokens, also **ca. 1–2 Cent** Analysekosten über die API – immer noch klein gegen die
8,8 Cent Transkription desselben Knopfs. Die Analysezeit über die API dürfte dabei eher bei 3–6 s liegen (mehr
Eingabetext, aber dasselbe `reasoning_effort="low"`), gegenüber den gemessenen 10,4–14,6 s über Codex.

**Fazit:** Codex ist für Entwicklung und diese Messung ideal (keine Kosten), im echten Betrieb macht die
API-Variante die Text-Analyse schneller und für ein bis zwei Cent je Knopf – gegenüber der Transkription (4–9
Cent je Knopf bei dieser Sprechdichte) bleibt das die kleinere Position.

## Hochrechnung „Kosten je Stunde bei 4 Knopfdrücken“

| Grundlage | Transkription (60 min) | Text-Analyse (API) | Bild | Summe |
|---|---|---|---|---|
| Gemessen, diese Probe (~49 % Sprechanteil) | 0,176 $ | ~0,01–0,02 $ (hochgerechnet) | 0,074 $ | **~0,26 $/h** |
| Hochgerechnet auf durchgehende Rede (~90 % Sprechanteil) | 0,176 × 0,90⁄0,489 ≈ 0,324 $ | ~0,02–0,03 $ | 0,074 $ | **~0,42 $/h** |

Beide Werte liegen unter der Lastenheft-Obergrenze „Knopfdruck ≤ 0,7 $ je Stunde“ (Abschnitt 5). Der Richtwert
auf der Startseite (`coach/config.py`, `richtwert_knopfdruck_eur`) wurde von 0,5 auf **0,4** gesenkt – ein Wert
zwischen der gemessenen und der hochgerechneten Zahl, vorsichtig zur sichereren (höheren) Seite gewählt, weil
reale Meetings vermutlich näher an durchgehender Rede liegen als die Ersatzprobe.

## Grenzen dieser Messung

- **Ersatzaufnahme statt echtem Meeting:** Sprechdichte, Satzlänge und Themenwechsel der Probe entsprechen
  nicht unbedingt einer echten Besprechung mit 3–8 Personen (Lastenheft Abschnitt 1). Die Hochrechnung oben
  versucht, das für die Kosten einzufangen; für die reine Wartezeit gilt weiterhin: sie hängt an der Menge
  offener Äußerungen, nicht am Sprechanteil – bei mehr gleichzeitig redenden Personen (höherer Sprechanteil,
  mehr Äußerungen in derselben Zeit) wäre also auch mit etwas längerer Transkriptionszeit pro Knopf zu rechnen.
- **Eine Agenda mit einem Punkt:** Der Meeting-Einrichtung fehlte ein echter Agendawechsel (die Probe wird
  nicht per Klick weitergeschaltet); „Protokoll“ hat deshalb nur einen statt mehrerer Agendapunkte ausgewertet.
  Das ändert die Kosten kaum (ein statt mehrerer `ergebnisse.pruefen`-Aufrufe je Knopf wären nötig gewesen,
  jeweils klein gegen die Transkription), dürfte die Wartezeit aber eher unterschätzen als überschätzen.
- **API-Analysekosten für Regeln/Protokoll sind hochgerechnet, nicht gemessen** (siehe oben) – um das Budget
  nicht für einen dritten echten API-Lauf auf großem Transkript zu verbrauchen.
- **Bild-Knopf separat gemessen**, nicht als echter Abschluss der 60-Minuten-Probe (siehe Erklärung oben).

## Kosten dieser Messung

Drei Läufe, alle mit echtem `OPENAI_API_KEY` (nur in der Umgebung, nie geloggt):

| Lauf | Inhalt | Kosten |
|---|---|---|
| Hauptlauf (60 min, `LMC_KI=codex`) | Stand (15 min) + Regeln (30 min) + Protokoll (60 min); Bild-Knopf schlug durch den o.g. Fehler fehl | 0,1762 $ |
| Bild-Zusatzlauf (100 s, `LMC_KI=codex`) | Stand (zum Befüllen des Transkripts) + Bild | 0,0797 $ |
| API-Vergleichslauf (100 s, `LMC_KI=openai`) | ein „Stand“-Knopf zum Zeit-/Kostenvergleich Codex↔API | 0,0071 $ |
| **Summe** | | **0,2630 $** |

Budget war 0,60 $, genutzt wurden 0,263 $ (44 %). Kein Lauf über 60 Minuten wurde wiederholt.
