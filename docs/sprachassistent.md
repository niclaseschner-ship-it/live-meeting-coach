# Sprachassistent „Nestor“

Stand 05.10.2026 · Ausbaustufe 2: Der Coach lässt sich mit Namen ansprechen und antwortet mit Sprache.

## Ablauf im Meeting

1. **Begrüßung mit Einverständnis.** Beim Start sagt der Coach: „Hallo zusammen, ich bin Nestor und begleite
   heute euer Meeting. Ihr habt euch folgende Regeln gewünscht: … Dafür höre ich mit. Wenn jemand damit nicht
   einverstanden ist, sagt jetzt bitte einfach Nein.“
   - **Kein Nein in 7 s:** „Ich habe kein Nein gehört. Dann geht es los. Wir starten mit Punkt eins: … Ich höre
     zu und melde mich nur, wenn ihr mich braucht. Sprecht mich einfach mit Nestor an.“
   - **Ein Nein:** Bisheriges Transkript und Stimmprofile werden gelöscht. Ab dann geht kein Ton mehr an
     OpenAI. Wieder einschalten geht nur über den Knopf, weil der Coach dann nichts mehr hört.
2. **Zuhören ohne Einmischen.** Ampeln und Hinweise laufen wie bisher still im Dashboard. Gesprochen wird
   nur auf Ansprache.
3. **Ansprache:** „Nestor, …“ irgendwo im Satz, oder Knopf „Nestor fragen“ (dann ohne Namen). Kommt nur
   der Name, antwortet er „Ja?“ und wartet auf die Frage. Bis 15 s nach einer Antwort geht eine Rückfrage
   auch ohne Namen, wenn sie als Frage endet.
4. **Antwort** gesprochen, kurz (meist 1–3 Sätze), dazu als Text in der Assistenten-Leiste.
   **Aktionen** auf Zuruf:

| Beispiel | Aktion |
|---|---|
| „Nestor, wo stehen wir?“, „Fass den aktuellen Punkt zusammen“, „Was kommt als Nächstes?“ | Antwort aus Agenda, Ergebnissen und Transkript |
| „Wir kommen jetzt zum nächsten Punkt“ | Agendapunkt wechseln, danach greift Regel 10 (Ergebnis des abgeschlossenen Punkts) |
| „Erstell uns die visuelle Übersicht“, „Visualisier nur den letzten Punkt“, „Zeig, was noch ansteht“, „Wo fehlen Entscheidungen?“ | Live-Bild mit diesem Fokus (Claude, ~1–2 min), danach „Das Bild ist fertig“ |
| „Gib uns einen Überblick zu …“, „Wie ist der aktuelle Stand bei …?“ | Recherche im Web: „Ich schau kurz nach“, dann gesprochene Zusammenfassung; danach bietet Nestor an, das Ergebnis mit Quellen auf einer Folie zusammenzustellen |
| „Ja, mach eine Folie“ (nach einer Recherche) | Recherche-Folie im Dashboard: Titel, Kernaussage, Stichpunkte, Offenes, Quellen als Links (~3 s) |
| „Nestor, hör bitte nicht mehr zu“ | Pause (wieder an per Knopf) |

## Architektur

Zwei Betriebsarten (`LMC_ASSISTENT_MODUS`):

**„gespraech“ (Standard): wie der ChatGPT-Sprachmodus.** Nestor ist Teil der Runde:

```
Mikrofon ─► Live-Text (läuft ohnehin) ─► Satz mit „Nestor“ ─► Realtime-Sitzung öffnen (gpt-realtime)
                                                               Anweisung: Persona + Meeting-Zustand
                                                               erste Frage als Text → Antwort als Sprache
Mikrofon ──────────────────────────────────────────────────► geht direkt in die offene Sitzung
                                                               (Modell hört Rückfragen, Gesagtes, Tonfall)
Live-Text: Name oder Rückfrage „…?“ kurz nach der Antwort ──► Coach löst die nächste Antwort aus
Jemand redet hinein ──► Modell bricht ab, Dashboard verstummt sofort
20 s Ruhe oder „danke, das war's“ ──► Sitzung zu, Nestor hört wieder nur auf seinen Namen
Werkzeuge: bild_zeichnen(fokus), agendapunkt_wechseln(nummer), recherchieren(frage), folie_erstellen, zuhoeren_pausieren,
           gespraech_beenden
Ton: PCM-Stücke ─► WebSocket ─► Dashboard (nur Moderationsansicht) spielt nahtlos ab
```

- **Natürlichkeit:** Stimme, Betonung und Tempo kommen direkt aus dem Sprachmodell, nicht aus einer
  vorgelesenen Textantwort. Rückfragen funktionieren ohne Namen, und man kann Nestor ins Wort fallen.
- **Wer entscheidet, wann er spricht:** der Coach, nicht das Modell (`create_response` aus). Abspieltest:
  Mit eigener Entscheidung kommentierte das Modell ungefragt das laufende Gespräch („Alles klar,
  Vorschlag: maximal 2000 Euro“). Jetzt antwortet es nur, wenn der Name im Live-Text fällt oder kurz nach
  seiner Antwort eine Rückfrage kommt. Es hört aber alles mit und weiß, was gesagt wurde.
- **Kosten** laut Token-Protokoll im Abspieltest: je Antwort ~1–2 Cent, solange die Sitzung offen ist
  dazu das mitgehörte Audio. Die Sitzung schließt nach 20 s Ruhe.

**„text“ (Rückfall, günstiger):** Satz mit Namen ─► GPT-5.4-mini gestreamt (erste Zeile Aktion, dann
Text) ─► Satz für Satz Sprachausgabe gpt-4o-mini-tts ─► Dashboard. Gemessen: erster Satz nach ~1,2 s,
erster Ton ~0,5 s später, ~1 Cent je Frage. Nicht unterbrechbar, Rückfragen nur als Frage mit „?“. Der
Coach nutzt diesen Weg automatisch, wenn keine Realtime-Sitzung zustande kommt.

**Recherche** (`coach/recherche.py`): Websuche über die OpenAI-Responses-API (GPT-5.4-mini mit
`web_search`). In die Suche geht nur das vom Modell formulierte Thema und der Meetingtitel, kein
Transkript. Eingebettete Quellenverweise werden vor dem Vorlesen entfernt. Gemessen 05.10.: Suche 5–8 s,
gesprochener Überblick ~11 s nach der Frage, ~2 Cent je Recherche.

**Nestor-Karten** (`coach/karten.py`): Was Nestor sagt, erscheint zusätzlich als Pop-up über dem Bildbereich –
Titel, die Frage, 2–4 Stichpunkte, bei Recherchen die Quellen. GPT-5.4-mini verdichtet die gesprochene Antwort
(gemessen 1,3–2,5 s, Frist 6 s, sonst die ersten Sätze) und lässt Bestätigungen, Rückfragen und Smalltalk weg.
Bei Aktionen (Bild, Agenda-Wechsel, Pause, Folie) gibt es keine Karte, weil das Dashboard das Ergebnis selbst
zeigt. Automatisch geöffnete Karten treten nach einer Minute zurück; alle bleiben im Verlauf (Reiter „Nestor“)
und lassen sich dort wieder öffnen. Solange eine Karte offen ist, entfällt der Untertitel.

**Recherche-Folie** (`coach/folie.py`): auf Zuruf oder per Knopf im Live-Bild-Bereich. GPT-5.4-mini macht aus
dem Rechercheergebnis Titel, Kernaussage, 3–5 Stichpunkte und Offenes – ohne neue Suche, ohne Transkript. Die
Folie ist eine Dashboard-Ansicht (umschaltbar mit dem Live-Bild), damit Text scharf und Quellen anklickbar
bleiben. Gemessen 05.10.: 2,8 s, unter 1 Cent.

**Gemeinsam:**
- **Kein eigenes Wake-Word-Modell.** Der Name wird im Live-Text gesucht, der ohnehin mitläuft; das kostet
  nichts zusätzlich. Der Name steht in der Stichwortliste und im Prompt der Texterkennung. Abspieltest:
  Ohne diese Hilfe kam „Nestor“ am Satzanfang 3 von 4 Mal als „Mestor“ an, mit ihr 4 von 4 richtig.
  Ähnliche Schreibweisen werden zusätzlich akzeptiert.
- **Begrüßung und Startsatz** sind feste Texte über die Sprachausgabe: schnell und verlässlich.
- **Eigene Stimme:** Mit Assistent nutzt das Mikrofon die Echo-Unterdrückung des Browsers. Zusätzlich
  verwirft der Server Sätze und Sprecherabschnitte aus den Zeitfenstern, in denen Nestor spricht. So zählt
  er weder im Transkript noch bei den Redeanteilen als Person.
- **Datenschutz:** Ein Nein bei der Begrüßung löscht alles Gehörte. Ab da geht kein Ton mehr an OpenAI,
  weder an den Live-Text noch an ein Gespräch. Die Antworten nennen keine Personen.

## Was (noch) nicht geht

- **Ins Wort fallen im Raum:** Im Gesprächsmodus bricht Nestor ab, sobald jemand spricht. Ob die
  Echo-Unterdrückung des Browsers seine eigene Stimme sicher heraushält (sonst unterbricht er sich selbst),
  zeigt erst der Raumtest. Notfalls gibt es den Knopf „Stopp“.
- **Kontext während eines Gesprächs:** Der Meeting-Stand wird beim Öffnen der Sitzung mitgegeben. Was
  danach passiert, hört Nestor direkt, Agenda und Ergebnisse aktualisiert er aber erst in der nächsten
  Sitzung.
- **Lautstärke im Raum:** Der Laptoplautsprecher reicht für einen kleinen Raum. Für 5 Personen am Tisch
  eher einen kleinen Lautsprecher anschließen; das Konferenzmikro mit eigenem Lautsprecher hat meist
  bessere Echo-Unterdrückung.
- **Wer fragt:** Nestor weiß nicht, wer ihn anspricht (Namen gibt es nur als „Person N“).
- **Fehlauslöser:** Fällt der Name im normalen Gespräch („wie Nestor vorhin sagte“), antwortet er. Ein
  seltener Name verringert das.

## Test

- `scripts/tts_assistent_probe.py` erzeugt zwei synthetische Meetings (Kosten wenige Cent):
  `assistent_dialog` (Begrüßung ohne Einwand, Gespräch, vier Fragen) und `assistent_nein` (Einwand).
- Abspielen: `scripts\abspielen.py testbibliothek\audio\assistent_dialog.wav --tempo 1`, oder im Dashboard
  unter „Aufnahme abspielen“ (dann ist die Stimme zu hören). Fragen und Antworten stehen im Bericht
  unter `protokoll` mit `art = "assistent"`.
- `assistent_recherche`: „Gib uns einen kurzen Überblick zum aktuellen Stand beim gesetzlichen
  Mindestlohn“ → „Ich schau kurz nach“, Suche 5,4 s, Überblick mit Stand 2026 und Ausblick 2027.
- Ergebnis 05.10.: Gesprächsmodus 4/4 Ansprachen beantwortet, bei nicht gerichtetem Gespräch still,
  Agenda-Wechsel per Zuruf, Fokusbild angestoßen. Der Textmodus beantwortete ebenfalls 4/4. Ein Einwand
  löscht alles und pausiert. Im Dashboard abgespielt: Assistenten-Leiste und Ton kommen an.
- Unit-Tests ohne Netz: `tests/test_assistent.py`.

## Name

Arbeitsname **Nestor**. In Homers Ilias ist Nestor der erfahrene Ratgeber, der im Rat der Griechen
vermittelt, zum Beispiel im Streit zwischen Agamemnon und Achilles. Der Name ist kurz, gut zu sprechen,
im Alltag selten und wird nach dem Stichwort-Trick zuverlässig erkannt.

Alternativen:
- **Forseti:** nordischer Gott der Schlichtung; in seiner Halle Glitnir gehen alle Streitenden versöhnt
  auseinander. Im Isländischen heißt „forseti“ heute „Vorsitzender“. Sehr passend, aber die
  Texterkennung muss ihn erst lernen (ungewohnt im Deutschen).
- **Solon:** Athener Gesetzgeber und Schlichter. Kurz und deutlich.
- Nicht geeignet: **Themis** (Göttin der Ordnung, beruft die Götterversammlung ein) klingt zu sehr nach
  „Thema“ und würde in Meetings ständig auslösen. **Mentor** ist ein Alltagswort.

Änderbar über `LMC_ASSISTENT_NAME` und `LMC_ASSISTENT_MUSTER` (Schreibweisen für die Erkennung).
