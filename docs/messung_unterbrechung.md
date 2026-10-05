# Messung Regel 1 „Ausreden lassen“: Unterbrechungen erkennen

Stand 05.10.2026 · `coach/unterbrechung.py`, `scripts/bench_unterbrechung.py`, `tests/test_unterbrechung.py`

## Kurzfassung

- **Brauchbar:** Ein Sprecherwechsel ohne Pause, nach dem die neue Person das Wort behält, trennt wild und
  geordnet deutlich. Die empfohlene Variante V2 liefert **13,3 je 10 min in der Talkshow**, **0–0,8 in
  geordneten Proben** (Stadtrat, Ahaus, Zoom, Landtag Freital). Das Ziel „≤ 1 Fehlalarm je 10 min geordnet“
  ist erreicht.
- **Nicht brauchbar:** Kurze Zwischenrufe (Bundestag) lassen sich so nicht erkennen. Nach der
  Arbeitsdefinition sind sie aber auch keine Unterbrechung, weil die Rednerin weiterspricht. Die
  Stimmen-Mischung taugt weder für das eine noch das andere: Sie schlägt in geordneten Proben genauso oft
  an (Zoom und Ahaus je 7,5 je 10 min) wie in der Talkshow oder öfter (Talkshow 1,7).
- **Offen:** Ob A mitten im Satz war, prüft das Verfahren nicht. Dafür fehlt Text je Sprecher. Außerdem
  stammen Schwellen und Messung aus denselben sechs Aufnahmen.

## Verfahren (V2, `unterbrechungen()`)

Als Eingabe dient nur, was live vorliegt: die VAD-Äußerungen, darin die Abschnitte aus
`Stimmen.analysieren` (Fenster 1,5 s, Schritt 0,75 s) und der Pegel je 0,25 s (`pegel_db(proben)`).

1. Läufe je Person bilden. Lücken unter 1 s werden überbrückt.
2. Ein Wechsel A → B zählt nur, wenn alle drei Bedingungen gelten:
   - A hat vorher **≥ 3 s** gesprochen.
   - B spricht danach **≥ 3 s**, ohne dass A zurückkommt. Damit gilt „A bricht ab, B behält das Wort“.
     Rückmeldungen wie „ja“ oder „mhm“ verschwinden schon durch die Fensterglättung.
   - Es gab **keine Pause**: A und B liegen in derselben VAD-Äußerung, also ohne Pause ≥ 0,5 s.
     Zusätzlich fällt der Pegel im Bereich −1 s … +0,5 s um die Wechselstelle nicht mehr als **15 dB**
     unter den mittleren Sprachpegel der Äußerung. Ein solcher Einbruch wäre eine kurze Pause und damit
     eine reguläre Übergabe.
3. Ergebnis: Zeit, Person A, Person B, Dauer davor und danach. Ein einmal gefundener Wechsel bleibt bei
   wachsender Spur erhalten (geprüft auf drei Proben und im Test).

Varianten im Vergleich:
- **V0 (Ausgangswert):** Folgen von Stimmen-Mischungen.
- **V1:** wie V2, aber ohne Pegelprüfung.
- **V3:** wie V2, aber streng mit 4 s / 4 s.
- **Verworfen**, weil sie den Kontrast verschlechterten: „Mischung am Wechsel“, „Pegelanstieg am
  Wechsel“, A-B-A-Einschübe als Einwurf, Pegelsprünge in laufender Rede.

## Wahrheit

- **Talkshow `untervier`:** Kandidaten aus der Sprecher-Referenz (gpt-4o-transcribe-diarize). Ein
  Kandidat ist ein Wechsel des Rederechts (Lauf ≥ 2 s, danach Lauf ≥ 3 s) ohne Lücke oder mit
  Zickzack-Schnipseln unter 0,5 s an der Wechselstelle. Die Diarisierung zerlegt Überlappung in solche
  Schnipsel. Das ergibt 12 Kandidaten, also 10 je 10 min. Gegengehört ist das nicht. Die Markierung von
  Hand fehlt weiterhin.
- **Geordnete Proben:** Die Referenzen enthalten keinen solchen Wechsel. Jedes Ereignis ist dort ein
  Fehlalarm.
- **Bundestag:** 31 protokollierte Zwischenrufe, Untertitelzeit ± 3 s.

## Zahlen (je 10 min; Talkshow: Treffer/Kandidaten; Bundestag: Treffer/Zwischenrufe)

| Probe | V0 Mischung | V1 | **V2 (empfohlen)** | V3 streng |
|---|---|---|---|---|
| `untervier` (Talkshow, wild) | 1,7 · 0/12 | 18,3 · 12/12 | **13,3 · 10/12** | 7,5 · 7/12 |
| `bundestag_ordnungsrufe` | 25,0 · 9/31 | 10,0 · 5/31 | **6,7 · 3/31** | 5,0 · 2/31 |
| `freital_buergerversammlung` (Landtag) | 3,3 | 0,0 | **0,0** | 0,0 |
| `zoom_inca4d` (geordnet) | 7,5 | 2,5 | **0,8** | 0,0 |
| `stadtrat` (geordnet) | 3,3 | 0,0 | **0,0** | 0,0 |
| `ahaus_rat` (geordnet) | 7,5 | 1,7 | **0,0** | 0,0 |

Was dahinter steckt:
- **Talkshow, V2:** 16 Stellen, davon 10 bei Kandidaten. Die übrigen 6 liegen alle in unruhigen
  Passagen mit Zickzack in der Referenz, aber außerhalb der Kandidatendefinition:
  - 3:09 und 11:09/11:12: Einwürfe der Moderation von 2–3 s, danach spricht der Gast weiter. Als Einwurf
    sind sie grenzwertig, weil B knapp 3 s spricht.
  - 7:02, 8:20 und 8:45: Mehrere Personen reden durcheinander.

  Mit der Pegelprüfung fallen die echten Übergaben mit kurzer Pause heraus, z. B. 4:27 und 9:01. V1 hatte
  sie noch gezählt.
- **Fehlalarme geordnet:**
  - Zoom 7:23: Die Sprecherzuordnung springt mitten in einem Beitrag.
  - V1 in Ahaus: „Dann Herr …“ der Bürgermeisterin, das Ratsmitglied setzt sofort ein. Die Pegelprüfung
    fängt das ab.
- **Landtag Freital:** Der Präsident fällt zweimal mit „Redezeit geht zu Ende“ ins Wort. Die Redenden
  sprechen weiter, also richtig keine Unterbrechung.
- **Bundestag, V2:** 8 Stellen, davon 3 bei Zwischenrufen. Die übrigen sind nicht geprüft; vermutlich
  Schnitte des Zusammenschnitts und Übernahmen durch das Präsidium.
- **Parameter:** Die Pegelschwelle ist zwischen 12 und 20 dB stabil (Talkshow 13,3, geordnet ≤ 0,8).
  Bei 25 dB steigen die Fehlalarme. Mit A ≥ 2 s statt 3 s kommt in Ahaus 1 Fehlalarm hinzu.
- **Verzug:** Erkannt wird mit dem Ende der Äußerung, in der B 3 s erreicht. Median 12 s (Talkshow) bzw.
  18 s (Bundestag), höchstens 68 s bei langen Äußerungen ohne Pause. Für einen gesammelten
  5-Minuten-Hinweis genügt das.

## Grenzen

- **Satzabbruch nicht geprüft:** In der Talkshow sind auch flüssige Übergaben ohne Pause häufig. Die Rate
  schätzt deshalb „Übernahmen ohne Pause“ und nicht „Unterbrechungen im strengen Sinn“. Die
  Satzprüfung über Live-Text oder Sprachmodell an der Wechselstelle wäre Stufe 2. Sie braucht Text je
  Sprecher (siehe Knackpunkt in `gespraechsregeln.md`).
- **Ungeprüfte Wahrheit:** Die Kandidaten der Talkshow kommen selbst aus einem Modell. Gemessen sind
  Richtung und Größenordnung, keine belastbare Trefferquote.
- **Kleine Datenbasis:** Schwellen und Messung stammen aus denselben Aufnahmen. Raumtest und Rollenspiel
  müssen das bestätigen, ein einzelnes Raummikrofon besonders.

## Empfehlung für die Pipeline (nicht umgesetzt; Dateien eines anderen Agenten)

1. In der Stimmanalyse je Äußerung `Aeusserung(start, ende, erg["abschnitte"], pegel_db(proben))` merken.
   Die letzten ~6 min genügen.
2. Nach jeder Äußerung `unterbrechungen(aeusserungen)` mit den Standardwerten aufrufen: `MIN_VORHER = 3`,
   `MIN_NACHHER = 3`, `PAUSE_DB = 15`. Dann die Stellen der letzten 5 min zählen; `je_10_min()` hilft
   beim Vergleich.
3. Hinweis nur, wenn die Gruppe Regel 1 gewählt hat, und erst ab **≥ 3 Stellen in 5 min**. Das entspricht
   6 je 10 min: geordnet höchstens 0,8, Talkshow 13. Danach frühestens nach 5 min wieder.
4. Text an die Gruppe, ohne Namen und beobachtend:
   `hinweistext(n, 5)` + `regeln.vereinbart(...)`. Beispiel: „In den letzten 5 Minuten hat 4-mal jemand
   das Wort übernommen, während noch gesprochen wurde. Vereinbart war: Ausreden lassen.“
5. Wer wen unterbrochen hat (`von_person`/`zu_person`), nur in der Moderationsansicht, nicht speichern.
6. Die Stimmen-Mischung nicht für Regel 1 verwenden. Sie bleibt technisches Signal der Überlappungs-Ampel.
7. Prüfstufe bleibt „Hinweis möglich, kann irren“.

## Sprecher-Referenzen Ahaus und Freital (neu)

- Erstellt mit gpt-4o-transcribe-diarize (de, `diarized_json`, `chunking_strategy="auto"`) auf 16 kHz.
  Texte geprüft, in `probe.json` nur Zeiten und Personen. `sprecher_quelle` beschreibt die Korrekturen.
- **Ahaus:** Die Diarisierung ist schwach. Sie fasst mehrere Ratsmitglieder unter einem Label zusammen
  und übersetzt große Teile ins Englische. Die Personen sind deshalb je Wortmeldung nach der
  Worterteilung der Bürgermeisterin vergeben. Zwei unklare Stellen (265–296 s, 579–655 s) bleiben
  Lücken.
  - `bench_sprecher.py`: **82,3 % richtig, 7 Personen** (Soll 12; nur 9 davon sprechen ≥ 10 s).
- **Freital:** Der Ausschnitt ist keine Bürgerversammlung, sondern die Aktuelle Debatte im Sächsischen
  Landtag (Präsident, drei Redebeiträge). Die Diarisierung ist plausibel. Zwei Rednerinnen mit demselben
  Label wurden nach Inhalt getrennt.
  - `bench_sprecher.py`: **97,2 % richtig, 4 Personen** (Soll 4).
  - `titel`, `setting` und `eignung` der Probe sollten entsprechend korrigiert werden. Hier bewusst nicht
    geändert, nur `referenz` ergänzt.

## Kosten

- **Zwei Aufrufe gpt-4o-transcribe-diarize** über je 12 min:
  - Ahaus: 17 134 Audio-Eingabe-, 1 496 Text-Eingabe- und 21 730 Ausgabe-Tokens.
  - Freital: 11 894 Audio-Eingabe-, 830 Text-Eingabe- und 21 198 Ausgabe-Tokens.
- **Nach Token-Preisen** ($6 je 1 M Audio-Eingabe, $2,50 je 1 M Text-Eingabe, $10 je 1 M Ausgabe) sind das
  **etwa 0,61 $**. Davon gehen ~0,43 $ auf die Ausgabe, die durch Wiederholungs-Halluzinationen und
  Übersetzungen ungewöhnlich lang ausfiel. Nach der Minutenschätzung ($0,006/min) wären es 0,14 $.
- Das Budget von 0,30 $ ist damit bei Token-Abrechnung **überschritten**. Für weitere Referenzen erst
  die Abrechnung im OpenAI-Dashboard prüfen.
- Alles Übrige lief lokal ohne Kosten.
