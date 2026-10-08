# Cloud-Testlauf

Prüft Nestor so, wie ein echter Kunde ihn benutzt: ein echter Browser (Chromium ohne Bildschirm) meldet
sich an (falls nötig), wählt den Modus, richtet das Meeting über die Agenda-per-Prompt-Eingabe ein, hört
zehn Minuten in Echtzeit zu (Mikrofon aus einer Datei, kein Vorspulen), drückt im Modus „Auf Knopfdruck“
die Knöpfe zu festen Zeiten und geht am Ende durch den Abschluss. Läuft gegen eine beliebige Adresse: lokal
(`python -m coach` oder Docker-Container) und später gegen die Cloud.

## Aufrufen

```
~/.venvs/lmc/bin/pip install -r requirements-test.txt   # einmalig, nur Playwright – kein `playwright install`
ln -s /home/buddy/repos/live-meeting-coach/modelle modelle   # falls noch nicht vorhanden

python -m coach &   # Server lokal starten (oder gegen eine laufende Adresse testen)
~/.venvs/lmc/bin/python scripts/cloudtest.py --url http://127.0.0.1:8000 --stufe premium
~/.venvs/lmc/bin/python scripts/cloudtest.py --url http://127.0.0.1:8000 --stufe basis
~/.venvs/lmc/bin/python scripts/cloudtest.py --url http://127.0.0.1:8000 --stufe basis --nur-knopfdruck
```

Seit Ticket #13 wählt die Startseite eine **Stufe** (`--stufe basis|premium`) statt eines Modus; der frühere
Modus „Auf Knopfdruck“ ist der Schalter `--nur-knopfdruck` in Basis (nur dort gültig). Die Knopfleiste (Wo
stehen wir, Regeln, Überblick, Protokoll, Nestor fragen) gibt es in beiden Stufen; nur mit `--nur-knopfdruck`
geht ohne Knopf nichts an einen KI-Dienst und es gibt zusätzlich „Verwerfen“.

Gegen die Cloud zusätzlich `--passwort <Kundenpasswort>`; ohne `--passwort` wird die Anmeldeseite
übersprungen (nur lokal möglich, dort prüft `coach/zugang.py` ohnehin "am Laptop selbst").

**Für einen lokalen Probelauf mit `LMC_OFFLINE=1` braucht es trotzdem einen (beliebigen) Schlüssel-String**
in der Umgebung bzw. `.env` (`OPENAI_API_KEY` für Premium, `MISTRAL_API_KEY`/`LMC_MISTRAL_SCHLUESSEL` für
Basis) – die Startseite blendet eine Stufe ohne Schlüssel-String ganz aus (`coach/api_start.py`), unabhängig
von `LMC_OFFLINE`. Ein echter KI-Aufruf bleibt trotzdem aus: `coach/pipeline.py` prüft `LMC_OFFLINE` vor dem
Schlüssel. `.env` ist gitignored.

Weitere Optionen: `--bericht <ordner>` (Standard `logs/cloudtest/<datum_uhrzeit>_<modus>/`), `--referenz`,
`--audio`, `--agenda-prompt` (Standard: die Dateien unter `testbibliothek/cloudtest/`), `--chromium`
(Standard `/usr/bin/chromium`).

**Server vorher/danach beenden** – auf dem Pi läuft wenig Speicher frei (Immich, Paperless); keinen
`python -m coach`-Prozess nach dem Lauf stehen lassen.

## Testmaterial

`testbibliothek/cloudtest/` (Drehbuch/Referenz/Agenda-Text im Git, `meeting.wav` per `.gitignore`
ausgenommen). Gebaut mit `testbibliothek/cloudtest/bauen.py` aus vorhandenem, schon vertontem synthetischem
Material (`~/arbeit/lmc-vertonung/vereinsrunde/`, Azure-Stimmen) statt neu zu erzeugen – das deckt allein
fünf der sechs geforderten Ereignisse ab (siehe `docs/testlauf_synthetisch.md`); nur eine „Aufgabe ohne
Zuständige/n“ fehlte und wurde ergänzt. Dazu eingeschnitten: die fünf Anweisungen an Nestor aus dem Ticket
(eigene Azure-Stimme „alloy“, im Material sonst ungenutzt). `referenz.json` hält alle Zeitmarken.

Ein Ausschnitt mit echten (nicht synthetischen) Stimmen aus einer öffentlichen Aufnahme ist bewusst
ausgelassen – hätte einen Download (yt-dlp) und einen manuellen Zuschnitt gebraucht, siehe Bericht des
Laufs, der das Material gebaut hat.

Neu bauen: `~/.venvs/lmc/bin/python testbibliothek/cloudtest/bauen.py` (kostet nichts – Azure läuft über
Teachbuddys eigenes Kontingent auf diesem Rechner).

## Was geprüft wird

Mitgeschnitten wird aus der laufenden Seite selbst (sie hält ihren Zustand über die gleiche WebSocket wie
das Dashboard aktuell) alle zwei Sekunden: Transkript, Hinweise, Agendawechsel, Karten, Kosten, Fehler.
Die Prüfliste vergleicht das gegen `referenz.json`:

- je eingebautem Ereignis (Monolog, Agendawechsel mit Ansage, Abschweifung, Kraftausdruck, Beschluss,
  Aufgabe ohne Zuständigkeit): erkannt ja/nein, Verzug
- je Anweisung an Nestor: beantwortet, Zeit bis zur Antwort, Karte da
- keine Einträge in `fehler`
- im Modus „Auf Knopfdruck“: kein KI-Aufruf vor dem ersten Knopf, Wartezeit je Knopf
- Zeit bis die Startseite steht (Kaltstart)

**Ohne OpenAI-Schlüssel bzw. mit `LMC_OFFLINE=1`** am Server laufen alle KI-Prüfpunkte als „übersprungen
(offline)“ statt als Fehler – Monolog, Redeanteile, Überlappung und Zeit sind lokale Signale (keine
KI nötig, Lastenheft Abschnitt 3) und werden auch offline echt geprüft. So lässt sich der Ablauf des
Skripts ohne API-Kosten prüfen; der echte Lauf mit KI-Antworten ist ein eigener Schritt.

Ergebnis je Lauf: `logs/cloudtest/<datum_uhrzeit>_<modus>/bericht.md` (+ `bericht.json`) mit Prüfliste,
Messwerten, Kosten und verlinkten Screenshots (Startseite, Agenda-Tabelle, Dashboard bei 2:45/5:30/9:30,
Abschlussseite).

## Kosten

Das Testmaterial kostet nichts (Azure über Teachbuddys Kontingent). Ein Lauf mit `LMC_OFFLINE=1` kostet
nichts. Ein echter Lauf mit Schlüssel kostet wie im Lastenheft angegeben (Live ≤ 2 $/h, Knopfdruck ≤
0,7 $/h) – die tatsächlichen Kosten stehen im jeweiligen Bericht.
