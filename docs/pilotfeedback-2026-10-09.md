# Technische Rückverfolgung des Pilotfeedbacks

Stand 09.10.2026. Diese Matrix fasst technische Anforderungen aus den privaten Pilotnotizen zusammen, ohne
Originalzitate oder personenbezogene Meetinginhalte zu übernehmen. Sie beschreibt Code- und Testbelege, nicht die
Abnahme eines Live-Piloten. Die folgende Matrix wurde vor Beginn der HTTPS-Abnahme erstellt. Der spätere
Belegstand und die ausdrücklich offenen Prüfungen stehen unter „Übergabe an Claude Opus“ am Ende.

| Ursprung / Thema | Umsetzung und Codebeleg | Ticket | Belegstand und offen |
|---|---|---|---|
| Variantenwahl: Fehler bei Auswahl darf nicht in einem scheinbar laufenden Meeting enden; Auswahl muss über Container-Neustarts gelten und beim Start zum tatsächlichen Serverzustand passen. | Startseite wechselt erst nach bestätigter Antwort; Cloudmiddleware speichert bestätigte Stufe/Modus im Durable Object, verwirft vom Browser gesetzte Vertrauensheader und setzt gespeicherte Werte für Folgeanfragen. Start prüft `X-Nestor-Erwartete-Stufe`. `static/start.js`, `cloudflare/src/variantenwahl.ts`, `coach/server.py`. | #54 Variante | Unit/API-Tests: `tests/test_variantenwahl_pilot.py`, `cloudflare/src/variantenwahl.test.ts`. Browser-Mock deckt HTTP-Fehler, Netzfehler und Doppelklick ab (`tests/test_pilot_ui_abnahme.py`); kein echter Cloud- oder Live-Klick. |
| Regel-Ampeln sollen nicht links versteckt sein; Kernbedienung soll kompakt bleiben und Zusatzaktionen sollen auffindbar, aber nachgeordnet sein. | Ampelzone liegt zwischen Kopfleiste und Aktionen (`static/index.html`). Fünf Kernaktionen sind Stand, Zusammenfassen, Lücken, Protokoll, Überblick; Meetingbild, Regelprüfung und Frage liegen unter „Weitere Aktionen“. Handyansicht hat dieselben Kernaktionen (`static/handy.html`). | #55 UI | Selektor-/Markup-Vertrag in `tests/test_pilot_ui_abnahme.py`; bisher kein visueller lokaler Abnahmeklick und kein Live-Klick. Responsive Wirkung und tatsächliche Kompaktheit daher noch nicht bestätigt. |
| Agenda-Eingabe per Mikrofon: Aufnahme soll durch Halten starten und beim Loslassen zur Verarbeitung gehen. | Pointer-/Tastatur-Halten und Freigabe im Agenda-Formular (`static/agenda.js`). | #56 Tests | Browser-Frontend-Mock in `test_agenda_mikro_pointer_hold_und_release_sind_getrennter_frontend_mock`; API-Antwort und Audioverarbeitung sind simuliert, kein Live-Sprachtest. |
| Monologdauer muss während eines langen, noch offenen VAD-Blocks weiterlaufen; Schwelle darf nicht erst nach Blockabschluss sichtbar werden. Kurze Pause darf nicht sofort zurücksetzen. | `monolog_live` nutzt frische VAD-Zeit zusätzlich zu Segmenten; 2,5-s-Frischefenster und 3-s Kettenlücke; Regelstatus zeigt Dauer und Schwelle. `coach/analyse.py`, `coach/pipeline.py`. | #57 Verhalten | Unit-Regressionen in `tests/test_monolog_pilot.py` und bestehende `tests/test_analyse.py`: fortlaufende Rede, Blockverzug, kurze Pause, echte Pause, bestätigter Wechsel. Kein Live-Mikrofonklick. |
| Monologwarnung darf bei ASR-Verzug nicht voreilig einer Person zugeordnet werden; Segmentbeginn allein ist kein Wechselbeleg. | Wechsel gilt erst mit vorherigem anderslautendem Sprechermaterial innerhalb der VAD-Phase als bestätigt; Dauer der neuen Kette läuft weiter live. Ohne Segmentierung kann die erste lange Phase anonym warnen. `coach/analyse.py`. | #57 Verhalten | Unit-Regressionen in `tests/test_monolog_pilot.py`; Stimmenzuordnung und Anzeige im echten Meeting nicht live abgenommen. |
| Natürliche Aufforderungen zum Bündeln/Zusammenfassen sollen den passenden Antwortbogen starten, beiläufige Erwähnungen in Fragen aber nicht kapern. | Eng umrissene Erkennung in `coach/bogen.py`; Positiv- und Negativbeispiele in `tests/test_bogen_sprachauftrag.py`. | #57 Verhalten | Unit-Tests belegen die Textklassifikation. Kein gesprochener Live-Pilotnachweis; keine Aussage über ASR-Qualität. |
| Ergebnisverarbeitung soll Aufgaben, Entscheidungen und offene Punkte im Verlauf erhalten und für Abschluss/Export nutzbar machen. | Abschnittsverarbeitung und Artefaktkarten in `coach/artefakte.py`; Protokoll/Meetingdaten und Export in `coach/abschluss.py`. ZIP enthält `meeting.json`, `tasks.json` (wenn vorhanden) und `technik.json`; Datenspende enthält `technik.json`. | #56 Tests | Regressionen u. a. `tests/test_artefakte.py`, `tests/test_abschluss.py`, `tests/test_technik_paket.py`. Testbelege prüfen Struktur/Dateiinhalte, nicht Vollständigkeit oder fachliche Richtigkeit in echten Meetings. |
| Angezeigte Inhalte sollen zur gewählten Stufe bzw. Bedienart passen; nicht verfügbare Funktionen dürfen nicht als gleichwertig versprochen werden. | Startwahl bestätigt Stufe/Modus; Aktionsleiste zeigt die fünf Kernaktionen und separat stufenabhängige Sprechtaste/Zusatzaktionen. Relevante Frontendpfade: `static/start.js`, `static/app.js`, `static/handy.js`, `static/index.html`, `static/handy.html`. | #55 UI / #54 Variante | API- und Quellvertragstests vorhanden; echter Wechsel Basis/Premium samt lokaler visueller Prüfung fehlt noch. |
| Voice-/Sprachauffälligkeiten: bisherige Rückmeldungen reichen nicht, um eine technische Ursache oder eine allgemeine Behebung zu belegen. | Basis nutzt das konfigurierte TTS-Modell `voxtral-mini-tts-latest` und die Mistral-Custom-Voice aus `LMC_BASIS_STIMME` (`coach/config.py`, `coach/mistral.py`). Der aktuelle Default ist eine KI-generierte Referenzstimme; eine hörbare Qualitätsaussage folgt daraus nicht. | zusätzliche Prüflücke; ggf. #56 Tests | Code belegt Konfiguration, nicht Aussprache, Sprachmischung oder Qualität des Live-Audios. Gezielter lokaler Hör-/Klicktest und Live-Klick stehen aus; Ursache bleibt offen. |
| Export-/Spendenpaket soll nachvollziehbare technische Auswahlmetadaten mitführen, ohne Geheimnisse zu exportieren. | `technik.json` wird in `coach/abschluss.py` für ZIP und Datenspende aus dem Technikbericht erzeugt. | #56 Tests | `tests/test_technik_paket.py` prüft beide Wege und Ausschluss eines Geheimnisfelds; `tests/test_abschluss.py` prüft die Spenden-Dateiliste. Download im Browser/live noch nicht angeklickt. |

## Abnahmegrenze

Unit-/API-Tests und ausdrücklich simulierte lokale Browser-Mocks ersetzen keine Hardware-Abnahme. Auch der
unten beschriebene teilweise erfolgreiche HTTPS-Lauf ist keine vollständige Einsatzbereitschaftsaussage.

## Übergabe an Claude Opus

Der vollständige Übernahmeauftrag mit Prüfschritten und Belegpfaden liegt in
[Ticket #59](https://github.com/niclaseschner-ship-it/live-meeting-coach/issues/59). #54–#58 bleiben offen.
Der laufende Reparaturstand wurde abgeschlossen, nicht als gesamtes Produkt freigegeben.

- Letzter vollständiger Regressionstest nach den Anbietergrenzen: **415 Python-Tests bestanden**,
  `logs/pilot56_live/regressionen-final.log`. Worker: **26 Tests bestanden**, TypeScript-Prüfung grün.
- Ein echter HTTPS-Basislauf bestätigte Login, Variantenwahl/Reload, Agenda-Rückfrage und Entwurf, QR-Kopplung
  ohne Handylogin, Mikro/Ton-Freigabe, Ausschluss des zweiten Handys, Start, Begrüßung, Mistral-ASR und fachlich
  richtige Ergebnis-Karte. Bericht: `logs/pilot56_live/basis/bericht.html` und `.json` (private lokale Belege).
  Dieser Bericht ist dennoch fehlgeschlagen: ISO-Freitagsdatum wurde vom Test fälschlich abgewiesen, anschließend
  verdeckte das offene Transkriptpanel den Stop-Knopf. Terminprüfung und tatsächlicher Layoutfehler sind inzwischen
  repariert; die vollständige Runde wurde danach nicht wiederholt. Keine Premium-Gesamtabnahme.
- Weitere UI-Reparaturen: kurzer Sprechtastentext mit Bedienhilfe; Verlaufpanel unter der tatsächlichen
  Headerhöhe, auch bei Umbruch; keine leere Mikro-/Vorbereitungskarte am Handy nach Meetingende.
- Premium-Stimme/Modus wird serverseitig vor Änderungen geprüft und im UI erst nach Bestätigung übernommen.
  Nova nur für Kurzantworten; neue Stimme wirkt nicht rückwirkend in einem offenen Realtime-Gespräch (#58).
- Die nochmals bestätigte Anbietergrenze ist nun auch gegen Legacy-Testoptionen abgesichert: **Premium nur
  OpenAI, Basis nur Mistral**. Kein AboClient im Produkt-Clientweg, keine Claude-Bildoption, kein Bild-Fallback
  zu Claude; fremder Bildanbieter wird vor einer Teilmutation abgewiesen. README und Lastenheft angepasst.
- Commits des letzten Abschlusses: `7c31075` (UI/Stimmen), `87c18a7` (Anbietergrenzen), `b36b9bc`
  (Abnahmeskript). Cloud- und Repo-Gleichstand muss am neuesten Deploylog/Rollout verifiziert werden.
- Offen für Opus: Gesamtdiff/alle Rückmeldungen inklusive Vorarbeiten prüfen; alle fünf Aktionen fachlich testen;
  Basis und Premium vollständig bis ZIP und Datenspende abnehmen; **echtes physisches Handy** ohne Registrierung
  oder Tailscale testen, einschließlich QR, Berechtigungen, Bereitschaft, Sprache/Ton, Wiederverbinden und Ende.
  Separate Playwright-Browserkontexte mit synthetischem Mikrofon ersetzen diese Hardware-Abnahme nicht.
  Agenda-Sprachverarbeitung, Monolog im echten längeren Sprachblock und Moderator-Promptwege zusätzlich prüfen.

Private Aufnahmen, Spenden-/ZIP-Belege, Originalanhänge und das nutzereigene `:memory:.ses` bleiben erhalten.
Keine privaten Audio-/Feedbackinhalte wurden ins öffentliche Repo übernommen. Die konkrete historische Ursache
des unerwarteten Basisverhaltens bei gewähltem Premium ist weiterhin nicht abschließend belegt.
