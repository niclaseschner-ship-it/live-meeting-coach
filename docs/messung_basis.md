# Messung Nestor Basis (Mistral)

Ticket #13 · Stand 08.10.2026 · Skript: [`scripts/basis_messen.py`](../scripts/basis_messen.py) (Rohdaten unter
`logs/basis/`, nicht im Git)

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
