# Cloud-Testlauf

Prüft Nestor so, wie ein echter Kunde ihn benutzt: ein echter Browser (Chromium ohne Bildschirm) meldet
sich an (falls nötig), wählt die Stufe (Basis/Premium, Ticket #13), richtet das Meeting über die
Agenda-per-Prompt-Eingabe ein, hört zehn Minuten in Echtzeit zu (Meeting-Audio aus einer Datei über ein
steuerbares Mikrofon, kein Vorspulen; die Teilnehmenden warten, bis Nestor fertig ist, siehe
[Abwechselnd reden](#abwechselnd-reden-ticket-25)), mit „Nur auf Knopfdruck“ drückt es die Knöpfe zu festen
Zeiten, und geht am Ende durch den Abschluss. Läuft
gegen eine beliebige Adresse: lokal (`python -m coach` oder Docker-Container) und gegen die Cloud.
`scripts/cloudtest_bewerten.py` (Ticket #11) wertet einen Lauf danach nach einer Qualitätsrubrik aus
([qualitaet.md](qualitaet.md)).

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
(Standard `/usr/bin/chromium`), `--am-stueck` (alter Modus für Lasttests: Audio am Stück, niemand wartet auf
Nestor), `--bis <s>` (nur die ersten s Sekunden des Materials – kurze Probeläufe, z. B. `--bis 250` für
Begrüßung, die ersten Fragen und beide Rückfragen in ~5 min).

**Server vorher/danach beenden** – auf dem Pi läuft wenig Speicher frei (Immich, Paperless); keinen
`python -m coach`-Prozess nach dem Lauf stehen lassen.

## Testmaterial

`testbibliothek/cloudtest/` (Drehbuch/Referenz/Agenda-Text im Git, die `.wav`-Dateien per `.gitignore`
ausgenommen). Zwei unabhängige Materialien, mit `--referenz`/`--audio`/`--agenda-prompt` gewählt:

**#9, Vereinsrunde** (`referenz.json`/`meeting.wav`/`agenda_prompt.txt`, Standard): gebaut mit
`testbibliothek/cloudtest/bauen.py` aus vorhandenem, schon vertontem synthetischem Material
(`~/arbeit/lmc-vertonung/vereinsrunde/`, Azure-Stimmen) statt neu zu erzeugen – das deckt allein fünf der
sechs geforderten Ereignisse ab (siehe `docs/testlauf_synthetisch.md`); nur eine „Aufgabe ohne Zuständige/n“
fehlte und wurde ergänzt. Dazu eingeschnitten: die fünf Anweisungen an Nestor aus dem Ticket (eigene
Azure-Stimme „alloy“, im Material sonst ungenutzt).

**#11, Incident-Review** (`referenz_grenzfaelle.json`/`meeting_grenzfaelle.wav`/`agenda_prompt_grenzfaelle.txt`):
gebaut mit `testbibliothek/cloudtest/bauen_grenzfaelle.py` – neues Drehbuch per Codex („Ausfall des
Kundenportals am Montag“, IT-Team, viel Fachsprache), ein ausdrücklich >90 s langer Monolog (in #9 blieben
einzelne „monolog“-Äußerungen oft unter der 60-s-Schwelle der lokalen Erkennung – kein Fehler in Nestor,
nur zu kurzes Material), plus die zwölf Grenzfälle der Ansprache aus dem Ticket (`referenz.json["grenzfaelle"]`,
je mit erwartetem Verhalten). Seit #25 trägt jeder Grenzfall `warten` (siehe unten), und zwei **Rückfragen im
Redefluss** kamen dazu: `1r_rueckfrage_reicht` („Und reicht das noch für alle Punkte?“ nach der Zeitfrage)
und `2r_rueckfrage_wer` („Und wer übernimmt das?“ nach „Was haben wir zu Punkt eins beschlossen?“) – ohne
Namen, direkt nach Nestors Antwort, danach geht das Meeting normal weiter. Eingeschnitten mit
`bauen_grenzfaelle.py --rueckfragen-nachtragen` (nur die beiden Sätze neu vertont, Azure „alloy“, 0 $; alle
Zeiten danach verschoben). **Die alte `meeting_grenzfaelle.wav` passt nicht mehr zur neuen Referenz** – der
Lauf bricht dann mit „Testmaterial passt nicht“ ab; dann die WAV neu bauen bzw. nachtragen.

Ein Ausschnitt mit echten (nicht synthetischen) Stimmen aus einer öffentlichen Aufnahme ist bewusst
ausgelassen – hätte einen Download (yt-dlp) und einen manuellen Zuschnitt gebraucht, siehe Bericht des
Laufs, der das Material gebaut hat.

Neu bauen: `~/.venvs/lmc/bin/python testbibliothek/cloudtest/bauen.py` bzw. `bauen_grenzfaelle.py` (kostet
nichts – Azure läuft über Teachbuddys eigenes Kontingent auf diesem Rechner, das Drehbuch über Codex/Abo).

## Abwechselnd reden (Ticket #25)

Bis #25 lief das Meeting-Audio am Stück (`--use-file-for-fake-audio-capture`). Seit Nestor unterbrechbar ist
(#23), hätte der Test ihn ständig unterbrochen. Jetzt (Standard; `--am-stueck` für den alten Modus):

- **Steuerbares Mikrofon:** ein Init-Script (`scripts/cloudtest_takt.py: INIT_SCRIPT`) ersetzt
  `navigator.mediaDevices.getUserMedia` durch einen Strom aus einer WebAudio-Quelle. Der Test lädt jeden
  Abschnitt als PCM in den Browser und startet ihn; dazwischen liefert das „Mikrofon“ Stille wie ein echtes
  im ruhigen Raum. Produktcode bleibt unverändert.
- **Abschnitte:** die Audiodatei wird an den Satzgrenzen aus der Referenz geschnitten – am Ende jedes
  Grenzfalls (bzw. Teils) mit `warten`, im #9-Material nach jeder Nestor-Anweisung. Den Vorlauf (25 s Stille
  für die Begrüßung) und die Stille, die das Material nach jeder Frage für die Antwort am Stück vorsah,
  überspringt der Test bis auf 0,8 s – nach Nestors Antwort redet die Runde gleich weiter.
- **Warten, bis Nestor fertig ist:** vor dem ersten Abschnitt die Begrüßung, nach jedem Schnitt die Antwort.
  Fertig heißt: Nestor hat reagiert (Ton oder Zustand denkt/recherchiert/spricht), sein Zustand ist wieder
  `bereit`/`gespraech`, seit ≥ 1,5 s kam kein `stimme`-Paket, im Browser steht keine Wiedergabe mehr an
  (`stimme.naechste` in static/basis.js) – und das 2 s am Stück. Reagiert Nestor 10 s lang gar nicht (Nuschel-
  fälle, offline), geht es weiter (📝 „keine Reaktion“). Zeitlimit 60 s, Begrüßung 120 s – dann ❌ statt Hängen.
- **`warten` in der Referenz:** `true` (bis fertig), `"bestaetigung"` (nur bis die erste Rückmeldung zu Ende
  gesprochen ist – Bild/Folie: „macht ruhig weiter“), `false` (gar nicht: Hineinreden #20 und alle Sätze, auf
  die Nestor nicht reagieren soll). Ohne Angabe gilt ein Standard je `erwartet`.
- **Meetinguhr:** die Regie schreibt einen Zeitplan (Quellzeit ↔ Laufachse) in `bericht.json`
  (`messwerte.takt`); über den Median aus `zustand.zeit` − Empfangszeit kommt er auf die Meetinguhr. Prüfliste,
  Bewertung und HTML-Bericht rechnen die Referenzzeiten damit um (Pausen verschieben alles danach); der
  Segment-Abgleich schätzt nur noch den Restversatz (Verarbeitung bis zum Transkript, lokal ~0,3 s).

Zusätzliche Prüfpunkte (`Takt: …` in bericht.md, eigene Tabelle „Abwechselnd reden“ in bewertung.md; sie
zählen nicht in Treffer/Verpasst, damit die mit älteren Läufen vergleichbar bleiben):

- Begrüßung ungestört durchgelaufen (fertig, kein `stimme_stopp`)
- je Schnitt: Nestor abgewartet – mit **Zeit bis zur ersten sichtbaren Bestätigung** (Zustand angesprochen/
  denkt/recherchiert/spricht oder seit #21 der erste mitlaufende Text `nestor_text`; stand er beim Frage-Ende
  schon darauf: 0 s) und **erstem Ton** (seit #21 meist die Bestätigungs-Floskel, `stimme` mit `floskel`)
- je Rückfrage im Redefluss: beantwortet und danach neue Segmente im Transkript (Meeting läuft weiter)
- **zu jeder Antwort Ton und Text** (#21 Punkt 5): jeder Ton-Block hat einen Text und umgekehrt; Begrüßung
  ausgenommen. Text ist seit #21 jede Äußerung aus `nestor_text` (beginnt mit `neu`, läuft in `#nestor-feld`/
  `#nf-text` mit); bei älteren Läufen ohne diese Nachricht `assistent.letzte` (früher Karte/Untertitel)
- **Meetinguhr läuft:** steht `zustand.zeit` 90 s still, endet der Lauf mit ❌ statt bis zum Notausgang zu
  warten (Cloudlauf 08.10.: Server verarbeitete ab 217,6 s nichts mehr)
- **Tonspur im Bericht ≤ 1 s** neben der Ankunft der Stimme (#21 Punkt 5), je Ton-Block. `nestor_stimme.wav`
  berücksichtigt dafür jetzt `stimme_stopp` wie der Browser (abgeschnitten, danach wieder ab Ankunft).

## Sprechtaste und Bedienung (Ticket #27)

- **Basis = Funkgerät:** Nestor Basis reagiert nicht auf „Nestor“. Im Takt-Modus hält die Regie deshalb die
  Sprechtaste (Leertaste) um jede Ansprache an Nestor gedrückt – 0,3 s vor dem Satz bis 0,4 s danach
  (`cloudtest_takt.taste_fenster`: jede Anweisung im #9-Schema und jeder Grenzfall, dessen Erwartung eine Antwort
  ist, auch Rückfragen und das Hineinreden; Fehlauslöser, späte Rückfrage und „Nein“ im Normalsatz ohne Taste,
  `taste` in der Referenz überschreibt). Das Material bleibt dasselbe: die Sätze beginnen weiter mit „Nestor, …“,
  vorher wird die Taste gedrückt. Premium nutzt den Namen wie bisher.
- **Bedienplan** (beide Stufen, nicht mit „Nur auf Knopfdruck“): einmal „Wo stehen wir?“ (ab 2:00 Quellzeit), der
  Band-Knopf „Zusammenfassen ›“, sobald das Fünf-Minuten-Band erscheint (sonst am Ende der Knopf „Zusammenfassen“),
  ✕ an einem langen Auftrag, sobald der Arbeitsring einen zeigt, und einmal „Still“ 1,5 s nach dem ersten Ton einer
  Antwort ab 7:30. Nach jedem Knopf wartet die Regie wie nach einer Frage.
- **Mitschnitt:** Jeder Druck steht in `bericht.json` unter `messwerte.takt.bedienung` (Laufachse, bei der
  Sprechtaste mit Loslassen, Dauer und Satz). `cloudtest_takt.bedienung_auswerten` rechnet die Meetinguhr und
  Nestors Reaktion aus dem WebSocket-Mitschnitt: Bestätigung (erster Text bzw. Ton), erster Ton, neue Karte im
  Verlauf; bei ✕ ob der Auftrag weg ist, bei „Still“ ob die Stimme stoppt.
- **Bericht:** im HTML-Zeitstrahl eine eigene violette Spur (👆) – Knopfname, Meetinguhr und bei der Sprechtaste der
  Satz; ein Klick springt ins Audio. In `bewertung.md` die Tabelle „Bedienung“ (Zeit, Knopf, Satz, Reaktion).
- **Cookie nach „Fertig“ (Cloud):** geprüft wird, dass das alte Meeting-Cookie weg ist. Die Startseite bekommt vom
  Worker sofort ein neues (neues Meeting) – der frühere Befund „noch gesetzt“ war dieses neue Cookie.

## Was geprüft wird

Mitgeschnitten wird aus der Seite selbst: alle Nachrichten auf der Zustands-WebSocket mit Zeitstempel
(`<lauf>/ws.jsonl`, Ticket #11 – die einzige verlässliche Quelle, ein reines 2-Sekunden-Polling verpasst
kurzlebige Hinweise und Kartenwechsel), dazu Konsolen-Fehler und fehlgeschlagene Netzanfragen des Browsers
und ein Mitschnitt von Nestors gesprochenen Antworten (`<lauf>/nestor_stimme.wav`, aus den `stimme`-
Nachrichten). Die Prüfliste vergleicht das gegen `referenz.json` – je Ereignistyp das passende Signal, nicht
pauschal „ein Hinweis irgendwo in der Nähe“:

- Agendawechsel mit Ansage: `aktiver_punkt` ändert sich
- Abschweifung/Kraftausdruck: die jeweilige Hinweisart (Fokus/Ton)
- Beschluss/Aufgabe ohne Zuständigkeit: Hinweisart „ergebnisse“ oder ein Ergebnis direkt am Agendapunkt
- Monolog: lokal, läuft auch mit `LMC_OFFLINE`
- je Anweisung an Nestor/Grenzfall: erster Ton (stimme-Nachricht), neue Karte oder – bei „Bild“/„Überblick“
  – eine neue Live-Bild-Version; je nach erwartetem Verhalten aus `referenz.json` wird eine Reaktion als
  Treffer oder (bei "sollte NICHT reagieren") als Fehlauslöser gewertet
- keine Einträge in `fehler`
- mit `--nur-knopfdruck`: kein KI-Aufruf vor dem ersten Knopf, Wartezeit je Knopf
- Zeit bis die Startseite steht (Kaltstart), Wartezeit bis das Abschlusspaket fertig ist (bis zu 4 min,
  selbst ein Nutzer-Erlebnis-Wert)
- „Fertig“ am Ende führt zurück zur Startseite und setzt den Server-Zustand zurück (Cloud: das
  Meeting-Cookie `nestor_meeting` fällt weg) – ein neuer Aufruf bekommt ein neues (leeres) Meeting statt das
  gerade beendete wiederzuverwenden (Ticket #17 Punkt 7/#12)

Vor „Meeting starten“ wählt der Lauf die Regeln **„Respektvoller Ton“** und **„Ergebnisse festhalten“** an
(`coach/regeln.py: STANDARD` enthält beide nicht) – ohne das kann die Prüfliste Kraftausdruck/Beschluss gar
nicht erkennen (Ticket #17 Punkt 7).

**Mit `--nur-knopfdruck`** reagiert Nestor grundsätzlich nicht auf spontane Ansprache (kein KI-Aufruf ohne
Knopf). Eine Nestor-Anweisung/ein Grenzfall, der eine Antwort erwartet, zählt dort deshalb nicht als „fehlt“,
sondern als „beobachtet“ (📝) – eine Eigenschaft des Modus, kein Mangel (Ticket #17 Punkt 7). Grenzfälle, die
ausdrücklich KEINE Reaktion erwarten, bleiben normal geprüft.

Manche Grenzfälle lassen sich offline bzw. ohne echte Nestor-Stimme nicht eindeutig werten (z. B.
Nuschelvarianten „Ergebnis dokumentieren“, Hineinreden) – die stehen als „beobachtet“ (📝) im Bericht, ohne
Note.

**Ohne OpenAI-/Mistral-Schlüssel bzw. mit `LMC_OFFLINE=1`** am Server laufen alle KI-Prüfpunkte als
„übersprungen (offline)“ statt als Fehler – Monolog, Redeanteile, Überlappung und Zeit sind lokale Signale
(keine KI nötig, Lastenheft Abschnitt 3) und werden auch offline echt geprüft. So lässt sich der Ablauf des
Skripts ohne API-Kosten prüfen; der echte Lauf mit KI-Antworten ist ein eigener Schritt. Seit Ticket #13
blendet die Startseite eine Stufe ohne jeden Schlüssel-String aus – für einen Offline-Probelauf trotzdem
irgendein Platzhalter-Wert in `OPENAI_API_KEY`/`MISTRAL_API_KEY` nötig (echte Aufrufe bleiben aus,
`coach/pipeline.py` prüft `LMC_OFFLINE` zuerst).

Ergebnis je Lauf: `logs/cloudtest/<datum_uhrzeit>_<modus>/bericht.md` (+ `bericht.json`, `ws.jsonl`,
`nestor_stimme.wav`) mit Prüfliste, Messwerten, Kosten und verlinkten Screenshots (Startseite,
Agenda-Tabelle, Abschlussseite, Dashboard alle 30 s plus an jedem Ereignis/jeder Anweisung/jedem
Grenzfall).

## HTML-Testbericht zum Präsentieren (Ticket #19)

```
~/.venvs/lmc/bin/python scripts/cloudtest_bericht.py logs/cloudtest/<lauf>
```

Baut aus `bericht.json` + `ws.jsonl` (dieselbe Prüflisten-/Versatz-Logik wie `cloudtest_bewerten.py`, nicht
zweimal gerechnet) und – wenn vorhanden – `bewertung.md` eine einzige, eigenständige `<lauf>/bericht.html`:

- **Audiospieler** mit dem Meeting-Ton (seit #25: im abwechselnden Modus aus dem Zeitplan zusammengesetzt,
  mit den Pausen, in denen alle auf Nestor gewartet haben; beide Spuren auf derselben Achse; der Zeitstrahl
  zeigt zusätzlich je Pause eine Marke „Nestor abgewartet“) (`testbibliothek/cloudtest/meeting[_grenzfaelle].wav`, aus dem
  `referenz_datei`-Namen abgeleitet) gemischt mit Nestors Stimme (`<lauf>/nestor_stimme.wav`, falls
  vorhanden – mit `--nur-knopfdruck` gibt es keine, siehe oben). Beide Spuren werden um ihren jeweils
  gemessenen Versatz auf die Meetinguhr verschoben: der Meeting-Ton um den Versatz Referenzzeit↔Meetinguhr
  (Segment-Abgleich, wie in `cloudtest_bewerten.py`), Nestors Stimme separat über die Zustandsmeldung, die
  einer `stimme`-Nachricht am nächsten liegt (robuster als `seite_bis_meeting_start_s`, das in älteren
  Berichten fehlt) – Nestor klingt dadurch etwas lauter (+4 dB) und beginnt seine Begrüßung bei ~0 s auf der
  Meetinguhr. Export als MP3 ~96 kbit/s (ffmpeg).
- **Zeitstrahl** darunter: eine Marke je Dashboard-Screenshot (Vorschaubild beim Überfahren, Klick springt
  im Audio dorthin) und eine farbige Marke je Ereignis/Nestor-Anweisung/Grenzfall aus der Prüfliste
  (✅ ok/❌ fehlt/📝 beobachtet/⏭️ offline, Klick springt ebenfalls dorthin).
- Beim Abspielen wechselt der große Screenshot automatisch zum zuletzt erreichten Zeitpunkt.
- **Kopf** mit den Kennzahlen und Urteilen aus `bewertung.md` (muss vorher mit `cloudtest_bewerten.py`
  erzeugt worden sein, sonst nur Ablauf/Screenshots ohne Kennzahlen-Kopf).
- Eine Datei, alles eingebettet als Base64 (Audio als MP3, Screenshots als WebP, 640 px breit) – funktioniert
  offline und am Handy, hell/dunkel (`prefers-color-scheme`). Rund 10–13 MB, meist Audio.

`cloudtest_bewerten.py` ruft das selbst am Ende auf (Fehler dabei brechen den Lauf nicht ab, nur ein
Hinweis) – ein `bericht.html` ist seitdem **Standard für jeden Lauf**, kein separater Schritt mehr nötig.

## Bewertung nach der Qualitätsrubrik (Ticket #11)

```
~/.venvs/lmc/bin/python scripts/cloudtest_bewerten.py logs/cloudtest/<lauf>
```

Rechnet aus `bericht.json` (das hat die Signal-Erkennung schon gemacht) und `ws.jsonl` die Kennzahlen aus
[`qualitaet.md`](qualitaet.md) – Treffer, Verpasst, Fehlauslöser, Antwortzeit (Median/längste), Hinweise je
10 Minuten, Kosten – und lässt eine Auswahl Screenshots (Start, Abschluss, bis zu sechs übers Meeting
verteilt) von Codex über das ChatGPT-Abo (`codex exec -i <Bild> …`, geprüft: funktioniert, 0 $) nach der
Rubrik mit 1–5 bewerten: Antwortgüte, Verständlichkeit auf einen Blick, Live-Bild/Überblick-Treue, Abschluss,
Gesamteindruck. Schreibt `<lauf>/bewertung.md` mit Kennzahlen-Tabelle, Urteilen und den „fünf schlimmsten
Stellen“ (die ❌-Prüfpunkte, mit Screenshot wo möglich). Ohne Codex (`--ohne-urteil` oder wenn der Aufruf
fehlschlägt): Kennzahlen und schlimmste Stellen stehen trotzdem da, die Urteile als „übersprungen“ – dann
entscheidet, wer den Bericht liest, von Auge anhand der Screenshots.

## Kosten

Das Testmaterial kostet nichts (Azure über Teachbuddys Kontingent, Drehbücher über Codex/Abo). Ein Lauf mit
`LMC_OFFLINE=1` kostet nichts, die Bewertung ebenso (Codex/Abo). Ein echter Lauf mit Schlüssel kostet wie im
Lastenheft angegeben (Premium ≤ 2 $/h, Basis ≤ 0,7 $/h) – die tatsächlichen Kosten stehen im jeweiligen
Bericht.
