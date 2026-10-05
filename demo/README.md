# Demo: „Messeplanung 2027“

Ein erfundenes Teammeeting mit drei Personen und drei Agendapunkten, Dauer 3:11 min. Die Stimmen sind
synthetisch (OpenAI-Sprachausgabe), die Aufnahme ist also frei verwendbar. Erzeugt wird sie mit
[`scripts/demo_erzeugen.py`](../scripts/demo_erzeugen.py).

| Datei | Inhalt |
|---|---|
| `messeplanung.wav` | Aufnahme, 24 kHz mono |
| `messeplanung.json` | Einrichtung: Titel, Ziel, Agenda mit je 1 min, sechs Gesprächsregeln, Nestor an |
| `dashboard_live.png` | Dashboard bei 2:09: Ton-Regel rot, Nestor beantwortet „Wo stehen wir gerade?“ |
| `dashboard_ende.png` | Dashboard nach dem Meeting: Agenda mit Ergebnissen, Live-Bild, Redeanteile |
| `zusammenfassung.png` | Meeting-Zusammenfassung (Live-Bild, Stand 3:11) |
| `protokoll.md` | Ergebnisse je Punkt, Hinweise an die Runde, Transkript |

## Abspielen

Coach starten (siehe [README](../README.md)) und im Dashboard „Testen ohne Runde“ aufklappen. Dort
`messeplanung` wählen, „Agenda automatisch“ anhaken und „Abspielen“ drücken. Wer Nestor hören will, gibt
vorher dem Browser den Ton frei. Ein Durchlauf kostete 0,28 $:

| Posten | Kosten |
|---|---|
| Live-Bild (2 Bilder) | 0,16 $ |
| Nestor | 0,06 $ |
| Live-Text | 0,05 $ |
| Agenda, Ton, Ergebnisse | 0,01 $ |

## Was die Demo zeigt

| Zeit | Im Meeting | Nestor |
|---|---|---|
| 0:00 | – | begrüßt die Runde und fragt, ob jemand Nein sagt |
| 0:25 | Punkt 1 Termin und Messestand | – |
| 1:00 | Zeitfenster von Punkt 1 erreicht | Zeit-Hinweis |
| 0:58–1:20 | Abschweifung zum Fußballspiel | „Bezug zum aktuellen Agendapunkt unklar“ |
| 1:24 | „Nun gehen wir weiter zu Punkt zwei, Budget.“ | wechselt sofort; prüft Ergebnis von Punkt 1 (Eckstand 40 m², Buchung bis Freitag) |
| 1:37 | „So ein Scheiß …“ | Regel „Respektvoller Ton“ wird rot |
| 1:51 | Beschluss: höchstens 25.000 € | – |
| 1:58 | „Nestor, wo stehen wir gerade?“ | antwortet gesprochen und als Untertitel |
| 2:20 | „Dann gehen wir weiter zu Punkt drei …“ | wechselt sofort |
| 2:46 | „Nestor, zeig uns bitte die Übersicht.“ | zeichnet das Live-Bild; am Ende schreibt er es zur Zusammenfassung fort |

Bekannte Schwäche: Bei 1:33 kam der Hinweis „Mehrere Personen sprechen gleichzeitig“, obwohl niemand
gleichzeitig spricht. Die synthetischen Stimmen klingen sich ähnlicher als echte, das verwirrt die
Mischungserkennung. Ob das auch bei echten Stimmen passiert, zeigt erst der Raumtest.
