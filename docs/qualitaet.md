# Qualität aus Nutzersicht

Der Cloud-Testlauf (`scripts/cloudtest.py`) prüft seit Ticket #9, ob alles funktioniert. Diese Rubrik macht
daraus einen Maßstab dafür, ob es sich auch **gut anfühlt** – was ein Mensch in der Runde erlebt, nicht nur
was im Code passiert. `scripts/cloudtest_bewerten.py` (Ticket #11) rechnet die messbaren Kennzahlen aus dem
Trace eines Laufs und lässt die Urteilskriterien von einem Sprachmodell mit Bild-Eingabe (Codex über das
ChatGPT-Abo, `codex exec -i <Screenshot>`, keine API-Kosten) nach dieser Rubrik bewerten.

## Messbare Kennzahlen

| Kriterium | Kennzahl | Woher |
|---|---|---|
| Ansprache | Treffer / Fehlauslöser / Verpasste je Grenzfall | `referenz.json` gegen Karten/Hinweise im Trace |
| Antwortzeit | Ende der Frage → erster Ton (Ziel ≤ 3 s), → Karte steht | `stimme`-Nachrichten und Karten-Zeitstempel in `ws.jsonl` |
| Ruhe | Hinweise je 10 Minuten, davon unnötig (kein passendes Ereignis in der Nähe) | Hinweise in `ws.jsonl` gegen `referenz.json` |
| Kosten | gesamt, je Stunde hochgerechnet | `zustand.kosten` am Laufende |

## Urteilskriterien (1–5, mit Begründung)

Vom Sprachmodell nach dieser Rubrik vergeben, mit Bild-Eingabe wo es um Screenshots geht. 1 = nicht brauchbar,
3 = brauchbar mit Abstrichen, 5 = wie von einem aufmerksamen menschlichen Protokollanten.

- **Antwortgüte:** Passt Nestors Antwort inhaltlich zur Frage und zum tatsächlichen Meeting-Stand (Agenda,
  bisherige Entscheidungen)? Erfindet sie etwas, das nicht gesagt wurde?
- **Verständlichkeit auf einen Blick:** Erkennt man im Dashboard-Screenshot in drei Sekunden, was gerade los
  ist und – falls etwas schiefläuft – was das Problem ist (Ampeln, Hinweistext, Karte)? Eine Bewertung je
  Screenshot.
- **Live-Bild / Überblick:** Stimmen die gezeigten Punkte, Entscheidungen und Aufgaben mit dem tatsächlichen
  Gespräch überein? Ist es auf einen Blick lesbar? Erfindet es etwas (Namen, Zahlen, Wappen, Beträge, die so
  nicht fielen)?
- **Abschluss:** Ist das heruntergeladene Paket brauchbar – würde man es kommentarlos an jemanden weiterleiten,
  der nicht dabei war?
- **Gesamteindruck:** „Würde ich das meinem Team empfehlen?“ – mit drei Sätzen Begründung, die konkret auf
  das Erlebte Bezug nimmt (nicht nur auf die Kennzahlen).

## Was „gut“ nicht heißt

Kein Signal muss perfekt sein, um als gut zu gelten – Abschnitt 4.3 im Lastenheft benennt offen, welche
Signale Beta sind und wie oft sie danebenliegen. Gut heißt: die Einstufung stimmt (ein Beta-Signal, das
danebenliegt, ist kein Mangel; ein verlässliches Signal, das danebenliegt, schon), und die Oberfläche
verschweigt die Unsicherheit nicht.

## Grenzfälle der Ansprache

Zwölf Fälle (Ticket #11, Liste im Ticket) prüfen die Ansprache-Regel nicht nur auf Textebene (`NAME_RE` in
`coach/assistent.py` erkennt alle textlich eindeutigen Fälle schon richtig – geprüft), sondern Ende zu Ende:
ob die Transkription aus einem Nicht-Namen einen Nestor-ähnlichen Text macht, und ob die Pipeline bei echten
Pausen, Lautstärken und Tempi richtig reagiert. Jeder Fall hat in `referenz.json` ein erwartetes Verhalten
(Antwort / keine Antwort / sinnvolle Nachfrage); die Bewertung hält ab, wenn es abweicht – ohne es zu
beheben (Tabu laut Ticket: `coach/`).
